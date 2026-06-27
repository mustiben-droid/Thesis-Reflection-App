"""
ai_engine.py — מנוע ה-AI והסוכן החכם (גרסה 2.7)
שדרוג: הזרקת נתונים סטטיסטיים מחושבים מראש (פייתון) כדי לאפשר לסוכן להפיק דוחות כמותיים מדויקים במאה אחוז.
"""

import streamlit as st
import pandas as pd
import numpy as np
import re
import json
import os
from scipy import stats
from difflib import get_close_matches

# הגדרות המדדים לטובת עיבודי פייתון פנימיים
SCORE_COLS = ['score_proj', 'score_spatial', 'score_conv', 'score_views', 'score_efficacy', 'score_model']
CAT_COLS   = ["cat_convert_rep", "cat_dims_props", "cat_proj_trans", "cat_3d_support"]

# ─────────────────────────────────────────────
# פונקציות עזר - ניקוי שמות וסריקת קבצים
# ─────────────────────────────────────────────
def clean_name(val: str) -> str:
    if pd.isna(val):
        return ""
    val = str(val).strip().lower()
    val = re.sub(r"[^\w]", "", val)
    return val

def fuzzy_match(key: str, pool: list[str], cutoff: float = 0.82) -> str | None:
    if key in pool:
        return key
    matches = get_close_matches(key, pool, n=1, cutoff=cutoff)
    return matches[0] if matches else None

def student_observations(df_master: pd.DataFrame, name_key: str) -> pd.DataFrame:
    sub = df_master[df_master["name_key"] == name_key].copy()
    available = [c for c in SCORE_COLS if c in sub.columns]
    sub = sub[sub[available].notna().any(axis=1)]
    return sub.sort_values("date")

def get_pre_post_cols(df: pd.DataFrame):
    pre_cols  = [c for c in df.columns if re.search(r"pre",  str(c), re.I) and re.search(r"q\d+", str(c), re.I)]
    post_cols = [c for c in df.columns if re.search(r"post", str(c), re.I) and re.search(r"q\d+", str(c), re.I)]
    pre_cols  = sorted(pre_cols,  key=lambda c: int(re.search(r"\d+", c).group()))
    post_cols = sorted(post_cols, key=lambda c: int(re.search(r"\d+", c).group()))
    return pre_cols, post_cols

def load_master_local(file) -> pd.DataFrame:
    df = pd.read_excel(file) if file.name.endswith(".xlsx") else pd.read_csv(file)
    df["name_key"] = df["student_name"].apply(clean_name)
    df["date"]     = pd.to_datetime(df.get("date", pd.NaT), errors="coerce")
    return df

def load_prepost_local(file) -> pd.DataFrame | None:
    raw = pd.read_excel(file, header=None) if file.name.endswith(".xlsx") else pd.read_csv(file, header=None)
    header_row = 0
    for idx, row in raw.iterrows():
        vals = " ".join([str(v) for v in row if str(v) not in ("nan", "")]).lower()
        if "name" in vals or "שם" in vals:
            header_row = idx
            break
            
    df = pd.read_excel(file, header=header_row) if file.name.endswith(".xlsx") else pd.read_csv(file, header=header_row)
    
    name_col = None
    for c in df.columns:
        c_str = str(c).lower().strip()
        if ("name" in c_str or "שם" in c_str) and "unnamed" not in c_str:
            name_col = c
            break
            
    if name_col is None:
        name_col = df.columns[0]
        
    df = df.rename(columns={name_col: "name"})
    df = df.loc[:, ~df.columns.duplicated()].copy()
    df = df[df["name"].notna()]
    df = df[df["name"].astype(str).str.strip() != ""]
    df["name_key"] = df["name"].astype(str).apply(clean_name)
    df.index = range(len(df))
    return df

# ─────────────────────────────────────────────
# פונקציית ארכוב ושמירה לדרייב
# ─────────────────────────────────────────────
def save_chain(name: str, messages: list) -> tuple[bool, str]:
    clean = re.sub(r"[^\w]", "_", name)
    path = os.path.abspath(f"Report_Triangulation_{clean}.txt")
    try:
        content = "\n\n" + "=" * 50 + "\n\n"
        content = content.join([f"[{m['role'].upper()}]:\n{m['content']}" for m in messages])
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return True, path
    except Exception as e:
        return False, str(e)

