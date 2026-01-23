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

# --- 1. הגדרות תשתית ולוגים ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DATA_FILE = "reflections.jsonl"
MASTER_FILENAME = "All_Observations_Master.xlsx"
GDRIVE_FOLDER_ID = st.secrets.get("GDRIVE_FOLDER_ID")
CLASS_ROSTER = ["נתנאל", "רועי", "אסף", "עילאי", "טדי", "גאל", "אופק", "דניאל.ר", "אלי", "טיגרן", "פולינה.ק", "תלמיד אחר..."]

st.set_page_config(page_title="מערכת תצפית תזה - 37.0", layout="wide")

# RTL ועיצוב
st.markdown("""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Heebo:wght@300;400;700&display=swap');
        html, body, .stApp { direction: rtl; text-align: right; font-family: 'Heebo', sans-serif !important; }
        [data-testid="stSlider"] { direction: ltr !important; }
        .stButton > button { width: 100%; font-weight: bold; border-radius: 12px; background-color: #28a745; color: white; }
        .feedback-box { background-color: #fff3cd; padding: 15px; border-radius: 10px; border: 1px solid #ffeeba; }
    </style>
""", unsafe_allow_html=True)

# --- 2. פונקציות Drive (מבוסס שיפורי Copilot) ---
@st.cache_resource
def get_drive_service():
    try:
        b64 = st.secrets.get("GDRIVE_SERVICE_ACCOUNT_B64")
        if not b64: return None
        json_str = base64.b64decode(b64).decode("utf-8")
        creds = Credentials.from_service_account_info(json.loads(json_str), scopes=["https://www.googleapis.com/auth/drive"])
        return build("drive", "v3", credentials=creds)
    except Exception as e:
        logger.error(f"Drive Auth Error: {e}")
        return None

def upload_file_to_drive(uploaded_file, svc):
    try:
        if not svc or uploaded_file is None: return None
        file_metadata = {'name': uploaded_file.name, 'parents': [GDRIVE_FOLDER_ID] if GDRIVE_FOLDER_ID else []}
        media = MediaIoBaseUpload(io.BytesIO(uploaded_file.getvalue()), mimetype=uploaded_file.type)
        file = svc.files().create(body=file_metadata, media_body=media, fields='id, webViewLink', supportsAllDrives=True).execute()
        return file.get('webViewLink')
    except Exception as e:
        logger.error(f"Upload Error: {e}")
        return None

@st.cache_data(ttl=120)
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
    except Exception as e:
        logger.error(f"Load Error: {e}")
        return None, None

def get_ai_response(prompt_type, context_data):
    api_key = st.secrets.get("GOOGLE_API_KEY")
    if not api_key: return "שגיאה: מפתח AI חסר ב-Secrets"
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-1.5-flash')
        prompts = {
            "chat": f"אתה עוזר מחקר. היסטוריה של {context_data['name']}: {context_data['history']}. שאלה: {context_data['question']}",
            "feedback": f"תצפית: {context_data['challenge']}. תן משוב פדגוגי קצר (2 שורות)."
        }
        res = model.generate_content(prompts[prompt_type])
        return res.text
    except Exception as e: return f"שגיאה ב-AI: {str(e)[:50]}"

# --- 3. ניהול מצב (Session State) ---
if "it" not in st.session_state: st.session_state.it = 0
if "chat_history" not in st.session_state: st.session_state.chat_history = []
if "student_context" not in st.session_state: st.session_state.student_context = ""
if "last_selected_student" not in st.session_state: st.session_state.last_selected_student = ""
if "show_success_bar" not in st.session_state: st.session_state.show_success_bar = False
if "last_feedback" not in st.session_state: st.session_state.last_feedback = ""

svc = get_drive_service()
st.title("🎓 מערכת תצפית חכמה - גרסה 37.0")
tab1, tab2, tab3 = st.tabs(["📝 הזנה ומשוב", "🔄 סנכרון", "📊 ניתוח"])

with tab1:
    col_in, col_chat = st.columns([1.2, 1])
    with col_in:
        it = st.session_state.it
        student_name = st.selectbox("👤 בחר סטודנט", CLASS_ROSTER, key=f"sel_{it}")
        
        # לוגיקת טעינה עם התיקונים של Copilot וחיפוש גמיש
        if student_name != st.session_state.last_selected_student:
            st.session_state.chat_history = []
            st.session_state.show_success_bar = False
            with st.spinner(f"טוען נתוני עבר עבור {student_name}..."):
                df_hist, _ = load_master_from_drive(id(svc))
                if df_hist is not None:
                    df_hist['student_name_clean'] = df_hist['student_name'].astype(str).str.strip()
                    match = df_hist[df_hist['student_name_clean'] == student_name.strip()]
                    if not match.empty:
                        st.session_state.student_context = match.tail(10).to_string()
                        st.session_state.show_success_bar = True
                    else: st.session_state.student_context = ""
            st.session_state.last_selected_student = student_name
            st.rerun()

        if st.session_state.show_success_bar:
            st.success(f"✅ נתוני {student_name} נטענו. הסוכן מוכן.")
        else:
            st.info(f"ℹ️ {student_name}: לא נמצאו תצפיות קודמות בדרייב.")

        # מדדים 1-5
        st.markdown("### 📊 מדדים כמותיים (1-5)")
        m1, m2 = st.columns(2)
        with m1:
            s_conv = st.slider("המרת ייצוגים", 1, 5, 3, key=f"s1_{it}")
            s_proj = st.slider("מעבר בין היטלים", 1, 5, 3, key=f"s2_{it}")
        with m2:
            s_modl = st.slider("שימוש במודל", 1, 5, 3, key=f"s3_{it}")
            s_effi = st.slider("מסוגלות עצמית", 1, 5, 3, key=f"s4_{it}")

        challenge = st.text_area("🗣️ תיאור התצפית", key=f"ch_{it}")
        up_files = st.file_uploader("📷 צרף תמונות", accept_multiple_files=True, type=['png','jpg','jpeg'], key=f"up_{it}")

        if st.session_state.last_feedback:
            st.markdown(f'<div class="feedback-box"><b>💡 משוב:</b><br>{st.session_state.last_feedback}</div>', unsafe_allow_html=True)

        if st.button("💾 שמור תצפית"):
            if not challenge: st.error("חובה להזין תיאור.")
            else:
                with st.spinner("מעלה ושומר..."):
                    links = [upload_file_to_drive(f, svc) for f in up_files] if up_files else []
                    entry = {
                        "date": date.today().isoformat(), "student_name": student_name,
                        "s1": s_conv, "s2": s_proj, "s3": s_modl, "s4": s_effi,
                        "challenge": challenge, "file_links": [l for l in links if l],
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
        
        u_q = st.chat_input("שאל על מגמות הסטודנט...")
        if u_q:
            r = get_ai_response("chat", {"name": student_name, "history": st.session_state.student_context, "question": u_q})
            st.session_state.chat_history.append((u_q, r))
            st.rerun()
