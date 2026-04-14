import streamlit as st
import psycopg2
from psycopg2.extras import DictCursor
from datetime import datetime, date, timedelta
import pytz
import pandas as pd
import re

# 1. データベース接続設定 (Supabase Secrets)
def get_connection():
    return psycopg2.connect(st.secrets["SUPABASE_URI"])

st.set_page_config(page_title="医学生専用ダッシュボード", layout="wide", page_icon="🩺")

# タイムゾーンと日付の基本設定
tokyo = pytz.timezone('Asia/Tokyo')
today = datetime.now(tokyo).date()

try:
    conn = get_connection()
    cur = conn.cursor(cursor_factory=DictCursor)

    # --- サイドバー：設定・統計・給与 ---
    st.sidebar.title("⚙️ 設定・統計")
    
    # 💰 【追加】給与サマリー（サイドバー最上部）
    st.sidebar.subheader("💸 今月の給与")
    first_day_this_month = today.replace(day=1)
    cur.execute("""
        SELECT SUM(pay_amount) as total FROM work_results 
        WHERE work_date >= %s
    """, (first_day_this_month.isoformat(),))
    this_month_earn = cur.fetchone()['total'] or 0
    st.sidebar.metric(f"{today.month}月の稼ぎ（目安）", f"¥{this_month_earn:,}")

    # CBT日程の設定
    st.sidebar.divider()
    cur.execute("SELECT value FROM settings WHERE key = 'cbt_date'")
    cbt_res = cur.fetchone()
    current_cbt = datetime.strptime(cbt_res['value'], '%Y-%m-%d').date() if cbt_res else today
    
    new_cbt = st.sidebar.date_input("CBT試験日を設定", value=current_cbt)
    if new_cbt != current_cbt:
        cur.execute("INSERT INTO settings (key, value) VALUES ('cbt_date', %s) ON CONFLICT (key) DO UPDATE SET value = %s", (new_cbt.isoformat(), new_cbt.isoformat()))
        conn.commit()
        st.rerun()

    # 📊 出欠統計（医学生ルール適用版）
    st.sidebar.divider()
    st.sidebar.subheader("📊 科目別・欠席許容数")
    # 💡 ルール：医学祭や休みは除外、実習は欠席可能数0
    cur.execute("""
        SELECT subject_name, COUNT(*) as total, 
               COUNT(CASE WHEN status = '欠席' THEN 1 END) as absences 
        FROM attendance 
        WHERE status IN ('予定', '出席', '欠席')
          AND subject_name NOT LIKE '%%医学祭%%'
          AND subject_name NOT LIKE '%%休み%%'
          AND subject_name NOT LIKE '%%休講%%'
        GROUP BY subject_name
    """)
    stats = cur.fetchall()
    
    for s in stats:
        name = s['subject_name']
        # 💡 実習系は強制的に許容数を0にする
        if "実習" in name or "臨床" in name:
            max_abs = 0
        else:
            max_abs = s['total'] // 3  # 通常は1/3まで
            
        rem = max_abs - s['absences']
        st.sidebar.write(f"**{name}**")
        color = "red" if rem <= 0 else "orange" if rem == 1 else "green"
        st.sidebar.markdown(f"欠席: {s['absences']} / 可: {max_abs} (残り: <span style='color:{color}; font-weight:bold;'>{rem}</span>)", unsafe_allow_html=True)
        # 進捗バー（欠席が増えるほど満たされる）
        progress = min(s['absences'] / max(max_abs, 1), 1.0) if max_abs > 0 else (1.0 if s['absences'] > 0 else 0.0)
        st.sidebar.progress(progress)

    # --- メイン画面 ---
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

    # タブ表示（給与実績タブを追加）
    tab1, tab2, tab3, tab4, tab5 = st.tabs(["🗓 本日の講義", "📝 提出物", "⚖️ 試験日程", "💰 給与実績", "🚀 一括登録"])

    # --- タブ1: 本日の講義 ---
    with tab1:
        selected_date = st.date_input("表示日を選択", value=today, key="view_date")
        cur.execute("SELECT * FROM attendance WHERE date = %s ORDER BY period ASC", (selected_date.isoformat(),))
        lectures = cur.fetchall()
        if not lectures: st.info("講義予定なし")
        else:
            occ = {str(r['period']) for r in lectures if r['status'] not in ['休講', '欠席'] and not any(k in r['subject_name'] for k in ["休み", "休講", "祭"])}
            empty = [p for p in range(1, 7) if str(p) not in occ]
            if empty: st.write(f"💡 空きコマ: {', '.join(map(str, empty))}限")

            for l in lectures:
                c1, c2, c3 = st.columns([1, 2, 4])
                c1.write(f"**{l['period']}限**")
                c2.write(f"**{l['subject_name']}** ({l['status']})")
                b = c3.columns(4)
                if b[0].button("出席", key=f"at_{l['id']}"):
                    cur.execute("UPDATE attendance SET status = '出席' WHERE id = %s", (l['id'],)); conn.commit(); st.rerun()
                if b[1].button("欠席", key=f"ab_{l['id']}"):
                    cur.execute("UPDATE attendance SET status = '欠席' WHERE id = %s", (l['id'],)); conn.commit(); st.rerun()
                if b[2].button("休講", key=f"ca_{l['id']}"):
                    cur.execute("UPDATE attendance SET status = '休講' WHERE id = %s", (l['id'],)); conn.commit(); st.rerun()
                if b[3].button("予定", key=f"re_{l['id']}"):
                    cur.execute("UPDATE attendance SET status = '予定' WHERE id = %s", (l['id'],)); conn.commit(); st.rerun()

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
        if exams: st.table(pd.DataFrame([dict(e) for e in exams])[['exam_date', 'subject_name', 'location']])
        else: st.info("試験予定なし")

    # --- タブ4: 【追加】給与実績 ---
    with tab4:
        st.subheader("💰 アルバイト給与詳細")
        cur.execute("SELECT * FROM work_results WHERE work_date >= %s ORDER BY work_date DESC", (first_day_this_month.isoformat(),))
        results = cur.fetchall()
        if results:
            df_work = pd.DataFrame([dict(r) for r in results])
            st.table(df_work[['work_date', 'job_name', 'actual_start', 'actual_end', 'pay_amount']])
        else: st.info("今月の実績はまだありません。")

    # --- タブ5: 予定を一括登録 ---
    with tab4:
        st.subheader("🚀 予定を一括流し込み")
        bulk_text = st.text_area("予定リストをペースト (例: 4/15 1 消化器内科)", height=200)
        if st.button("一括登録を実行", type="primary"):
            if bulk_text:
                lines = bulk_text.strip().split('\n')
                success_count = 0
                for line in lines:
                    match = re.search(r'(\d+)[/月](\d+)日?\s*(\d+)限?\s*(.+)', line)
                    if match:
                        m, d, p, s = match.groups()
                        t_date = date(2026, int(m), int(d))
                        cur.execute("INSERT INTO attendance (date, period, subject_name, status) VALUES (%s, %s, %s, '予定')", (t_date.isoformat(), int(p), s.strip()))
                        success_count += 1
                conn.commit(); st.success(f"✅ {success_count}件 登録完了！"); st.rerun()

    cur.close()
    conn.close()

except Exception as e:
    st.error(f"エラーが発生しました: {e}")