# ─────────────────────────────────────────────
# סוכן Gemini - הגדרת זהות נקייה מהמלצות
# ─────────────────────────────────────────────
SYSTEM_RULES = """
אתה פרופסור ומתודולוג מחקר בכיר המלווה כתיבת פרק ממצאים (Results) בלבד לתזת מאסטר במחקר פעולה.
תפקידך לחלץ תמות, קטגוריות וקשרים כמותיים ואיכותניים מתוך הדאטה האמיתי המועבר אליך בעוגני המערכת.

חוק קשיח ואבסולוטי: אסור לך בשום אופן לכתוב המלצות פדגוגיות, עצות למורה, או הצעות לעתיד. התמקד אך ורק במה שהנתונים הסטטיסטיים והטקסטים מראים בפועל ברמת הממצא הטהור.

הנחיה קריטית למניעת סלט:
- משתני cat_* (מוקדי קושי) הם ספירת שגיאות גולמית בסולם 1-5! ציון נמוך (כמו 1) הוא חוזק ומצוין (אפס שגיאות). אל תציג ציון נמוך ב-cat_* כחולשה.
- ציר הזמן מסודר כרונולוגית: דצמבר 2025 הוא תחילת הסמסטר (Baseline), פברואר ומאי 2026 הם ההמשך.
נהל שיחה משורשרת. כתוב בעברית אקדמית רהוטה לפי כללי APA 7th Edition (הצג משתנים סטטיסטיים באותיות נטויות, וללא אפס לפני הנקודה העשרונית במתאמים ומובהקות, לדוגמה: r = -.60).
"""

def init_gemini(api_key: str):
    import google.generativeai as genai
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-2.5-flash", system_instruction=SYSTEM_RULES)
    return model.start_chat(history=[])

