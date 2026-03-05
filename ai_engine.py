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
        return {"error": f"השוואה דורשת בדיוק 2 קבוצות בעמודה '{group_col}'. נמצאו: {list(groups)}"}
    
    g1 = df[df[group_col] == groups[0]][val_col].dropna()
    g2 = df[df[group_col] == groups[1]][val_col].dropna()
    
    if len(g1) < 2 or len(g2) < 2:
        return {"error": f"אין מספיק תצפיות לביצוע מבחן (נמצאו {len(g1)} ו-{len(g2)} תצפיות). נדרשות לפחות 2 לכל קבוצה."}
    
    # במדגמים קטנים (פחות מ-20 תצפיות) תמיד עדיף מבחן Mann-Whitney (לא פרמטרי)
    use_non_parametric = len(g1) < 20 or len(g2) < 20
    
    res = {
        "group1": {"name": str(groups[0]), "M": round(g1.mean(), 2), "SD": round(g1.std(), 2), "N": len(g1), "Md": round(g1.median(), 2)},
        "group2": {"name": str(groups[1]), "M": round(g2.mean(), 2), "SD": round(g2.std(), 2), "N": len(g2), "Md": round(g2.median(), 2)}
    }

    if use_non_parametric:
        u_stat, p_val = stats.mannwhitneyu(g1, g2, alternative='two-sided')
        res.update({
            "test_type": "Mann-Whitney U Test (Non-parametric)",
            "stat_name": "U",
            "stat_val": round(u_stat, 3),
            "p": round(p_val, 4),
            "note": "נעשה שימוש במבחן לא-פרמטרי בשל גודל מדגם קטן."
        })
    else:
        t_stat, p_val = stats.ttest_ind(g1, g2)
        res.update({
            "test_type": "Independent Samples T-Test",
            "stat_name": "t",
            "stat_val": round(t_stat, 3),
            "p": round(p_val, 4),
            "df": len(g1) + len(g2) - 2,
            "note": "נעשה שימוש במבחן t למדגמים בלתי תלויים."
        })
        
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

            with st.spinner("מחשב נתונים ומפיק דוח סטטיסטי..."):
                # סינון נתונים לפי שם הסטודנט אם מופיע בבקשה
                analysis_df = df.copy()
                # זיהוי שמות עבריים בתוך הפרומפט
                mentioned_names = [name for name in df['student_name'].unique() if str(name) in prompt]
                if mentioned_names:
                    analysis_df = df[df['student_name'].isin(mentioned_names)]

                num_cols = analysis_df.select_dtypes(include=[np.number]).columns.tolist()
                cat_cols = [c for c in analysis_df.columns if analysis_df[c].nunique() < 10 and c not in num_cols]
                
                # שלב 1: הבנת הכוונה הסטטיסטית (Intent)
                intent_prompt = f"""
                Analyze the user request: "{prompt}"
                Available Columns: {list(analysis_df.columns)}
                Numerical: {num_cols}
                Categorical: {cat_cols}
                Return ONLY JSON:
                {{"type": "compare"|"correlation"|"general", "group_col": "string", "val_col": "string"}}
                """
                
                try:
                    raw_intent = model.generate_content(intent_prompt).text
                    decision = json.loads(re.search(r'\{.*\}', raw_intent, re.DOTALL).group())
                except:
                    decision = {"type": "general"}

                stats_result = None
                if decision.get("type") == "compare" and decision.get("group_col") and decision.get("val_col"):
                    stats_result = run_smart_comparison(analysis_df, decision["group_col"], decision["val_col"])
                
                # שלב 2: הפקת הדוח הסופי (Report)
                # שימוש בהנחיות קשיחות למניעת נתונים מדומים
                report_prompt = f"""
                אתה יועץ סטטיסטי אקדמי. עליך לדווח על הממצאים הבאים שנמצאו בחישוב המערכת.
                
                נתוני החישוב האמיתיים:
                {json.dumps(stats_result, ensure_ascii=False)}
                
                הנחיות קשיחות:
                1. אל תמציא נתונים. השתמש רק בערכים המופיעים ב-JSON למעלה.
                2. פתח בטבלה מעוצבת (Markdown) תחת הכותרת "Group Statistics" (כולל עמודות: Group, N, Mean, Std. Deviation).
                3. הצג טבלה שנייה תחת הכותרת "Test Results" במבנה SPSS (כולל ערך המבחן ו-Sig. 2-tailed).
                4. כתוב פסקה בפורמט APA 7th Edition בעברית רהוטה המדווחת על הממצאים (p, t/U, M, SD).
                5. אם p > 0.05, ציין שאין הבדל מובהק. אם p < 0.05, ציין שיש הבדל מובהק.
                6. תן פרשנות פדגוגית קצרה על בסיס התוצאה האמיתית בלבד.
                7. אל תכתוב קוד פייטון בתשובה.
                """
                
                ai_reply = model.generate_content(report_prompt).text
                st.markdown(ai_reply)
                st.session_state.agent_messages.append({"role": "assistant", "content": ai_reply})
