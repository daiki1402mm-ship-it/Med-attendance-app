    # --- タブ4: 予定登録 (一括登録対応版) ---
    with tab4:
        st.subheader("🆕 講義予定の追加")
        
        # 1. 手動登録フォーム (1つだけ修正したい時用)
        with st.expander("単発で登録する"):
            with st.form("add_lecture_form", clear_on_submit=True):
                col_d, col_p, col_s = st.columns([2, 1, 3])
                new_date = col_d.date_input("日付")
                new_period = col_p.selectbox("時限", options=[1, 2, 3, 4, 5, 6])
                new_subject = col_s.text_input("科目名")
                if st.form_submit_button("単発登録"):
                    if new_subject:
                        cur.execute("INSERT INTO attendance (date, period, subject_name, status) VALUES (%s, %s, %s, '予定')",
                                    (new_date.isoformat(), new_period, new_subject))
                        conn.commit()
                        st.success(f"登録完了！")
                        st.rerun()

        st.divider()

        # 2. 一括登録エリア (メイン)
        st.subheader("🚀 1ヶ月分を一括登録")
        st.info("以下の形式で1行ずつ入力してください：\n`月/日 時限 科目名`  (例: 6/1 1限 解剖学)")
        
        bulk_text = st.text_area("ここに予定を貼り付けてください", height=300, placeholder="6/1 1 解剖学\n6/1 2 生理学\n6/2 1 薬理学...")
        
        if st.button("一括登録を実行"):
            if bulk_text:
                lines = bulk_text.strip().split('\n')
                success_count = 0
                error_lines = []
                
                for line in lines:
                    try:
                        # 正規表現で 日付(1)、時限(2)、科目(3) を抽出
                        import re
                        match = re.search(r'(\d+)[/月](\d+)日?\s*(\d+)限?\s*(.+)', line)
                        if match:
                            m, d, p, s = match.groups()
                            # 2026年として日付オブジェクトを作成
                            target_date = datetime(2026, int(m), int(d)).date()
                            
                            cur.execute(
                                "INSERT INTO attendance (date, period, subject_name, status) VALUES (%s, %s, %s, '予定')",
                                (target_date.isoformat(), int(p), s.strip())
                            )
                            success_count += 1
                        else:
                            error_lines.append(line)
                    except Exception as e:
                        error_lines.append(f"{line} (エラー: {e})")
                
                conn.commit()
                
                if success_count > 0:
                    st.success(f"🎉 {success_count} 件の講義を登録しました！")
                if error_lines:
                    st.error("以下の行は読み取れませんでした：")
                    for err in error_lines:
                        st.write(f"- {err}")
                
                if success_count > 0:
                    st.rerun()
            else:
                st.warning("テキストを入力してください。")
