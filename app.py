import streamlit as st
import psycopg2
from psycopg2.extras import DictCursor
import yfinance as yf 
from datetime import datetime, date, timedelta
import pytz
import pandas as pd
import re
import urllib.request
import json

# 1. データベース接続設定
def get_connection():
    return psycopg2.connect(st.secrets["SUPABASE_URI"])

st.set_page_config(page_title="医学生専用ダッシュボード", layout="wide", page_icon="🩺")

def get_usd_jpy():
    # パターン1: yfinanceによる取得試行（マルチインデックス対策版）
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

    # パターン2: yfinanceが制限された場合のオープンAPIバックアップ
    try:
        url = "https://open.er-api.com/v6/latest/USD"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response:
            res_data = json.loads(response.read().decode())
            rate = res_data["rates"]["JPY"]
            return float(rate)
    except:
        return 0

# タイムゾーンと日付の基本設定
tokyo = pytz.timezone('Asia/Tokyo')
today = datetime.now(tokyo).date()

try:
    conn = get_connection()
    cur = conn.cursor(cursor_factory=DictCursor)

    page = st.sidebar.radio("ページ選択", ["ダッシュボード", "為替分析・円転戦略"])
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
        tab1, tab2, tab3, tab4, tab5 = st.tabs(["🗓 本日の予定", "📝 提出物", "⚖️ 試験日程", "💰 給与実績", "🚀 一括登録"])

        # --- タブ1: 本日の予定（講義 ＋ プライベート） ---
        with tab1:
            selected_date = st.date_input("表示日を選択", value=today, key="view_date")
            cur.execute("SELECT * FROM attendance WHERE date = %s ORDER BY period ASC", (selected_date.isoformat(),))
            lectures = cur.fetchall()
            cur.execute("SELECT * FROM lifestyle_schedules WHERE event_date = %s ORDER BY start_time ASC", (selected_date.isoformat(),))
            lifestyles = cur.fetchall()

            col_lec, col_life = st.columns([3, 2])
            with col_lec:
                st.subheader("📚 大学の講義")
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
                
                # 明日以降の直近の予定を表示するセクション
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

        # --- タブ4: 💰 給与実績 ---
        with tab4:
            st.subheader("🚀 Project Lyra 収益・納税サマリー")
            cur.execute("SELECT * FROM lyra_rewards ORDER BY date DESC")
            lyra_data = cur.fetchall()
            if lyra_data:
                df_lyra = pd.DataFrame([dict(r) for r in lyra_data])
                
                # Decimal型とfloat型の競合によるTypeErrorを完全に防ぐキャスト
                total_jpy = float(df_lyra['amount_jpy'].sum())
                latest_jpy = float(df_lyra.iloc[0]['amount_jpy'])
                
                c1, c2, c3 = st.columns(3)
                c1.metric("合計収益 (円)", f"¥{int(total_jpy):,}")
                c2.metric("納税ストック(累計)", f"¥{int(total_jpy * 0.3):,}")
                c3.metric("当日分納税予定", f"¥{int(latest_jpy * 0.3):,}")
                st.line_chart(df_lyra.set_index('date')['amount_jpy'])
                st.table(df_lyra[['date', 'amount_usd', 'amount_jpy']])
            else:
                st.info("Project Lyra の実績データはまだありません。データが登録されるとサマリーが表示されます。")
            
            # Project Lyra 実績の手動登録フォーム
            with st.form("lyra_reward_form"):
                st.caption("✍️ Project Lyra 報酬の手動入力")
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
                
                # ピボットテーブル作成
                pivot_table = df_all.pivot_table(
                    index='job_name', 
                    columns='月', 
                    values='pay_amount', 
                    aggfunc='sum', 
                    fill_value=0
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

            # 月を選択して稼働実績を確認できるセクション
            st.divider()
            st.subheader("🗓 月別・稼働実績の確認")
            st.caption("確認したい年月を選択してください。その月に働いた日と時間が一覧表示されます。")
            
            col_y, col_m = st.columns([1, 1])
            with col_y:
                view_year = st.selectbox("年を選択", [today.year, today.year - 1], index=0)
            with col_m:
                view_month = st.selectbox("月を選択", list(range(1, 13)), index=today.month - 1)
                
            view_start = date(view_year, view_month, 1)
            if view_month == 12:
                view_end = date(view_year + 1, 1, 1)
            else:
                view_end = date(view_year, view_month + 1, 1)

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

            # 過去・その他給与の手入力フォーム
            st.divider()
            st.subheader("✍️ 過去・その他給与の手入力")
            st.caption("💡 ヒント：3月分など「月ごとの給与」を入力する場合は、その月の末日（3/31など）を選択してください。週ごとなら週末を選ぶと集計がきれいにまとまります。")
            
            with st.form("manual_salary_form"):
                col_d, col_j, col_a = st.columns([1, 1, 1])
                with col_d:
                    manual_date = st.date_input("日付を選択", value=today)
                with col_j:
                    job_sel = st.selectbox("バイト名", ["東進", "Welocalize", "ファミマ", "トライ(講師)", "トライ(事務)", "単発", "その他(直接入力)"])
                with col_a:
                    manual_amount = st.number_input("金額 (円)", min_value=0, step=1000)
                    
                manual_job_custom = st.text_input("※「その他」を選んだ場合のみ、ここにバイト名を入力", "")
                
                submit_manual = st.form_submit_button("給与実績を登録")
                
                if submit_manual:
                    final_job_name = manual_job_custom if job_sel == "その他(直接入力)" else job_sel
                    if final_job_name.strip() == "":
                        st.error("バイト名を入力してください。")
                    elif manual_amount <= 0:
                        st.error("0円以上の金額を入力してください。")
                    else:
                        cur.execute(
                            "INSERT INTO work_results (job_name, work_date, pay_amount) VALUES (%s, %s, %s)",
                            (final_job_name.strip(), manual_date.isoformat(), manual_amount)
                        )
                        conn.commit()
                        st.success(f"✅ {manual_date.strftime('%m/%d')}の「{final_job_name}」に ¥{manual_amount:,} を登録しました！")
                        st.rerun()

        # --- タブ5: 🚀 一括登録 ---
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
    # 為替分析ページ
    # ==========================================
    elif page == "為替分析・円転戦略":
        st.title("💱 為替分析・円転戦略")
        rate = get_usd_jpy()
        
        # もしレートが0円の場合のフォールバック表示
        if rate == 0:
            st.error("データの取得に失敗しました。時間をおいて再読み込みするか、SBI証券等のアプリで直接レートをご確認ください。")
        else:
            st.metric("現在のドル円レート", f"1 USD = {rate:.2f} JPY")
            
            if rate >= 160:
                st.error("⚠️ 介入警戒ライン(160円)到達！円転の好機かもしれません。")
            elif rate >= 155:
                st.warning("👀 監視域：円安傾向です。")
        
        st.write("---")
        st.write("### 戦略メモ")
        st.write("・片山財務大臣の介入示唆：160円を超えると介入の可能性大。")
        st.write("・3-8円程度の急激な円高反落を狙った円転タイミングを検討してください。")

    cur.close(); conn.close()

except Exception as e:
    st.error(f"エラーが発生しました: {e}")
