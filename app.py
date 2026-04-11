import streamlit as st
import psycopg2
from psycopg2.extras import DictCursor
import pandas as pd
from datetime import date, datetime
import requests
import json

DB_URI = st.secrets["SUPABASE_URI"]

def get_db_connection():
    return psycopg2.connect(DB_URI)

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
            conn.commit()
        return True
    except Exception:
        return False

db_initialized = init_db()

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

def fetch_dataframe(query, params=None):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(query, params)
            data = cursor.fetchall()
            cols = [desc[0] for desc in cursor.description]
            return pd.DataFrame(data, columns=cols)

st.set_page_config(page_title="医学科4年 時間割・出欠管理", layout="wide", initial_sidebar_state="expanded")
st.title("🩺 医学科4年 時間割・出欠管理アプリ")

if not db_initialized:
    st.stop()

# 💡 新しく「時間割の一括登録」メニューを追加しました！
menu = st.sidebar.selectbox("メニュー", ["出欠登録", "出席率・成績確認", "試験・提出物管理", "時間割の一括登録", "設定 (LINE通知)"])

try:
    subjects_df = fetch_dataframe("SELECT subject_name FROM subjects")
    subject_list = subjects_df['subject_name'].tolist()
except Exception:
    subject_list = []

if menu == "出欠登録":
    st.header("📝 本日の出欠登録")
    selected_date = st.date_input("日付を選択", date.today())
    with st.form("attendance_form"):
        records = []
        for i in range(1, 7):
            col1, col2, col3 = st.columns([1, 3, 3])
            with col1: st.markdown(f"**{i}時限**")
            with col2: selected_sub = st.selectbox("科目", ["(予定なし)"] + subject_list, key=f"sub_{i}", label_visibility="collapsed")
            with col3: status = st.radio("状態", ["出席", "欠席", "休講"], key=f"stat_{i}", horizontal=True, label_visibility="collapsed")
            if selected_sub != "(予定なし)":
                records.append((str(selected_date), i, selected_sub, status))
        if st.form_submit_button("記録を保存する"):
            if records:
                with get_db_connection() as conn:
                    with conn.cursor() as cursor:
                        for rec in records:
                            cursor.execute("DELETE FROM attendance WHERE date = %s AND period = %s", (rec[0], rec[1]))
                            cursor.execute("INSERT INTO attendance (date, period, subject_name, status) VALUES (%s, %s, %s, %s)", rec)
                    conn.commit()
                st.success("出欠を保存しました！")
                st.balloons()

# 💡 ここが追加された一括登録画面です
elif menu == "時間割の一括登録":
    st.header("📂 時間割テキストの一括登録")
    st.info("💡 下の枠に、作成したカンマ区切りのテキストを貼り付けるだけで、1ヶ月分の予定を一瞬でデータベースに登録できます。")
    
    csv_text = st.text_area("ここにデータを貼り付けてください", height=300)
    
    if st.button("このデータで一括登録する"):
        if csv_text.strip():
            try:
                lines = csv_text.strip().split('\n')
                header = lines[0].split(',')
                if 'date' not in header or 'period' not in header or 'subject_name' not in header:
                    st.error("1行目は必ず `date,period,subject_name` にしてください。")
                else:
                    date_idx = header.index('date')
                    period_idx = header.index('period')
                    sub_idx = header.index('subject_name')
                    
                    with st.spinner("データベースに書き込み中..."):
                        with get_db_connection() as conn:
                            with conn.cursor() as cursor:
                                for line in lines[1:]:
                                    if not line.strip(): continue
                                    cols = line.split(',')
                                    d = cols[date_idx].strip()
                                    p = int(cols[period_idx].strip())
                                    s = cols[sub_idx].strip()
                                    
                                    # 同じ日時の古い予定があれば消して、「予定」というステータスで登録する
                                    cursor.execute("DELETE FROM attendance WHERE date = %s AND period = %s", (d, p))
                                    cursor.execute("INSERT INTO attendance (date, period, subject_name, status) VALUES (%s, %s, %s, '予定')", (d, p, s))
                            conn.commit()
                    st.success("✨ 時間割の一括登録が完了しました！LINE Botで予定を聞いてみてください！")
                    st.balloons()
            except Exception as e:
                st.error(f"エラーが発生しました。テキストの形がおかしくないか確認してください: {e}")

elif menu == "出席率・成績確認":
    st.header("📊 出席率・単位取得判定")
    df_att = fetch_dataframe("SELECT subject_name as 科目名, COUNT(CASE WHEN status != '休講' AND status != '予定' THEN 1 END) as 実施回数, COUNT(CASE WHEN status = '出席' THEN 1 END) as 出席回数 FROM attendance GROUP BY subject_name")
    if not df_att.empty and df_att['科目名'].notna().any():
        df_att['出席率(%)'] = df_att.apply(lambda row: round((row['出席回数'] / row['実施回数'] * 100), 1) if row['実施回数'] > 0 else 0.0, axis=1)
        st.dataframe(df_att)
    else:
        st.write("データがありません。")

elif menu == "試験・提出物管理":
    st.header("⏳ 試験・提出物カウンター")
    st.write("今後のスケジュールが表示されます（省略中）")

elif menu == "設定 (LINE通知)":
    st.header("⚙️ LINE Messaging API 設定")
    st.write("（設定画面省略中）")
