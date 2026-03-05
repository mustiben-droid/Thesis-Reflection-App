import streamlit as st
import pandas as pd
import numpy as np
import re
import json

# ניסיון ייבוא ספריות גרפיות וספריית ה-AI של גוגל
try:
    import plotly.express as px
    import google.generativeai as genai
except ImportError as e:
    st.error(f"חסרה ספרייה להפעלת ה-AI: {e}")

def get_ai_model():
    """
    אתחול מודל ה-Gemini מתוך ה-Secrets של Streamlit.
    וודא שהגדרת GOOGLE_API_KEY בתוך ה-Secrets בלוח הבקרה של Streamlit.
    """
    api_key = st.secrets.get("GOOGLE_API_KEY")
    if not api_key:
        st.error("⚠️ חסר מפתח API (GOOGLE_API_KEY) ב-Secrets של המערכת.")
        return None
    genai.configure(api_key=api_key)
    # שימוש במודל Gemini 2.0 Flash המהיר והחכם
    return genai.GenerativeModel('gemini-2.0-flash')

def plot_student_trend(df, student_name, score_col):
    """
    כלי ויזואלי לייצור גרף מגמה עבור סטודנט ספציפי לאורך זמן.
    """
    # זיהוי אוטומטי של עמודת תאריך או חותמת זמן
    date_col = next((c for c in df.columns if 'date' in str(c).lower() or 'timestamp' in str(c).lower()), None)
    
    if not date_col or score_col not in df.columns:
        return None

    temp = df.copy()
    temp[date_col] = pd.to_datetime(temp[date_col], errors="coerce")
    
    # סינון הנתונים עבור הסטודנט שנבחר
    student_data = temp[temp['student_name'] == student_name].dropna(subset=[score_col, date_col])
    
    if student_data.empty: 
        return None
        
    student_data = student_data.sort_values(date_col)
    
    fig = px.line(student_data, x=date_col, y=score_col, markers=True, 
                   title=f"מגמת {score_col} - {student_name}",
                   template="plotly_white",
                   labels={date_col: "תאריך", score_col: "ערך המדד"})
    # התאמת הכיוון לעברית
    fig.update_layout(title_x=0.5)
    return fig

def render_ai_agent_tab(df):
    """
    הפונקציה המרכזית שמוצגת בטאב ה-AI באפליקציה הראשית.
    """
    st.header("🤖 סוכן מחקר חכם (AI Agent)")
    
    if df is None or df.empty:
        st.info("אין עדיין מספיק נתונים במערכת כדי שהסוכן יוכל לנתח.")
        return

    # ניהול היסטוריית השיחה בתוך ה-Session State כדי שהצ'אט לא יימחק ברענון
    if "messages" not in st.session_state:
        st.session_state.messages = []

    # הצגת הודעות קודמות מהצ'אט
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg.get("plot") is not None:
                st.plotly_chart(msg["plot"], use_container_width=True)

    # תיבת קלט להודעות המשתמש
    if prompt := st.chat_input("איך אוכל לעזור בניתוח התצפיות היום?"):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            model = get_ai_model()
            if not model:
                return

            with st.spinner("הסוכן מעבד את הנתונים ומנתח..."):
                # שלב 1: ניתוח כוונת המשתמש (Intent Analysis)
                columns_list = list(df.columns)
                students_list = list(df['student_name'].unique()) if 'student_name' in df.columns else []
                
                # פנייה ל-AI כדי להבין אם המשתמש רוצה גרף או ניתוח כללי
                intent_prompt = f"""
                Analyze the user request based on these columns: {columns_list}.
                Available students in database: {students_list}
                User query: "{prompt}"
                
                Return ONLY a valid JSON object:
                {{
                  "type": "trend" (if asking for progress/trend of a specific student) OR "general",
                  "student_name": "the exact name from list or null",
                  "target_col": "the exact column name for analysis if mentioned, otherwise null"
                }}
                """
                
                try:
                    raw_res = model.generate_content(intent_prompt).text
                    json_match = re.search(r'\{.*\}', raw_res, re.DOTALL)
                    decision = json.loads(json_match.group()) if json_match else {"type": "general"}
                except:
                    decision = {"type": "general"}

                fig, response_text = None, ""

                # שלב 2: ביצוע פעולה בהתאם להחלטת ה-AI (למשל יצירת גרף)
                if decision["type"] == "trend" and decision.get("student_name"):
                    target = decision.get("target_col")
                    if not target or target not in df.columns:
                        # אם לא זוהתה עמודה ספציפית, נבחר את הראשונה שסוגה מספר
                        num_cols = df.select_dtypes(include=[np.number]).columns
                        target = num_cols[0] if len(num_cols) > 0 else None
                    
                    if target:
                        fig = plot_student_trend(df, decision["student_name"], target)
                        if fig:
                            st.plotly_chart(fig, use_container_width=True)
                            response_text = f"ניתחתי את הנתונים והפקתי גרף מגמה עבור **{decision['student_name']}** במדד **{target}**. "

                # שלב 3: הפקת תובנה טקסטואלית סופית מה-AI על בסיס כל המידע
                final_analysis_prompt = f"""
                You are an expert pedagogical research assistant and data analyst.
                User question: {prompt}
                Statistical Summary of the data: {df.describe().to_string()}
                Last 5 observations recorded: {df.tail(5).to_string()}
                
                Provide a professional, helpful, and concise insight in Hebrew. 
                Focus on pedagogical implications. If a specific student is mentioned, refer to their data.
                """
                
                try:
                    ai_reply = model.generate_content(final_analysis_prompt).text
                    response_text += ai_reply
                except Exception as e:
                    response_text += f"\n(שגיאה בהפקת תובנה טקסטואלית: {str(e)})"
                
                st.markdown(response_text)
                
                # שמירת התשובה והגרף להיסטוריית השיחה
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": response_text,
                    "plot": fig
                })
