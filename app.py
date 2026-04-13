import streamlit as st
import psycopg2
from psycopg2.extras import DictCursor
from datetime import datetime, date, timedelta
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

    # --- 出欠統計（修正版：実習・休講・医学祭対応） ---
    st.sidebar.divider()
    st.sidebar.subheader("📊 出欠統計")
    # SQLで「休講」「休み」「祭」を統計から除外して取得
    cur.execute("""
        SELECT subject_name, 
               COUNT(*) as total, 
               COUNT(CASE WHEN status = '欠席' THEN 1 END) as absences 
        FROM attendance 
        WHERE status IN ('予定', '出席', '欠席') 
          AND subject_name NOT LIKE '%休講%'
          AND subject_name NOT LIKE '%休み%'
          AND subject_name NOT LIKE '%祭%'
        GROUP BY subject_name
    """)
    stats = cur.fetchall()
    
    if stats:
        for s in stats:
            subject = s['subject_name']
            
            # 「実習」が含まれる場合は欠席可能回数を0にする
            if "実習" in subject:
                max_abs = 0
            else:
                max_abs = s['total'] // 3
            
            remaining = max_abs - s['absences']
            
            # 色判定：実習で1回でも休む、または講義で残り1回以下なら赤
            if "実習" in subject:
                color = "red" if s['absences'] > 0 else "green"
            else:
                color = "red" if remaining <= 1 else "green"
            
            st.sidebar.write(f"**{subject}**")
            st.sidebar.markdown(
                f"欠席: {s['absences']} / 可: {max_abs} (残り: <span style='color:{color}; font-weight:bold;'>{remaining}</span>)", 
                unsafe_allow_html=True
            )
            
            # プログレスバー
            if max_abs == 0:
                progress_val = 1.0 if s['absences'] > 0 else 0.0
            else:
                progress_val = min(s['absences'] / max_abs, 1.0)
            st.sidebar.progress(progress_val)
    else:
        st.sidebar.info("統計データがありません")

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
            # 空きコマ判定（休講、休み、祭を除外）
            occ = {str(r['period']) for r in lectures if r['status'] not in ['休講', '欠席'] and not any(k in r['subject_name'] for k in ["休み", "休講", "祭"])}
            empty = [p for p in range(1, 7) if str(p) not in occ]
            if empty:
                st.write(f"💡 空きコマ: {', '.join(map(str, empty))}限")

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
        st.subheader("🚀 予定を一気に流し込む")
        bulk_text = st.text_area("予定リストをペースト (例: 6/1 1 小児科)", height=300)
        
        if st.button("一括登録を実行", type="primary"):
            if bulk_text:
                lines = bulk_text.strip().split('\n')
                success_count = 0
                error_lines = []
                for line in lines:
                    try:
                        match = re.search(r'(\d+)[/月](\d+)日?\s*(\d+)限?\s*(.+)', line)
                        if match:
                            m, d, p, s = match.groups()
                            t_date = date(2026, int(m), int(d))
                            cur.execute(
                                "INSERT INTO attendance (date, period, subject_name, status) VALUES (%s, %s, %s, '予定')",
                                (t_date.isoformat(), int(p), s.strip())
                            )
                            success_count += 1
                        else: error_lines.append(line)
                    except Exception as e: error_lines.append(f"{line} (エラー: {e})")
                
                conn.commit()
                if success_count > 0:
                    st.success(f"✅ {success_count}件の登録に成功しました！")
                    st.rerun()
                if error_lines:
                    st.error("登録失敗:")
                    for el in error_lines: st.text(el)
            else: st.warning("テキストを入力してください。")

    cur.close()
    conn.close()

except Exception as e:
    st.error(f"エラーが発生しました: {e}")
