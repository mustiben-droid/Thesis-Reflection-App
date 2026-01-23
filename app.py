import json
import base64
import os
import io
import logging
from datetime import date, datetime
import pandas as pd
import streamlit as st
import google.generativeai as genai
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload

# --- הגדרות לוגים ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- הגדרות קבועות ---
DATA_FILE = "reflections.jsonl"
MASTER_FILENAME = "All_Observations_Master.xlsx"
GDRIVE_FOLDER_ID = st.secrets.get("GDRIVE_FOLDER_ID")
CLASS_ROSTER = ["נתנאל", "רועי", "אסף", "עילאי", "טדי", "גאל", "אופק", "דניאל.ר", "אלי", "טיגרן", "פולינה.ק", "תלמיד אחר..."]
TAGS_OPTIONS = ["התעלמות מקווים נסתרים", "בלבול בין היטלים", "קושי ברוטציה מנטלית", "טעות בפרופורציות", "קושי במעבר בין היטלים", "שימוש בכלי מדידה", "סיבוב פיזי של המודל", "תיקון עצמי", "עבודה עצמאית שוטפת"]

st.set_page_config(page_title="מערכת תצפית - גרסה 35.4", layout="wide")

# --- RTL Styling ---
st.markdown("""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Heebo:wght@300;400;700&display=swap');
        html, body, .stApp { direction: rtl; text-align: right; font-family: 'Heebo', sans-serif !important; }
        .stTextInput input, .stTextArea textarea, .stSelectbox > div > div { direction: rtl; text-align: right; }
        [data-testid="stSlider"] { direction: ltr !important; }
        .stButton > button { width: 100%; font-weight: bold; border-radius: 12px; height: 3em; background-color: #28a745; color: white; }
        .feedback-box { background-color: #fff3cd; color: #856404; padding: 15px; border-radius: 10px; border: 1px solid #ffeeba; margin-bottom: 20px; font-size: 0.95em; }
    </style>
""", unsafe_allow_html=True)

# --- פונקציות תשתית (Drive & Cache) ---

@st.cache_resource
def get_drive_service():
    try:
        b64 = st.secrets.get("GDRIVE_SERVICE_ACCOUNT_B64")
        if not b64: return None
        json_str = base64.b64decode(b64).decode("utf-8")
        creds = Credentials.from_service_account_info(json.loads(json_str), scopes=["https://www.googleapis.com/auth/drive"])
        return build("drive", "v3", credentials=creds)
    except Exception: return None

def upload_file_to_drive(uploaded_file, svc):
    try:
        if not svc or uploaded_file is None: return None
        file_metadata = {'name': uploaded_file.name, 'parents': [GDRIVE_FOLDER_ID] if GDRIVE_FOLDER_ID else []}
        media = MediaIoBaseUpload(io.BytesIO(uploaded_file.getvalue()), mimetype=uploaded_file.type)
        file = svc.files().create(body=file_metadata, media_body=media, fields='id, webViewLink', supportsAllDrives=True).execute()
        return file.get('webViewLink')
    except Exception: return None

@st.cache_data(ttl=300)
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
    except Exception: return None, None

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
    except Exception: return False

def get_ai_response(prompt_type, context_data):
    api_key = st.secrets.get("GOOGLE_API_KEY")
    if not api_key: return "חסר מפתח API."
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-1.5-flash')
        prompts = {
            "feedback": f"מנחה פדגוגי. בקר תצפית: {context_data['challenge']}. תן 2 שורות משוב.",
            "chat": f"עוזר מחקר. היסטוריה של {context_data['name']}: {context_data['history']}. שאלה: {context_data['question']}",
            "analysis": f"נתח מאקרו: {context_data['stats']} ומיקרו: {context_data['raw']}. בנה פרופילים."
        }
        res = model.generate_content(prompts[prompt_type])
        return res.text
    except Exception: return "שגיאה ב-AI."

# --- ניהול מצב ---
if "it" not in st.session_state: st.session_state.it = 0
if "chat_history" not in st.session_state: st.session_state.chat_history = []
if "student_context" not in st.session_state: st.session_state.student_context = ""
if "last_selected_student" not in st.session_state: st.session_state.last_selected_student = ""
if "show_success_bar" not in st.session_state: st.session_state.show_success_bar = False
if "last_obs_feedback" not in st.session_state: st.session_state.last_obs_feedback = ""

svc = get_drive_service()
st.title("🎓 מנחה מחקר חכם - 35.4")
tab1, tab2, tab3 = st.tabs(["📝 הזנה ומשוב", "🔄 סנכרון", "🤖 ניתוח מגמות"])

with tab1:
    col_in, col_chat = st.columns([1.2, 1])
    with col_in:
        with st.container(border=True):
            it = st.session_state.it
            c1, c2 = st.columns(2)
            with c1:
                name_sel = st.selectbox("👤 בחר סטודנט", CLASS_ROSTER, key=f"n_{it}")
                student_name = st.text_input("שם חופשי:", key=f"fn_{it}") if name_sel == "תלמיד אחר..." else name_sel
                if student_name != st.session_state.last_selected_student:
                    st.session_state.chat_history = []
                    st.session_state.show_success_bar = False
                    with st.spinner("טוען..."):
                        df_hist, _ = load_master_from_drive(id(svc))
                        if df_hist is not None:
                            match = df_hist[df_hist['student_name'].astype(str).str.strip() == student_name.strip()]
                            if not match.empty:
                                st.session_state.student_context = match.tail(5).to_string()
                                st.session_state.show_success_bar = True
                            else: st.session_state.student_context = ""
                    st.session_state.last_selected_student = student_name
                    st.rerun()

            if st.session_state.show_success_bar:
                st.success(f"✅ נתוני {student_name} נטענו בהצלחה.")

            with c2:
                work_method = st.radio("🛠️ סוג תרגול:", ["🧊 בעזרת גוף מודפס", "🎨 ללא גוף (דמיון)"], key=f"wm_{it}", horizontal=True)
                exercise_diff = st.select_slider("📉 רמת קושי:", options=["קל", "בינוני", "קשה"], value="בינוני", key=f"ed_{it}")

            q1, q2 = st.columns(2)
            with q1: drawings_count = st.number_input("כמות שרטוטים", min_value=0, step=1, key=f"dc_{it}")
            with q2: duration_min = st.number_input("זמן עבודה (דק')", min_value=0, step=5, key=f"dm_{it}")

            st.markdown("### 📊 מדדים כמותיים (1-5)")
            m1, m2 = st.columns(2)
            with m1:
                cat_convert_rep = st.slider("ה