# ─────────────────────────────────────────────
# 🤖 פונקציית הטאב הראשי
# ─────────────────────────────────────────────
def render_ai_agent_tab():
    st.subheader("🤖 סוכן ניתוח ממצאים (שיחה משורשרת)")
    
    st.markdown("### 📁 שלב א': טעינת קבצי המחקר לסוכן")
    uploaded_files = st.file_uploader(
        "גרור לכאן את קובץ המאסטר ואת קובץ השאלונים יחד:", 
        type=["xlsx", "csv"], 
        accept_multiple_files=True,
        key="agent_tab_file_uploader"
    )

    df_master_local = None
    df_pp_local = None

    if uploaded_files:
        for file in uploaded_files:
            try:
                sniff = pd.read_excel(file, header=None, nrows=5) if file.name.endswith(".xlsx") else pd.read_csv(file, header=None, nrows=5)
                combined_text = " ".join([str(v) for v in sniff.values.flatten() if str(v) not in ("nan", "")]).lower()
                file.seek(0)
                
                if 'work_method' in combined_text or 'student_name' in combined_text or 'score_spatial' in combined_text:
                    df_master_local = load_master_local(file)
                    st.success(f"✅ קובץ תצפיות (Master) נטען בהצלחה: {file.name}")
                elif 'preq' in combined_text or 'post' in combined_text or 'q1_pre' in combined_text:
                    df_pp_local = load_prepost_local(file)
                    st.success(f"✅ קובץ שאלונים (Pre/Post) נטען בהצלחה: {file.name}")
            except Exception as e:
                st.error(f"שגיאה בעיבוד הקובץ {file.name}: {e}")

    st.markdown("---")
    st.markdown("### 💬 שלב ב': התכתבות וניתוח תמות")
    st.caption("הסוכן זוכר את כל השיחה. שאל שאלות המשך בצורה רציפה (למשל: 'למה הציון שלו ירד אובייקטיבית?').")

    if "gemini_session" not in st.session_state:
        st.session_state.gemini_session = None
    if "agent_messages" not in st.session_state:
        st.session_state.agent_messages = []
    if "current_analyzed_student" not in st.session_state:
        st.session_state.current_analyzed_student = None

    for msg in st.session_state.agent_messages:
        with st.chat_message(msg["role"]): 
            st.markdown(msg["content"])

    prompt = st.chat_input("שאל על ממצאים, תמות, קטגוריות...")
    if prompt:
        st.session_state.agent_messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"): 
            st.markdown(prompt)

        with st.chat_message("assistant"):
            api_key = st.secrets.get("GOOGLE_API_KEY", "")
            if not api_key:
                st.error("⚠️ חסר מפתח GOOGLE_API_KEY ב-Streamlit Secrets.")
                st.stop()

            if st.session_state.gemini_session is None:
                st.session_state.gemini_session = init_gemini(api_key)

            active_master = df_master_local if df_master_local is not None else st.session_state.get("df_master")
            active_pp = df_pp_local if df_pp_local is not None else st.session_state.get("df_pp")

            # 🛠️ פתרון קסם: פייתון מפיק את הדוח הסטטיסטי האמיתי ומזריק אותו כעוגן קשיח ל-Gemini
            global_stats_payload = {}
            if active_master is not None:
                global_stats_payload["master_total_rows"] = int(len(active_master))
                
                # חישוב מדדי ביצוע אמיתיים
                scores_summary = {}
                for c in SCORE_COLS:
                    if c in active_master.columns:
                        valid_data = active_master[c].dropna()
                        if not valid_data.empty:
                            scores_summary[c] = {
                                "n": int(len(valid_data)),
                                "mean": round(float(valid_data.mean()), 2),
                                "sd": round(float(valid_data.std()), 2),
                                "min": float(valid_data.min()),
                                "max": float(valid_data.max())
                            }
                global_stats_payload["performance_scores_stats"] = scores_summary

                # חישוב מדדי שגיאה אמיתיים
                cats_summary = {}
                for c in CAT_COLS:
                    if c in active_master.columns:
                        valid_data = active_master[c].dropna()
                        if not valid_data.empty:
                            cats_summary[c] = {
                                "n": int(len(valid_data)),
                                "mean": round(float(valid_data.mean()), 2),
                                "sd": round(float(valid_data.std()), 2),
                                "min": float(valid_data.min()),
                                "max": float(valid_data.max())
                            }
                global_stats_payload["error_categories_stats"] = cats_summary

            if active_pp is not None:
                pre_q_cols, post_q_cols = get_pre_post_cols(active_pp)
                if pre_q_cols and post_q_cols:
                    active_pp['pre_m'] = active_pp[pre_q_cols].apply(pd.to_numeric, errors='coerce').mean(axis=1)
                    active_pp['post_m'] = active_pp[post_q_cols].apply(pd.to_numeric, errors='coerce').mean(axis=1)
                    
                    # קבוצה כללית
                    valid_paired = active_pp[['pre_m', 'post_m']].dropna()
                    global_stats_payload["questionnaire_total_paired"] = int(len(valid_paired))
                    global_stats_payload["questionnaire_global_pre_mean"] = round(float(valid_paired['pre_m'].mean()), 2)
                    global_stats_payload["questionnaire_global_post_mean"] = round(float(valid_paired['post_m'].mean()), 2)
                    
                    # קבוצת ה-3D (N=10)
                    3d_col = next((c for c in active_pp.columns if '3d' in c.lower()), None)
                    if 3d_col is not None:
                        df_10 = active_pp[active_pp[3d_col].astype(str).str.contains('1|yes|true|כן', na=False)].dropna(subset=['pre_m', 'post_m'])
                        global_stats_payload["questionnaire_3d_group_n"] = int(len(df_10))
                        global_stats_payload["questionnaire_3d_pre_mean"] = round(float(df_10['pre_m'].mean()), 2)
                        global_stats_payload["questionnaire_3d_post_mean"] = round(float(df_10['post_m'].mean()), 2)

            # זיהוי תלמיד ספציפי
            student_payload = ""
            if active_master is not None:
                all_students = list(active_master["student_name"].dropna().unique())
                found_student = None
                for s in all_students:
                    if str(s).strip() in prompt:
                        found_student = s
                        break
                
                if found_student and found_student != st.session_state.current_analyzed_student:
                    st.session_state.current_analyzed_student = found_student
                    key = clean_name(found_student)
                    obs = student_observations(active_master, key)
                    available = [c for c in SCORE_COLS if c in obs.columns]
                    
                    timeline = []
                    for _, row in obs.iterrows():
                        inverted_cats = {}
                        for c in CAT_COLS:
                            if c in row and pd.notna(row[c]):
                                inverted_cats[f"{c}_efficiency_index"] = round(float(5.0 - pd.to_numeric(row[c])), 2)

                        timeline.append({
                            "date": str(row.get("date", ""))[:10],
                            "difficulty": row.get("difficulty"),
                            "performance_scores": {c: row.get(c) for c in available},
                            "error_category_counts_raw": {c: row.get(c) for c in CAT_COLS if c in row},
                            "cognitive_efficiency_indices_calculated": inverted_cats,
                            "work_method": row.get("work_method"),
                            "interpretation": str(row.get("interpretation", row.get("insight", "")))[:500],
                            "tags": str(row.get("tags", "")),
                        })
                    
                    pp_data = {}
                    if active_pp is not None:
                        name_col = "name_key" if "name_key" in active_pp.columns else "name"
                        pp_row = active_pp[active_pp[name_col] == key]
                        if not pp_row.empty:
                            if pre_q_cols: pp_data["mean_pre"] = round(float(pp_row['pre_m'].values[0]), 2)
                            if post_q_cols: pp_data["mean_post"] = round(float(pp_row['post_m'].values[0]), 2)
                    
                    student_payload = f"\n[נתוני מקרה בוחן ממוקד - תלמיד: {found_student}]: {json.dumps({'timeline': timeline, 'questionnaire': pp_data}, ensure_ascii=False)}"

            # בניית עוגן הנתונים המאוחד שנשלח ל-Gemini
            full_context_injection = f"\n### 📊 עוגן נתונים סטטיסטיים אמיתיים ומחושבים (מנוע פייתון פנימי): ###\n{json.dumps(global_stats_payload, ensure_ascii=False)}\n{student_payload}\n"

            with st.spinner("הסוכן מנתח ומגבש תמות..."):
                response = st.session_state.gemini_session.send_message(prompt + full_context_injection).text
            st.markdown(response)
            st.session_state.agent_messages.append({"role": "assistant", "content": response})

    if st.session_state.agent_messages:
        st.divider()
        col_name, col_btn = st.columns([3, 1])
        save_name = col_name.text_input("שם לקובץ הניתוח בארכיון:", value=f"Analysis_{st.session_state.current_analyzed_student or 'Output'}")
        if col_btn.button("💾 שמור שיחה לדרייב"):
            ok, path = save_chain(save_name, st.session_state.agent_messages)
            if ok: st.success(f"✅ כלל ממצאי השיחה המשורשרת אורכבו בהצלחה בנתיב המאסטר: `{path}`")
            else: st.error(f"⚠️ שגיאה בשמירה: {path}")"""
ai_engine.py — מנוע ה-AI והסוכן החכם (גרסה 2.6)
כולל: תיבות העלאת קבצים עצמאיות בטאב, מניעת סלט משתני קושי, מניעת Token Bloat ושרשור שיחה
"""

