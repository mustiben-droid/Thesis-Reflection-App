import streamlit as st
import pandas as pd
import numpy as np
import re
import json
import os
from scipy import stats

# ==========================================================
# מילון המיפוי וההגדרות הרשמי של המחקר
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
        "definition": "מידת ההבנה והיעילות של התלמיד בעבודה עם מודלים תלת-ממדיים מודפסים או דיגיטליים כפיגום למידה."
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
        "definition": "מדד המעריך את רמת האתגר או השגיאות שהתלמיד חווה במעבר בין שפות ייצוג (תלת-ממד לדו-ממד), כולל קשיי רוטציה מנטלית."
    },
    "cat_dims_props": {
        "app_name": "מוקד קושי: פרופורציות וממדים",
        "definition": "מדד המעריך קשיים בשמירה על יחסי גודל אחידים, קריאת מידות חסרות, שימוש בכלי מדידה או קווי התאמה בין המבטים."
    },
    "cat_proj_trans": {
        "app_name": "מוקד קושי: היטלים והעתקות",
        "definition": "מדד המעריך שגיאות בטרנספורמציות גיאומטריות (שיקוף, היפוך כיוונים, זיהוי ושרטוט קווים נסתרים, בלבול בין היטלים)."
    },
    "cat_3d_support": {
        "app_name": "מוקד קושי: תמיכה תלת-ממדית",
        "definition": "מדד המעריך עד כמה התלמיד תלוי פיזית וקוגניטיבית בנוכחות/בסיבוב של מודל תלת-ממדי מוחשי כדי להצליח לשרטט."
    }
}

SCORE_COLS = ['score_proj', 'score_spatial', 'score_conv', 'score_efficacy', 'score_model', 'score_views']
CAT_COLS = ['cat_convert_rep', 'cat_dims_props', 'cat_proj_trans', 'cat_3d_support']

TAG_TO_CAT_MAP = {
    "התעלמות מקווים נסתרים": ["cat_proj_trans"],
    "בלבול בין היטלים": ["cat_proj_trans"],
    "קושי ברוטציה מנטלית": ["cat_convert_rep", "cat_3d_support"],
    "טעות בפרופורציות": ["cat_dims_props"],
    "קושי במעבר בין היטלים": ["cat_proj_trans", "cat_convert_rep"],
    "שימוש בכלי מדידה": ["cat_dims_props"],
    "סיבוב פיזי של המודל": ["cat_3d_support"],
    "תיקון עצמי": [],
    "עבודה עצמאית שוטפת": [],
}

# ==========================================================
# פונקציות עזר - ניקוי, הצלבה ושמירה אבסולוטית לדרייב
# ==========================================================

def clean_name_string(val):
    if pd.isna(val):
        return ""
    val = str(val).strip().lower()
    val = re.sub(r'[^\w\s]', '', val)
    return val.replace(' ', '')

def find_name_column(df):
    name_cols = [c for c in df.columns if ('name' in str(c).lower() and 'unnamed' not in str(c).lower()) or 'שם' in str(c)]
    return name_cols[0] if name_cols else df.columns[0]

def save_report_to_local_or_drive(student_name, report_text):
    clean_name = student_name.replace(' ', '_').replace('.', '')
    filename = f"Report_Triangulation_{clean_name}.txt"
    target_path = os.path.abspath(os.path.join(os.getcwd(), filename))
    try:
        with open(target_path, "w", encoding="utf-8") as f:
            f.write(report_text)
        return True, target_path
    except Exception as e:
        return False, str(e)

# ==========================================================
# עיבודי פייטון סטטיסטיים (חילוץ קשרי זמנים ומדדים)
# ==========================================================

def get_pre_post_pairs(df_quest):
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

