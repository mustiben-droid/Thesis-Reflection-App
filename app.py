import streamlit as st
import pandas as pd
import numpy as np
import re
import json
from scipy import stats

# ==========================================================
# מילון המיפוי וההגדרות הרשמי המלא של המחקר שלך (יישור קו סופי!)
# ==========================================================
METRICS_DICTIONARY = {
    "score_proj": {
        "app_name": "📐 המרת ייצוגים (הטלה)",
        "definition": "היכולת הקוגניטיבית לתרגם גוף מתלת-ממד (מודל פיזי/איזומטריה) לדו-ממד (היטלים שטוחים) ולהיפך."
    },
    "score_spatial": {
        "app_name": "🧠 תפיסה מרחבית",
        "definition": "יכולת מנטלית לתפוס, לעבד, לסובב (רוטציה מנטלית) ולדמיין אלמנטים וצורות במרחב התלת-ממדי."
    },
    "score_conv": {
        "app_name": "📏 פרופורציות ומוסכמות",
        "definition": "חשיבה מתכנסת - יישום חוקים נוקשים של שרטוט טכני (קווים נסתרים, צירים) ושמירה על יחסי גודל וקנה מידה מדויקים."
    },
    "score_efficacy": {
        "app_name": "ציון מסוגלות עצמית בתצפית",
        "definition": "הערכת החוקר בזמן אמת בכיתה לגבי מידת הביטחון, העצמאות ותפיסת היכולת שהתלמיד מפגין מול המטלה (להפריד משאלוני Pre/Post)."
    },
    "score_model": {
        "app_name": "🧊 שימוש במודל 3D / הבנת מודל",
        "definition": "מידת ההבנה והיעילות של התלמיד בעבודה WITH מודלים תלת-ממדיים מודפסים או דיגיטליים כפיגום למידה."
    },
    "score_views": {
        "app_name": "🔄 מעבר בין היטלים",
        "definition": "מיומנות מנטלית לנוע בתוך עולם הדו-ממד בין המבטים השונים (השלכת גבהים ורוחב בין מבט פנים, על וצד)."
    },
    "difficulty": {
        "app_name": "📉 רמת קושי התרגיל",
        "definition": "ציון (1-5) המגדיר את המורכבות הגיאומטרית של המטלה שניתנה לתלמיד באותו שיעור (עוגן להערכת מגמת השתפרות)."
    },
    "cat_convert_rep": {
        "app_name": "מוקד קושי: המרת ייצוגים",
        "definition": "מדד המעריך את רמת האתגר או השגיאות שהתלמיד חווה במעבר בין שפות ייצוג (תלת-ממד לדו-ממד)."
    },
    "cat_dims_props": {
        "app_name": "מוקד קושי: פרופורציות וממדים",
        "definition": "מדד המעריך קשיים בשמירה על יחסי גודל אחידים, קריאת מידות חסרות או קווי התאמה בין המבטים."
    },
    "cat_proj_trans": {
        "app_name": "מוקד קושי: היטלים והעתקות",
        "definition": "מדד המעריך שגיאות בטרנספורמציות גיאומטריות (שיקוף, היפוך כיוונים, זיהוי ושרטוט קווים נסתרים)."
    },
    "cat_3d_support": {
        "app_name": "מוקד קושי: תמיכה תלת-ממדית",
        "definition": "מדד המעריך עד כמה התלמיד תלוי פיזית וקוגניטיבית בנוכחות של מודל תלת-ממדי מוחשי כדי להצליח לשרטט."
    }
}

SCORE_COLS = ['score_proj', 'score_spatial', 'score_conv', 'score_efficacy', 'score_model', 'score_views', 'difficulty']
CAT_COLS = ['cat_convert_rep', 'cat_dims_props', 'cat_proj_trans', 'cat_3d_support']

# ==========================================================
# פונקציות עזר - ניקוי והצלבת שמות
# ==========================================================
def clean_name_string(val):
    if pd.isna(val): return ""
    val = str(val).strip().lower()
    val = re.sub(r'[^\w\s]', '', val)
    return val.replace(' ', '')

