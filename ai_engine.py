import streamlit as st
import pandas as pd
import numpy as np
import re
import json

# ייבוא ספריות לניתוח סטטיסטי מתקדם
try:
    import plotly.express as px
    import google.generativeai as genai
    from scipy import stats
    import statsmodels.api as sm
    from statsmodels.formula.api import ols
except ImportError as e:
    st.error(f"Error: Missing library for statistical engine: {e}")

def get_ai_model():
    """אתחול והגדרת מודל ה-Gemini מתוך ה-Secrets"""
    api_key = st.secrets.get("GOOGLE_API_KEY", "")
    if not api_key:
        st.error("⚠️ חסר מפתח API (GOOGLE_API_KEY) ב-Secrets.")
        return None
    genai.configure(api_key=api_key)
    return genai.GenerativeModel('gemini-2.0-flash')

# --- פונקציות חישוב סטטיסטי (SPSS-like) ---

def run_smart_comparison(df, group_col, val_col):
    """
    בוחר אוטומטית בין T-test למבחן Mann-Whitney 
    בהתאם לגודל המדגם והנחות היסוד.
    """
    groups = df[group_col].dropna().unique()
    if len(groups) != 2:
        return {"error": f"השוואה דורשת בדיוק 2 קבוצות. נמצאו: {list(groups)}"}
    
    g1 = df[df[group_col] == groups[0]][val_col].dropna()
    g2 = df[df[group_col] == groups[1]][val_col].dropna()
    
    if len(g1) < 2 or len(g2) < 2:
        return {"error": "אין מספיק תצפיות (מינימום 2 לכל קבוצה) לביצוע מבחן סטטיסטי."}
    
    # בדיקת נורמליות (Shapiro-Wilk) - אם המדגם קטן מדי, נשתמש במבחן לא פרמטרי
    use_non_parametric = len(g1) < 10 or len(g2) < 10
    
    res = {
        "group1": {"name": str(groups[0]), "M": round(g1.mean(), 2), "SD": round(g1.std(), 2), "N": len(g1), "Md": round(g1.median(), 2)},
        "group2": {"name": str(groups[1]), "M": round(g2.mean(), 2), "SD": round(g2.std(), 2), "N": len(g2), "Md": round(g2.median(), 2)}
    }

    if use_non_parametric:
        u_stat, p_val = stats.mannwhitneyu(g1, g2, alternative='two-sided')
        res.update({"test": "Mann-Whitney U Test (Non-parametric)", "stat_name": "U", "stat_val": round(u_stat, 3), "p": round(p_val, 4)})
    else:
        t_stat, p_val = stats.ttest_ind(g1, g2)
        res.update({"test": "Independent Samples T-Test", "stat_name": "t", "stat_val": round(t_stat, 3), "p": round(p_val, 4), "df": len(g1)+len(g2)-2})
        
    return res

def render_ai_agent_tab(df):
    st.header("🤖 יועץ סטטיסטי ומחקרי (APA7 & SPSS)")
    
    if df is None or df.empty:
        st.info("אין נתונים זמינים לניתוח.")
        return

    if "agent_messages" not in st.session_state:
        st.session_state.agent_messages = []

    for msg in st.session_state.agent_messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if prompt := st.chat_input("הזן בקשה לניתוח (למשל: השוואת ביצועי נתנאל בין שיטות עבודה)"):
        st.session_state.agent_messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            model = get_ai_model()
            if not model: return

            with st.spinner("מנתח נתונים ומפיק דוח SPSS..."):
                # סינון נתונים ראשוני לפי שם אם הוזכר
                analysis_df = df.copy()
                names = [n for n in df['student_name'].unique() if str(n) in prompt]
                if names:
                    analysis_df = df[df['student_name'].isin(names)]

                num_cols = analysis_df.select_dtypes(include=[np.number]).columns.tolist()
                cat_cols = [c for c in analysis_df.columns if analysis_df[c].nunique() < 10 and c not in num_cols]
                
                intent_prompt = f"""
                נתח את בקשת המשתמש: "{prompt}"
                עמודות זמינות: {list(analysis_df.columns)}
                החזר אך ורק JSON במבנה הבא:
                {{"type": "compare"|"correlation"|"general", "group_col": "שם עמודת הקבוצות", "val_col": "שם עמודת הציון"}}
                """
                
                try:
                    raw_res = model.generate_content(intent_prompt).text
                    decision = json.loads(re.search(r'\{.*\}', raw_res, re.DOTALL).group())
                except:
                    decision = {"type": "general"}

                stats_result = None
                if decision.get("type") == "compare" and decision.get("group_col") and decision.get("val_col"):
                    stats_result = run_smart_comparison(analysis_df, decision["group_col"], decision["val_col"])
                
                # יצירת הדוח הסופי
                report_prompt = f"""
                תפקיד: יועץ סטטיסטי אקדמי.
                שאלה: "{prompt}"
                תוצאות גולמיות מהחישוב: {json.dumps(stats_result, ensure_ascii=False)}
                
                הנחיות קשיחות:
                1. אל תכתוב קוד פייתון בתשובה.
                2. פתח בטבלה מעוצבת (Markdown) שנראית כמו SPSS Output (כולל Group Statistics ו-Independent Samples Test).
                3. המשך בדיווח בפורמט APA 7th Edition בעברית אקדמית רהוטה.
                4. התייחס למדגם קטן אם קיים (למשל שימוש ב-Mann-Whitney במקום t).
                5. תן פרשנות פדגוגית יישומית.
                """
                
                ai_reply = model.generate_content(report_prompt).text
                st.markdown(ai_reply)
                st.session_state.agent_messages.append({"role": "assistant", "content": ai_reply})
