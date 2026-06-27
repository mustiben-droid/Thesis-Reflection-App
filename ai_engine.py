"""
ai_engine.py — מנוע ה-AI והסוכן החכם (גרסה 2.8)
תיקון קריטי: מאפשר לסוכן לקבל את הנתונים המצרפיים של כלל הכיתה (N=43) 
ולא להינעל על תלמיד בודד כאשר מתבקש ניתוח כמותי כללי.
"""

import streamlit as st
import pandas as pd
import numpy as np
import re
import json
import os
from scipy import stats
from difflib import get_close_matches

SCORE_COLS = ['score_proj', 'score_spatial', 'score_conv', 'score_views', 'score_efficacy', 'score_model']
CAT_COLS   = ["cat_convert_rep", "cat_dims_props", "cat_proj_trans", "cat_3d_support"]

def clean_name(val: str) -> str:
    if pd.isna(val): return ""
    val = str(val).strip().lower()
    val = re.sub(r"[^\w]", "", val)
    return val

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
    name_col = next((c for c in df.columns if ("name" in str(c).lower() or "שם" in str(c)) and "unnamed" not in str(c).lower()), df.columns[0])
    df = df.rename(columns={name_col: "name"})
    df = df.loc[:, ~df.columns.duplicated()].copy()
    df = df[df["name"].notna() & (df["name"].astype(str).str.strip() != "")]
    df["name_key"] = df["name"].astype(str).apply(clean_name)
    df.index = range(len(df))
    return df

def save_chain(name: str, messages: list) -> tuple[bool, str]:
    clean = re.sub(r"[^\w]", "_", name)
    path = os.path.abspath(f"Report_Triangulation_{clean}.txt")
    try:
        content = "\n\n" + "=" * 50 + "\n\n"
        content = content.join([f"[{m['role'].upper()}]:\n{m['content']}" for m in messages])
        with open(path, "w", encoding="utf-8") as f: f.write(content)
        return True, path
    except Exception as e: return False, str(e)

SYSTEM_RULES = """
אתה פרופסור ומתודולוג מחקר בכיר המלווה כתיבת פרק ממצאים (Results) בלבד לתזת מאסטר במחקר פעולה.
תפקידך לחלץ תמות, קטגוריות וקשרים כמותיים ואיכותניים מתוך הדאטה האמיתי המועבר אליך בעוגני המערכת.
חוק קשיח ואבסולוטי: אסור לך בשום אופן לכתוב המלצות פדגוגיות או הצעות לעתיד. התמקד אך ורק במה שהנתונים הסטטיסטיים מראים בפועל ברמת הממצא הטהור.
הנחיה קריטית למניעת סלט:
- משתני cat_* (מוקדי קושי) הם ספירת שגיאות גולמית בסולם 1-5! ציון נמוך (כמו 1) הוא חוזק ומצוין (אפס שגיאות).
- ציר הזמן מסודר כרונולוגית: דצמבר 2025 הוא תחילת הסמסטר, פברואר ומאי 2026 הם ההמשך.
נהל שיחה משורשרת. כתוב בעברית אקדמית רהוטה לפי כללי APA 7th Edition (אותיות נטויות למדדים, ללא אפס לפני הנקודה העשרונית במתאמים, למשל: r = -.60).
"""

