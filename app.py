%%writefile app.py
import streamlit as st
import sqlite3
import pandas as pd
from datetime import date, datetime
import requests
import json

DB_PATH = 'attendance_manager.db'

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def load_settings():
    settings = {}
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT key, value FROM settings")
        for row in cursor.fetchall():
            settings[row['key']] = row['value']
    return settings

def save_setting(key, value):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
        conn.commit()

def send_line_message(message, access_token, user_id):
    url = "https://api.line.me/v2/bot/message/push"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {access_token}"}
    data = {"to": user_id, "messages": [{"type": "text", "text": message}]}
    try:
        response = requests.post(url, headers=headers, data=json.dumps(data), timeout=10)
        return response.status_code == 200, response.text
    except Exception as e:
        return False, str(e)

st.set_page_config(page_title="医学科4年 時間割・出欠管理", layout="wide", initial_sidebar_state="expanded")
st.title("🩺 医学科4年 時間割・出欠管理アプリ")

menu = st.sidebar.selectbox("メニュー", ["出欠登録", "出席率・成績確認", "試験・提出物管理", "設定 (LINE通知)"])

with get_db_connection() as conn:
    subjects_df = pd.read_sql_query("SELECT subject_name FROM subjects", conn)
subject_list = subjects_df['subject_name'].tolist()

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
                with get_db_connection() as conn:
                    cursor = conn.cursor()
                    for rec in records:
                        cursor.execute("DELETE FROM attendance WHERE date = ? AND period = ?", (rec[0], rec[1]))
                        cursor.execute("INSERT INTO attendance (date, period, subject_name, status) VALUES (?, ?, ?, ?)", rec)
                    conn.commit()
                
                # ★ご褒美システム1：風船を飛ばす
                st.success("出欠を保存しました！")
                st.balloons()
                
                # ★ご褒美システム2：金曜日ならLINEに労いメッセージを送信
                if selected_date.weekday() == 4:
                    settings = load_settings()
                    token = settings.get('LINE_TOKEN', '')
                    uid = settings.get('LINE_USER_ID', '')
                    if token and uid:
                        reward_msg = "【💮1週間お疲れ様！】\n今週の講義も無事終了！よく頑張りました。\n週末はカルカソンヌでもプレイして、しっかりリフレッシュしてね🎲"
                        send_line_message(reward_msg, token, uid)

elif menu == "出席率・成績確認":
    st.header("📊 出席率・単位取得判定")
    st.info("💡 条件: 休講を除外した全実施回数の2/3（66.7%）以上出席 ＆ 試験60点以上")
    with get_db_connection() as conn:
        query = """SELECT subject_name as "科目名", COUNT(CASE WHEN status != '休講' THEN 1 END) as "実施回数(分母)", COUNT(CASE WHEN status = '出席' THEN 1 END) as "出席回数", COUNT(CASE WHEN status = '欠席' THEN 1 END) as "欠席回数", COUNT(CASE WHEN status = '休講' THEN 1 END) as "休講回数" FROM attendance GROUP BY subject_name"""
        df_att = pd.read_sql_query(query, conn)
    
    if not df_att.empty:
        df_att['出席率(%)'] = df_att.apply(lambda row: round((row['出席回数'] / row['実施回数(分母)'] * 100), 1) if row['実施回数(分母)'] > 0 else 0.0, axis=1)
        df_att['判定(出席)'] = df_att['出席率(%)'].apply(lambda x: '🟢 クリア' if x >= 66.7 else '🔴 要注意')
        st.dataframe(df_att.sort_values('出席率(%)', ascending=True), use_container_width=True, hide_index=True)
    else:
        st.write("まだ出欠データが登録されていません。")

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
                        cursor = conn.cursor()
                        cursor.execute("INSERT INTO tasks (task_name, task_date, task_type) VALUES (?, ?, ?)", (t_name, str(t_date), t_type))
                        conn.commit()
                    st.success(f"「{t_name}」を追加しました！")
                    st.rerun()

    st.markdown("---")
    st.subheader("今後のスケジュール")
    today = date.today()
    with get_db_connection() as conn:
        df_tasks = pd.read_sql_query("SELECT id, task_name, task_date, task_type FROM tasks ORDER BY task_date", conn)
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
            success, msg = send_line_message("【出席管理アプリ】設定完了！\nシステムとの連携が正常に行われました。", token, uid)
            if success:
                st.success("LINEにテストメッセージを送信しました！スマホを確認してください。")
            else:
                st.error(f"送信失敗: {msg}")
        else:
            st.error("上のフォームに設定を保存してください。")
