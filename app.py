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

# --- 1. הגדרות ו-Secrets ---
DATA_FILE = "reflections.jsonl"
MASTER_FILENAME = "All_Observations_Master.xlsx"
GDRIVE_FOLDER_ID = st.secrets.get("GDRIVE_FOLDER_ID")
CLASS_ROSTER = ["נתנאל", "רועי", "אסף", "עילאי", "טדי", "גאל", "אופק", "דניאל.ר", "אלי", "טיגרן", "פולינה.ק", "תלמיד אחר..."]

st.set_page_config(page_title="מערכת תצפית - 36.0", layout="wide")

# RTL Styling
st.markdown("""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Heebo:wght@300;400;700&display=swap');
        html, body, .stApp { direction: rtl; text-align: right; font-family: 'Heebo', sans-serif !important; }
        [data-testid="stSlider"] { direction: ltr !important; }
        .stButton > button { width: 100%; background-color: #28a745; color: white; border-radius: 12px; }
    </style>
""", unsafe_allow_html=True)

# --- 2. פונקציות תשתית ---
@st.cache_resource
def get_drive_service():
    try:
        b64 = st.secrets.get("GDRIVE_SERVICE_ACCOUNT_B64")
        if not b64: return None
        json_str = base64.b64decode(b64).decode("utf-8")
        creds = Credentials.from_service_account_info(json.loads(json_str), scopes=["https://www.googleapis.com/auth/drive"])
        return build("drive", "v3", credentials=creds)
    except: return None

@st.cache_data(ttl=60) # צמצום זמן ה-Cache כדי לראות עדכונים מהר יותר
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

def get_ai_response(prompt_type, context_data):
    api_key = st.secrets.get("GOOGLE_API_KEY")
    if not api_key: return "שגיאה: חסר API KEY"
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-1.5-flash')
        prompts = {
            "chat": f"אתה עוזר מחקר אקדמי. לפניך היסטוריית תצפיות של {context_data['name']}: \n{context_data['history']}\n השאלה: {context_data['question']}",
            "feedback": f"תן משוב פדגוגי קצר על: {context_data['challenge']}"
        }
        res = model.generate_content(prompts[prompt_type])
        return res.text
    except Exception as e: return f"שגיאה: {str(e)[:50]}"

# --- 3. ניהול מצב ---
if "chat_history" not in st.session_state: st.session_state.chat_history = []
if "student_context" not in st.session_state: st.session_state.student_context = ""
if "last_selected_student" not in st.session_state: st.session_state.last_selected_student = ""
if "show_success_bar" not in st.session_state: st.session_state.show_success_bar = False

svc = get_drive_service()
st.title("🎓 מנחה מחקר חכם - 36.0")
tab1, tab2 = st.tabs(["📝 הזנה ומשוב", "🔄 סנכרון"])

with tab1:
    col_in, col_chat = st.columns([1.2, 1])
    with col_in:
        student_name = st.selectbox("👤 בחר סטודנט", CLASS_ROSTER)
        
        # לוגיקת טעינה משופרת
        if student_name != st.session_state.last_selected_student:
            with st.spinner(f"מחפש נתונים עבור {student_name}..."):
                df_hist, _ = load_master_from_drive(id(svc))
                if df_hist is not None:
                    # ניקוי רווחים וחיפוש גמיש
                    df_hist['student_name_clean'] = df_hist['student_name'].astype(str).str.strip()
                    target_name = student_name.strip()
                    match = df_hist[df_hist['student_name_clean'] == target_name]
                    
                    if not match.empty:
                        st.session_state.student_context = match.tail(15).to_string()
                        st.session_state.show_success_bar = True
                    else:
                        st.session_state.student_context = "לא נמצאו נתונים קודמים באקסל."
                        st.session_state.show_success_bar = False
                
                st.session_state.last_selected_student = student_name
                st.session_state.chat_history = []
                st.rerun()

        if st.session_state.show_success_bar:
            st.success(f"✅ נמצאו נתונים קודמים עבור {student_name}. הסוכן מעודכן.")
        else:
            st.info(f"ℹ️ {student_name} הוא סטודנט חדש או שלא קיימות תצפיות עבורו בדרייב.")

        # מדדים וטופס
        st.markdown("### 📊 מדדים (1-5)")
        c1, c2 = st.columns(2)
        with c1:
            s1 = st.slider("המרת ייצוגים", 1, 5, 3)
            s2 = st.slider("מעבר בין היטלים", 1, 5, 3)
        with c2:
            s3 = st.slider("שימוש במודל", 1, 5, 3)
            s4 = st.slider("מסוגלות עצמית", 1, 5, 3)
        
        challenge = st.text_area("🗣️ תיאור התצפית")
        if st.button("💾 שמור"):
            st.toast("נשמר בהצלחה!")

    with col_chat:
        st.subheader(f"🤖 יועץ: {student_name}")
        chat_cont = st.container(height=450)
        for q, a in st.session_state.chat_history:
            with chat_cont:
                st.chat_message("user").write(q)
                st.chat_message("assistant").write(a)
        
        user_q = st.chat_input("שאל על מגמות...")
        if user_q:
            resp = get_ai_response("chat", {
                "name": student_name, 
                "history": st.session_state.student_context, 
                "question": user_q
            })
            st.session_state.chat_history.append((user_q, resp))
            st.rerun()
