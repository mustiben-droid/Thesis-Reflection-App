import streamlit as st
import pandas as pd
import numpy as np
import re
import json
from scipy import stats

# ==========================================================
# קבועים ומדדים כמותיים מוגדרים (המשתנים שלך!)
# ==========================================================
SCORE_COLS = ['score_proj', 'score_spatial', 'score_conv', 'score_efficacy']
CAT_COLS = ['cat_convert_rep', 'cat_dims_props', 'cat_proj_trans', 'cat_3d_support']

# ==========================================================
# פונקציות עזר - ניקוי והצלבת שמות
# ==========================================================
def clean_name_string(val):
    """מנקה שם תלמיד לצורך הצלבה בין קבצים: רווחים, נקודות, אותיות גדולות."""
    if pd.isna(val):
        return ""
    val = str(val).strip().lower()
    val = re.sub(r'[^\w\s]', '', val)   # הסרת נקודות/סימני פיסוק
    val = val.replace(' ', '')          # הסרת רווחים (מתקן רווחים פנימיים)
    return val

def get_pre_post_pairs(df_quest):
    """מאתר זוגות עמודות Pre/Post תואמות לפי מספר השאלה."""
    pre_cols, post_cols = {}, {}
    for c in df_quest.columns:
        m = re.search(r'(\d+)', str(c))
        if not m:
            continue
        num = int(m.group(1))
        c_low = str(c).lower()
        if 'pre' in c_low:
            pre_cols[num] = c
        elif 'post' in c_low:
            post_cols[num] = c
    return [(pre_cols[n], post_cols[n], n) for n in sorted(pre_cols) if n in post_cols]

