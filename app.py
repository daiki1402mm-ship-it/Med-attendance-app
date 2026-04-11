import streamlit as st
import psycopg2
from psycopg2.extras import DictCursor
import pandas as pd
from datetime import date, datetime
import requests
import json

# --- 1. Supabaseへのセキュアな接続 ---
DB_URI = st.secrets["SUPABASE_URI"]

def get_db_connection():
    conn = psycopg2.connect(DB_URI)
    return conn

# --- 2. データベースの初期構築（PostgreSQL仕様） ---
@st.cache_resource
def init_db():
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute('''CREATE TABLE IF NOT EXISTS subjects (id SERIAL PRIMARY KEY, subject_name TEXT UNIQUE, target_score INTEGER DEFAULT 60)''')
                cursor.execute('''CREATE TABLE IF NOT EXISTS attendance (id SERIAL PRIMARY KEY, date TEXT, period INTEGER, subject_name TEXT, status TEXT)''')
                cursor.execute('''CREATE TABLE IF NOT EXISTS tasks (id SERIAL PRIMARY KEY, task_name TEXT, task_date TEXT, task_type TEXT)''')
                cursor.execute('''CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)''')
                
                subjects = ['小児科学', '整形外科学', '歯科口腔外科学', '泌尿器科学', '老年医学', '耳鼻咽喉科学', '眼科学', '衛生学・公衆衛生学', '産科婦人科学', '皮膚科学', '脳神経外科学', '症候学講義', '人間と医療', '医療と法律', '東洋医学']
                for sub in subjects:
                    cursor.execute('INSERT INTO subjects (subject_name) VALUES (%s) ON CONFLICT (subject_name) DO NOTHING', (sub,))
                
                tasks = [
                    ('CBT本試験(1日目)', '2026-09-24', '試験'), ('CBT本試験(2日目)', '2026-09-25', '試験'),
                    ('OSCE本試験', '2026-10-01', '試験'), ('PreBSL', '2026-12-09', '実習'),
                    ('PreBSL', '2026-12-10', '実習'), ('PreBSL', '2026-12-11', '実習'),
                    ('PreBSL', '2026-12-14', '実習'), ('PreBSL', '2026-12-15', '実習'),
                    ('導入型臨床実習ガイダンス・白衣授与式', '2026-12-18', 'その他')
                ]
                for t_name, t_date, t_type in tasks:
                    cursor.execute('SELECT 1 FROM tasks WHERE task_name = %s AND task_date = %s', (t_name, t_date))
                    if not cursor.fetchone():
                        cursor.execute('INSERT INTO tasks (task_name, task_date, task_type) VALUES (%s, %s, %s)', (t_name, t_date, t_type))
            conn.commit()
        return True
    except Exception as e:
        st.error(f"データベースの初期化に失敗しました: {e}")
        return False

db_initialized = init_db()

# --- 3. 設定の読み書きとデータ取得ユーティリティ ---
def load_settings():
    settings = {}
    try:
        with get_db_connection() as conn:
            with conn.cursor(cursor_factory=DictCursor) as cursor:
                cursor.execute("SELECT key, value FROM settings")
                for row in cursor.fetchall():
                    settings[row['key']] = row['value']
    except Exception:
        pass
    return settings

def save_setting(key, value):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("INSERT INTO settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", (key, value))
        conn.commit()

def fetch_dataframe(query, params=None):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(query, params)
            data = cursor.fetchall()
            cols = [desc[0] for desc in cursor.description]
            return pd.DataFrame(data, columns=cols)

# --- 4. LINE Messaging API ---
def send_line_message(message, access_token, user_id):
    url = "https://api.line.me/v2/bot/message/push"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {access_token}"}
    data = {"to": user_id, "messages": [{"type": "text", "text": message}]}
    try:
        response = requests.post(url, headers=headers, data=json.dumps(data), timeout=10)
        return response.status_code == 200, response.text
    except Exception as e:
        return False, str(e)

# --- 5. アプリケーションUI ---
st.set_page_config(page_title="医学科4年 時間割・出欠管理", layout="wide", initial_sidebar_state="expanded")
st.title("🩺 医学科4年 時間割・出欠管理アプリ")

if not db_initialized:
    st.stop()

menu = st.sidebar.selectbox("メニュー", ["出欠登録", "出席率・成績確認", "試験・提出物管理", "設定 (LINE通知)"])

try:
    subjects_df = fetch_dataframe("SELECT subject_name FROM subjects")
    subject_list = subjects_df['subject_name'].tolist()
except Exception as e:
    st.error(f"科目データの読み込みに失敗しました: {e}")
    subject_list = []

