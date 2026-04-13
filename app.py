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

# サイドバー：出欠統計
def show_sidebar_stats(cur):
    st.sidebar.title("📊 出欠統計")
    cur.execute("""
        SELECT subject_name, 
               COUNT(*) as total, 
               COUNT(CASE WHEN status = '欠席' THEN 1 END) as absences 
        FROM attendance 
        WHERE status IN ('予定', '出席', '欠席')
        GROUP BY subject_name
    """)
    stats = cur.fetchall()
    if stats:
        for s in stats:
            max_abs = s['total'] // 3
            remaining = max_abs - s['absences']
            st.sidebar.write(f"**{s['subject_name']}**")
            color = "red" if remaining <= 1 else "green"
            # 💡 ここを修正しました
            st.sidebar.markdown(
                f"欠席: {s['absences']} / 可: {max_abs} (残り <span style='color:{color}; font-weight:bold;'>{remaining}</span>)", 
                unsafe_allow_html=True, 
                help="1/3以上欠席で留年リーチ"
            )
            st.sidebar.progress(min(s['absences'] / max(max_abs, 1), 1.0))
    else:
        st.sidebar.info("統計データがありません")

# メインコンテンツ
st.title("👨‍⚕️ 医学生専用ダッシュボード")

try:
    conn = get_connection()
    cur = conn.cursor(cursor_factory=DictCursor)

    # サイドバー表示
    show_sidebar_stats(cur)

    # タブで表示を切り替え
    tab1, tab2, tab3 = st.tabs(["🗓 本日の講義", "📝 提出物", "⚖️ 試験日程"])

    now = datetime.now(pytz.timezone('Asia/Tokyo'))
    today = now.date()

    # --- タブ1: 本日の講義 ---
    with tab1:
        selected_date = st.date_input("表示日を選択", value=today)
        target_date_str = selected_date.strftime('%Y-%m-%d')
        
        cur.execute("SELECT * FROM attendance WHERE date = %s ORDER BY period ASC", (target_date_str,))
        lectures = cur.fetchall()

        if not lectures:
            st.info("講義予定はありません。")
        else:
            for l in lectures:
                col1, col2, col3 = st.columns([1, 2, 4])
                col1.write(f"**{l['period']}限**")
                col2.write(f"**{l['subject_name']}** ({l['status']})")
                
                b_cols = col3.columns(3)
                if b_cols[0].button("出席", key=f"att_{l['id']}"):
                    cur.execute("UPDATE attendance SET status = '出席' WHERE id = %s", (l['id'],))
                    conn.commit()
                    st.rerun()
                if b_cols[1].button("欠席", key=f"abs_{l['id']}"):
                    cur.execute("UPDATE attendance SET status = '欠席' WHERE id = %s", (l['id'],))
                    conn.commit()
                    st.rerun()
                if b_cols[2].button("休講", key=f"can_{l['id']}"):
                    cur.execute("UPDATE attendance SET status = '休講' WHERE id = %s", (l['id'],))
                    conn.commit()
                    st.rerun()

    # --- タブ2: 提出物 ---
    with tab2:
        st.subheader("未完了の提出物")
        cur.execute("SELECT * FROM assignments WHERE is_completed = FALSE ORDER BY deadline ASC")
        assignments = cur.fetchall()
        
        if not assignments:
            st.success("全ての課題が完了しています！")
        else:
            for a in assignments:
                col1, col2, col3 = st.columns([2, 4, 1])
                days_left = (a['deadline'] - today).days
                
                # 期限に応じたバッジ
                if days_left <= 3:
                    col1.error(f"あと {days_left} 日")
                else:
                    col1.warning(f"あと {days_left} 日")
                
                col2.write(f"**{a['subject_name']}** : {a['content']}")
                if col3.button("完了", key=f"comp_{a['id']}"):
                    cur.execute("UPDATE assignments SET is_completed = TRUE WHERE id = %s", (a['id'],))
                    conn.commit()
                    st.rerun()

    # --- タブ3: 試験日程 ---
    with tab3:
        st.subheader("直近の試験日程")
        cur.execute("SELECT * FROM exams WHERE exam_date >= %s ORDER BY exam_date ASC", (today,))
        exams = cur.fetchall()
        
        if not exams:
            st.info("現在予定されている試験はありません。")
        else:
            df_exams = pd.DataFrame([dict(e) for e in exams])
            st.table(df_exams[['exam_date', 'exam_time', 'subject_name', 'location']])

    cur.close()
    conn.close()

except Exception as e:
    st.error(f"エラーが発生しました: {e}")