def init_gemini(api_key: str):
    import google.generativeai as genai
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-2.5-flash", system_instruction=SYSTEM_RULES)
    return model.start_chat(history=[])

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

    if "gemini_session" not in st.session_state: st.session_state.gemini_session = None
    if "agent_messages" not in st.session_state: st.session_state.agent_messages = []
    if "current_analyzed_student" not in st.session_state: st.session_state.current_analyzed_student = None

    for msg in st.session_state.agent_messages:
        with st.chat_message(msg["role"]): st.markdown(msg["content"])

    prompt = st.chat_input("שאל על ממצאים, תמות, קטגוריות...")
    if prompt:
        st.session_state.agent_messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"): st.markdown(prompt)

        with st.chat_message("assistant"):
            api_key = st.secrets.get("GOOGLE_API_KEY", "")
            if not api_key: st.error("⚠️ חסר מפתח GOOGLE_API_KEY."); st.stop()
            if st.session_state.gemini_session is None: st.session_state.gemini_session = init_gemini(api_key)

            active_master = df_master_local if df_master_local is not None else st.session_state.get("df_master")
            active_pp = df_pp_local if df_pp_local is not None else st.session_state.get("df_pp")

            # 🛠️ חישוב והזרקת נתוני חתך כרונולוגיים ומצרפיים של כלל המערכת (N=43)
            global_stats_payload = {}
            if active_master is not None:
                global_stats_payload["master_total_rows"] = int(len(active_master))
                
                # חישוב מדדי ביצוע אמיתיים לכל הכיתה
                scores_summary = {}
                for c in SCORE_COLS:
                    if c in active_master.columns:
                        v_data = active_master[c].dropna()
                        if not v_data.empty:
                            scores_summary[c] = {
                                "n": int(len(v_data)), "mean": round(float(v_data.mean()), 2),
                                "sd": round(float(v_data.std()), 2), "min": float(v_data.min()), "max": float(v_data.max())
                            }
                global_stats_payload["performance_scores_stats_all_class"] = scores_summary

                # חישוב מדדי שגיאה אמיתיים לכל הכיתה
                cats_summary = {}
                for c in CAT_COLS:
                    if c in active_master.columns:
                        v_data = active_master[c].dropna()
                        if not v_data.empty:
                            cats_summary[c] = {
                                "n": int(len(v_data)), "mean": round(float(v_data.mean()), 2),
                                "sd": round(float(v_data.std()), 2), "min": float(v_data.min()), "max": float(v_data.max())
                            }
                global_stats_payload["error_categories_stats_all_class"] = cats_summary

            if active_pp is not None:
                pre_q_cols, post_q_cols = get_pre_post_cols(active_pp)
                if pre_q_cols and post_q_cols:
                    active_pp['pre_m'] = active_pp[pre_q_cols].apply(pd.to_numeric, errors='coerce').mean(axis=1)
                    active_pp['post_m'] = active_pp[post_q_cols].apply(pd.to_numeric, errors='coerce').mean(axis=1)
                    valid_paired = active_pp[['pre_m', 'post_m']].dropna()
                    global_stats_payload["questionnaire_total_paired_all_class"] = int(len(valid_paired))
                    global_stats_payload["questionnaire_global_pre_mean_all_class"] = round(float(valid_paired['pre_m'].mean()), 2)
                    global_stats_payload["questionnaire_global_post_mean_all_class"] = round(float(valid_paired['post_m'].mean()), 2)
                    
                    3d_col = next((c for c in active_pp.columns if '3d' in c.lower()), None)
                    if 3d_col is not None:
                        df_10 = active_pp[active_pp[3d_col].astype(str).str.contains('1|yes|true|כן', na=False)].dropna(subset=['pre_m', 'post_m'])
                        global_stats_payload["questionnaire_3d_group_n_subset"] = int(len(df_10))
                        global_stats_payload["questionnaire_3d_pre_mean_subset"] = round(float(df_10['pre_m'].mean()), 2)
                        global_stats_payload["questionnaire_3d_post_mean_subset"] = round(float(df_10['post_m'].mean()), 2)

            # 🛠️ שיפור קריטי: בודק אם הפרומפט של המשתמש מבקש ניתוח כללי או תלמיד ספציפי
            student_payload = ""
            is_general_query = any(w in prompt.lower() for w in ["כלל", "כל הכיתה", "מצרפי", "המדגם", "הכיתה", "טבלה 1", "טבלה 2"])
            
            if active_master is not None and not is_general_query:
                all_students = list(active_master["student_name"].dropna().unique())
                found_student = None
                for s in all_students:
                    if str(s).strip() in prompt: found_student = s; break
                
                if found_student:
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
                            "date": str(row.get("date", ""))[:10], "difficulty": row.get("difficulty"),
                            "performance_scores": {c: row.get(c) for c in available},
                            "error_category_counts_raw": {c: row.get(c) for c in CAT_COLS if c in row},
                            "cognitive_efficiency_indices_calculated": inverted_cats,
                            "work_method": row.get("work_method"),
                            "interpretation": str(row.get("interpretation", row.get("insight", "")))[:500],
                            "tags": str(row.get("tags", ""))
                        })
                    pp_data = {}
                    if active_pp is not None:
                        name_col = "name_key" if "name_key" in active_pp.columns else "name"
                        pp_row = active_pp[active_pp[name_col] == key]
                        if not pp_row.empty:
                            pp_data["mean_pre"] = round(float(pp_row['pre_m'].values[0]), 2)
                            pp_data["mean_post"] = round(float(pp_row['post_m'].values[0]), 2)
                    student_payload = f"\n[נתוני מקרה בוחן בודד]: {json.dumps({'student_name': found_student, 'timeline': timeline, 'questionnaire': pp_data}, ensure_ascii=False)}"

            # הזרקת ההקשר המלא המורחב
            full_context_injection = f"\n### 📊 עוגן נתונים מצרפיים מחושבים של כלל הכיתה (N=43): ###\n{json.dumps(global_stats_payload, ensure_ascii=False)}\n{student_payload}\n"

            with st.spinner("הסוכן מנתח ומגבש תמות..."):
                response = st.session_state.gemini_session.send_message(prompt + full_context_injection).text
            st.markdown(response)
            st.session_state.agent_messages.append({"role": "assistant", "content": response})

    if st.session_state.agent_messages:
        st.divider()
        col_name, col_btn = st.columns([3, 1])
        save_name = col_name.text_input("שם לקובץ הניתוח:", value=f"Analysis_{st.session_state.current_analyzed_student or 'Class_Global'}")
        if col_btn.button("💾 שמור שיחה לדרייב"):
            ok, path = save_chain(save_name, st.session_state.agent_messages)
            if ok: st.success(f"✅ השיחה אורכבה בהצלחה בנתיב: `{path}`")
            else: st.error(f"⚠️ שגיאה בשמירה: {path}")