def compute_questionnaire_deltas(df_quest, name_col):
    pairs = get_pre_post_pairs(df_quest)
    if not pairs:
        return pd.DataFrame(columns=['name_key', 'mean_pre', 'mean_post', 'delta_quest'])
    pre_cols = [p[0] for p in pairs]
    post_cols = [p[1] for p in pairs]
    work = df_quest.copy()
    work['name_key'] = work[name_col].apply(clean_name_string)
    work['mean_pre'] = work[pre_cols].apply(pd.to_numeric, errors='coerce').mean(axis=1)
    work['mean_post'] = work[post_cols].apply(pd.to_numeric, errors='coerce').mean(axis=1)
    work['delta_quest'] = work['mean_post'] - work['mean_pre']
    out = work[['name_key', 'mean_pre', 'mean_post', 'delta_quest']].dropna(subset=['mean_pre', 'mean_post'])
    return out.groupby('name_key', as_index=False).mean(numeric_only=True)

def compute_master_trends(df_master, name_col='student_name'):
    df = df_master.copy()
    df['name_key'] = df[name_col].apply(clean_name_string)
    available_scores = [c for c in SCORE_COLS if c in df.columns]
    if not available_scores:
        return pd.DataFrame(columns=['name_key', 'mean_master', 'delta_master', 'slope_master', 'work_method_mode'])
    df['overall_score'] = df[available_scores].apply(pd.to_numeric, errors='coerce').mean(axis=1)
    if 'date' in df.columns:
        df['date_parsed'] = pd.to_datetime(df['date'], errors='coerce')
    elif 'timestamp' in df.columns:
        df['date_parsed'] = pd.to_datetime(df['timestamp'], errors='coerce')
    else:
        df['date_parsed'] = pd.NaT
    rows = []
    for key, g in df.groupby('name_key'):
        if not key:
            continue
        g = g.dropna(subset=['overall_score']).sort_values('date_parsed')
        if g.empty:
            continue
        mean_master = g['overall_score'].mean()
        delta_master = g['overall_score'].iloc[-1] - g['overall_score'].iloc[0]
        slope_master = np.nan
        if g['date_parsed'].notna().sum() >= 2 and len(g) >= 2:
            x = g['date_parsed'].astype('int64') / 1e9 / 86400.0
            y = g['overall_score'].values
            mask = ~np.isnan(x) & ~np.isnan(y)
            if mask.sum() >= 2 and np.std(x[mask]) > 0:
                slope_master, _, _, _, _ = stats.linregress(x[mask], y[mask])
        work_method_mode = g['work_method'].dropna().mode().iloc[0] if 'work_method' in g.columns and not g['work_method'].dropna().empty else None
        rows.append({
            "name_key": key, "n_observations": len(g),
            "mean_master": round(float(mean_master), 3), "delta_master": round(float(delta_master), 3),
            "slope_master": round(float(slope_master), 4) if not np.isnan(slope_master) else None,
            "work_method_mode": work_method_mode
        })
    return pd.DataFrame(rows)

def compute_tag_category_counts(df_master, name_col='student_name'):
    if 'tags' not in df_master.columns:
        return pd.DataFrame(columns=['name_key', 'n_observations'] + CAT_COLS)
    df = df_master.copy()
    df['name_key'] = df[name_col].apply(clean_name_string)
    def parse_tags(val):
        if pd.isna(val) or val == "": return []
        if isinstance(val, list): return val
        s = str(val)
        try:
            parsed = json.loads(s.replace("'", '"'))
            if isinstance(parsed, list): return parsed
        except: pass
        return [t.strip().strip("[]'\"") for t in s.split(',') if t.strip().strip("[]'\"")]
    rows = []
    for key, g in df.groupby('name_key'):
        if not key: continue
        counts = {c: 0 for c in CAT_COLS}
        for tags_val in g['tags']:
            for tag in parse_tags(tags_val):
                for cat in TAG_TO_CAT_MAP.get(tag, []): counts[cat] += 1
        row = {"name_key": key, "n_observations": len(g)}
        row.update(counts)
        rows.append(row)
    return pd.DataFrame(rows)

# ==========================================================
# 💬 ניהול שיחה משורשרת (Memory) באמצעות Streamlit Session
# ==========================================================
def init_gemini_chat(api_key, system_rules):
    import google.generativeai as genai
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name='gemini-2.5-flash', system_instruction=system_rules)
    return model.start_chat(history=[])

