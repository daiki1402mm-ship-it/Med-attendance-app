import streamlit as st
import os
import re
import psycopg2
from psycopg2.extras import DictCursor
import yfinance as yf 
from datetime import datetime, date, timedelta
import pytz
import pandas as pd
import urllib.request
import urllib.parse  
import json
# 🌟 カレンダーコンポーネントのインポート
from streamlit_calendar import calendar

# 🚨 一番最初（何よりも前）にページ設定を実行する
st.set_page_config(page_title="医学生専用ダッシュボード", layout="wide", page_icon="🩺")

# 📱 iPadの分割メニュー（…）との衝突を回避するため、開閉トグルボタンを常時35ピクセル下にずらすハック
st.markdown("""
    <style>
        /* ① サイドバーが【開いている】ときのボタンを押し下げる */
        [data-testid="stSidebarCollapseButton"] {
            margin-top: 35px !important;
        }
        /* ② サイドバーが【閉じている】ときの最左上のボタン枠ごと強制的に押し下げる */
        [data-testid="stHeader"] {
            padding-top: 35px !important;
        }
        /* ③ ヘッダー全体の高さを調整してロゴやタイトルとのバランスをキープする */
        [data-testid="stAppViewContainer"] {
            padding-top: 35px !important;
        }
    </style>
""", unsafe_allow_html=True)

# 1. データベース接続設定
def get_connection():
    return psycopg2.connect(os.environ.get("SUPABASE_URI") if "SUPABASE_URI" in os.environ else st.secrets["SUPABASE_URI"])

def get_usd_jpy():
    try:
        data = yf.download("JPY=X", period="5d", interval="1d", progress=False)
        if not data.empty:
            close_series = data['Close']
            if isinstance(close_series, pd.DataFrame):
                val = close_series.iloc[-1, 0]
            else:
                val = close_series.iloc[-1]
            if float(val) > 0:
                return float(val)
    except:
        pass

    try:
        url = "https://open.er-api.com/v6/latest/USD"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response:
            res_data = json.loads(response.read().decode())
            rate = res_data["rates"]["JPY"]
            return float(rate)
    except:
        return 0

# 💡 日本語シート名エラーを完全に克服した修正版ロード関数
@st.cache_data(ttl=10)
def load_total_data():
    spreadsheet_id = "13dg65zF2hcsKe42QJ2Fqz9GfXryaw2En4hPJKLG_Yes"
    sheet_name = "統合（税金関連その他）"
    
    encoded_sheet_name = urllib.parse.quote(sheet_name)
    url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/gviz/tq?tqx=out:csv&sheet={encoded_sheet_name}"
    
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response:
            df = pd.read_csv(response)
            return df
    except Exception as e:
        st.error(f"統合シートの読み込みに失敗しました: {e}")
        return pd.DataFrame()

# タイムゾーンと日付の基本設定
tokyo = pytz.timezone('Asia/Tokyo')
today = datetime.now(tokyo).date()