def get_pre_post_pairs(df_quest):
    pre_cols, post_cols = {}, {}
    for c in df_quest.columns:
        m = re.search(r'(\d+)', str(c))
        if not m: continue
        num = int(m.group(1))
        c_low = str(c).lower()
        if 'pre' in c_low: pre_cols[num] = c
        elif 'post' in c_low: post_cols[num] = c
    return [(pre_cols[n], post_cols[n], n) for n in sorted(pre_cols) if n in post_cols]

def run_paired_pre_post_test(df_quest, name_col):
    pairs = get_pre_post_pairs(df_quest)
    if not pairs: return {"error": "לא נמצאו זוגות עמודות Pre/Post תואמות."}
    pre_cols = [p[0] for p in pairs]
    post_cols = [p[1] for p in pairs]

    work_df = df_quest.copy()
    work_df['mean_pre'] = work_df[pre_cols].apply(pd.to_numeric, errors='coerce').mean(axis=1)
    work_df['mean_post'] = work_df[post_cols].apply(pd.to_numeric, errors='coerce').mean(axis=1)
    work_df = work_df.dropna(subset=['mean_pre', 'mean_post'])

    if len(work_df) < 2: return {"error": "אין מספיק תלמידים עם נתונים כפולים."}
    pre_vals, post_vals = work_df['mean_pre'].values, work_df['mean_post'].values
    diffs = post_vals - pre_vals
    n = len(diffs)

    per_student = [{"name": str(row.get(name_col, "")), "mean_pre": round(float(row['mean_pre']), 2), "mean_post": round(float(row['mean_post']), 2), "delta": round(float(row['mean_post'] - row['mean_pre']), 2)} for _, row in work_df.iterrows()]
    
    result = {"n_students": n, "n_questions_matched": len(pairs), "descriptive": {"M_pre": round(float(np.mean(pre_vals)), 2), "SD_pre": round(float(np.std(pre_vals, ddof=1)), 2), "M_post": round(float(np.mean(post_vals)), 2), "SD_post": round(float(np.std(post_vals, ddof=1)), 2), "M_diff": round(float(np.mean(diffs)), 2), "SD_diff": round(float(np.std(diffs, ddof=1)), 2)}, "per_student": per_student}

    if n < 20:
        try:
            w_stat, p_val = stats.wilcoxon(pre_vals, post_vals)
            z_approx = stats.norm.isf(p_val / 2 if p_val > 0 else 0.0001)
            result.update({"test_type": "Wilcoxon Signed-Rank Test", "stat_name": "W", "stat_val": round(float(w_stat), 3), "p": round(float(p_val), 4), "effect_size_name": "r", "effect_size": round(float(z_approx / np.sqrt(n)), 3)})
        except:
            result.update({"error": "שגיאה בריצת מבחן וילקוקסון"})
    else:
        t_stat, p_val = stats.ttest_rel(pre_vals, post_vals)
        result.update({"test_type": "Paired Samples T-Test", "stat_name": "t", "stat_val": round(float(t_stat), 3), "df": n - 1, "p": round(float(p_val), 4), "effect_size_name": "Cohen's d_z", "effect_size": round(float(np.mean(diffs) / np.std(diffs, ddof=1)), 3) if np.std(diffs, ddof=1) != 0 else 0.0})
    return result

def data_quality_report(df_master, df_quest=None, name_col='student_name'):
    issues = {}
    df = df_master.copy()
    df['name_key'] = df[name_col].apply(clean_name_string)
    counts = df.groupby('name_key').size()
    issues["students_with_under_2_observations"] = counts[counts < 2].index.tolist()

    if df_quest is not None:
        name_cols = [c for c in df_quest.columns if ('name' in str(c).lower() and 'unnamed' not in str(c).lower()) or 'שם' in str(c)]
        q_col = name_cols[0] if name_cols else df_quest.columns[0]
        quest_keys = set(df_quest[q_col].apply(clean_name_string).dropna().unique())
        master_keys = set(df['name_key'].unique())
        issues["students_in_master_missing_from_questionnaire"] = sorted(master_keys - quest_keys - {''})
    return issues

