import streamlit as st
import pandas as pd
import json
import base64
import os
import io
import time
import requests
from datetime import date, datetime
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload
from streamlit_mic_recorder import mic_recorder

# --- חיבור למנוע הסטטיסטי המעודכן (ai_engine.py) ---
try:
    from ai_engine import render_ai_agent_tab
except ImportError:
    def render_ai_agent_tab():
        st.warning("⚠️ קובץ ai_engine.py לא נמצא או מכיל שגיאה. הטאב הזה מושבת.")

# ==========================================
# --- 0. הגדרות מערכת ועיצוב ---
# ==========================================
DATA_FILE = "reflections.jsonl"
MASTER_FILENAME = "All_Observations_Master.xlsx"

# תיקיית האם (לתמונות ותצפיות רגילות)
GDRIVE_FOLDER_ID = st.secrets.get("GDRIVE_FOLDER_ID")

# התיקייה החדשה שלך להקלטות וניתוחי ראיונות
INTERVIEW_FOLDER_ID = "1NQz2UZ6BfAURfN4a8h4_qSkyY-_gxhxP"

CLASS_ROSTER = ["נתנאל", "רועי", "אסף", "עילאי", "טדי", "מירון", "אופק", "דניאל.ר", "אלי", "טיגרן", "פולינה.ק", "תלמיד אחר..."]
TAGS_OPTIONS = ["התעלמות מקווים נסתרים", "בלבול בין היטלים", "קושי ברוטציה מנטלית", "טעות בפרופורציות", "קושי במעבר בין היטלים", "שימוש בכלי מדידה", "סיבוב פיזי של המודל", "תיקון עצמי", "עבודה עצמאית שוטפת"]

st.set_page_config(page_title="מערכת תצפית מחקרית - 54.0", layout="wide")

st.markdown("""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Heebo:wght=300;400;700&display=swap');
        
        /* הגדרות כלליות */
        html, body, .stApp { 
            direction: rtl; 
            text-align: right; 
            font-family: 'Heebo', sans-serif !important; 
        }

        /* מניעת היפוך של סליידרים */
        [data-testid="stSlider"] { direction: ltr !important; }

        /* תיקון להתראות ופסים ירוקים */
        [data-testid="stNotification"], .stAlert {
            direction: rtl;
            width: 100% !important;
            margin: 10px 0 !important;
        }
        
        /* --- פתרון הסיידבר החותך בטלפון --- */
        @media (max-width: 600px) {
            section[data-testid="stSidebar"] {
                display: none !important;
            }
            .main .block-container {
                padding-right: 1rem !important;
                padding-left: 1rem !important;
                width: 100% !important;
            }
        }

        /* עיצוב כפתורים ותיבות משוב */
        .stButton > button { width: 100%; font-weight: bold; border-radius: 12px; height: 3em; }
        .stButton button[kind="primary"] { background-color: #28a745; color: white; }
        .feedback-box { background-color: #f8f9fa; padding: 20px; border-radius: 15px; border: 1px solid #dee2e6; margin: 15px 0; color: #333; }
    </style>
""", unsafe_allow_html=True)

# ==========================================
# --- 1. פונקציות לוגיקה (נתונים ו-AI) ---
# ==========================================

def normalize_name(name):
    if not isinstance(name, str): return ""
    import re
    name = name.replace(" ", "")
    clean = re.sub(r'[^א-תa-zA-Z0-9]', '', name)
    return clean.strip().lower()

@st.cache_resource
def get_drive_service():
    try:
        b64 = st.secrets.get("GDRIVE_SERVICE_ACCOUNT_B64")
        if not b64: return None
        js = base64.b64decode("".join(b64.split())).decode("utf-8")
        creds = Credentials.from_service_account_info(json.loads(js), scopes=["https://www.googleapis.com/auth/drive"])
        return build("drive", "v3", credentials=creds)
    except: 
        return None