import streamlit as st
import pandas as pd
import numpy as np
import re
import json
import os
from scipy import stats
from difflib import get_close_matches

# הגדרות המדדים לטובת עיבודי פייתון פנימיים
SCORE_COLS = ['score_proj', 'score_spatial', 'score_conv', 'score_efficacy', 'score_model', 'score_views']
CAT_COLS   = ["cat_convert_rep", "cat_dims_props", "cat_proj_trans", "cat_3d_support"]

# ─────────────────────────────────────────────
# פונקציות עזר - ניקוי שמות וסריקת קבצים
# ─────────────────────────────────────────────
def clean_name(val: str) -> str:
    if pd.isna(val):
        return ""
    val = str(val).strip().lower()
    val = re.sub(r"[^\w]", "", val)
    return val

def fuzzy_match(key: str, pool: list[str], cutoff: float = 0.82) -> str | None:
    if key in pool:
        return key
    matches = get_close_matches(key, pool, n=1, cutoff=cutoff)
    return matches[0] if matches else None

def student_observations(df_master: pd.DataFrame, name_key: str) -> pd.DataFrame:
    sub = df_master[df_master["name_key"] == name_key].copy()
    available = [c for c in SCORE_COLS if c in sub.columns]
    sub = sub[sub[available].notna().any(axis=1)]
    return sub.sort_values("date")