if menu == "出欠登録":
    st.header("📝 本日の出欠登録")
    selected_date = st.date_input("日付を選択", date.today())
    
    with st.form("attendance_form"):
        st.markdown(f"**{selected_date} の記録**")
        records = []
        for i in range(1, 7):
            col1, col2, col3 = st.columns([1, 3, 3])
            with col1:
                st.markdown(f"**{i}時限**")
            with col2:
                selected_sub = st.selectbox("科目", ["(予定なし)"] + subject_list, key=f"sub_{i}", label_visibility="collapsed")
            with col3:
                status = st.radio("状態", ["出席", "欠席", "休講"], key=f"stat_{i}", horizontal=True, label_visibility="collapsed")
            
            if selected_sub != "(予定なし)":
                records.append((str(selected_date), i, selected_sub, status))
        
        st.markdown("---")
        submitted = st.form_submit_button("記録を保存する")
        
        if submitted:
            if not records:
                st.warning("登録する科目が選択されていません。")
            else:
                try:
                    with get_db_connection() as conn:
                        with conn.cursor() as cursor:
                            for rec in records:
                                cursor.execute("DELETE FROM attendance WHERE date = %s AND period = %s", (rec[0], rec[1]))
                                cursor.execute("INSERT INTO attendance (date, period, subject_name, status) VALUES (%s, %s, %s, %s)", rec)
                        conn.commit()
                    
                    st.success("出欠を保存しました！")
                    st.balloons()
                    
                    if selected_date.weekday() == 4:
                        settings = load_settings()
                        token = settings.get('LINE_TOKEN', '')
                        uid = settings.get('LINE_USER_ID', '')
                        if token and uid:
                            reward_msg = "【💮1週間お疲れ様！】\n今週の講義も無事終了！よく頑張りました。\n週末はカルカソンヌでもプレイして、しっかりリフレッシュしてね🎲"
                            send_line_message(reward_msg, token, uid)
                except Exception as e:
                    st.error(f"保存中にエラーが発生しました: {e}")

elif menu == "出席率・成績確認":
    st.header("📊 出席率・単位取得判定")
    st.info("💡 条件: 休講を除外した全実施回数の2/3（66.7%）以上出席 ＆ 試験60点以上")
    try:
        query = """
        SELECT 
            subject_name as "科目名", 
            COUNT(CASE WHEN status != '休講' THEN 1 END) as "実施回数(分母)", 
            COUNT(CASE WHEN status = '出席' THEN 1 END) as "出席回数", 
            COUNT(CASE WHEN status = '欠席' THEN 1 END) as "欠席回数", 
            COUNT(CASE WHEN status = '休講' THEN 1 END) as "休講回数" 
        FROM attendance 
        GROUP BY subject_name
        """
        df_att = fetch_dataframe(query)
        
        if not df_att.empty and df_att['科目名'].notna().any():
            df_att['出席率(%)'] = df_att.apply(lambda row: round((row['出席回数'] / row['実施回数(分母)'] * 100), 1) if row['実施回数(分母)'] > 0 else 0.0, axis=1)
            df_att['判定(出席)'] = df_att['出席率(%)'].apply(lambda x: '🟢 クリア' if x >= 66.7 else '🔴 要注意')
            st.dataframe(df_att.sort_values('出席率(%)', ascending=True), use_container_width=True, hide_index=True)
        else:
            st.write("まだ出欠データが登録されていません。")
    except Exception as e:
        st.error(f"データの集計中にエラーが発生しました: {e}")

elif menu == "試験・提出物管理":
    st.header("⏳ 試験・提出物カウンター")
    with st.expander("➕ 新しいタスク・試験を追加する", expanded=False):
        with st.form("task_form"):
            t_name = st.text_input("タスク名 (例: 整形外科学 レポート)")
            t_date = st.date_input("期日・実施日")
            t_type = st.selectbox("種類", ["試験", "提出物", "実習", "その他"])
            if st.form_submit_button("追加"):
                if t_name.strip() == "":
                    st.error("タスク名を入力してください。")
                else:
                    with get_db_connection() as conn:
                        with conn.cursor() as cursor:
                            cursor.execute("INSERT INTO tasks (task_name, task_date, task_type) VALUES (%s, %s, %s)", (t_name, str(t_date), t_type))
                        conn.commit()
                    st.success(f"「{t_name}」を追加しました！")
                    st.rerun()

    st.markdown("---")
    st.subheader("今後のスケジュール")
    today = date.today()
    try:
        df_tasks = fetch_dataframe("SELECT id, task_name, task_date, task_type FROM tasks ORDER BY task_date")
        if not df_tasks.empty:
            for index, row in df_tasks.iterrows():
                target_date = datetime.strptime(row['task_date'], '%Y-%m-%d').date()
                delta = (target_date - today).days
                if delta > 0:
                    st.info(f"📅 **{row['task_name']}** ({row['task_type']}) \n\n期日: {row['task_date']} ➡ **あと {delta} 日**")
                elif delta == 0:
                    st.error(f"🚨 **{row['task_name']}** ({row['task_type']}) は **本日** です！")
                else:
                    st.write(f"✅ ~~{row['task_name']} (終了: {row['task_date']})~~")
        else:
            st.write("予定されているタスクはありません。")
    except Exception as e:
        st.error("スケジュールの読み込みに失敗しました。")

elif menu == "設定 (LINE通知)":
    st.header("⚙️ LINE Messaging API 設定")
    settings = load_settings()
    with st.form("line_settings_form"):
        line_token = st.text_input("チャネルアクセストークン", value=settings.get('LINE_TOKEN', ''), type="password")
        user_id = st.text_input("あなたのユーザーID", value=settings.get('LINE_USER_ID', ''), type="password")
        if st.form_submit_button("設定を保存する"):
            save_setting('LINE_TOKEN', line_token.strip())
            save_setting('LINE_USER_ID', user_id.strip())
            st.success("LINE設定を保存しました。")
            st.rerun()
    st.markdown("---")
    if st.button("テスト通知を送信する"):
        current_settings = load_settings()
        token = current_settings.get('LINE_TOKEN', '')
        uid = current_settings.get('LINE_USER_ID', '')
        if token and uid:
            with st.spinner("送信中..."):
                success, msg = send_line_message("【出席管理アプリ】設定完了！\nSupabase(PostgreSQL)との連携が正常に行われました。", token, uid)
            if success:
                st.success("LINEにテストメッセージを送信しました！スマホを確認してください。")
            else:
                st.error(f"送信失敗: {msg}")
        else:
            st.error("上のフォームに設定を保存してください。")