# ==========================================================
# טאב הסוכן הראשי
# ==========================================================
def render_ai_agent_tab():
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

    df_master, df_quest, quest_col_name = None, None, None
    other_dfs = {}

    if uploaded_files:
        for file in uploaded_files:
            try:
                test_df = pd.read_csv(file, header=None).fillna("") if file.name.endswith('.csv') else pd.read_excel(file, header=None).fillna("")
                combined_text = " ".join([str(x) for x in test_df.values.flatten() if pd.notna(x)]).lower()

                if 'work_method' in combined_text or 'student_name' in combined_text or 'score_spatial' in combined_text:
                    file.seek(0)
                    df_master = pd.read_csv(file) if file.name.endswith('.csv') else pd.read_excel(file)
                    st.success(f"✅ קובץ התצפיות (Master) זוהה ונטען בהצלחה: {file.name}")
                elif 'preq' in combined_text or 'post' in combined_text or 'q1_pre' in combined_text:
                    file.seek(0)
                    header_line = 0
                    for idx, row in test_df.iterrows():
                        if any(k in " ".join([str(item) for item in row.tolist()]).lower() for k in ['name', 'q1', 'שם']):
                            header_line = idx
                            break
                    file.seek(0)
                    df_quest = pd.read_csv(file, header=header_line) if file.name.endswith('.csv') else pd.read_excel(file, header=header_line)
                    name_cols = [c for c in df_quest.columns if ('name' in str(c).lower() and 'unnamed' not in str(c).lower()) or 'שם' in str(c)]
                    quest_col_name = name_cols[0] if name_cols else df_quest.columns[0]
                    st.success(f"✅ קובץ השאלונים (Pre/Post) זוהה ונטען בהצלחה: {file.name}")
                else:
                    file.seek(0)
                    other_dfs[file.name] = pd.read_csv(file) if file.name.endswith('.csv') else pd.read_excel(file)
                    st.info(f"📁 נטען קובץ נתונים נוסף: {file.name}")
            except Exception as e:
                st.error(f"שגיאה בטעינת הקובץ {file.name}: {e}")

    if df_master is not None:
        with st.expander("🔍 בדיקת תקינות נתונים (Data Quality Check)"):
            dq = data_quality_report(df_master, df_quest)
            if dq.get("students_with_under_2_observations"):
                st.warning(f"תלמידים עם פחות מ-2 תצפיות: {', '.join(dq['students_with_under_2_observations'])}")
            if dq.get("students_in_master_missing_from_questionnaire"):
                st.info(f"תלמידים החסרים בשאלון: {', '.join(dq['students_in_master_missing_from_questionnaire'])}")

    st.markdown("---")
    st.subheader("💬 התכתבות עם הסוכן הסטטיסטי")

    if "agent_messages" not in st.session_state:
        st.session_state.agent_messages = []

    for msg in st.session_state.agent_messages:
        with st.chat_message(msg["role"]): st.markdown(msg["content"])

    prompt = st.chat_input("שאל את הסוכן הסטטיסטי...")
    
    if prompt:
        st.session_state.agent_messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"): st.markdown(prompt)

        with st.chat_message("assistant"):
            api_key = st.secrets.get("GOOGLE_API_KEY", "")
            if not api_key:
                st.error("⚠️ חסר מפתח API ב-Secrets.")
                return

            import google.generativeai as genai
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel('gemini-2.5-flash')
            p_low = prompt.lower()
            clean_prompt_target = clean_name_string(prompt)

            selected_student = None
            if df_master is not None:
                for name in df_master['student_name'].dropna().unique():
                    if clean_name_string(name) in clean_prompt_target:
                        selected_student = name
                        break
            if not selected_student and df_quest is not None:
                for name in df_quest[quest_col_name].dropna().unique():
                    if clean_name_string(name) in clean_prompt_target:
                        selected_student = name
                        break

            # --------------------------------------------------------
            # 📊 מסלול ג': ניתוח איכותני-כמותי מוצלב (Mixed Methods Engine)
            # --------------------------------------------------------
            QUAL_KEYWORDS = ["איכותני", "פרשנות", "הערות", "הקשר בין", "טקסט", "תוכן", "תובנות", "challenge", "insight", "done", "interpretation"]
            if (any(kw in p_low for kw in QUAL_KEYWORDS) or selected_student) and df_master is not None:
                with st.spinner("מחלץ נתוני ביצוע, מפות קושי ועמודות תיעוד ומבצע אינטגרציה..."):
                    
                    target_df = df_master[df_master['student_name'].apply(clean_name_string) == clean_name_string(selected_student)] if selected_student else df_master
                    
                    active_scores = {c: round(float(target_df[c].mean()), 2) for c in SCORE_COLS if c in target_df.columns and pd.notna(target_df[c].mean())}
                    active_cats = {c: round(float(target_df[c].mean()), 2) for c in CAT_COLS if c in target_df.columns and pd.notna(target_df[c].mean())}
                    
                    work_method_mode = str(target_df['work_method'].dropna().mode().iloc[0]) if 'work_method' in target_df.columns and not target_df['work_method'].dropna().empty else "לא צוין"
                    
                    qualitative_blocks = []
                    my_qual_fields = ['challenge', 'insight', 'done', 'interpretation']
                    available_fields = [f for f in my_qual_fields if f in target_df.columns]
                    
                    for _, row in target_df.dropna(subset=['student_name']).iterrows():
                        s_name = row.get('student_name', 'כללי')
                        date_val = row.get('date', 'תאריך לא צוין')
                        method_val = row.get('work_method', 'לא צוין')
                        
                        line_blocks = [f"  🔹 {f.upper()}: {row.get(f)}" for f in available_fields if pd.notna(row.get(f)) and str(row.get(f)).strip() != ""]
                        if line_blocks:
                            qualitative_blocks.append(f"📌 [תלמיד: {s_name} | תאריך: {date_val} | שיטה: {method_val}]:\n" + "\n".join(line_blocks))

                    quest_summary = {"status": "לא הועלה קובץ שאלונים לטריאנגולציה"}
                    if df_quest is not None and selected_student:
                        student_questionnaire = df_quest[df_quest[quest_col_name].apply(clean_name_string) == clean_name_string(selected_student)]
                        if not student_questionnaire.empty:
                            pairs = get_pre_post_pairs(df_quest)
                            q_row = student_questionnaire.iloc[0]
                            pre_vals = [pd.to_numeric(q_row[p[0]], errors='coerce') for p in pairs if pd.notna(q_row[p[0]])]
                            post_vals = [pd.to_numeric(q_row[p[1]], errors='coerce') for p in pairs if pd.notna(q_row[p[1]])]
                            quest_summary = {
                                "mean_pre": round(float(np.mean(pre_vals)), 2) if pre_vals else None,
                                "mean_post": round(float(np.mean(post_vals)), 2) if post_vals else None,
                                "delta_questionnaire": round(float(np.mean(post_vals) - np.mean(pre_vals)), 2) if pre_vals and post_vals else None
                            }
                        else:
                            quest_summary = {"status": "התלמיד ספציפית לא נמצא בקובץ השאלונים שהועלה"}

                    mixed_data_json = {
                        "scope": f"תלמיד ספציפי ({selected_student})" if selected_student else "כלל הכיתה (בכללי)",
                        "metrics_dictionary_definitions": METRICS_DICTIONARY,
                        "quantitative_performance_scores_found_in_file": active_scores,
                        "quantitative_difficulty_categories_found_in_file": active_cats,
                        "dominant_work_method": work_method_mode,
                        "extracted_qualitative_observations_from_my_columns": qualitative_blocks[:30],
                        "questionnaire_triangulation_data": quest_summary
                    }

                    # בניית היסטוריית השיחה לצורך המשכיות ההתכתבות
                    conversation_history_str = ""
                    for msg in st.session_state.agent_messages[:-1]: # לוקח את כל ההודעות הקודמות
                        role_label = "משתמש" if msg["role"] == "user" else "יועץ"
                        conversation_history_str += f"{role_label}: {msg['content']}\n"

                    mixed_prompt = f"""
                    אתה מומחה בכיר למתודולוגיית מחקר משולבת (Mixed Methods) ומלווה כתיבת תזות במחקר פעולה פדגוגי.
                    עליך להפיק דוח מחקר אקדמי מוצלב המקשר בין המספרים לתיעוד השדה, או לענות על שאלת ההמשך של החוקר.

                    היסטוריית השיחה עד כה (השתמש בה כדי לשמור על רצף השיחה בשאלות המשך):
                    {conversation_history_str}

                    השאלה הנוכחית של החוקר: {prompt}

                    השתמש במילון המדדים הרשמי המצורף ב-JSON (metrics_dictionary_definitions) כדי להבין בדיוק מה מייצג כל קושי או ציון שהשתמר באקסל.
                    שים לב: אם מדד מסוים חסר ברשימות ה-found_in_file, פירוש הדבר שהוא לא תועד בקובץ הנוכחי - ציין זאת בפירוש ואל תמציא עבורו ממוצעים.

                    הנתונים הסטטיסטיים והטקסטים האמיתיים שנשלפו מהאקסל באמצעות פייטון:
                    {json.dumps(mixed_data_json, ensure_ascii=False)}

                    הפק דוח מדעי מפורט (בעברית אקדמית, רהוטה וגבוהה) לפי המבנה הבא (אם מדובר בשאלת המשך ספציפית, ענה עליה ישירות תוך שימוש במבנה רלוונטי):
                    1. כותרת ראשית מתאימה.
                    2. ניתוח הפרופיל הכמותי: פרש את המדדים שנמצאו. מהן החוזקות והאתגרים העולים מהמספרים על סמך הגדרות המדדים הרשמיות?
                    3. חיבור איכותני-כמותי: הצלב את הציונים עם 4 עמודות התיעוד (challenge, insight, done, interpretation). כיצד האתגרים והתובנות המילוליות מסבירים ומעמיקים את המספרים?
                    4. מעגל מחקר הפעולה והפיגומים: דון באפקטיביות של שיטת העבודה (work_method) והפעולות (done) שננקטו - כיצד הן קידמו את הלמידה?
                    5. הערכת טריאנגולציה (אם יש נתוני שאלון): קשר בין השינוי במסוגלות העצמית בשאלון (delta) לבין הביצועים וההערות מהכיתה.
                    6. אל תמציא נתונים שאינם ב-JSON, ואל תכלול קוד פייטון בתשובה.
                    """
                    
                    ai_reply = model.generate_content(mixed_prompt).text
                    st.markdown(ai_reply)
                    st.session_state.agent_messages.append({"role": "assistant", "content": ai_reply})
                return

            elif any(kw in p_low for kw in ["מובהק", "pre", "post", "פרה", "פוסט", "כיתתי", "t-test"]):
                if df_quest is None:
                    st.warning("⚠️ קובץ השאלונים חסר לניתוח זה.")
                    return
                with st.spinner("מחשב נתונים כיתתיים..."):
                    stats_result = run_paired_pre_post_test(df_quest, quest_col_name)
                    report_prompt = f"אתה יועץ סטטיסטי. כתוב דוח בפורמט APA 7th Edition בעברית על תוצאות ה-Pre/Post הכיתתיות הבאות:\n{json.dumps(stats_result, ensure_ascii=False)}"
                    ai_reply = model.generate_content(report_prompt).text
                    st.markdown(ai_reply)
                    st.session_state.agent_messages.append({"role": "assistant", "content": ai_reply})
            else:
                st.info("🔍 לא זיהיתי שם תלמיד מוכר או דרישה למבחן כיתתי. נסה לנסח שוב באופן ברור (למשל: 'נתח את עילאי').")
