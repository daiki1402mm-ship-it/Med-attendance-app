import streamlit as st
import psycopg2
from psycopg2.extras import DictCursor
from datetime import datetime
import pytz

# 1. データベース接続設定
def get_connection():
    # StreamlitのSecrets管理に保存したSUPABASE_URIを使用
    return psycopg2.connect(st.secrets["SUPABASE_URI"])

st.set_page_config(page_title="スマート出欠管理システム", layout="centered")
st.title("📅 出欠管理ダッシュボード")

# 2. 日付選択機能
st.subheader("表示する日付を選択")
now = datetime.now(pytz.timezone('Asia/Tokyo'))
selected_date = st.date_input(
    "日付を選択してください",
    value=now.date(),
    help="過去の修正や未来の予定確認が可能です。"
)

target_date_str = selected_date.strftime('%Y-%m-%d')
display_date = selected_date.strftime('%m月%d日')

# 3. スケジュール取得と表示
try:
    conn = get_connection()
    cur = conn.cursor(cursor_factory=DictCursor)

    # 選択された日の講義を取得
    cur.execute(
        "SELECT id, period, subject_name, status FROM attendance WHERE date = %s ORDER BY period ASC",
        (target_date_str,)
    )
    lectures = cur.fetchall()

    st.write(f"### {display_date} のスケジュール")

    if not lectures:
        st.info(f"{display_date} の講義予定は登録されていません。")
    else:
        for lecture in lectures:
            # 1行を3つのカラムに分割して表示
            col1, col2, col3 = st.columns([1, 2, 4])
            
            with col1:
                st.write(f"**{lecture['period']}限**")
            
            with col2:
                st.write(f"**{lecture['subject_name']}**")
                # 現在のステータスを表示
                status = lecture['status']
                if status == '出席':
                    st.success(status)
                elif status == '欠席':
                    st.error(status)
                elif status == '休講':
                    st.warning(status)
                else:
                    st.info("未登録")

            with col3:
                # 更新ボタン
                b_cols = st.columns(3)
                if b_cols[0].button("出席", key=f"att_{lecture['id']}"):
                    cur.execute("UPDATE attendance SET status = '出席' WHERE id = %s", (lecture['id'],))
                    conn.commit()
                    st.rerun()
                
                if b_cols[1].button("欠席", key=f"abs_{lecture['id']}"):
                    cur.execute("UPDATE attendance SET status = '欠席' WHERE id = %s", (lecture['id'],))
                    conn.commit()
                    st.rerun()
                
                if b_cols[2].button("休講", key=f"can_{lecture['id']}"):
                    cur.execute("UPDATE attendance SET status = '休講' WHERE id = %s", (lecture['id'],))
                    conn.commit()
                    st.rerun()
            st.divider()

    cur.close()
    conn.close()

except Exception as e:
    st.error(f"データベース接続エラー: {e}")

# 4. (任意) 統計情報や一括登録機能などをここに配置
