import streamlit as st
import psycopg2
from psycopg2.extras import DictCursor
from datetime import datetime, timedelta
import pytz
import pandas as pd
import re

# 1. データベース接続設定
def get_connection():
    return psycopg2.connect(st.secrets["SUPABASE_URI"])

st.set_page_config(page_title="医学生専用ダッシュボード", layout="wide")

try:
    conn = get_connection()
    cur = conn.cursor(cursor_factory=DictCursor)

    # --- サイドバー：設定と統計 ---
    st.sidebar.title("⚙️ 設定・統計")
    
    # CBT日程の設定
    cur.execute("SELECT value FROM settings WHERE key = 'cbt_date'")
    cbt_res = cur.fetchone()
    current_cbt = datetime.strptime(cbt_res['value'], '%Y-%m-%d').date() if cbt_res else datetime.now().date()
    
    new_cbt = st.sidebar.date_input("CBT試験日を設定", value=current_cbt)
    if new_cbt != current_cbt:
        cur.execute("INSERT INTO settings (key, value) VALUES ('cbt_date', %s) ON CONFLICT (key) DO UPDATE SET value = %s", (new_cbt.isoformat(), new_cbt.isoformat()))
        conn.commit()
        st.rerun()

    # 出欠統計
    st.sidebar.divider()
    st.sidebar.subheader("📊 出欠統計")
    cur.execute("""
        SELECT subject_name, COUNT(*) as total, 
               COUNT(CASE WHEN status = '欠席' THEN 1 END) as absences 
        FROM attendance WHERE status IN ('予定', '出席', '欠席')
        GROUP BY subject_name
    """)
    stats = cur.fetchall()
    for s in stats:
        max_abs = s['total'] // 3
        rem = max_abs - s['absences']
        st.sidebar.write(f"**{s['subject_name']}**")
        color = "red" if rem <= 1 else "green"
        st.sidebar.markdown(f"欠席: {s['absences']} / 可: {max_abs} (残り: <span style='color:{color}; font-weight:bold;'>{rem}</span>)", unsafe_allow_html=True)
        st.sidebar.progress(min(s['absences'] / max(max_abs, 1), 1.0))

    # --- メイン画面 ---
    now = datetime.now(pytz.timezone('Asia/Tokyo'))
    today = now.date()
    
    # CBTカウントダウン
    days_to_cbt = (new_cbt - today).days
    col_title, col_count = st.columns([2, 1])
    with col_title:
        st.title("👨‍⚕️ 医学生専用ダッシュボード")
    with col_count:
        if days_to_cbt >= 0:
            st.metric(label="⚔️ CBTまであと", value=f"{days_to_cbt} 日")
        else:
            st.success("🎉 CBTお疲れ様でした！")

    st.divider()

    # タブ表示
    tab1, tab2, tab3, tab4 = st.tabs(["🗓 本日の講義", "📝 提出物", "⚖️ 試験日程", "🚀 予定を一括登録"])

    # --- タブ1: 本日の講義 ---
    with tab1:
        selected_date = st.date_input("表示日を選択", value=today, key="view_date")
        cur.execute("SELECT * FROM attendance WHERE date = %s ORDER BY period ASC", (selected_date.isoformat(),))
        lectures = cur.fetchall()
        if not lectures: st.info("講義予定なし")
        else:
            for l in lectures:
                c1, c2, c3 = st.columns([1, 2, 4])
                c1.write(f"**{l['period']}限**")
                c2.write(f"**{l['subject_name']}** ({l['status']})")
                b = c3.columns(3)
                if b[0].button("出席", key=f"at_{l['id']}"):
                    cur.execute("UPDATE attendance SET status = '出席' WHERE id = %s", (l['id'],)); conn.commit(); st.rerun()
                if b[1].button("欠席", key=f"ab_{l['id']}"):
                    cur.execute("UPDATE attendance SET status = '欠席' WHERE id = %s", (l['id'],)); conn.commit(); st.rerun()
                if b[2].button("休講", key=f"ca_{l['id']}"):
                    cur.execute("UPDATE attendance SET status = '休講' WHERE id = %s", (l['id'],)); conn.commit(); st.rerun()

    # --- タブ2: 提出物 ---
    with tab2:
        cur.execute("SELECT * FROM assignments WHERE is_completed = FALSE ORDER BY deadline ASC")
        assigns = cur.fetchall()
        if not assigns: st.success("全ての課題が完了しています！")
        else:
            for a in assigns:
                c1, c2, c3 = st.columns([2, 4, 1])
                dl_days = (a['deadline'] - today).days
                if dl_days <= 3: c1.error(f"あと {dl_days} 日")
                else: c1.warning(f"あと {dl_days} 日")
                c2.write(f"**{a['subject_name']}** : {a['content']}")
                if c3.button("完了", key=f"cp_{a['id']}"):
                    cur.execute("UPDATE assignments SET is_completed = TRUE WHERE id = %s", (a['id'],)); conn.commit(); st.rerun()

    # --- タブ3: 試験日程 ---
    with tab3:
        cur.execute("SELECT * FROM exams WHERE exam_date >= %s ORDER BY exam_date ASC", (today.isoformat(),))
        exams = cur.fetchall()
        if exams: st.table(pd.DataFrame([dict(e) for e in exams])[['exam_date', 'exam_time', 'subject_name', 'location']])
        else: st.info("試験予定なし")

    # --- タブ4: 予定を一括登録 ---
    with tab4:
        st.subheader("🚀 6月分の予定などを一気に流し込む")
        st.markdown("""
        下のエリアに予定を貼り付けて「一括登録」を押してください。
        **形式例:** `6/1 1限 解剖学` (スペース区切り)
        """)
        
        bulk_text = st.text_area("予定リストをペースト", height=300, placeholder="6/1 1 解剖学\n6/1 2 解剖学\n6/2 1 生理学...")
        
        if st.button("一括登録を実行", type="primary"):
            if bulk_text:
                lines = bulk_text.strip().split('\n')
                success_count = 0
                error_lines = []
                
                for line in lines:
                    try:
                        # 日付、時限、科目を解析
                        match = re.search(r'(\d+)[/月](\d+)日?\s*(\d+)限?\s*(.+)', line)
                        if match:
                            m, d, p, s = match.groups()
                            # 2026年として処理
                            t_date = date(2026, int(m), int(d))
                            cur.execute(
                                "INSERT INTO attendance (date, period, subject_name, status) VALUES (%s, %s, %s, '予定')",
                                (t_date.isoformat(), int(p), s.strip())
                            )
                            success_count += 1
                        else:
                            error_lines.append(line)
                    except Exception as e:
                        error_lines.append(f"{line} (エラー: {e})")
                
                conn.commit()
                if success_count > 0:
                    st.success(f"✅ {success_count}件の登録に成功しました！")
                    st.rerun()
                if error_lines:
                    st.error("以下の行は登録できませんでした（形式を確認してください）")
                    for el in error_lines: st.text(el)
            else:
                st.warning("テキストを入力してください。")

    cur.close()
    conn.close()

except Exception as e:
    st.error(f"エラーが発生しました: {e}")