def run_paired_pre_post_test(df_quest, name_col):
    """מריץ מבחן Pre/Post כיתתי זוגי ומחשב גודל אפקט."""
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
    """דוח תקינות נתונים פנימי."""
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

            # זיהוי תלמיד חכם
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
            if any(kw in p_low for kw in QUAL_KEYWORDS) and df_master is not None:
                with st.spinner("מחלץ נתוני ביצוע, קטגוריות קושי ועמודות תיעוד ומצליב..."):
                    
                    target_df = df_master[df_master['student_name'].apply(clean_name_string) == clean_name_string(selected_student)] if selected_student else df_master
                    
                    # 🎯 חישוב ממוצעים מדויק בפייטון לפי המשתנים הכמותיים שלך!
                    active_scores = {c: round(float(target_df[c].mean()), 2) for c in SCORE_COLS if c in target_df.columns and pd.notna(target_df[c].mean())}
                    active_cats = {c: round(float(target_df[c].mean()), 2) for c in CAT_COLS if c in target_df.columns and pd.notna(target_df[c].mean())}
                    
                    # חילוץ שיטת עבודה שכיחה
                    work_method_mode = "לא צוין"
                    if 'work_method' in target_df.columns and not target_df['work_method'].dropna().empty:
                        work_method_mode = str(target_df['work_method'].dropna().mode().iloc[0])
                    
                    # חילוץ מילולי של 4 עמודות התיעוד המדויקות שלך
                    qualitative_blocks = []
                    my_qual_fields = ['challenge', 'insight', 'done', 'interpretation']
                    available_fields = [f for f in my_qual_fields if f in target_df.columns]
                    
                    for _, row in target_df.dropna(subset=['student_name']).iterrows():
                        s_name = row.get('student_name', 'כללי')
                        date_val = row.get('date', 'תאריך לא צוין')
                        method_val = row.get('work_method', 'לא צוין')
                        
                        line_blocks = [f"  🔹 {f.upper()}: {row[f]}" for f in available_fields if pd.notna(row[f]) and str(row[f]).strip() != ""]
                        if line_blocks:
                            qualitative_blocks.append(f"📌 [תלמיד: {s_name} | תאריך: {date_val} | שיטה בשורה זו: {method_val}]:\n" + "\n".join(line_blocks))

                    mixed_data_json = {
                        "scope": f"תלמיד ספציפי ({selected_student})" if selected_student else "כלל הכיתה (בכללי)",
                        "quantitative_performance_scores_averages": active_scores,
                        "quantitative_difficulty_categories_averages": active_cats,
                        "dominant_work_method": work_method_mode,
                        "extracted_qualitative_observations_from_my_columns": qualitative_blocks[:30]
                    }

                    mixed_prompt = f"""
                    אתה מומחה בכיר למתודולוגיית מחקר משולבת (Mixed Methods) ומלווה כתיבת תזות במחקר פעולה פדגוגי.
                    עליך לבצע אינטגרציה וקורלציה מוצלבת בין המדדים הכמותיים הבאים לבין עמודות התיעוד של החוקר.

                    המשתנים הכמותיים שהוגדרו במערכת:
                    - score_proj (ציון היטלים), score_spatial (ציון חשיבה מרחבית), score_conv (חשיבה מתכנסת), score_efficacy (מסוגלות עצמית בתצפית).
                    - קטגוריות מוקדי קושי: cat_convert_rep (המרת ייצוגים), cat_dims_props (פרופורציות), cat_proj_trans (היטלים והעתקות), cat_3d_support (צורך בתמיכה תלת-ממדית).
                    - work_method (שיטת העבודה: בעזרת גוף מודפס / ללא גוף).

                    הנתונים הסטטיסטיים והטקסטים האמיתיים שנשלפו מהאקסל באמצעות פייטון:
                    {json.dumps(mixed_data_json, ensure_ascii=False)}

                    הפק דוח מדעי מפורט (בעברית אקדמית, רהוטה וגבוהה) לפי המבנה הבא:
                    1. כותרת ראשית: "📊 דוח אינטגרציה מתודולוגית: הצלבת מדדי ביצוע ומוקדי קושי עם עמודות התיעוד המחקריות"
                    2. ניתוח פרופיל כמותי: פרש את ממוצעי מדדי הביצוע (score_*) ומפת מוקדי הקושי (cat_*). מהם החוזקות והאתגרים הבולטים ביותר שעולים מהמספרים?
                    3. חיבור איכותני-כמותי: הצלב את המספרים ישירות עם עמודות התיעוד שלך (challenge, insight, done, interpretation). כיצד האתגרים והתובנות המילוליות מסבירים את גובה הציונים?
                    4. אפקטיביות שיטת העבודה והפיגומים (work_method): דון בשיטת העבודה הדומיננטית (גוף מודפס מול דמיון) ובפעולות שננקטו (done) – כיצד הן סייעו או השפיעו על מדדי הקושי והביצוע?
                    5. מסקנות יישומיות למחזור מחקר הפעולה הבא: מהן ההמלצות המעשיות העולות משילוב המספרים וההערות עבור החוקר?
                    6. אל תמציא נתונים שאינם ב-JSON, ואל תכלול קוד פייטון בתשובה.
                    """
                    
                    ai_reply = model.generate_content(mixed_prompt).text
                    st.markdown(ai_reply)
                    st.session_state.agent_messages.append({"role": "assistant", "content": ai_reply})
                return

            # --------------------------------------------------------
            # מסלול א': פרופיל תלמיד מוצלב (Triangulation) - רגיל
            # --------------------------------------------------------
            if selected_student:
                if df_master is None or df_quest is None:
                    st.warning("⚠️ יש להעלות את קובץ המאסטר והשאלון לביצוע הצלבה.")
                    return
                
                with st.spinner(f"מצליב נתונים ומפיק דוח פרופיל עבור {selected_student}..."):
                    student_key = clean_name_string(selected_student)
                    student_observations = df_master[df_master['student_name'].apply(clean_name_string) == student_key]
                    
                    master_summary = {}
                    if not student_observations.empty:
                        num_data = student_observations.select_dtypes(include=[np.number])
                        master_summary = {
                            "total_observations": len(student_observations),
                            "average_quantitative_scores": num_data.mean().round(2).to_dict(),
                            "detailed_qualitative_observations": [f"תאריך: {r.get('date','')} | שיטה: {r.get('work_method','')} | קושי: {r.get('difficulty','')}\n- פרשנות: {r.get('interpretation','')}" for _, r in student_observations.iterrows()]
                        }

                    student_questionnaire = df_quest[df_quest[quest_col_name].apply(clean_name_string) == student_key]
                    quest_summary = {"status": "לא נמצא בשאלון"}
                    if not student_questionnaire.empty:
                        pairs = get_pre_post_pairs(df_quest)
                        q_row = student_questionnaire.iloc[0]
                        pre_vals = [pd.to_numeric(q_row[p[0]], errors='coerce') for p in pairs if pd.notna(q_row[p[0]])]
                        post_vals = [pd.to_numeric(q_row[p[1]], errors='coerce') for p in pairs if pd.notna(q_row[p[1]])]
                        quest_summary = {
                            "mean_pre": round(float(np.mean(pre_vals)), 2) if pre_vals else None,
                            "mean_post": round(float(np.mean(post_vals)), 2) if post_vals else None,
                            "delta": round(float(np.mean(post_vals) - np.mean(pre_vals)), 2) if pre_vals and post_vals else None
                        }

                    student_profile_json = {"student_name": str(selected_student), "observations_master_data": master_summary, "questionnaire_survey_data": quest_summary}
                    report_prompt = f"אתה יועץ סטטיסטי אקדמי. הפק דוח פרופיל מוצלב עמוק (Triangulation Report) בעברית אקדמית עבור התלמיד {selected_student} על בסיס הנתונים האמיתיים הבאים:\n{json.dumps(student_profile_json, ensure_ascii=False)}"
                    
                    ai_reply = model.generate_content(report_prompt).text
                    st.markdown(ai_reply)
                    st.session_state.agent_messages.append({"role": "assistant", "content": ai_reply})

            # --------------------------------------------------------
            # מסלול ב': ניתוחים כיתתיים
            # --------------------------------------------------------
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
                st.info("🔍 לא זיהיתי שם תלמיד מוכר (כגון עילאי או דניאל) או דרישה למבחן כיתתי/איכותני. נסה לנסח שוב באופן ברור.")
