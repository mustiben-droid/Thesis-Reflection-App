import streamlit as st
import pandas as pd
import numpy as np
import re
import json

def render_ai_agent_tab():
    """
    טאב 5: מעבדת מחקר וסוכן חכם לריבוי קבצים (Triangulation Lab) - גרסה פתוחה
    """
    st.header("🤖 סוכן חכם - הצלבת נתונים מרובים (Triangulation Lab)")
    st.subheader("📋 שלב א': טעינת קבצי המחקר מהמחשב")
    
    # תיבת העלאה
    uploaded_files = st.file_uploader(
        "גרור והשלך לכאן את כל קבצי המחקר שלך (מאסטר, שאלונים, מבחנים וכו')", 
        type=["csv", "xlsx"], 
        accept_multiple_files=True
    )
    
    df_master = None
    df_quest = None
    other_dfs = {}

    if uploaded_files:
        for file in uploaded_files:
            try:
                if file.name.endswith('.csv'):
                    current_df = pd.read_csv(file)
                else:
                    current_df = pd.read_excel(file)
                
                # 1. זיהוי אוטומטי של קובץ התצפיות (Master)
                if 'work_method' in current_df.columns or 'student_name' in current_df.columns:
                    df_master = current_df
                    st.success(f"✅ קובץ התצפיות (Master) זוהה ונטען: {file.name}")
                
                # 2. זיהוי אוטומטי של קובץ השאלונים (Pre/Post)
                elif any('pre' in str(col).lower() or 'post' in str(col).lower() for col in current_df.columns):
                    file.seek(0)
                    if file.name.endswith('.csv'):
                        df_quest = pd.read_csv(file, header=1)
                    else:
                        df_quest = pd.read_excel(file, header=1)
                    st.success(f"✅ קובץ השאלונים (Pre/Post) זוהה ונטען: {file.name}")
                
                # 3. קבצים אחרים
                else:
                    other_dfs[file.name] = current_df
                    st.info(f"📁 נטען קובץ נתונים נוסף: {file.name}")
                    
            except Exception as e:
                st.error(f"שגיאה בטעינת הקובץ {file.name}: {e}")

    # הודעת סטטוס קטנה (כבר לא חוסמת את המשך ריצת הדף!)
    if df_master is None or df_quest is None:
        st.warning("💡 שים לב: כדי לבצע קורלציה והצלבה מלאה, מומלץ להעלות את קובץ המאסטר וקובץ השאלונים בתיבה למעלה.")

    # פונקציית עזר פנימית לניקוי שמות
    def clean_name_string(val):
        if pd.isna(val): return ""
        val = str(val).strip().lower()
        val = re.sub(r'[^\w\s]', '', val)
        return val

    # -----------------------------------------------------------
    # 💬 חלק הצ'אט וההתכתבות - מופיע תמיד על המסך!
    # -----------------------------------------------------------
    st.subheader("💬 התכתבות עם הסוכן הסטטיסטי")

    if "agent_messages" not in st.session_state:
        st.session_state.agent_messages = []

    for msg in st.session_state.agent_messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # תיבת הקלט פתוחה וזמינה לשימוש מהרגע הראשון
    if prompt := st.chat_input("שאל על תלמיד (למשל: נתח את הפרופיל והפרשנויות של עילאי)"):
        st.session_state.agent_messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            # הגנה: אם המשתמש מנסה לשאול שאלות מורכבות בלי להעלות קבצים
            if df_master is None or df_quest is None:
                ai_reply = "⚠️ לא ניתן לבצע ניתוח או הצלבה מכיוון שלא העלית את קבצי המחקר (מאסטר ושאלונים) בתיבת ההעלאה בראש העמוד. אנא גרור את הקבצים ונסה שוב."
                st.warning(ai_reply)
                st.session_state.agent_messages.append({"role": "assistant", "content": ai_reply})
                return

            api_key = st.secrets.get("GOOGLE_API_KEY", "")
            if not api_key:
                st.error("⚠️ חסר מפתח API ב-Secrets.")
                return
                
            import google.generativeai as genai
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel('models/gemini-1.5-flash')

            with st.spinner("מצליב נתונים ומנתח את קבצי המחקר..."):
                
                # ניקוי שמות במאסטר
                master_clean = df_master.copy()
                master_clean['name_key'] = master_clean['student_name'].apply(clean_name_string)
                
                # ניקוי שמות בשאלונים
                quest_col_name = 'name' if 'name' in df_quest.columns else df_quest.columns[0]
                quest_clean = df_quest.copy()
                quest_clean['name_key'] = quest_clean[quest_col_name].apply(clean_name_string)

                # זיהוי אוטומטי של שם התלמיד מתוך הפרומפט
                selected_student = None
                all_master_names = master_clean['student_name'].dropna().unique()
                for name in all_master_names:
                    if str(name).strip() in prompt:
                        selected_student = name
                        break
                
                if not selected_student:
                    all_quest_names = df_quest[quest_col_name].dropna().unique()
                    for name in all_quest_names:
                        if str(name).strip().replace('.', '') in prompt:
                            selected_student = name
                            break

                if not selected_student:
                    st.error("🔍 לא זיהיתי שם של תלמיד מוכר מהקבצים (לדוגמה, נסה לכתוב במפורש: 'עילאי')")
                    return

                student_key = clean_name_string(selected_student)
                
                # 📊 שליפת נתונים מקובץ 1: מאסטר
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

                # 📝 שליפת נתונים מקובץ 2: שאלונים
                student_questionnaire = quest_clean[quest_clean['name_key'].str.contains(student_key, na=False)]
                quest_summary = {}
                
                if not student_questionnaire.empty:
                    q_row = student_questionnaire.iloc[0].to_dict()
                    pre_questions = {k: v for k, v in q_row.items() if 'pre' in k.lower()}
                    post_questions = {k: v for k, v in q_row.items() if 'post' in k.lower()}
                    
                    quest_summary = {
                        "has_questionnaire_data": True,
                        "raw_name_in_file": str(q_row.get(quest_col_name)),
                        "key_responses_pre": list(pre_questions.items())[:15], 
                        "key_responses_post": list(post_questions.items())[:15]
                    }
                else:
                    quest_summary = {"status": "התלמיד לא נמצא בקובץ שאלוני ה-Pre/Post"}

                # 📁 שליפת נתונים מקבצים נוספים
                other_summary = {}
                for f_name, other_df in other_dfs.items():
                    possible_name_cols = [c for c in other_df.columns if 'name' in c.lower() or 'שם' in c]
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
                
                # הפרומפט האקדמי
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
                5. דיון פדגוגי עמוק למחקר הפעולה: כיצד פרשנויות המורה והמדדים הללו מעידים על ההתקדמות של התלמיד עקב ההתערבות החינוכית שלך (למשל, המעבר לשרטוט ידני או שימוש במותל)?
                6. אל תמציא נתונים שאינם מופיעים בטקסט, ואל תכלול קוד פייטון בתשובה.
                """
                
                try:
                    response = model.generate_content(report_prompt)
                    ai_reply = response.text
                except Exception as api_err:
                    ai_reply = f"⚠️ שגיאה בהפקת הפרומפט מול שרתי גוגל: {str(api_err)}"
                
                st.subheader(f"📊 פרופיל מחקרי מוצלב ופרשנות עומק: {selected_student}")
                st.markdown(ai_reply)
                st.session_state.agent_messages.append({"role": "assistant", "content": ai_reply})
