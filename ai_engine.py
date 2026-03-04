import streamlit as st
import pandas as pd
import numpy as np

# ייבוא זהיר של ספריות כבדות
try:
    import plotly.express as px
    import statsmodels.api as sm
    from statsmodels.formula.api import ols
    from scipy import stats
except ImportError as e:
    st.error(f"חסרה ספרייה סטטיסטית בשרת: {e}")

import google.generativeai as genai
import re
import json

# --- כלים (Tools) שה-Agent יכול להפעיל ---

def plot_student_trend(df, student_id, score_col):
    """כלי לניתוח מגמה אישית של תלמיד לאורך זמן"""
    student_col = next((c for c in df.columns if 'id' in str(c).lower()), None)
    date_col = next((c for c in df.columns if 'date' in str(c).lower() or 'time' in str(c).lower()), None)
    
    if not student_col or not date_col or not score_col:
        return None

    temp = df.copy()
    temp[date_col] = pd.to_datetime(temp[date_col], dayfirst=True, errors="coerce")
    student_data = temp[temp[student_col] == student_id].dropna(subset=[score_col, date_col])
    
    if student_data.empty: return None
    student_data = student_data.sort_values(date_col)
    
    return px.line(student_data, x=date_col, y=score_col, markers=True, 
                   title=f"מגמת {score_col} - תלמיד {student_id}", template="simple_white")

def run_anova(df, prompt):
    """כלי לביצוע ניתוח שונות (ANOVA) אוטומטי"""
    num_cols = df.select_dtypes(include=[np.number]).columns.tolist()
    cat_cols = [c for c in df.columns if df[c].nunique() < 10 and c not in num_cols]
    
    if num_cols and cat_cols:
        dv, iv = num_cols[0], cat_cols[0] # ברירת מחדל למשתנים הראשונים
        model_ols = ols(f'Q("{dv}") ~ C(Q("{iv}"))', data=df).fit()
        table = sm.stats.anova_lm(model_ols, typ=3).round(3)
        return table, dv, iv
    return None, None, None

# --- לוגיקת ה-Agent המרכזית ---

def render_ai_engine(df):
    st.header("🤖 סוכן מחקר חכם (AI Agent)")
    
    if "messages" not in st.session_state:
        st.session_state.messages = []

    # הצגת היסטוריית השיחה
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg.get("plot") is not None: st.plotly_chart(msg["plot"], use_container_width=True)
            if msg.get("table") is not None: st.table(msg["table"])

    if prompt := st.chat_input("איך אוכל לעזור במחקר היום?"):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"): st.markdown(prompt)

        with st.chat_message("assistant"):
            model = genai.GenerativeModel('gemini-2.0-flash')
            
            # שלב 1: הבנת כוונת המשתמש (Intent Classification)
            extract_prompt = f"""
            Analyze the user request based on these columns: {list(df.columns)}.
            Request: "{prompt}"
            Return ONLY a JSON with:
            {{
              "type": "trend" (for specific student) OR "anova" (for group comparison) OR "general",
              "student_id": number or null,
              "target_col": "exact_column_name" or null
            }}
            """
            
            try:
                raw_res = model.generate_content(extract_prompt).text
                decision = json.loads(re.search(r'\{.*\}', raw_res, re.DOTALL).group())
            except:
                decision = {"type": "general"}

            # שלב 2: ביצוע הפעולה (Action)
            fig, table, response_text = None, None, ""

            if decision["type"] == "trend" and decision["student_id"] is not None:
                target = decision["target_col"] or df.select_dtypes(include=[np.number]).columns[0]
                fig = plot_student_trend(df, decision["student_id"], target)
                if fig:
                    st.plotly_chart(fig)
                    response_text = f"ניתחתי את המגמה של תלמיד {decision['student_id']} במשתנה {target}. ניתן לראות את השינוי לאורך זמן בגרף."
                else:
                    response_text
