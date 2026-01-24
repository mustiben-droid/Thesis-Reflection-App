with tab1:
    # חלוקה לטורים: טור ימני להזנה, טור שמאלי לצ'אט
    col_in, col_chat = st.columns([1.2, 1])
    
    with col_in:
        it = st.session_state.it
        student_name = st.selectbox("👤 בחר סטודנט", CLASS_ROSTER, key=f"sel_{it}")
        
        if student_name != st.session_state.last_selected_student:
            target = normalize_name(student_name)
            match = full_df[full_df['name_clean'] == target] if not full_df.empty else pd.DataFrame()
            st.session_state.show_success_bar = not match.empty
            st.session_state.student_context = match.tail(15).to_string() if not match.empty else ""
            st.session_state.last_selected_student = student_name
            st.session_state.chat_history = []
            st.rerun()

        if st.session_state.show_success_bar:
            st.success(f"✅ נמצאה היסטוריה עבור {student_name}.")
        else:
            st.info(f"ℹ️ {student_name}: אין תצפיות קודמות.")

        st.markdown("---")
        work_method = st.radio("🛠️ צורת עבודה:", ["🧊 בעזרת גוף מודפס", "🎨 ללא גוף (דמיון)"], key=f"wm_{it}", horizontal=True)

        st.markdown("### 📊 מדדים כמותיים (1-5)")
        m1, m2 = st.columns(2)
        with m1:
            s1 = st.slider("המרת ייצוגים", 1, 5, 3, key=f"s1_{it}")
            s2 = st.slider("מעבר בין היטלים", 1, 5, 3, key=f"s2_{it}")
        with m2:
            s3 = st.slider("שימוש במודל 3D", 1, 5, 3, key=f"s3_{it}")
            s_diff = st.slider("📉 רמת קושי התרגיל", 1, 5, 3, key=f"sd_{it}")
            s4 = st.slider("📏 פרופורציות ומימדים", 1, 5, 3, key=f"s4_{it}")

        tags = st.multiselect("🏷️ תגיות אבחון", TAGS_OPTIONS, key=f"t_{it}")
        ch = st.text_area("🗣️ תצפית שדה (Challenge):", height=150, key=f"ch_{it}")
        ins = st.text_area("🧠 תובנה/פרשנות (Insight):", height=100, key=f"ins_{it}")
        up_files = st.file_uploader("📷 צרף תמונות", accept_multiple_files=True, type=['png', 'jpg', 'jpeg'], key=f"up_{it}")

        if st.session_state.last_feedback:
            st.markdown(f'<div class="feedback-box"><b>💡 משוב AI:</b><br>{st.session_state.last_feedback}</div>', unsafe_allow_html=True)

        c_btns = st.columns(2)
        with c_btns[0]:
            if st.button("🔍 בקש רפלקציה (AI)"):
                if ch:
                    try:
                        genai.configure(api_key=st.secrets.get("GOOGLE_API_KEY"), transport='rest')
                        model = genai.GenerativeModel('models/gemini-1.5-flash')
                        st.session_state.last_feedback = model.generate_content(f"נתח תצפית אקדמית עבור {student_name}: {ch}").text
                        st.rerun()
                    except Exception as e: st.error(f"שגיאת AI: {e}")
        with c_btns[1]:
            if st.button("💾 שמור תצפית", type="primary"):
                if ch:
                    with st.spinner("מעלה תמונות ושומר..."):
                        links = []
                        if up_files and svc:
                            for f in up_files:
                                try:
                                    f_meta = {'name': f.name, 'parents': [GDRIVE_FOLDER_ID] if GDRIVE_FOLDER_ID else []}
                                    media = MediaIoBaseUpload(io.BytesIO(f.getvalue()), mimetype=f.type)
                                    res = svc.files().create(body=f_meta, media_body=media, fields='webViewLink', supportsAllDrives=True).execute()
                                    links.append(res.get('webViewLink'))
                                except: pass
                        
                        entry = {
                            "date": date.today().isoformat(), "student_name": student_name, "work_method": work_method,
                            "challenge": ch, "insight": ins, "difficulty": s_diff, "cat_dims_props": int(s4),
                            "cat_convert_rep": int(s1), "cat_proj_trans": int(s2), "cat_3d_support": int(s3),
                            "tags": tags, "file_links": links, "timestamp": datetime.now().isoformat()
                        }
                        with open(DATA_FILE, "a", encoding="utf-8") as f:
                            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                        st.session_state.it += 1; st.session_state.last_feedback = ""; st.rerun()

    with col_chat:
        st.subheader(f"🤖 יועץ: {student_name}")
        chat_cont = st.container(height=400)
        # הצגת היסטוריית צ'אט
        if "chat_history" not in st.session_state: st.session_state.chat_history = []
        for q, a in st.session_state.chat_history:
            with chat_cont:
                st.chat_message("user").write(q)
                st.chat_message("assistant").write(a)
        
        u_q = st.chat_input("שאל על הסטודנט...")
        if u_q:
            try:
                genai.configure(api_key=st.secrets.get("GOOGLE_API_KEY"), transport='rest')
                model = genai.GenerativeModel('models/gemini-1.5-flash')
                resp = model.generate_content(f"היסטוריה: {st.session_state.student_context}. שאלה: {u_q}").text
                st.session_state.chat_history.append((u_q, resp))
                st.rerun()
            except Exception as e: st.error(f"שגיאת צ'אט: {e}")