try:
    conn = get_connection()
    cur = conn.cursor(cursor_factory=DictCursor)

    # 🌟 ページ選択肢に「🗓️ 月間スケジュール」を追加
    page = st.sidebar.radio("ページ選択", ["ダッシュボード", "🗓️ 月間スケジュール", "為替分析・円転戦略", "全体統合アナリティクス"])
    st.sidebar.divider()
    # --- サイドバー：設定・進級管理 ---
    st.sidebar.title("⚙️ 設定・進級管理")
    
    # CBT日程の設定
    cur.execute("SELECT value FROM settings WHERE key = 'cbt_date'")
    cbt_res = cur.fetchone()
    current_cbt = datetime.strptime(cbt_res['value'], '%Y-%m-%d').date() if cbt_res else today
    
    new_cbt = st.sidebar.date_input("CBT試験日を設定", value=current_cbt)
    if new_cbt != current_cbt:
        cur.execute("INSERT INTO settings (key, value) VALUES ('cbt_date', %s) ON CONFLICT (key) DO UPDATE SET value = %s", (new_cbt.isoformat(), new_cbt.isoformat()))
        conn.commit(); st.rerun()

    # 📊 出欠統計（厳格な医学生ルール ＋ 出席数合計）
    st.sidebar.divider()
    st.sidebar.subheader("📊 科目別・欠席許容状況")
    cur.execute("""
        SELECT subject_name, COUNT(*) as total, 
               COUNT(CASE WHEN status = '出席' THEN 1 END) as attended,
               COUNT(CASE WHEN status = '欠席' THEN 1 END) as absences 
        FROM attendance 
        WHERE status IN ('予定', '出席', '欠席')
          AND subject_name NOT LIKE '%%医学祭%%'
          AND subject_name NOT LIKE '%%休み%%'
          AND subject_name NOT LIKE '%%休講%%'
        GROUP BY subject_name
    """)
    stats = cur.fetchall()
    
    for s in stats:
        name = s['subject_name']
        if any(k in name for k in ["実習", "臨床"]):
            max_abs = 0
        else:
            max_abs = s['total'] // 3
            
        rem = max_abs - s['absences']
        st.sidebar.write(f"**{name}**")
        color = "red" if rem <= 0 else "orange" if rem == 1 else "green"
        st.sidebar.markdown(f"出席: {s['attended']} / 欠席: {s['absences']} / 可: {max_abs} (残り: <span style='color:{color}; font-weight:bold;'>{rem}</span>)", unsafe_allow_html=True)
        progress = min(s['absences'] / max(max_abs, 1), 1.0) if max_abs > 0 else (1.0 if s['absences'] > 0 else 0.0)
        st.sidebar.progress(progress)

    # ==========================================
    # ページ分岐
    # ==========================================
    if page == "ダッシュボード":

        # --- メイン画面 ---
        days_to_cbt = (new_cbt - today).days
        col_title, col_count = st.columns([2, 1])
        with col_title:
            st.title("👨‍⚕️ 医学生専用ダッシュボード")
        with col_count:
            if days_to_cbt >= 0:
                st.metric(label="⚔️ CBTまであと", value=f"{days_to_cbt} 日")
            else:
                st.success("🎉 CBTお疲れ様でした！")

        st.divider()

        # タブ表示
        tab1, tab2, tab3, tab4, tab5 = st.tabs(["🗓 本日の予定", "📝 提出物", "⚖️ 試験日程", "💰 収支・給与実績", "🚀 一括登録"])

        # --- タブ1: 本日の予定 ---
        with tab1:
            selected_date = st.date_input("表示日を選択", value=today, key="view_date")
            cur.execute("SELECT * FROM attendance WHERE date = %s ORDER BY period ASC", (selected_date.isoformat(),))
            lectures = cur.fetchall()
            cur.execute("SELECT * FROM lifestyle_schedules WHERE event_date = %s ORDER BY start_time ASC", (selected_date.isoformat(),))
            lifestyles = cur.fetchall()

            col_lec, col_life = st.columns([3, 2])
            with col_lec:
                st.subheader("📚 本日の講義")
                if not lectures: st.info("講義予定なし")
                else:
                    occ = {str(r['period']) for r in lectures if r['status'] not in ['休講', '欠席'] and not any(k in r['subject_name'] for k in ["休み", "休講", "祭"])}
                    empty = [p for p in range(1, 7) if str(p) not in occ]
                    if empty: st.write(f"💡 空きコマ: {', '.join(map(str, empty))}限")
                    for l in lectures:
                        with st.container():
                            c1, c2, c3 = st.columns([1, 2, 4])
                            c1.write(f"**{l['period']}限**")
                            c2.write(f"**{l['subject_name']}**\n({l['status']})")
                            b = c3.columns(4)
                            for idx, btn_label in enumerate(["出席", "欠席", "休講", "予定"]):
                                if b[idx].button(btn_label, key=f"btn_{btn_label}_{l['id']}"):
                                    cur.execute("UPDATE attendance SET status = %s WHERE id = %s", (btn_label, l['id'])); conn.commit(); st.rerun()
                            st.divider()

            with col_life:
                st.subheader("🏠 本日の予定")
                if not lifestyles: st.info("予定なし")
                else:
                    for life in lifestyles:
                        start = life['start_time'].strftime('%H:%M') if life['start_time'] else ""
                        end = f"〜{life['end_time'].strftime('%H:%M')}" if life['end_time'] else ""
                        st.warning(f"⏰ {start}{end}\n\n{life['detail']}")
                
                st.divider()
                st.subheader("🔜 今後のお楽しみ・予定")
                cur.execute("""
                    SELECT * FROM lifestyle_schedules 
                    WHERE event_date > %s 
                    ORDER BY event_date ASC, start_time ASC 
                    LIMIT 7
                """, (selected_date.isoformat(),))
                upcoming = cur.fetchall()
                
                if upcoming:
                    for u in upcoming:
                        u_start = u['start_time'].strftime('%H:%M') if u['start_time'] else ""
                        u_time_str = f" {u_start}〜" if u_start else ""
                        st.write(f"・**{u['event_date'].strftime('%m/%d')}**: {u['detail']}{u_time_str}")
                else:
                    st.caption("直近の予定はまだありません。")

        # --- タブ2: 提出物 ---
        with tab2:
            cur.execute("SELECT * FROM assignments WHERE is_completed = FALSE ORDER BY deadline ASC")
            assigns = cur.fetchall()
            if not assigns: st.success("全ての課題が完了しています！")
            else:
                for a in assigns:
                    c1, c2, c3 = st.columns([2, 4, 1])
                    dl_days = (a['deadline'] - today).days
                    if dl_days <= 3: c1.error(f"あと {dl_days} 日")
                    else: c1.warning(f"あと {dl_days} 日")
                    remind_text = f" (🔔 リマインド: {a['remind_date'].strftime('%m/%d')})" if a['remind_date'] else ""
                    c2.write(f"**{a['subject_name']}** : {a['content']}{remind_text}")
                    if c3.button("完了", key=f"cp_{a['id']}"):
                        cur.execute("UPDATE assignments SET is_completed = TRUE WHERE id = %s", (a['id'],)); conn.commit(); st.rerun()

        # --- タブ3: 試験日程 ---
        with tab3:
            cur.execute("SELECT * FROM exams WHERE exam_date >= %s ORDER BY exam_date ASC", (today.isoformat(),))
            exams = cur.fetchall()
            if exams: st.table(pd.DataFrame([dict(e) for e in exams])[['exam_date', 'subject_name', 'location']])
            else: st.info("試験予定なし")

        # --- タブ4: 💰 収支・給与実績 ---
        with tab4:
            st.subheader("🚀 Project Lyra 収益・経費・純利益サマリー")
            
            cur.execute("SELECT * FROM lyra_rewards ORDER BY date DESC")
            lyra_data = cur.fetchall()
            
            cur.execute("SELECT * FROM expenses ORDER BY date DESC")
            expense_data = cur.fetchall()
            
            df_lyra = pd.DataFrame([dict(r) for r in lyra_data]) if lyra_data else pd.DataFrame()
            df_exp = pd.DataFrame([dict(e) for e in expense_data]) if expense_data else pd.DataFrame()
            
            total_jpy = float(df_lyra['amount_jpy'].sum()) if not df_lyra.empty else 0.0
            latest_jpy = float(df_lyra.iloc[0]['amount_jpy']) if not df_lyra.empty else 0.0
            total_exp = float(df_exp['amount'].sum()) if not df_exp.empty else 0.0
            
            net_profit = total_jpy - total_exp
            profit_rate = (net_profit / total_jpy * 100) if total_jpy > 0 else 0.0
            
            c_kpi1, c_kpi2, c_kpi3, c_kpi4 = st.columns(4)
            c_kpi1.metric("総報酬 (円)", f"¥{int(total_jpy):,}")
            c_kpi2.metric("総経費 (累計)", f"¥{int(total_exp):,}")
            c_kpi3.metric("現在純利益", f"¥{int(net_profit):,}", f"利益率 {profit_rate:.1f}%")
            c_kpi4.metric("納税ストック(利益ベース30%)", f"¥{int(max(0.0, net_profit * 0.3)):,}", f"当日分予定: ¥{int(latest_jpy * 0.3):,}")
            
            st.write("---")
            col_graph_reward, col_graph_expense = st.columns(2)
            
            with col_graph_reward:
                st.markdown("📈 **Project Lyra 収益推移**")
                if not df_lyra.empty:
                    st.line_chart(df_lyra.set_index('date')['amount_jpy'])
                    st.caption("💵 報酬明細（直近）")
                    st.dataframe(df_lyra[['date', 'amount_usd', 'amount_jpy', 'status']], use_container_width=True)
                else:
                    st.info("報酬データがありません。")
                    
            with col_graph_expense:
                st.markdown("📊 **経費カテゴリ比率**")
                if not df_exp.empty:
                    df_exp_grouped = df_exp.groupby('category')['amount'].sum().reset_index()
                    st.bar_chart(df_exp_grouped.set_index('category')['amount'])
                    st.caption("🧾 経費明細（直近）")
                    st.dataframe(df_exp[['date', 'category', 'amount', 'detail']], use_container_width=True)
                else:
                    st.info("経費データがありません。")

            st.write("---")
            col_form1, col_form2 = st.columns(2)
            
            with col_form1:
                with st.form("lyra_reward_form"):
                    st.markdown("✨ **Project Lyra 報酬の手動入力**")
                    col_ly1, col_ly2, col_ly3 = st.columns(3)
                    with col_ly1:
                        lyra_form_date = st.date_input("獲得日を選択", value=today, key="lyra_form_date")
                    with col_ly2:
                        lyra_usd = st.number_input("金額 (USD)", min_value=0.0, step=10.0, format="%.2f")
                    with col_ly3:
                        lyra_jpy = st.number_input("確定円転額 (JPY) ※未円転なら0換算", min_value=0, step=1000)
                    submit_lyra = st.form_submit_button("Lyra実績を登録")
                    
                    if submit_lyra:
                        if lyra_usd <= 0 and lyra_jpy <= 0:
                            st.error("金額を入力してください。")
                        else:
                            cur.execute(
                                "INSERT INTO lyra_rewards (date, amount_usd, amount_jpy) VALUES (%s, %s, %s)",
                                (lyra_form_date.isoformat(), lyra_usd, lyra_jpy)
                            )
                            conn.commit()
                            st.success(f"✅ {lyra_form_date.strftime('%m/%d')}分として ${lyra_usd} / ¥{lyra_jpy:,} を登録しました！")
                            st.rerun()
            
            with col_form2:
                with st.form("manual_expense_form"):
                    st.markdown("💸 **経費データの手動入力**")
                    col_ex1, col_ex2, col_ex3 = st.columns(3)
                    with col_ex1:
                        exp_form_date = st.date_input("利用日を選択", value=today, key="exp_form_date")
                    with col_ex2:
                        exp_cat = st.selectbox("カテゴリ", ['医学書・問題集', '交通費', '通信費', '飲食・会議費', '機材・周辺機器', '消耗品費', '家賃・光熱費', 'その他'])
                    with col_ex3:
                        exp_amount = st.number_input("金額 (円)", min_value=0, step=500, key="exp_amount")
                    
                    exp_detail = st.text_input("詳細（内容や店舗名など）", placeholder="イヤーノート、スタバ打ち合わせなど")
                    submit_expense = st.form_submit_button("経費を登録")
                    
                    if submit_expense:
                        if exp_amount <= 0:
                            st.error("0円以上の金額を入力してください。")
                        elif exp_detail.strip() == "":
                            st.error("詳細を入力してください。")
                        else:
                            cur.execute(
                                "INSERT INTO expenses (date, category, amount, detail) VALUES (%s, %s, %s, %s)",
                                (exp_form_date.isoformat(), exp_cat, exp_amount, exp_detail.strip())
                            )
                            conn.commit()
                            st.success(f"✅ {exp_form_date.strftime('%m/%d')}の「{exp_cat}」として ¥{exp_amount:,} を登録しました！")
                            st.rerun()

            st.divider()
            st.subheader("💰 バイト別・月別給与サマリー")
            first_day_year = today.replace(month=1, day=1)
            
            cur.execute("""
                SELECT job_name, pay_amount, work_date 
                FROM work_results 
                WHERE work_date >= %s
            """, (first_day_year.isoformat(),))
            all_work = cur.fetchall()
            
            if not all_work:
                st.info("今年の実績データはまだありません。")
            else:
                df_all = pd.DataFrame([dict(r) for r in all_work])
                df_all['月'] = pd.to_datetime(df_all['work_date']).dt.month
                
                pivot_table = df_all.pivot_table(
                    index='job_name', columns='月', values='pay_amount', aggfunc='sum', fill_value=0
                )
                pivot_table.columns = [f"{c}月" for c in pivot_table.columns]
                pivot_table['年間合計'] = pivot_table.sum(axis=1)
                pivot_table.loc['月間合計(全体)'] = pivot_table.sum()
                
                formatted_table = pivot_table.map(lambda x: f"¥{x:,}")
                st.table(formatted_table)

                this_month_col = f"{today.month}月"
                m_total = pivot_table[this_month_col].loc['月間合計(全体)'] if this_month_col in pivot_table.columns else 0
                y_total = pivot_table['年間合計'].loc['月間合計(全体)']
                
                c_met1, c_met2 = st.columns(2)
                c_met1.metric(f"{today.month}月の総収入", f"¥{int(m_total):,}")
                c_met2.metric(f"{today.year}年の総計", f"¥{int(y_total):,}")

            st.divider()
            st.subheader("🗓 月別・稼働実績の確認")
            col_y, col_m = st.columns([1, 1])
            with col_y:
                view_year = st.selectbox("年を選択", [today.year, today.year - 1], index=0)
            with col_m:
                view_month = st.selectbox("月を選択", list(range(1, 13)), index=today.month - 1)
                
            view_start = date(view_year, view_month, 1)
            view_end = date(view_year + 1, 1, 1) if view_month == 12 else date(view_year, view_month + 1, 1)

            cur.execute("""
                SELECT work_date, job_name, actual_start, actual_end, pay_amount 
                FROM work_results 
                WHERE work_date >= %s AND work_date < %s
                ORDER BY work_date DESC
            """, (view_start.isoformat(), view_end.isoformat()))
                
            month_detail = cur.fetchall()
            if month_detail:
                st.table(pd.DataFrame([dict(r) for r in month_detail]))
            else:
                st.info(f"{view_year}年{view_month}月の稼働実績はありません。")

            st.divider()
            st.subheader("🛡️ 過去・その他給与の実績登録")
            
            # 💡 フォームの枠の外で状態を管理するためのセレクトボックス
            job_sel = st.selectbox("バイト名", ["東進 (2万行自動電卓)", "Welocalize", "ファミマ", "トライ(講師)", "トライ(事務)", "単発", "その他(直接入力)"])
            
            with st.form("manual_salary_form_upgraded"):
                manual_date = st.date_input("日付を選択", value=today)
                
                # 東進が選ばれている場合は、LINEと同じ直貼り解析モードを起動
                if job_sel == "東進 (2万行自動電卓)":
                    st.markdown("📋 **東進コピペ直貼り解析エリア**")
                    toshin_input_text = st.text_area(
                        "LINEに貼るテキスト（.pdfが含まれる文章）をそのままここに貼り付けてください",
                        placeholder="030830140146676678.pdf 早稲田大学教育学部...\n020930190260957506.pdf 早稲田大学商学部...",
                        height=120
                    )
                    manual_amount = 0 # 自動計算されるためフォーム上は非表示
                else:
                    manual_amount = st.number_input("金額 (円)", min_value=0, step=1000)
                    toshin_input_text = ""
                    
                manual_job_custom = st.text_input("※「その他(直接入力)」を選んだ場合のみ、ここにバイト名を入力", "")
                submit_manual = st.form_submit_button("給与実績をデータベースへ登録")
                
                if submit_manual:
                    final_job_name = manual_job_custom if job_sel == "その他(直接入力)" else "東進" if job_sel == "東進 (2万行自動電卓)" else job_sel
                    
                    if final_job_name.strip() == "":
                        st.error("バイト名を入力してください。")
                    elif job_sel == "東進 (2万行自動電卓)" and not toshin_input_text.strip():
                        st.error("東進のテキストを入力してください。")
                    elif job_sel != "東進 (2万行自動電卓)" and manual_amount <= 0:
                        st.error("0円以上の金額を入力してください。")
                    else:
                        calc_amount = manual_amount
                        
                        # 🚀【東進直貼り自動電卓エンジン】Streamlit側でも2万行から1秒でパース＆自動計算
                        if job_sel == "東進 (2万行自動電卓)":
                            toshin_lines = toshin_input_text.split('\n')
                            target_exams = []
                            for t_line in toshin_lines:
                                t_line = t_line.strip()
                                if ".pdf" in t_line:
                                    exam_match = re.search(r'\.pdf\s+(.+?)(?:\s+未添削|\s+削除|\s+添削|$)', t_line)
                                    if exam_match:
                                        target_exams.append(exam_match.group(1).strip())
                            
                            if target_exams:
                                format_strings = ', '.join(['%s'] * len(target_exams))
                                # 大文字小文字の区別防衛のために "Toshin_wages" をダブクォで囲みます
                                cur.execute(f'SELECT exam_name, price FROM "Toshin_wages" WHERE exam_name IN ({format_strings})', tuple(target_exams))
                                price_rows = cur.fetchall()
                                db_price_map = {row[0]: int(row[1]) for row in price_rows}
                                
                                for exam in target_exams:
                                    calc_amount += db_price_map.get(exam, 50) # マスタになければ安全策で50円
                            else:
                                calc_amount = 0
                        
                        if job_sel == "東進 (2万行自動電卓)" and calc_amount == 0:
                            st.error("有効な東進データ（.pdfの行）が検出できませんでした。")
                        else:
                            # work_resultsへのシュート（GAS側にも自動で1行圧縮されて着弾します）
                            cur.execute(
                                "INSERT INTO work_results (job_name, work_date, pay_amount, raw_text) VALUES (%s, %s, %s, %s)",
                                (final_job_name.strip(), manual_date.isoformat(), calc_amount, toshin_input_text.strip() if toshin_input_text else None)
                            )
                            conn.commit()
                            st.success(f"✅ {manual_date.strftime('%m/%d')}の実績として「{final_job_name}」に ¥{calc_amount:,} を自動計算で登録しました！")
                            st.rerun()

        # --- タブ5: 一括登録 ---
        with tab5:
            st.subheader("🚀 講義予定を一括登録")
            bulk_text = st.text_area("形式: 4/15 1 消化器内科", height=200)
            if st.button("実行", type="primary"):
                if bulk_text:
                    count = 0
                    for line in bulk_text.strip().split('\n'):
                        match = re.search(r'(\d+)[/月](\d+)日?\s*(\d+)限?\s*(.+)', line)
                        if match:
                            m, d, p, s = match.groups()
                            cur.execute("INSERT INTO attendance (date, period, subject_name, status) VALUES (%s, %s, %s, '予定')", 
                                        (date(today.year, int(m), int(d)), int(p), s.strip()))
                            count += 1
                    conn.commit(); st.success(f"✅ {count}件登録！"); st.rerun()

    # ==========================================
    # 👑 新設ページ：🗓️ 月間スケジュール
    # ==========================================
    elif page == "🗓️ 月間スケジュール":
        st.title("🗓️ 月間スケジュール・コックピット")
        st.caption("バイト・私生活の予定、大学の試験日程、CBT等の重要イベントをマージした統合カレンダービューです。")
        st.write("---")

        calendar_events = []

        # ① プライベート・バイト予定（lifestyle_schedules）の取得とマッピング
        cur.execute("""
            SELECT event_date, start_time, end_time, detail, category, sub_category 
            FROM lifestyle_schedules 
            WHERE event_date >= CURRENT_DATE - INTERVAL '3 month'
              AND event_date <= CURRENT_DATE + INTERVAL '6 month'
        """)
        for row in cur.fetchall():
            start_str = f"{row['event_date']}T{row['start_time']}" if row['start_time'] else str(row['event_date'])
            end_str = f"{row['event_date']}T{row['end_time']}" if row['end_time'] else None
            
            # 識別用のスマート色分け（ファミマ、トライ、プライベートなど）
            if row['sub_category'] == 'famima':
                color = "#2ecc71"  # ファミマグリーン
            elif row['sub_category'] == 'try':
                color = "#3498db"  # トライブルー
            elif row['category'] == 'part_time':
                color = "#1abc9c"  # その他バイト
            else:
                color = "#9b59b6"  # プライベート紫

            calendar_events.append({
                "title": row['detail'],
                "start": start_str,
                "end": end_str,
                "color": color,
                "allDay": False if row['start_time'] else True
            })

        # ② 大学定期試験（exams）の取得とマッピング
        cur.execute("SELECT exam_date, subject_name, location FROM exams")
        for row in cur.fetchall():
            loc_str = f" (📍{row['location']})" if row['location'] else ""
            calendar_events.append({
                "title": f"🚨【試験】{row['subject_name']}{loc_str}",
                "start": str(row['exam_date']),
                "color": "#e74c3c",  # 警告の赤
                "allDay": True
            })

        # ③ マスタ重要イベント（CBT日程カウントダウン用全日フラグ）
        if current_cbt:
            calendar_events.append({
                "title": "⚔️【重要】CBT 本番当日",
                "start": current_cbt.isoformat(),
                "color": "#e67e22",  # 燃えるオレンジ
                "allDay": True
            })

        # --- iPad横画面/Split ViewにジャストフィットするFullCalendar設定 ---
        calendar_options = {
            "editable": False,
            "selectable": True,
            "headerToolbar": {
                "left": "prev,next today",
                "center": "title",
                "right": "dayGridMonth,timeGridWeek"
            },
            "initialView": "dayGridMonth",
            "locale": "ja",
            "firstDay": 1,  # 医学生の週次サイクルに合わせた月曜始まり
            "buttonText": {
                "today": "今日",
                "month": "月",
                "week": "週"
            },
            "height": "700px"  # iPadの画面にスクロールなしで綺麗に収まる設計
        }

        # カレンダーの描画実行
        state = calendar(
            events=calendar_events,
            options=calendar_options,
            key="dashboard_integrated_calendar"
        )
        
        # 凡例表示（スマートインフォ）
        st.write("---")
        st.markdown("""
        **🎨 カラー凡例:** <span style='background-color:#2ecc71; padding:2px 8px; border-radius:3px; color:white; font-size:12px;'>ファミマ</span> 
        <span style='background-color:#3498db; padding:2px 8px; border-radius:3px; color:white; font-size:12px;'>トライ</span> 
        <span style='background-color:#9b59b6; padding:2px 8px; border-radius:3px; color:white; font-size:12px;'>プライベート</span> 
        <span style='background-color:#e74c3c; padding:2px 8px; border-radius:3px; color:white; font-size:12px;'>定期試験</span> 
        <span style='background-color:#e67e22; padding:2px 8px; border-radius:3px; color:white; font-size:12px;'>CBT/OSCE重要期日</span>
        """, unsafe_allow_html=True)

    # ==========================================
    # 為替分析・投資戦略ページ
    # ==========================================
    elif page == "為替分析・円転戦略":
        st.title("💱 為替分析 ＆ 📊 Lyra投資戦略コックピット")
        
        rate = get_usd_jpy()
        if rate == 0:
            st.error("データの取得に失敗しました。時間をおいて再読み込みするか、SBI証券等のアプリで直接レートをご確認ください。")
        else:
            st.metric("現在のドル円レート", f"1 USD = {rate:.2f} JPY")
            if rate >= 160:
                st.error("⚠️ 介入警戒ライン(160円)到達！円転の好機かもしれません。")
            elif rate >= 155:
                st.warning("👀 監視域：円安傾向です。")
        
        st.write("---")
        st.subheader("🛡️ 資産配分・現金余力マネジメント")
        st.caption("Project Lyraの純利益を元手に、現在の「リアルタイム投資可能余力」と「現物待機資金（フリーキャッシュ）」を自動算出します。")
        
        cur.execute("SELECT amount_jpy FROM lyra_rewards")
        r_data = cur.fetchall()
        cur.execute("SELECT amount FROM expenses")
        e_data = cur.fetchall()
        
        cur.execute("SELECT amount FROM investment_logs")
        i_logs_data = cur.fetchall()
        actual_invested = sum([int(il['amount']) for il in i_logs_data]) if i_logs_data else 0
        
        lyra_total = sum([float(r['amount_jpy']) for r in r_data]) if r_data else 0.0
        exp_total = sum([float(e['amount']) for e in e_data]) if e_data else 0.0
        
        net_prof = lyra_total - exp_total
        tax_stk = net_prof * 0.3 if net_prof > 0 else 0.0
        auto_investment_capacity = max(0.0, net_prof - tax_stk)
        
        cur.execute("SELECT monthly_investment_target, strategy_notes FROM investment_strategies WHERE id = 1")
        strategy_res = cur.fetchone()
        
        if strategy_res:
            monthly_target = strategy_res['monthly_investment_target']
            notes = strategy_res['strategy_notes']
        else:
            monthly_target = 0
            notes = '現金余力重視。チャンスを待つ。'
            
        free_cash = auto_investment_capacity - actual_invested
        
        col_inv1, col_inv2, col_inv3, col_inv4 = st.columns(4)
        col_inv1.metric("総資産・投資可能総余力", f"¥{int(auto_investment_capacity):,}")
        col_inv2.metric("現物投資 累計実績", f"¥{int(actual_invested):,}")
        
        if free_cash > 0:
            col_inv3.metric("現在待機資金 (自由枠)", f"¥{int(free_cash):,}", "現物買いチャンス待機")
        else:
            col_inv3.metric("現在待機資金 (自由枠)", f"¥{int(free_cash):,}", "余力なし・入金待ち", delta_color="inverse")
            
        col_inv4.metric("今月の目標積立額", f"¥{int(monthly_target):,}")
        st.info(f"💡 **現在の配分比率・戦略メモ**\n\n{notes}")
        st.write("---")
        
        with st.form("investment_strategy_form"):
            st.markdown("✍️ **投資戦略・実績データの更新設定**")
            new_target = st.number_input("今月の目標積立額 (円)", min_value=0, value=int(monthly_target), step=5000)
            new_notes = st.text_area("配分比率・戦略メモ", value=notes, placeholder="例: キャッシュ比率7割維持。150円以下で現物買い全力。")
            submit_strategy = st.form_submit_button("投資戦略を更新・スプレッドシートへ同期")
            
            if submit_strategy:
                cur.execute("""
                    INSERT INTO investment_strategies (id, monthly_investment_target, strategy_notes, updated_at)
                    VALUES (1, %s, %s, NOW())
                    ON CONFLICT (id) DO UPDATE SET 
                        monthly_investment_target = EXCLUDED.monthly_investment_target,
                        strategy_notes = EXCLUDED.strategy_notes,
                        updated_at = NOW()
                """, (new_target, new_notes.strip()))
                conn.commit()
                st.success("✅ 投資戦略を更新しました！")
                st.rerun()

    # ==========================================
    # 👑 新設：全体統合アナリティクス ページ (★データクレンジング防衛強化)
    # ==========================================
    elif page == "全体統合アナリティクス":
        st.title("🦅 全体統合財務アナリティクス")
        st.caption("Lyra報酬、経費、各種バイト代をすべて月別に集費した個人最高財務責任者（CFO）コックピット画面です。")
        st.write("---")
        
        df_total = load_total_data()
        
        if not df_total.empty:
            current_month_idx = datetime.now(tokyo).month - 1
            
            if len(df_total) > current_month_idx:
                df_chart = df_total.copy()
                numeric_cols = ['売上合計', '経費合計', '推定納税額', '実行納税額', '投資余力', '純資産推移', 'バイト給与合計', '月間総利益', 'フリー待機資金']
                
                # ★【超重要ディフェンス】：未入力のゴミ（空文字やカンマなど）を完全に0リセットしてエラーを消滅させる
                for col in numeric_cols:
                    if col in df_chart.columns:
                        df_chart[col] = df_chart[col].astype(str).str.replace('¥', '').str.replace(',', '').str.strip()
                        df_chart[col] = pd.to_numeric(df_chart[col], errors='coerce').fillna(0).astype(int)
                
                selected_month_name = st.selectbox("確認する月を選択", df_chart['月'].tolist(), index=current_month_idx)
                month_data = df_chart[df_chart['月'] == selected_month_name].iloc[0]
                
                st.markdown(f"### 📅 {month_data['月']} の確定財務ステータス")
                
                col_cfo1, col_cfo2, col_cfo3, col_cfo4 = st.columns(4)
                col_cfo1.metric(label="🔌 Lyra売上合計", value=f"¥{int(month_data['売上合計']):,}")
                col_cfo2.metric(label="💸 経費合計", value=f"¥{int(month_data['経費合計']):,}")
                col_cfo3.metric(label="📝 バイト給与合計", value=f"¥{int(month_data['バイト給与合計']):,}")
                
                total_net = month_data['月間総利益']
                col_cfo4.metric(label="👑 真の月間総利益", value=f"¥{int(total_net):,}", 
                                delta=f"内、税ストック推定: -¥{int(month_data['推定納税額']):,}", delta_color="inverse")
                
                st.write("---")
                st.markdown("### 📈 月別・収益およびコストのバランス推移")
                df_bar_data = df_chart.set_index('月')[['売上合計', 'バイト給与合計', '経費合計']]
                st.bar_chart(df_bar_data, height=350)
                
                st.write("---")
                st.markdown("### 🛡️ 純資産（累積投資可能余力）の成長推移曲線")
                df_area_data = df_chart.set_index('月')[['純資産推移', 'フリー待機資金']]
                st.area_chart(df_area_data, height=300)
                
                st.write("---")
                with st.expander("📄 『統合（税金関連その他）』シートの年間生データを一覧確認"):
                    st.dataframe(df_total, use_container_width=True)
            else:
                st.warning("シートデータの構造が不完全です。スプレッドシートをご確認ください。")
        else:
            st.info("統合シートにまだデータが蓄積されていません。")

    cur.execute("COMMIT") 
    cur.close(); conn.close()

except Exception as e:
    st.error(f"エラーが発生しました: {e}")
