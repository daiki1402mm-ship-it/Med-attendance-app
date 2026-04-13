import streamlit as st
import psycopg2
from psycopg2.extras import DictCursor
from datetime import datetime, timedelta
import pytz
import pandas as pd

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

    # タブ表示（「予定登録」を追加）
    tab1, tab2, tab3, tab4 = st.tabs(["🗓 本日の講義", "📝 提出物", "⚖️ 試験日程", "➕ 予定登録"])

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
        for a in cur.fetchall():
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

    # --- タブ4: 予定登録 (復活版) ---
    with tab4:
        st.subheader("🆕 講義予定の追加")
        
        with st.form("add_lecture_form", clear_on_submit=True):
            col_d, col_p, col_s = st.columns([2, 1, 3])
            new_date = col_d.date_input("日付")
            new_period = col_p.selectbox("時限", options=[1, 2, 3, 4, 5, 6])
            new_subject = col_s.text_input("科目名")
            
            submit = st.form_submit_state = st.form_submit_button("登録する")
            
            if submit:
                if new_subject:
                    cur.execute(
                        "INSERT INTO attendance (date, period, subject_name, status) VALUES (%s, %s, %s, '予定')",
                        (new_date.isoformat(), new_period, new_subject)
                    )
                    conn.commit()
                    st.success(f"{new_date.strftime('%m/%d')} {new_period}限に {new_subject} を登録しました！")
                else:
                    st.error("科目名を入力してください。")

        st.divider()
        st.write("💡 **ヒント**: 6月の予定を一気に入れる場合は、日付を切り替えながらこのフォームを連続で使うのが確実です。")

    cur.close()
    conn.close()

except Exception as e:
    st.error(f"エラーが発生しました: {e}")