def get_pre_post_cols(df: pd.DataFrame):
    pre_cols  = [c for c in df.columns if re.search(r"pre",  str(c), re.I) and re.search(r"q\d+", str(c), re.I)]
    post_cols = [c for c in df.columns if re.search(r"post", str(c), re.I) and re.search(r"q\d+", str(c), re.I)]
    pre_cols  = sorted(pre_cols,  key=lambda c: int(re.search(r"\d+", c).group()))
    post_cols = sorted(post_cols, key=lambda c: int(re.search(r"\d+", c).group()))
    return pre_cols, post_cols

def load_master_local(file) -> pd.DataFrame:
    df = pd.read_excel(file) if file.name.endswith(".xlsx") else pd.read_csv(file)
    df["name_key"] = df["student_name"].apply(clean_name)
    df["date"]     = pd.to_datetime(df.get("date", pd.NaT), errors="coerce")
    return df

def load_prepost_local(file) -> pd.DataFrame | None:
    # 1. מציאת שורת הכותרת (השם או name) בצורה בטוחה
    raw = pd.read_excel(file, header=None) if file.name.endswith(".xlsx") else pd.read_csv(file, header=None)
    header_row = 0
    for idx, row in raw.iterrows():
        vals = " ".join([str(v) for v in row if str(v) not in ("nan", "")]).lower()
        if "name" in vals or "שם" in vals:
            header_row = idx
            break
            
    # 2. טעינת הקובץ מחדש
    df = pd.read_excel(file, header=header_row) if file.name.endswith(".xlsx") else pd.read_csv(file, header=header_row)
    
    # 🛠️ שיפור קריטי: הגנה מפני עמודות Unnamed המכילות את המחרוזת "name"
    # מאתר את עמודת השם האמיתית (שמכילה name או שם, אך אינה עמודה ריקה מסוג Unnamed)
    name_col = None
    for c in df.columns:
        c_str = str(c).lower().strip()
        if ("name" in c_str or "שם" in c_str) and "unnamed" not in c_str:
            name_col = c
            break
            
    # פתרון גיבוי למקרה שלא נמצאה עמודה מתאימה
    if name_col is None:
        name_col = df.columns[0]
        
    df = df.rename(columns={name_col: "name"})
    
    # 🛠️ ניקוי עמודות כפולות אחרות אם קיימות באקסל
    df = df.loc[:, ~df.columns.duplicated()].copy()
    
    # 3. הגנה אבסולוטית: ניקוי שורות ריקות ללא שימוש במתודות ציר בעייתיות
    df = df[df["name"].notna()]
    df = df[df["name"].astype(str).str.strip() != ""]
    
    # יצירת מפתח השם הנקי למנוע
    df["name_key"] = df["name"].astype(str).apply(clean_name)
    
    # איפוס אינדקס מספרי נקי
    df.index = range(len(df))
    
    return df
    
# ─────────────────────────────────────────────
# פונקציית ארכוב ושמירה לדרייב
# ─────────────────────────────────────────────

def save_chain(name: str, messages: list) -> tuple[bool, str]:
    clean = re.sub(r"[^\w]", "_", name)
    path = os.path.abspath(f"Report_Triangulation_{clean}.txt")
    try:
        content = "\n\n" + "=" * 50 + "\n\n"
        content = content.join([f"[{m['role'].upper()}]:\n{m['content']}" for m in messages])
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return True, path
    except Exception as e:
        return False, str(e)

