import streamlit as st
import psycopg2
from psycopg2.extras import DictCursor
from datetime import datetime, date, timedelta
import pytz
import pandas as pd

# 1. データベース接続
def get_connection():
    return psycopg2.connect(st.secrets["SUPABASE_URI"])

st.set_page_config(page_title="医学生マネージャー", layout="wide")

try:
    conn = get_connection()
    cur = conn.cursor(cursor_factory=DictCursor)

    # --- サイドバー：CBT設定と統計 ---
    st.sidebar.title("⚙️ 管理パネル")
    cur.execute("SELECT value FROM settings WHERE key = 'cbt_date'")
    cbt_res = cur.fetchone()
    current_cbt = datetime.strptime(cbt_res['value'], '%Y-%m-%d').date() if cbt_res else datetime.now().date()
    
    new_cbt = st.sidebar.date_input("CBT試験日", value=current_cbt)
    if new_cbt != current_cbt:
        cur.execute("INSERT INTO settings (key, value) VALUES ('cbt_date', %s) ON CONFLICT (key) DO UPDATE SET value = %s", (new_cbt.isoformat(), new_cbt.isoformat()))
        conn.commit()
        st.rerun()

    # 出欠統計（講義のみ）
    st.sidebar.divider()
    st.sidebar.subheader("📊 単位アラート")
    cur.execute("""
        SELECT subject_name, COUNT(*) as total, 
               COUNT(CASE WHEN status = '欠席' THEN 1 END) as absences 
        FROM attendance 
        WHERE status IN ('予定', '出席', '欠席') 
          AND subject_name NOT LIKE '%休講%' 
          AND subject_name NOT LIKE '%休み%'
        GROUP BY subject_name
    """)
    for s in cur.fetchall():
        max_abs = 0 if "実習" in s['subject_name'] else s['total'] // 3
        rem = max_abs - s['absences']
        color = "red" if rem <= 1 else "white"
        st.sidebar.markdown(f"**{s['subject_name']}** (残り: <span style='color:{color};'>{rem}</span>)", unsafe_allow_html=True)
        st.sidebar.progress(min(s['absences'] / max_abs, 1.0) if max_abs > 0 else 0.0)

    # --- メイン画面 ---
    jst = pytz.timezone('Asia/Tokyo')
    today = datetime.now(jst).date()
    
    col1, col2 = st.columns([2, 1])
    with col1:
        st.title("👨‍⚕️ Medical Dashboard")
    with col2:
        st.metric("⚔️ CBTまで", f"{(new_cbt - today).days} 日")

    st.divider()
    tab1, tab2, tab3 = st.tabs(["🗓 本日の予定", "📝 提出物", "⚖️ 試験日程"])

    # --- タブ1: 本日の予定（統合表示） ---
    with tab1:
        view_date = st.date_input("表示日", value=today)
        
        # データの取得
        cur.execute("SELECT * FROM attendance WHERE date = %s ORDER BY period ASC", (view_date.isoformat(),))
        lectures = cur.fetchall()
        cur.execute("SELECT * FROM lifestyle_schedules WHERE event_date = %s ORDER BY start_time ASC", (view_date.isoformat(),))
        lifestyle = cur.fetchall()

        if not lectures and not lifestyle:
            st.info("予定はありません。ゆっくり休みましょう！🍵")
        else:
            # 1. 大学の講義
            if lectures:
                st.subheader("📚 大学の講義")
                for l in lectures:
                    c1, c2, c3 = st.columns([1, 3, 2])
                    c1.write(f"**{l['period']}限**")
                    c2.write(f"{l['subject_name']} ({l['status']})")
                    btn_cols = c3.columns(3)
                    if btn_cols[0].button("出", key=f"at_{l['id']}"):
                        cur.execute("UPDATE attendance SET status = '出席' WHERE id = %s", (l['id'],)); conn.commit(); st.rerun()
                    if btn_cols[1].button("欠", key=f"ab_{l['id']}"):
                        cur.execute("UPDATE attendance SET status = '欠席' WHERE id = %s", (l['id'],)); conn.commit(); st.rerun()
                    if btn_cols[2].button("休", key=f"ca_{l['id']}"):
                        cur.execute("UPDATE attendance SET status = '休講' WHERE id = %s", (l['id'],)); conn.commit(); st.rerun()

            # 2. 私生活（バイト・部活）
            if lifestyle:
                st.divider()
                st.subheader("🏠 プライベート・活動")
                for item in lifestyle:
                    c1, c2, c3 = st.columns([1, 3, 2])
                    start = item['start_time'].strftime('%H:%M') if item['start_time'] else "未定"
                    end = f"〜{item['end_time'].strftime('%H:%M')}" if item['end_time'] else ""
                    
                    # カテゴリ別アイコン
                    icon = "🛵" if item['category'] == 'part_time' else "🎺" if item['category'] == 'club' else "🌟"
                    
                    c1.write(f"**{start}{end}**")
                    c2.write(f"{icon} **{item['detail']}**")
                    if c3.button("削除", key=f"del_{item['id']}"):
                        cur.execute("DELETE FROM lifestyle_schedules WHERE id = %s", (item['id'],)); conn.commit(); st.rerun()

    # --- タブ2/3: 提出物・試験（既存のロジック） ---
    with tab2:
        cur.execute("SELECT * FROM assignments WHERE is_completed = FALSE ORDER BY deadline ASC")
        for a in cur.fetchall():
            st.checkbox(f"{a['deadline'].strftime('%m/%d')} : {a['subject_name']} - {a['content']}", key=f"assign_{a['id']}")

    cur.close()
    conn.close()

except Exception as e:
    st.error(f"エラー: {e}")
