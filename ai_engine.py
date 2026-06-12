import streamlit as st
import pandas as pd
import numpy as np
import re
import json

try:
    import plotly.express as px
    import google.generativeai as genai
    from scipy import stats
    import statsmodels.api as sm
    from statsmodels.formula.api import ols
except ImportError as e:
    st.error(f"Error: Missing library for statistical engine: {e}")

api_key = st.secrets.get("GOOGLE_API_KEY", "")
genai.configure(api_key=api_key)

MODEL_NAME = "gemini-1.5-flash"

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

    if prompt := st.chat_input("הזן בקשה לניתוח (למשל: השוואת תפיסה מרחבית בין שיטות עבודה)"):
        st.session_state.agent_messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            api_key = st.secrets.get("GOOGLE_API_KEY", "")
            if not api_key:
                st.error("⚠️ חסר מפתח API (GOOGLE_API_KEY) ב-Secrets.")
                return
                
            import google.generativeai as genai
            genai.configure(api_key=api_key)
            
            # סריקה דינמית למציאת מודל פעיל בשרת
            selected_model_name = None
            try:
                available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
                for m_name in available_models:
                    if 'flash' in m_name.lower(): selected_model_name = m_name; break
                if not selected_model_name and available_models: selected_model_name = available_models[0]
            except:
                selected_model_name = 'models/gemini-1.5-flash'

            model = genai.GenerativeModel(selected_model_name)

            with st.spinner("מחשב נתונים ומפיק דוח סטטיסטי..."):
                analysis_df = df.copy()
                
                # סינון לפי שם סטודנט אם הוזכר בשאלה
                mentioned_names = [name for name in df['student_name'].unique() if str(name) in prompt]
                if mentioned_names:
                    analysis_df = df[df['student_name'].isin(mentioned_names)]

                num_cols = analysis_df.select_dtypes(include=[np.number]).columns.tolist()
                
                # שלב 1: זיהוי כוונת הניתוח
                intent_prompt = f"""
                Analyze the user request: "{prompt}"
                Available Columns in Excel: {list(analysis_df.columns)}
                Return ONLY valid JSON:
                {{"type": "compare"|"correlation"|"general", "group_col": "string", "val_col": "string"}}
                """
                
                decision = {"type": "general"}
                try:
                    raw_intent = model.generate_content(intent_prompt).text
                    match = re.search(r'\{.*\}', raw_intent, re.DOTALL)
                    if match:
                        decision = json.loads(match.group())
                except:
                    pass

                # -----------------------------------------------------------
                # מיפוי קשיח וחכם לפי מבנה האקסל האמיתי שלך!
                # -----------------------------------------------------------
                group_col = decision.get("group_col")
                val_col = decision.get("val_col")
                
                # הגנה קשיחה על עמודת הקבוצות (שיטת עבודה)
                if not group_col or group_col not in analysis_df.columns:
                    if 'work_method' in analysis_df.columns:
                        group_col = 'work_method'
                    elif 'physical_model' in analysis_df.columns:
                        group_col = 'physical_model'
                    else:
                        group_col = 'work_method' if 'work_method' in analysis_df.columns else None

                # הגנה קשיחה על עמודת המדד המספרי (ברירת מחדל: תפיסה מרחבית)
                if not val_col or val_col not in analysis_df.columns:
                    # מנסה לזהות מה המשתמש ביקש בעברית ולהתאים לעמודה הנכונה
                    if 'הטלה' in prompt or 'ייצוג' in prompt: val_col = 'score_proj'
                    elif 'מעבר' in prompt or 'היטל' in prompt: val_col = 'score_views'
                    elif 'מודל' in prompt or 'תלת' in prompt: val_col = 'score_model'
                    elif 'פרופורצ' in prompt: val_col = 'score_conv'
                    else: val_col = 'score_spatial' # ברירת מחדל תפיסה מרחבית

                # הרצת החישוב הסטטיסטי האמיתי
                stats_result = None
                if group_col and val_col and group_col in analysis_df.columns and val_col in analysis_df.columns:
                    try:
                        # ניקוי ערכים ריקים או שורות פגומות לפני הניתוח
                        clean_df = analysis_df.dropna(subset=[group_col, val_col])
                        stats_result = run_smart_comparison(clean_df, group_col, val_col)
                    except Exception as calc_err:
                        stats_result = {"error": f"תקלה בחישוב הסטטיסטי: {str(calc_err)}"}
                else:
                    stats_result = {"error": f"לא נמצאו עמודות מתאימות להשוואה באקסל. נמצאו: group={group_col}, val={val_col}"}
                
                # שלב 2: הפקת הדוח הסופי על בסיס תוצאות האמת
                report_prompt = f"""
                אתה יועץ סטטיסטי אקדמי בכיר ומנוסה. עליך לכתוב דוח מחקר מקיף ומקצועי על הממצאים הסטטיסטיים הבאים.
                
                נתוני החישוב האמיתיים שהופקו מקובץ המאסטר:
                {json.dumps(stats_result, ensure_ascii=False)}
                
                עמודת הקבוצות שנבדקה: {group_col}
                עמודת המדד שנבדקה: {val_col}
                
                הנחיות קשיחות לדיווח:
                1. אם יש הודעת שגיאה ב-JSON (כמו חוסר בתצפיות או עמודה חסרה), הסבר למשתמש בשפה אקדמית אדיבה ומפורשת מה חסר ואיך לתקן (למשל: לבצע סנכרון נתונים או להוסיף תצפיות לשיטת העבודה השנייה), ואל תבנה טבלאות ריקות עם הערות 'לא סופק'.
                2. אם יש נתונים מספריים אמיתיים ב-JSON:
                   - פתח בטבלה מעוצבת (Markdown) תחת הכותרת "Group Statistics" (עמודות: Group, N, Mean, Std. Deviation).
                   - הצג טבלה שנייה תחת הכותרת "Test Results" במבנה SPSS (ערך המבחן ו-Sig. 2-tailed).
                   - כתוב פסקה בפורמט APA 7th Edition בעברית רהוטה המדווחת על הממצאים (p, t/U, M, SD).
                   - קבע מובהקות: p > 0.05 (אין הבדל מובהק) או p < 0.05 (יש הבדל מובהק).
                   - ספק פרשנות פדגוגית מעמיקה ומקצועית המקשרת בין התוצאות לבין תהליכי הלמידה של שרטוט טכני ותפיסה מרחבית במחקר הפעולה שלך (למשל, היתרונות של שרטוט ידני לעומת מודל תלת-ממדי מודפס).
                3. בשום אופן אל תמציא מספרים או נתונים שאינם מופיעים ב-JSON.
                4. אל תכלול קוד פייטון בתשובה.
                """
                
                try:
                    response = model.generate_content(report_prompt)
                    ai_reply = response.text
                except Exception as api_err:
                    ai_reply = f"⚠️ שגיאה בתקשורת מול שרתי גוגל: {str(api_err)}"
                
                st.markdown(ai_reply)
                st.session_state.agent_messages.append({"role": "assistant", "content": ai_reply})
