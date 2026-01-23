import json
import base64
import os
import io
import pandas as pd
import streamlit as st
import google.generativeai as genai
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload
from datetime import date, datetime

# --- 1. הגדרות ועיצוב RTL ---
st.set_page_config(page_title="מערכת תצפית - 35.1", layout="wide")

st.markdown("""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Heebo:wght@300;400;700&display=swap');
        html, body, .stApp { direction: rtl; text-align: right; font-family: 'Heebo', sans-serif !important; }
        .stSuccess { border: 2px solid #28a745; padding: 10px; border-radius: 8px; }
    </style>
""", unsafe_allow_html=True)

# --- 2. פונקציות תשתית (Caching) ---
@st.cache_resource
def get_drive_service():
    try:
        b64 = st.secrets.get("GDRIVE_SERVICE_ACCOUNT_B64")
        if not b64: return None
        json_str = base64.b64decode(b64).decode("utf-8")
        creds = Credentials.from_service_account_info(json.loads(json_str), scopes=["https://www.googleapis.com/auth/drive"])
        return build("drive", "v3", credentials=creds)
    except: return None

@st.cache_data(ttl=300)
def load_master_data(svc_id):
    svc = get_drive_service()
    try:
        query = "name = 'All_Observations_Master.xlsx' and trashed = false"
        res = svc.files().list(q=query, spaces='drive', supportsAllDrives=True).execute().get('files', [])
        if not res: return None
        request = svc.files().get_media(fileId=res[0]['id'])
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done: _, done = downloader.next_chunk()
        fh.seek(0)
        return pd.read_excel(fh)
    except: return None

# --- 3. ניהול מצב (Session State) ---
if "last_student" not in st.session_state: st.session_state.last_student = ""
if "student_context" not in st.session_state: st.session_state.student_context = ""
if "show_success" not in st.session_state: st.session_state.show_success = False

svc = get_drive_service()
st.title("🎓 מנחה מחקר חכם - 35.1")

tab1, tab2 = st.tabs(["📝 הזנה", "🤖 ניתוח"])

with tab1:
    col_in, col_chat = st.columns([1.2, 1])
    with col_in:
        student_name = st.selectbox("👤 בחר סטודנט", ["נתנאל", "רועי", "אסף", "עילאי", "טדי", "גאל", "אופק", "דניאל.ר", "אלי", "טיגרן", "פולינה.ק"])
        
        # לוגיקת טעינה עם "זיכרון" לסטריפ הירוק
        if student_name != st.session_state.last_student:
            st.session_state.show_success = False # איפוס לפני טעינה חדשה
            with st.spinner(f"טוען נתונים עבור {student_name}..."):
                df = load_master_data(id(svc))
                if df is not None:
                    # חיפוש מדויק (Exact Match)
                    match = df[df['student_name'].astype(str).str.strip() == student_name.strip()]
                    if not match.empty:
                        st.session_state.student_context = match.tail(5).to_string()
                        st.session_state.show_success = True # סימון להצגת הסטריפ
                    else:
                        st.session_state.student_context = ""
                        st.session_state.show_success = False
                st.session_state.last_student = student_name
                st.rerun()

        # הצגת הסטריפ הירוק אם המצב הוא True
        if st.session_state.show_success:
            st.success(f"✅ נתוני העבר של {student_name} נטענו בהצלחה.")

        # המשך הטופס
        challenge = st.text_area("🗣️ תיאור ותצפית")
        if st.button("💾 שמור"):
            # איפוס הסטריפ בשמירה כדי לא להעמיס
            st.session_state.show_success = False
            st.success("התצפית נשמרה!")
