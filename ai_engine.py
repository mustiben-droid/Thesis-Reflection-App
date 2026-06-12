import streamlit as st
import pandas as pd
import numpy as np
import re
import json

def render_ai_agent_tab():
    """
    טאב 5: מעבדת מחקר וסוכן חכם לריבוי קבצים (Triangulation Lab) - גרסה נקייה ויציבה
    """
    st.header("🤖 סוכן חכם - הצלבת נתונים מרובים (Triangulation Lab)")
    st.markdown("---")
    
    st.subheader("📋 שלב א': טעינת קבצי המחקר מהמחשב")
    st.info("💡 הנחיה: יש לסמן את קובץ המאסטר (התצפיות) ואת קובץ השאלונים יחד ולגרור אותם לתיבה מטה.")
    
    uploaded_files = st.file_uploader(
        "לחץ כאן לבחירת קבצים או גרור והשלך לכאן (קבצי Excel או CSV)", 
        type=["csv", "xlsx"], 
        accept_multiple_files=True,
        key="research_files_uploader"
    )
    
    df_master = None
    df_quest = None
    other_dfs = {}

    if uploaded_files:
        for file in uploaded_files:
            try:
                if file.name.endswith('.csv'):
                    test_df = pd.read_csv(file, header=None).fillna("")
                else:
                    test_df = pd.read_excel(file, header=None).fillna("")
                
                all_text_list = [str(x) for x in test_df.values.flatten() if pd.notna(x)]
                combined_text = " ".join(all_text_list).lower()
                
                # 1. זיהוי אוטומטי של קובץ התצפיות (Master)
                if 'work_method' in combined_text or 'student_name' in combined_text or 'score_spatial' in combined_text:
                    file.seek(0)
                    if file.name.endswith('.csv'):
                        df_master = pd.read_csv(file)
                    else:
                        df_master = pd.read_excel(file)
                    st.success(f"✅ קובץ התצפיות (Master) זוהה ונטען בהצלחה: {file.name}")
                
                # 2. זיהוי אוטומטי של קובץ השאלונים (Pre/Post)
                elif 'preq' in combined_text or 'post' in combined_text or 'q1_pre' in combined_text:
                    file.seek(0)
                    header_line = 0
                    for idx, row in test_df.iterrows():
                        row_items = [str(item) for item in row.tolist() if pd.notna(item)]
                        row_str = " ".join(row_items).lower()
                        if 'name' in row_str or 'q1' in row_str:
                            header_line = idx
                            break
                    
                    file.seek(0)
                    if file.name.endswith('.csv'):
                        df_quest = pd.read_csv(file, header=header_line)
                    else:
                        df_quest = pd.read_excel(file, header=header_line)
                    st.success(f"✅ קובץ השאלונים (Pre/Post) זוהה ונטען בהצלחה: {file.name}")
                
                # 3. קבצים אחרים
                else:
                    file.seek(0)
                    if file.name.endswith('.csv'):
                        other_dfs[file.name] = pd.read_csv(file)
                    else:
                        other_dfs[file.name] = pd.read_excel(file)
                    st.info(f"📁 נטען קובץ נתונים נוסף: {file.name}")
                    
            except Exception as e:
                st.error(f"שגיאה בטעינת הקובץ {file.name}: {e}")

    st.markdown("---")

    # -----------------------------------------------------------
    # 💬 חלק הצ'אט וההתכתבות - מופיע תמיד על המסך!
    # -----------------------------------------------------------
    st.subheader("💬 התכתבות עם הסוכן הסטטיסטי")

    if "agent_messages" not in st.session_state:
        st.session_state.agent_messages = []

    for msg in st.session_state.agent_messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if prompt := st.chat_input("שאל על תלמיד (למשל: נתח את הפרופיל והפרשנויות של עילאי)"):
        st.session_state.agent_messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            if df_master is None or df_quest is None:
                missing_files = []
                if df_master is None: missing_files.append("קובץ התצפיות (Master)")
                if df_quest is None: missing_files.append("קובץ השאלונים (Pre/Post)")
                
                ai_reply = f"⚠️ לא ניתן לבצע את הניתוח המבוקש מכיוון שהמערכת לא הצליחה לזהות את: {', '.join(missing_files)}. אנא ודא שהעלית את הקבצים הנכונים בתיבת ההעלאה שלמעלה ונסה שוב."
                st.warning(ai_reply)
                st.session_state.agent_messages.append({"role": "assistant", "content": ai_reply})
                return

            api_key = st.secrets.get("GOOGLE_API_KEY", "")
            if not api_key:
                st.error("⚠️ חסר מפתח API ב-Secrets.")
                return
                
            import google.generativeai as genai
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel('gemini-1.5-flash')

            with st.spinner("מצליב נתונים ומנתח את קבצי המחקר..."):
                
                def clean_name_string(val):
                    if pd.isna(val): return ""
                    val = str(val).strip().lower()
                    val = re.sub(r'[^\w\s]', '', val)
                    return val

                master_clean = df_master.copy()
                if 'student_name' in master_clean.columns:
                    master_clean['name_key'] = master_clean['student_name'].apply(clean_name_string)
                else:
                    st.error("⚠️ עמודת student_name לא נמצאה בקובץ המאסטר!")
                    return
                
                quest_col_name = [c for c in df_quest.columns if 'name' in str(c).lower() or 'שם' in str(c)]
                quest_col_name = quest_col_name[0] if quest_col_name else df_quest.columns[0]
                
                quest_clean = df_quest.copy()
                quest_clean['name_key'] = quest_clean[quest_col_name].apply(clean_name_string)

                selected_student = None
                all_master_names = master_clean['student_name'].dropna().unique()
                for name in all_master_names:
                    if str(name).strip() in prompt:
                        selected_student = name
                        break
                
                if not selected_student:
                    all_quest_names = df_quest[quest_col_name].dropna().unique()
                    for name in all_quest_names:
                        if str(name).strip().replace('.', '').strip() in prompt:
                            selected_student = name
                            break

                if not selected_student:
                    st.error("🔍 לא זיהיתי שם של תלמיד מוכר מתוך השאלה שלך. אנא ודא שכתבת את השם במדויק (למשל: עילאי).")
                    return

                student_key = clean_name_string(selected_student)
                
                student_observations = master_clean[master_clean['name_key'] == student_key]
                master_summary = {}
                
                if not student_observations.empty:
                    num_data = student_observations.select_dtypes(include=[np.number])
                    means = num_data.mean().round(2).to_dict()
                    
                    raw_interpretations = []
                    for idx, row in student_observations.iterrows():
                        date_str = str(row.get('date', 'תאריך חסר'))
                        diff_text = str(row.get('difficulty', '')).strip()
                        interp_text = str(row.get('interpretation', '')).strip()
                        method_text = str(row.get('work_method', 'לא צוין'))
                        
                        obs_block = f"תאריך: {date_str} | שיטה: {method_text}\n- קושי: {diff_text}\n- פרשנות חוקר: {interp_text}"
                        raw_interpretations.append(obs_block)
                    
                    master_summary = {
                        "total_observations": len(student_observations),
                        "average_quantitative_scores": means,
                        "detailed_qualitative_observations": raw_interpretations
                    }
                else:
                    master_summary = {"status": "לא נמצאו תצפיות עבור תלמיד זה במאסטר"}

                student_questionnaire = quest_clean[quest_clean['name_key'].str.contains(student_key, na=False)]
                quest_summary = {}
                
                if not student_questionnaire.empty:
                    q_row = student_questionnaire.iloc[0].to_dict()
                    pre_questions = {k: v for k, v in q_row.items() if 'pre' in str(k).lower()}
                    post_questions = {k: v for k, v in q_row.items() if 'post' in str(k).lower()}
                    
                    quest_summary = {
                        "has_questionnaire_data": True,
                        "raw_name_in_file": str(q_row.get(quest_col_name)),
                        "key_responses_pre": list(pre_questions.items())[:20], 
                        "key_responses_post": list(post_questions.items())[:20]
                    }
                else:
                    quest_summary = {"status": "התלמיד לא נמצא בקובץ שאלוני ה-Pre/Post"}

                other_summary = {}
                for f_name, other_df in other_dfs.items():
                    possible_name_cols = [c for c in other_df.columns if 'name' in str(c).lower() or 'שם' in str(c)]
                    if possible_name_cols:
                        other_clean = other_df.copy()
                        other_clean['name_key'] = other_clean[possible_name_cols[0]].apply(clean_name_string)
                        sub_row = other_clean[other_clean['name_key'] == student_key]
                        if not sub_row.empty:
                            other_summary[f_name] = sub_row.iloc[0].drop(['name_key', possible_name_cols[0]], errors='ignore').to_dict()

                student_profile_json = {
                    "student_name": str(selected_student),
                    "observations_master_data": master_summary,
                    "questionnaire_survey_data": quest_summary,
                    "additional_files_data": other_summary
                }
                
                report_prompt = f"""
                אתה יועץ סטטיסטי ומחקרי אקדמי בכיר המלווה תזות בחינוך ומחקר פעולה פדגוגי.
                עליך להפיק דוח פרופיל מוצלב עמוק (Triangulation Report) המשלב בין המדדים הכמותיים לפרשנות האיכותנית של החוקר.
                
                הנתונים הממוזגים האמיתיים של התלמיד מכל קבצי המחקר שהועלו:
                {json.dumps(student_profile_json, ensure_ascii=False)}
                
                משימות הדיווח האקדמי (עליך לכתוב בעברית אקדמית רהוטה וגבוהה):
                1. כותרת ראשית: "🕵️ דוח פרופיל מוצלב והערכת מגמה - [שם התלמיד]"
                2. ניתוח המדדים הכמותיים: הצג את ממוצעי הציונים של התלמיד מהתצפיות (score_spatial, score_views וכו').
                3. שילוב וניתוח פרשנויות המורה: קרא בעיון את ההערות תחת 'detailed_qualitative_observations'. סכם אילו תובנות פדגוגיות וקשיים מנטליים המורה תיעד בזמן אמת (בלבול בין היטלים, קווים נסתרים, שימוש במרקרים וכו').
                4. הצלבה מול השאלונים (Triangulation): קשר בין 'תפיסת המסוגלות' של התלמיד בשאלון לבין המציאות בכיתה. האם מה שהוא אומר על עצמו בשאלון (Pre/Post) תואם את המדדים הכמותיים ואת הפרשנויות שאתה כחוקר רשמת עליו?
                5. דיון פדגוגי עמוק למחקר הפעולה: כיצד פרשנויות המורה והמדדים הללו מעידים על ההתקדמות של התלמיד עקב ההתערבות החינוכית שלך (למשל, המעבר לשרטוט ידני או שימוש במודל)?
                6. אל תמציא נתונים שאינם מופיעים בטקסט, ואל תכלול קוד פייטון בתשובה.
                """
                
                try:
                    response = model.generate_content(report_prompt)
                    ai_reply = response.text
                except Exception as api_err:
                    ai_reply = f"⚠️ שגיאה בהפקת הפרומפט מול שרתי גוגל: {str(api_err)}"
                
                st.markdown(ai_reply)
                st.session_state.agent_messages.append({"role": "assistant", "content": ai_reply})
