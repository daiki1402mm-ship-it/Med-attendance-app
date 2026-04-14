import streamlit as st
import psycopg2
from psycopg2.extras import DictCursor
import os
from datetime import datetime, timedelta
import pytz
import pandas as pd

# 1. データベース接続関数（utils.pyがない場合はここに記述）
def get_db_connection():
    return psycopg2.connect(os.environ.get('SUPABASE_URI'))

# タイムゾーン設定
tokyo = pytz.timezone('Asia/Tokyo')
today = datetime.now(tokyo).date()

# --- メイン画面の処理（既存の講義予定表示など） ---
st.title("🩺 Med-Attendance")

# (ここに以前からあるカレンダー表示などのコードが入る)

# --- 💰 サイドバー：給料・実績集計 ---
st.sidebar.title("Dashboard")
st.sidebar.divider()
st.sidebar.subheader("💸 給与・報酬状況")

try:
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            # ① 今月の稼ぎ（来月支給予定）
            first_day_this_month = today.replace(day=1)
            cur.execute("""
                SELECT job_name, SUM(pay_amount) as total 
                FROM work_results 
                WHERE work_date >= %s AND work_date <= %s 
                GROUP BY job_name
            """, (first_day_this_month, today))
            this_month_data = cur.fetchall()

            # ② 先月の稼ぎ（今月の支給額：10日/25日払）
            last_month_end = first_day_this_month - timedelta(days=1)
            last_month_start = last_month_end.replace(day=1)
            cur.execute("""
                SELECT SUM(pay_amount) as total 
                FROM work_results 
                WHERE work_date >= %s AND work_date <= %s
            """, (last_month_start, last_month_end))
            last_month_row = cur.fetchone()
            last_month_total = last_month_row['total'] if last_month_row['total'] else 0

    # --- 表示部分 ---
    total_earned = sum(row['total'] for row in this_month_data)
    
    # メインの数字
    st.sidebar.metric(f"{today.month}月の稼ぎ合計", f"¥{total_earned:,}")
    
    # 内訳
    for row in this_month_data:
        st.sidebar.caption(f" ・{row['job_name']}: ¥{row['total']:,}")

    st.sidebar.write("") # スペース

    # 今月もらえる予定の額（先月頑張った分）
    st.sidebar.info(f"📅 今月の支給予定: ¥{last_month_total:,}")
    st.sidebar.caption(f"※{last_month_start.month}月実績の合計")

except Exception as e:
    st.sidebar.error(f"給与データ取得エラー: {e}")

# --- 📅 以降、既存の予定表示ロジック ---