# ==========================================================
# טאב הסוכן החכם והמשורשר
# ==========================================================
def render_ai_agent_tab():
    st.header("🤖 מעבדת ממצאים מוצלב (Triangulation Lab) - שיחה משורשרת")
    st.markdown("---")

    uploaded_files = st.file_uploader("גרור לכאן את קובץ המאסטר ואובץ השאלונים יחד:", type=["csv", "xlsx"], accept_multiple_files=True)

    df_master, df_quest, quest_col_name, other_dfs = None, None, None, {}

    if uploaded_files:
        for file in uploaded_files:
            try:
                test_df = pd.read_csv(file, header=None).fillna("") if file.name.endswith('.csv') else pd.read_excel(file, header=None).fillna("")
                combined_text = " ".join([str(x) for x in test_df.values.flatten() if pd.notna(x)]).lower()
                file.seek(0)
                if 'work_method' in combined_text or 'student_name' in combined_text or 'score_spatial' in combined_text:
                    df_master = pd.read_csv(file) if file.name.endswith('.csv') else pd.read_excel(file)
                    st.success(f"✅ נטען קובץ תצפיות (Master): {file.name}")
                elif 'preq' in combined_text or 'post' in combined_text or 'q1_pre' in combined_text:
                    header_line = 0
                    for idx, row in test_df.iterrows():
                        if 'name' in " ".join([str(item) for item in row.tolist() if pd.notna(item)]).lower():
                            header_line = idx
                            break
                    df_quest = pd.read_csv(file, header=header_line) if file.name.endswith('.csv') else pd.read_excel(file, header=header_line)
                    quest_col_name = find_name_column(df_quest)
                    st.success(f"✅ נטען קובץ שאלונים (Pre/Post): {file.name}")
                else:
                    other_dfs[file.name] = pd.read_csv(file) if file.name.endswith('.csv') else pd.read_excel(file)
            except Exception as e:
                st.error(f"שגיאה בטעינת קובץ: {e}")

    st.markdown("---")
    st.subheader("💬 ערוץ ניתוח ממצאים ותמות (ללא המלצות פדגוגיות)")
    st.caption("הסוכן זוכר את ההיסטוריה של השיחה. אתה יכול לשאול שאלות המשך כמו 'למה הציון שלו ירד בפוסט?' או 'תעמיק בתמה האיכותנית הזו'.")

    # חוקי מערכת קשיחים - ניקוי המלצות וחיזוק תמות וקטגוריות
    system_rules = (
        "אתה פרופסור ומתודולוג מחקר בכיר המלווה כתיבת פרק ממצאים (Results) בלבד לתזת מאסטר במחקר פעולה. "
        "תפקידך לחלץ תמות, קטגוריות וקשרים כמותיים ואיכותניים מתוך הדאטה שמועבר אליך. "
        "חוק קשיח: אסור לך בשום אופן לכתוב המלצות פדגוגיות, עצות למורה או הצעות לעתיד (כמו 'מומלץ להשתמש בתוכנות CAD' או 'כדאי לתת לו משוב'). "
        "התמקד אך ורק במה שהנתונים מראים בפועל ברמת הממצא הטהור. "
        "משתני cat_* הם ספירת שגיאות/מוקדי קושי (נמוך זה חזק ומצוין). ציר הזמן מתחיל בדצמבר 2025 ומסתיים במאי 2026. "
        "נהל את השיחה בצורה משורשרת, וענה על שאלות המשך בהלימה מלאה להודעות הקודמות בצ'אט, בהתבסס על כללי APA 7th Edition."
    )

    # אתחול הזיכרון המשורשר ב-Session State
    if "gemini_chat_session" not in st.session_state:
        st.session_state.gemini_chat_session = None
    if "agent_messages" not in st.session_state:
        st.session_state.agent_messages = []

    # הצגת הודעות קודמות מההיסטוריה
    for msg in st.session_state.agent_messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    prompt = st.chat_input("שאל את הסוכן על הממצאים, קטגוריות ותמות...")
    if not prompt: return

    st.session_state.agent_messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        api_key = st.secrets.get("GOOGLE_API_KEY", "")
        if not api_key:
            st.error("⚠️ חסר מפתח API ב-Secrets.")
            return

        # אתחול אובייקט הצ'אט של גוגל אם הוא לא קיים עדיין
        if st.session_state.gemini_chat_session is None:
            st.session_state.gemini_chat_session = init_gemini_chat(api_key, system_rules)

        # הכנת הנתונים במידה ומדובר בשאילתה ראשונה על תלמיד
        student_data_payload = ""
        if df_master is not None and df_quest is not None:
            master_clean = df_master.copy()
            master_clean['name_key'] = master_clean['student_name'].apply(clean_name_string) if 'student_name' in master_clean.columns else ""
            
            selected_student = None
            for name in master_clean['student_name'].dropna().unique():
                if str(name).strip() in prompt:
                    selected_student = name
                    break
            
            if selected_student:
                student_key = clean_name_string(selected_student)
                sub_obs = master_clean[master_clean['name_key'] == student_key]
                if 'date' in sub_obs.columns:
                    sub_obs['date_parsed'] = pd.to_datetime(sub_obs['date'], errors='coerce')
                    sub_obs = sub_obs.sort_values('date_parsed')
                
                raw_interps = []
                for _, row in sub_obs.iterrows():
                    raw_interps.append(f"תאריך: {row.get('date')} | קושי: {row.get('difficulty')} | תגיות: {row.get('tags')}\n- פרשנות חוקר: {row.get('interpretation', row.get('insight', ''))}")
                
                quest_clean = df_quest.copy()
                quest_clean['name_key'] = quest_clean[quest_col_name].apply(clean_name_string)
                sub_q = quest_clean[quest_clean['name_key'] == student_key]
                
                quest_summary = {}
                if not sub_q.empty:
                    pairs = get_pre_post_pairs(df_quest)
                    pre_vals = [sub_q.iloc[0][p[0]] for p in pairs if pd.notna(sub_q.iloc[0][p[0]])]
                    post_vals = [sub_q.iloc[0][p[1]] for p in pairs if pd.notna(sub_q.iloc[0][p[1]])]
                    quest_summary = {"mean_pre": round(float(np.mean(pre_vals)),2) if pre_vals else None, "mean_post": round(float(np.mean(post_vals)),2) if post_vals else None}
                
                payload = {
                    "student_name": str(selected_student),
                    "observations_scores_mean": sub_obs.select_dtypes(include=[np.number]).mean().round(2).to_dict(),
                    "chronological_qualitative_observations": raw_interps,
                    "questionnaire_data": quest_summary
                }
                student_data_payload = f"\n[עוגן נתוני פייטון עבור הסטודנט שנשלף]: {json.dumps(payload, ensure_ascii=False)}"

        with st.spinner("הסוכן מנתח את הנתונים ומסנכרן את שרשרת השיחה..."):
            # שליחת ההודעה הנוכחית לתוך אובייקט הצאט המשורשר (הזוכר את ההיסטוריה)
            final_prompt = prompt + student_data_payload
            response_text = st.session_state.gemini_chat_session.send_message(final_prompt).text
            
            # הצגת התשובה ושמירתה ב-Session
            st.markdown(response_text)
            st.session_state.agent_messages.append({"role": "assistant", "content": response_text})

        # רכיב שמירה אבסולוטי ומאובטח לדרייב
        st.markdown("---")
        st.subheader("💾 ארכוב ממצאים")
        doc_name = "עילאי" if "עילאי" in prompt else "Analysis_Output"
        if st.button(f"💾 שמור את שרשרת הניתוח הנוכחית לדרייב", key="save_drive_chain"):
            with st.spinner("מייצר קובץ ומסנכרן לענן..."):
                # איחוד כל שרשרת ההודעות לקובץ טקסט אחד סדור
                full_chain_text = "\n\n=========================================\n\n".join([f"[{msg['role'].upper()}]:\n{msg['content']}" for msg in st.session_state.agent_messages])
                success, filepath = save_report_to_local_or_drive(doc_name, full_chain_text)
                if success:
                    st.success(f"✅ כלל הניתוחים והשיחה שורשרו ונשמרו בהצלחה בנתיב המאסטר: `{filepath}`!")
                else:
                    st.error(f"⚠️ שגיאה בשמירת הקובץ: {filepath}")