# ─────────────────────────────────────────────
# סוכן Gemini - הגדרת זהות נקייה מהמלצות
# ─────────────────────────────────────────────
SYSTEM_RULES = """
אתה פרופסור ומתודולוג מחקר בכיר המלווה כתיבת פרק ממצאים (Results) בלבד לתזת מאסטר במחקר פעולה.
תפקידך לחלץ תמות, קטגוריות וקשרים כמותיים ואיכותניים מתוך הדאטה שמועבר אליך.

חוק קשיח ואבסולוטי: אסור לך בשום אופן לכתוב המלצות פדגוגיות, עצות למורה, או הצעות לעתיד (כמו 'מומלץ להשתמש ב-AR' או 'כדאי לתת לו משוב'). התמקד אך ורק במה שהנתונים מראים בפועל ברמת הממצא הטהור.

הנחיה קריטית למניעת סלט:
- משתני cat_* (מוקדי קושי) הם ספירת שגיאות! ציון נמוך (כמו 1) הוא חוזק ומצוין (אפס שגיאות). אל תציג ציון נמוך ב-cat_* כחולשה.
- ציר הזמן מסודר כרונולוגית: דצמבר 2025 הוא תחילת הסמסטר (Baseline), פברואר ומאי 2026 הם ההמשך.
נהל שיחה משורשרת. כתוב בעברית אקדמית רהוטה לפי כללי APA 7th Edition.
"""

def init_gemini(api_key: str):
    import google.generativeai as genai
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-2.5-flash", system_instruction=SYSTEM_RULES)
    return model.start_chat(history=[])

