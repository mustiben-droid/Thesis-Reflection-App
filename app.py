import json
import base64
import os
import io
import logging
import pandas as pd
import streamlit as st
import google.generativeai as genai
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload
from datetime import date, datetime

# --- 1. הגדרות תשתית ---
logging.basicConfig(level=logging.INFO)
DATA_FILE = "reflections.jsonl"
MASTER_FILENAME = "All_Observations_Master.xlsx"
GDRIVE_FOLDER_ID = st.secrets.get("GDRIVE_FOLDER_ID")
CLASS_ROSTER = ["נתנאל", "רועי", "אסף", "עילאי", "טדי", "גאל", "אופק", "דניאל.ר", "אלי", "טיגרן", "פולינה.ק", "תלמיד אחר..."]
TAGS_OPTIONS = ["התעלמות מקווים נסתרים", "בלבול בין היטלים", "קושי ברוטציה מנטלית", "טעות בפרופורציות", "קושי במעבר בין היטלים", "שימוש בכלי מדידה", "סיבוב פיזי של המודל", "תיקון עצמי", "עבודה עצמאית שוטפת"]

st.set_page_config(page_title="מערכת תצפית תזה - 38.0", layout="wide")

# RTL Styling
st.markdown("""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Heebo:wght@300;400;700&display=swap');
        html, body, .stApp { direction: rtl; text-align: right; font-family: 'Heebo', sans-serif !important; }
        [data-testid="stSlider"] { direction: ltr !important; }
        .stButton > button { width: 100%; font-weight: bold; border-radius: 12px; background-color: #28a745; color: white; height: 3em; }
        .feedback-box { background-color: #fff3cd; padding: 15px; border-radius: 10px; border: 1px solid #ffeeba; margin-top: 10px; }
    </style>
""", unsafe_allow_html=True)

# --- 2. פונקציות עזר (Drive & AI) ---
@st.cache_resource
def get_drive_service():
    try:
        b64 = st.secrets.get("GDRIVE_SERVICE_ACCOUNT_B64")
        if not b64: return None
        json_str = base64.b64decode(b64).decode("utf-8")
        creds = Credentials.from_service_account_info(json.loads(json_str), scopes=["https://www.googleapis.com/auth/drive"])
        return build("drive", "v3", credentials=creds)
    except Exception as e: return None

def upload_file_to_drive(uploaded_file, svc):
    try:
        if not svc or uploaded_file is None: return None
        file_metadata = {'name': uploaded_file.name, 'parents': [GDRIVE_FOLDER_ID] if GDRIVE_FOLDER_ID else []}
        media = MediaIoBaseUpload(io.BytesIO(uploaded_file.getvalue()), mimetype=uploaded_file.type)
        file = svc.files().create(body=file_metadata, media_body=media, fields='id, webViewLink', supportsAllDrives=True).execute()
        return file.get('webViewLink')
    except: return None

@st.cache_data(ttl=60)
def load_master_from_drive(svc_id):
    svc = get_drive_service()
    try:
        query = f"name = '{MASTER_FILENAME}' and trashed = false"
        res = svc.files().list(q=query, spaces='drive', supportsAllDrives=True).execute().get('files', [])
        target = next((f for f in res if f['name'] == MASTER_FILENAME), None)
        if not target: return None, None
        request = svc.files().get_media(fileId=target['id'])
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done: _, done = downloader.next_chunk()
        fh.seek(0)
        return pd.read_excel(fh), target['id']
    except: return None, None