@st.cache_data(ttl=300)
def load_full_dataset(_svc):
    df_drive = pd.DataFrame()
    file_id = st.secrets.get("MASTER_FILE_ID")
    
    if _svc and file_id:
        try:
            req = _svc.files().get_media(fileId=file_id)
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, req)
            done = False
            while not done:
                _, done = downloader.next_chunk()
            fh.seek(0)
            df_drive = pd.read_excel(fh)
            
            if 'student_name' not in df_drive.columns:
                cols = [c for c in df_drive.columns if any(x in str(c).lower() for x in ["student", "name", "שם", "תלמיד"])]
                if cols:
                    df_drive.rename(columns={cols[0]: "student_name"}, inplace=True)
        except Exception as e:
            st.error(f"❌ שגיאה בטעינת קובץ המאסטר מהדרייב: {e}")

    df_local = pd.DataFrame()
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                df_local = pd.DataFrame([json.loads(l) for l in f if l.strip()])
        except Exception as e:
            st.error(f"❌ שגיאה בקריאת הנתונים המקומיים (reflections.jsonl): {e}")

    df = pd.concat([df_drive, df_local], ignore_index=True)
    
    if not df.empty:
        if 'timestamp' in df.columns:
            df['timestamp'] = pd.to_datetime(df['timestamp'], errors='coerce')
        
        df = df.drop_duplicates(subset=['student_name', 'timestamp'], keep='last')
        
        if 'student_name' in df.columns:
            df['student_name'] = df['student_name'].astype(str).str.strip()
            df['name_clean'] = df['student_name'].apply(normalize_name)
    
    return df
    
def call_gemini(prompt, audio_bytes=None):
    try:
        api_key = st.secrets.get("GOOGLE_API_KEY")
        if not api_key: return "שגיאה: חסר API Key"

        model_id = "gemini-1.5-flash" 
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent?key={api_key}"
        headers = {'Content-Type': 'application/json'}
        
        if audio_bytes:
            mime_type = "audio/webm" if audio_bytes.startswith(b'\x1a\x45\xdf\xa3') else "audio/wav"
            audio_base64 = base64.b64encode(audio_bytes).decode('utf-8')
            
            payload = {
                "contents": [{
                    "parts": [
                        {"text": prompt},
                        {"inlineData": {"mimeType": mime_type, "data": audio_base64}}
                    ]
                }]
            }
        else:
            payload = { "contents": [{"parts": [{"text": prompt}]}] }

        response = requests.post(url, headers=headers, json=payload, timeout=90)
        res_json = response.json()

        if response.status_code != 200:
            return f"שגיאת API ({response.status_code}): {res_json.get('error', {}).get('message', 'Unknown error')}"

        candidates = res_json.get('candidates', [])
        if not candidates:
            return "ג'ימיני לא החזיר תשובה. ייתכן שהתוכן נחסם עקב מגבלות בטיחות."
        
        return candidates[0].get('content', {}).get('parts', [{}])[0].get('text', 'לא התקבל טקסט מהמודל.')
    except Exception as e:
        return f"שגיאה טכנית: {str(e)}"

# ==========================================
# --- 2. פונקציות ממשק משתמש (Tabs) ---
# ==========================================

def validate_entry(entry):
    errors = []
    if not entry.get('student_name') or entry.get('student_name') == "תלמיד אחר...":
        errors.append("חובה לבחור שם תלמיד")
    if entry.get('duration_min', 0) <= 0:
        errors.append("זמן עבודה חייב להיות גדול מ-0")
    
    if errors:
        for err in errors:
            st.warning(f"⚠️ {err}")
        return False
    return True

def render_tab_entry(svc, full_df):
    it = st.session_state.it
    
    student_name = st.selectbox("👤 בחר סטודנט", CLASS_ROSTER, key=f"sel_{it}")
    
    if student_name != st.session_state.last_selected_student:
        target = normalize_name(student_name)
        match = full_df[full_df['name_clean'] == target] if not full_df.empty else pd.DataFrame()
        st.session_state.show_success_bar = not match.empty
        st.session_state.student_context = match.tail(15).to_string() if not match.empty else ""
        st.session_state.last_selected_student = student_name
        st.session_state.chat_history = []
        st.rerun()

    if st.session_state.show_success_bar:
        st.success(f"✅ נמצאה היסטוריה עבור {student_name}.")
    else:
        st.info(f"ℹ️ {student_name}: אין תצפיות קודמות.")

    col_in, col_chat = st.columns([1.2, 1])
    
    with col_in:
        c_metrics1, c_metrics2 = st.columns(2)
        with c_metrics1: # <--- כאן הקוד שלך נקטע! זה התיקון
            duration = st.number_input("⏱️ זמן עבודה (בדקות):", min_value=0, value=45, step=5, key=f"dur_{it}")
        with c_metrics2:
            drawings = st.number_input("📋 מספר שרטוטים שבוצעו:", min_value=0, value=1, step=1, key=f"drw_{it}")
