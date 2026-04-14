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
st.set_page_config(page_title="Med-Attendance", page_icon="🩺", layout="wide")

# --- 💰 サイドバー：給料・実績集計（維持） ---
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
            last_month_total = cur.fetchone()['total'] or 0

    # サイドバー表示
    total_earned = sum(row['total'] for row in this_month_data)
    st.sidebar.metric(f"{today.month}月の稼ぎ合計", f"¥{total_earned:,}")
    for row in this_month_data:
        st.sidebar.caption(f" ・{row['job_name']}: ¥{row['total']:,}")

    st.sidebar.write("") 
    st.sidebar.info(f"📅 今月の支給予定: ¥{last_month_total:,}")

except Exception as e:
    st.sidebar.error(f"給与取得エラー: {e}")


# --- 🗓 メイン画面：出欠統計・今日の予定 ---
st.title("🩺 Med-Attendance System")

# --- 📊 【復活】出席日数・統計セクション ---
st.subheader("📊 出欠統計（通年）")
try:
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            # 全コマ数、出席、欠席、休講のカウント
            cur.execute("SELECT status, COUNT(*) as count FROM attendance GROUP BY status")
            stats = {row['status']: row['count'] for row in cur.fetchall()}
            
            total_classes = sum(stats.values())
            attended = stats.get('出席', 0)
            absent = stats.get('欠席', 0)
            cancelled = stats.get('休講', 0)
            
            # 統計表示（メトリクス）
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("総コマ数", f"{total_classes} 回")
            m2.metric("出席数", f"{attended} 回", delta=f"{(attended/total_classes*100):.1f}%" if total_classes else "0%")
            m3.metric("欠席数", f"{absent} 回", delta=f"-{absent}", delta_color="inverse")
            # 欠席可能回数の計算（例：各科目4回まで、全体で20回まで等、運用に合わせ調整可能）
            remaining = max(0, 20 - absent) # ここでは仮に年間20回までとしています
            m4.metric("残り欠席可能(目安)", f"{remaining} 回", help="年間合計の欠席許容目安です")

except Exception as e:
    st.error(f"統計取得エラー: {e}")

st.divider()

# --- 📅 今日の予定と出欠登録 ---
st.subheader(f"📅 {today.strftime('%Y/%m/%d')} の予定")

try:
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            # 今日の講義予定
            cur.execute("SELECT id, period, subject_name, status FROM attendance WHERE date = %s ORDER BY period ASC", (today.isoformat(),))
            lectures = cur.fetchall()
            
            # 今日の生活予定
            cur.execute("SELECT detail, start_time, end_time FROM lifestyle_schedules WHERE event_date = %s ORDER BY start_time ASC", (today.isoformat(),))
            lifestyles = cur.fetchall()

    col1, col2 = st.columns([3, 2])

    with col1:
        st.markdown("#### 📚 大学の講義 & 出欠登録")
        if lectures:
            for lec in lectures:
                # 講義ごとの登録カード
                with st.expander(f"{lec['period']}限: {lec['subject_name']} （現在の状態: {lec['status']}）", expanded=True):
                    c1, c2, c3, c4 = st.columns(4)
                    # ステータス更新ボタン
                    if c1.button("✅ 出席", key=f"att_{lec['id']}"):
                        with get_db_connection() as conn:
                            with conn.cursor() as cur:
                                cur.execute("UPDATE attendance SET status = '出席' WHERE id = %s", (lec['id'],))
                            conn.commit()
                        st.rerun()
                    if c2.button("❌ 欠席", key=f"abs_{lec['id']}"):
                        with get_db_connection() as conn:
                            with conn.cursor() as cur:
                                cur.execute("UPDATE attendance SET status = '欠席' WHERE id = %s", (lec['id'],))
                            conn.commit()
                        st.rerun()
                    if c3.button("💤 休講", key=f"can_{lec['id']}"):
                        with get_db_connection() as conn:
                            with conn.cursor() as cur:
                                cur.execute("UPDATE attendance SET status = '休講' WHERE id = %s", (lec['id'],))
                            conn.commit()
                        st.rerun()
                    if c4.button("⏳ 予定", key=f"rst_{lec['id']}"):
                        with get_db_connection() as conn:
                            with conn.cursor() as cur:
                                cur.execute("UPDATE attendance SET status = '予定' WHERE id = %s", (lec['id'],))
                            conn.commit()
                        st.rerun()
        else:
            st.info("今日の講義予定はありません。")

    with col2:
        st.markdown("#### 🏠 その他の予定")
        if lifestyles:
            for l in lifestyles:
                start_str = l['start_time'].strftime('%H:%M') if l['start_time'] else ""
                end_str = f"〜{l['end_time'].strftime('%H:%M')}" if l['end_time'] else ""
                time_range = f"{start_str}{end_str}" if start_str else "時間指定なし"
                st.warning(f"**{time_range}**\n\n{l['detail']}")
        else:
            st.info("部活やバイトの予定はありません。")

except Exception as e:
    st.error(f"予定データ取得エラー: {e}")
