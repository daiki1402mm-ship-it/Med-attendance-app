import streamlit as st
import psycopg2
from psycopg2.extras import DictCursor
import os
from datetime import datetime, timedelta
import pytz
import pandas as pd
import math

# 1. データベース接続
def get_db_connection():
    return psycopg2.connect(os.environ.get('SUPABASE_URI'))

tokyo = pytz.timezone('Asia/Tokyo')
today = datetime.now(tokyo).date()

st.set_page_config(page_title="Med-Attendance Pro", page_icon="🩺", layout="wide")

# --- サイドバー：メニュー切り替え ---
st.sidebar.title("🏥 統合管理メニュー")
menu = st.sidebar.radio(
    "表示切り替え",
    ["今日の予定 & 出欠登録", "科目別・出席状況統計", "給与・報酬管理", "テスト・提出物一覧", "講義予定の一括登録"]
)

st.sidebar.divider()

# --- サイドバー共通：簡易給与表示（常に表示） ---
try:
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            first_day = today.replace(day=1)
            cur.execute("SELECT SUM(pay_amount) as total FROM work_results WHERE work_date >= %s", (first_day.isoformat(),))
            total_earned = cur.fetchone()['total'] or 0
            st.sidebar.metric(f"{today.month}月の暫定給与", f"¥{total_earned:,}")
except: pass

# ==========================================
# 1. 今日の予定 & 出欠登録
# ==========================================
if menu == "今日の予定 & 出欠登録":
    st.header(f"📅 {today.strftime('%Y/%m/%d')} の予定")
    
    try:
        with get_db_connection() as conn:
            with conn.cursor(cursor_factory=DictCursor) as cur:
                cur.execute("SELECT id, period, subject_name, status FROM attendance WHERE date = %s ORDER BY period ASC", (today.isoformat(),))
                lectures = cur.fetchall()
                cur.execute("SELECT detail, start_time, end_time FROM lifestyle_schedules WHERE event_date = %s ORDER BY start_time ASC", (today.isoformat(),))
                lifestyles = cur.fetchall()

        col1, col2 = st.columns([3, 2])
        with col1:
            st.subheader("📚 今日の講義")
            if lectures:
                for lec in lectures:
                    with st.expander(f"{lec['period']}限: {lec['subject_name']} [{lec['status']}]", expanded=True):
                        c1, c2, c3, c4 = st.columns(4)
                        for label, status in zip(["✅出席", "❌欠席", "💤休講", "⏳予定"], ["出席", "欠席", "休講", "予定"]):
                            if c1.button(label, key=f"btn_{lec['id']}_{status}"):
                                with get_db_connection() as conn:
                                    with conn.cursor() as update_cur:
                                        update_cur.execute("UPDATE attendance SET status = %s WHERE id = %s", (status, lec['id']))
                                    conn.commit()
                                st.rerun()
            else: st.info("今日の講義はありません。")

        with col2:
            st.subheader("🏠 生活・バイト予定")
            if lifestyles:
                for l in lifestyles:
                    st.warning(f"**{l['start_time'].strftime('%H:%M') if l['start_time'] else ''}〜** : {l['detail']}")
            else: st.info("予定なし")
    except Exception as e: st.error(e)

# ==========================================
# 2. 科目別・出席状況統計 (Pass/Fail 判定)
# ==========================================
elif menu == "科目別・出席状況統計":
    st.header("📊 科目別・出席状況統計")
    st.info("💡 条件: 出席率 66.7% ($2/3$) 以上 ＋ 試験 60% 以上で単位取得")
    
    try:
        with get_db_connection() as conn:
            with conn.cursor(cursor_factory=DictCursor) as cur:
                # 科目ごとの統計を取得
                cur.execute("""
                    SELECT subject_name, 
                           COUNT(*) FILTER (WHERE status = '出席') as attended,
                           COUNT(*) FILTER (WHERE status = '欠席') as absent,
                           COUNT(*) FILTER (WHERE status IN ('出席', '欠席', '予定')) as total_count
                    FROM attendance 
                    GROUP BY subject_name
                """)
                stats = cur.fetchall()

        if stats:
            for s in stats:
                total = s['total_count']
                attended = s['attended']
                absent = s['absent']
                # 出席率計算
                rate = (attended / total * 100) if total > 0 else 0
                # 必要出席数 (2/3)
                required = math.ceil(total * (2/3))
                safe_absent = total - required
                
                with st.container():
                    c1, c2, c3 = st.columns([2, 3, 1])
                    c1.markdown(f"### {s['subject_name']}")
                    # プログレスバー
                    c2.progress(rate / 100)
                    # 判定
                    if absent > safe_absent:
                        c3.error(f"留年危機\n(欠席:{absent})")
                    else:
                        c3.success(f"OK (残り欠席:{safe_absent - absent}回)")
                    
                    st.caption(f"全{total}コマ | 出席: {attended} | 欠席: {absent} | 現在の出席率: {rate:.1f}% (必要: {required}回)")
                    st.divider()
        else: st.info("データがありません。")
    except Exception as e: st.error(e)

# ==========================================
# 3. 給与・報酬管理
# ==========================================
elif menu == "給与・報酬管理":
    st.header("💰 給与・報酬ダッシュボード")
    # (以前作成した詳細な給与集計ロジックをここに配置)
    # 今月の内訳表示、先月（今月支給）の確定額表示など
    st.success("LINEでの実績入力がここにリアルタイム反映されます。")

# ==========================================
# 4. テスト・提出物一覧
# ==========================================
elif menu == "テスト・提出物一覧":
    st.header("📝 テスト・提出物管理")
    try:
        with get_db_connection() as conn:
            with conn.cursor(cursor_factory=DictCursor) as cur:
                cur.execute("SELECT subject_name, content, deadline FROM assignments WHERE is_completed = FALSE ORDER BY deadline ASC")
                tasks = cur.fetchall()
        if tasks:
            st.table(pd.DataFrame(tasks))
        else: st.info("予定されているタスクはありません。")
    except Exception as e: st.error(e)

# ==========================================
# 5. 講義予定の一括登録
# ==========================================
elif menu == "講義予定の一括登録":
    st.header("🗓 講義予定の一括登録")
    st.write("曜日ごとの固定コマを期間指定で登録します。")
    with st.form("bulk_form"):
        subject = st.text_input("科目名")
        period = st.selectbox("時限", [1, 2, 3, 4, 5, 6])
        dow = st.selectbox("曜日", ["月", "火", "水", "木", "金", "土"])
        start_date = st.date_input("開始日")
        end_date = st.date_input("終了日")
        
        if st.form_submit_button("一括登録実行"):
            # ここに日付ループでのINSERT処理
            st.success(f"{subject} を登録しました（開発中）")