def update_master_in_drive(new_data_df, svc):
    try:
        existing_df, file_id = load_master_from_drive(id(svc))
        df = pd.concat([existing_df, new_data_df], ignore_index=True).drop_duplicates(subset=['student_name', 'timestamp'], keep='last') if existing_df is not None else new_data_df
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False)
        output.seek(0)
        media = MediaIoBaseUpload(output, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        if file_id: svc.files().update(fileId=file_id, media_body=media, supportsAllDrives=True).execute()
        else:
            meta = {'name': MASTER_FILENAME, 'parents': [GDRIVE_FOLDER_ID] if GDRIVE_FOLDER_ID else []}
            svc.files().create(body=meta, media_body=media, supportsAllDrives=True).execute()
        st.cache_data.clear()
        return True
    except: return False

def get_ai_response(prompt_type, context_data):
    api_key = st.secrets.get("GOOGLE_API_KEY")
    if not api_key: return "שגיאת API"
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-1.5-flash')
        prompts = {
            "chat": f"אתה עוזר מחקר. היסטוריה של {context_data['name']}: {context_data['history']}. שאלה: {context_data['question']}",
            "feedback": f"תצפית: {context_data['challenge']}. תן 2 שורות משוב פדגוגי בונה."
        }
        res = model.generate_content(prompts[prompt_type])
        return res.text
    except: return "שגיאה ב-AI"

# --- 3. ניהול מצב (Session State) ---
if "it" not in st.session_state: st.session_state.it = 0
if "chat_history" not in st.session_state: st.session_state.chat_history = []
if "student_context" not in st.session_state: st.session_state.student_context = ""
if "last_selected_student" not in st.session_state: st.session_state.last_selected_student = ""
if "show_success_bar" not in st.session_state: st.session_state.show_success_bar = False
if "last_feedback" not in st.session_state: st.session_state.last_feedback = ""

svc = get_drive_service()
st.title("🎓 מערכת תצפית חכמה - גרסה 38.0")
tab1, tab2, tab3 = st.tabs(["📝 הזנה ומשוב", "🔄 סנכרון", "📊 ניתוח"])

with tab1:
    col_in, col_chat = st.columns([1.2, 1])
    with col_in:
        it = st.session_state.it
        student_name = st.selectbox("👤 בחר סטודנט", CLASS_ROSTER, key=f"sel_{it}")
        
        # לוגיקה חדשה לסטריפ הירוק: חיפוש משולב (דרייב + מקומי)
        if student_name != st.session_state.last_selected_student:
            st.session_state.chat_history = []
            st.session_state.show_success_bar = False
            with st.spinner(f"סורק היסטוריה עבור {student_name}..."):
                # 1. חיפוש בדרייב
                df_hist, _ = load_master_from_drive(id(svc))
                # 2. חיפוש בקובץ המקומי (אם קיים)
                df_local = pd.DataFrame([json.loads(l) for l in open(DATA_FILE, "r", encoding="utf-8")] if os.path.exists(DATA_FILE) else [])
                
                # איחוד מקורות
                full_data = pd.concat([df_hist, df_local], ignore_index=True) if df_hist is not None else df_local
                
                if not full_data.empty and 'student_name' in full_data.columns:
                    match = full_data[full_data['student_name'].astype(str).str.strip() == student_name.strip()]
                    if not match.empty:
                        st.session_state.student_context = match.tail(10).to_string()
                        st.session_state.show_success_bar = True
                    else: st.session_state.student_context = ""
            st.session_state.last_selected_student = student_name
            st.rerun()

        if st.session_state.show_success_bar:
            st.success(f"✅ נמצאה היסטוריה עבור {student_name}. הסוכן מעודכן.")
        else:
            st.info(f"ℹ️ {student_name}: אין תצפיות קודמות (בדרייב או מקומית).")

        # טופס מלא
        c1, c2 = st.columns(2)
        with c1:
            work_method = st.radio("🛠️ סוג תרגול:", ["🧊 בעזרת גוף מודפס", "🎨 ללא גוף (דמיון)"], key=f"wm_{it}", horizontal=True)
            ex_diff = st.select_slider("📉 רמת קושי:", options=["קל", "בינוני", "קשה"], key=f"ed_{it}")
        with c2:
            drw_cnt = st.number_input("כמות שרטוטים", min_value=0, key=f"dc_{it}")
            dur_min = st.number_input("זמן עבודה (דק')", min_value=0, key=f"dm_{it}")

        st.markdown("### 📊 מדדים כמותיים (1-5)")
        m1, m2 = st.columns(2)
        with m1:
            s_conv = st.slider("המרת ייצוגים", 1, 5, 3, key=f"s1_{it}")
            s_proj = st.slider("מעבר בין היטלים", 1, 5, 3, key=f"s2_{it}")
        with m2:
            s_modl = st.slider("שימוש במודל", 1, 5, 3, key=f"s3_{it}")
            s_effi = st.slider("מסוגלות עצמית", 1, 5, 3, key=f"s4_{it}")

        tags = st.multiselect("🏷️ תגיות אבחון", TAGS_OPTIONS, key=f"t_{it}")
        challenge = st.text_area("🗣️ תיאור התצפית", key=f"ch_{it}")
        interpretation = st.text_area("🧠 פרשנות מחקרית", key=f"int_{it}")
        up_files = st.file_uploader("📷 צרף תמונות", accept_multiple_files=True, type=['png','jpg','jpeg'], key=f"up_{it}")

        if st.session_state.last_feedback:
            st.markdown(f'<div class="feedback-box"><b>💡 משוב:</b><br>{st.session_state.last_feedback}</div>', unsafe_allow_html=True)

        if st.button("💾 שמור תצפית"):
            if not challenge: st.error("מלא תיאור.")
            else:
                with st.spinner("שומר..."):
                    links = [upload_file_to_drive(f, svc) for f in up_files] if up_files else []
                    entry = {
                        "date": date.today().isoformat(), "student_name": student_name, "work_method": work_method,
                        "exercise_difficulty": ex_diff, "drawings_count": int(drw_cnt), "duration_min": int(dur_min),
                        "s1": s_conv, "s2": s_proj, "s3": s_modl, "s4": s_effi, "tags": tags,
                        "challenge": challenge, "interpretation": interpretation, "file_links": [l for l in links if l],
                        "timestamp": datetime.now().isoformat()
                    }
                    with open(DATA_FILE, "a", encoding="utf-8") as f:
                        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                    st.session_state.last_feedback = get_ai_response("feedback", {"challenge": challenge})
                    st.session_state.show_success_bar = False
                    st.rerun()

    with col_chat:
        st.subheader(f"🤖 יועץ: {student_name}")
        chat_cont = st.container(height=450)
        for q, a in st.session_state.chat_history:
            with chat_cont:
                st.chat_message("user").write(q)
                st.chat_message("assistant").write(a)
        u_q = st.chat_input("שאל את היועץ...")
        if u_q:
            r = get_ai_response("chat", {"name": student_name, "history": st.session_state.student_context, "question": u_q})
            st.session_state.chat_history.append((u_q, r))
            st.rerun()

with tab2:
    if os.path.exists(DATA_FILE):
        if st.button("🚀 סנכרן הכל לדרייב"):
            with open(DATA_FILE, "r", encoding="utf-8") as fh: all_entries = [json.loads(l) for l in fh if l.strip()]
            if update_master_in_drive(pd.DataFrame(all_entries), svc): st.success("סונכרן!")

with tab3:
    st.header("📊 ניתוח נתונים")
    if st.button("✨ בצע ניתוח מגמות AI"):
        df, _ = load_master_from_drive(id(svc))
        if df is not None:
            stats = df.groupby(['student_name'])[['s1', 's2', 's3', 's4']].mean().to_string()
            st.markdown(get_ai_response("chat", {"name": "מערכת", "history": stats, "question": "נתח את המגמות הכלליות של הכיתה"}))
