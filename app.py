import streamlit as st
import psycopg2
from psycopg2.extras import DictCursor
import os
from datetime import datetime, timedelta
import pytz
import pandas as pd

# 1. データベース接続関数
def get_db_connection():
    return psycopg2.connect(os.environ.get('SUPABASE_URI'))

# タイムゾーンと今日の日付設定
tokyo = pytz.timezone('Asia/Tokyo')
today = datetime.now(tokyo).date()

# ページ設定
st.set_page_config(page_title="Med-Attendance", page_icon="🩺")

# --- 💰 サイドバー：給料・実績集計 ---
st.sidebar.title("Dashboard")
st.sidebar.divider()
st.sidebar.subheader("💸 給与・報酬状況")

try:
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            # ① 今月の稼ぎ合計
            first_day_this_month = today.replace(day=1)
            cur.execute("""
                SELECT job_name, SUM(pay_amount) as total 
                FROM work_results 
                WHERE work_date >= %s AND work_date <= %s 
                GROUP BY job_name
            """, (first_day_this_month.isoformat(), today.isoformat()))
            this_month_data = cur.fetchall()

            # ② 先月の稼ぎ（今月の支給額）
            last_month_end = first_day_this_month - timedelta(days=1)
            last_month_start = last_month_end.replace(day=1)
            cur.execute("""
                SELECT SUM(pay_amount) as total 
                FROM work_results 
                WHERE work_date >= %s AND work_date <= %s
            """, (last_month_start.isoformat(), last_month_end.isoformat()))
            last_month_row = cur.fetchone()
            last_month_total = last_month_row['total'] if last_month_row and last_month_row['total'] else 0

    # サイドバー表示
    total_earned = sum(row['total'] for row in this_month_data)
    st.sidebar.metric(f"{today.month}月の稼ぎ合計", f"¥{total_earned:,}")
    for row in this_month_data:
        st.sidebar.caption(f" ・{row['job_name']}: ¥{row['total']:,}")

    st.sidebar.write("") 
    st.sidebar.info(f"📅 今月の支給予定: ¥{last_month_total:,}")
    st.sidebar.caption(f"※{last_month_start.month}月実績の合計")

except Exception as e:
    st.sidebar.error(f"給料取得エラー: {e}")


# --- 🗓 メイン画面：今日の予定表示 ---
st.title("🩺 Med-Attendance")
st.subheader(f"📅 {today.strftime('%Y/%m/%d')} の予定")

try:
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            # 💡 修正箇所：today を .isoformat() にして渡す
            # 今日の講義予定
            cur.execute("SELECT period, subject_name, status FROM attendance WHERE date = %s ORDER BY period ASC", (today.isoformat(),))
            lectures = cur.fetchall()
            
            # 今日の生活予定（部活・バイト）
            cur.execute("SELECT detail, start_time, end_time FROM lifestyle_schedules WHERE event_date = %s ORDER BY start_time ASC", (today.isoformat(),))
            lifestyles = cur.fetchall()

    # 表示用カラム作成
    col1, col2 = st.columns(2)

    with col1:
        st.markdown("#### 📚 大学の講義")
        if lectures:
            df_lec = pd.DataFrame(lectures)
            df_lec.columns = ['時限', '科目名', '状態']
            # 表をスッキリ表示
            st.dataframe(df_lec, use_container_width=True, hide_index=True)
        else:
            st.info("今日の講義予定はありません。")

    with col2:
        st.markdown("#### 🏠 その他の予定")
        if lifestyles:
            for l in lifestyles:
                # 終了時間の有無で表示を切り替え
                start_str = l['start_time'].strftime('%H:%M') if l['start_time'] else ""
                end_str = f"〜{l['end_time'].strftime('%H:%M')}" if l['end_time'] else ""
                time_range = f"{start_str}{end_str}" if start_str else "時間指定なし"
                
                st.warning(f"**{time_range}**\n\n{l['detail']}")
        else:
            st.info("部活やバイトの予定はありません。")

except Exception as e:
    st.error(f"予定データ取得エラー: {e}")

# --- 🧪 デバッグ用データ（必要に応じて） ---
with st.expander("生データを確認"):
    st.write("今日のタイムスタンプ (ISO):", today.isoformat())