# ─────────────────────────────────────────────
# 🤖 פונקציית הטאב הראשי - רצה מתוך הבלוק שלך
# ─────────────────────────────────────────────
def render_ai_agent_tab():
    st.subheader("🤖 סוכן ניתוח ממצאים (שיחה משורשרת)")
    
    # 📁 פתרון: הוספת רכיב העלאת הקבצים ישירות לתוך הטאב של הסוכן
    st.markdown("### 📁 שלב א': טעינת קבצי המחקר לסוכן")
    uploaded_files = st.file_uploader(
        "גרור לכאן את קובץ המאסטר ואת קובץ השאלונים יחד:", 
        type=["xlsx", "csv"], 
        accept_multiple_files=True,
        key="agent_tab_file_uploader"
    )

    # משתני קבצים פנימיים לטאב
    df_master_local = None
    df_pp_local = None

    if uploaded_files:
        for file in uploaded_files:
            try:
                sniff = pd.read_excel(file, header=None, nrows=5) if file.name.endswith(".xlsx") else pd.read_csv(file, header=None, nrows=5)
                combined_text = " ".join([str(v) for v in sniff.values.flatten() if str(v) not in ("nan", "")]).lower()
                file.seek(0)
                
                if 'work_method' in combined_text or 'student_name' in combined_text or 'score_spatial' in combined_text:
                    df_master_local = load_master_local(file)
                    st.success(f"✅ קובץ תצפיות (Master) נטען בהצלחה: {file.name}")
                elif 'preq' in combined_text or 'post' in combined_text or 'q1_pre' in combined_text:
                    df_pp_local = load_prepost_local(file)
                    st.success(f"✅ קובץ שאלונים (Pre/Post) נטען בהצלחה: {file.name}")
            except Exception as e:
                st.error(f"שגיאה בעיבוד הקובץ {file.name}: {e}")

    st.markdown("---")
    st.markdown("### 💬 שלב ב': התכתבות וניתוח תמות")
    st.caption("הסוכן זוכר את כל השיחה. שאל שאלות המשך בצורה רציפה (למשל: 'למה הציון שלו ירד אובייקטיבית?').")

    # סנכרון משתני הזיכרון ב-Session State
    if "gemini_session" not in st.session_state:
        st.session_state.gemini_session = None
    if "agent_messages" not in st.session_state:
        st.session_state.agent_messages = []
    if "current_analyzed_student" not in st.session_state:
        st.session_state.current_analyzed_student = None

    # הצגת הודעות קודמות מההיסטוריה
    for msg in st.session_state.agent_messages:
        with st.chat_message(msg["role"]): 
            st.markdown(msg["content"])

    prompt = st.chat_input("שאל על ממצאים, תמות, קטגוריות...")
    if prompt:
        st.session_state.agent_messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"): 
            st.markdown(prompt)

        with st.chat_message("assistant"):
            api_key = st.secrets.get("GOOGLE_API_KEY", "")
            if not api_key:
                st.error("⚠️ חסר מפתח GOOGLE_API_KEY ב-Streamlit Secrets.")
                st.stop()

            if st.session_state.gemini_session is None:
                st.session_state.gemini_session = init_gemini(api_key)

            # זיהוי תלמיד בפרומפט לשליפת נתונים
            payload_str = ""
            # העדפת קבצים שנטענו בטאב הנוכחי, ואם אין - שימוש בקבצי המערכת הכלליים
            active_master = df_master_local if df_master_local is not None else st.session_state.get("df_master")
            active_pp = df_pp_local if df_pp_local is not None else st.session_state.get("df_pp")

            if active_master is not None:
                all_students = list(active_master["student_name"].dropna().unique())
                found_student = None
                for s in all_students:
                    if str(s).strip() in prompt:
                        found_student = s
                        break
                
                # מניעת Token Bloat - הזרקת ה-JSON מתבצעת רק אם זה תלמיד חדש בשיחה
                if found_student and found_student != st.session_state.current_analyzed_student:
                    st.session_state.current_analyzed_student = found_student
                    key = clean_name(found_student)
                    obs = student_observations(active_master, key)
                    available = [c for c in SCORE_COLS if c in obs.columns]
                    
                    timeline = []
                    for _, row in obs.iterrows():
                        # שיפור: היפוך מדדי השגיאה למדדי יעילות הפוכים (שגיאה נמוכה = יעילות גבוהה)
                        inverted_cats = {}
                        for c in CAT_COLS:
                            if c in row and pd.notna(row[c]):
                                inverted_cats[f"{c}_efficiency_index"] = round(float(5.0 - pd.to_numeric(row[c])), 2)

                        timeline.append({
                            "date": str(row.get("date", ""))[:10],
                            "difficulty": row.get("difficulty"),
                            "performance_scores": {c: row.get(c) for c in available},
                            "error_category_counts_raw": {c: row.get(c) for c in CAT_COLS if c in row},
                            "cognitive_efficiency_indices_calculated": inverted_cats,
                            "work_method": row.get("work_method"),
                            "interpretation": str(row.get("interpretation", row.get("insight", "")))[:500],
                            "tags": str(row.get("tags", "")),
                        })
                    
                    pp_data = {}
                    if active_pp is not None:
                        name_col = "name_key" if "name_key" in active_pp.columns else "name"
                        active_pp[name_col] = active_pp[name_col].apply(clean_name)
                        pp_row = active_pp[active_pp[name_col] == key]
                        if not pp_row.empty:
                            pre_cols, post_cols = get_pre_post_cols(active_pp)
                            if pre_cols: pp_data["mean_pre"] = round(float(pp_row[pre_cols].apply(pd.to_numeric, errors="coerce").mean(axis=1).mean()), 2)
                            if post_cols: pp_data["mean_post"] = round(float(pp_row[post_cols].apply(pd.to_numeric, errors="coerce").mean(axis=1).mean()), 2)
                    
                    payload_str = f"\n[עוגן נתוני מחקר - סטודנט: {found_student}]: {json.dumps({'timeline': timeline, 'questionnaire': pp_data}, ensure_ascii=False)}"

            with st.spinner("הסוכן מנתח ומגבש תמות..."):
                response = st.session_state.gemini_session.send_message(prompt + payload_str).text
            st.markdown(response)
            st.session_state.agent_messages.append({"role": "assistant", "content": response})

        # ממשק שמירה וארכוב אחיד לדרייב
        if st.session_state.agent_messages:
            st.divider()
            col_name, col_btn = st.columns([3, 1])
            save_name = col_name.text_input("שם לקובץ הניתוח בארכיון:", value=f"Analysis_{st.session_state.current_analyzed_student or 'Output'}")
            if col_btn.button("💾 שמור שיחה לדרייב"):
                ok, path = save_chain(save_name, st.session_state.agent_messages)
                if ok: st.success(f"✅ כלל ממצאי השיחה המשורשרת אורכבו בהצלחה בנתיב המאסטר: `{path}`")
                else: st.error(f"⚠️ שגיאה בשמירה: {path}")
