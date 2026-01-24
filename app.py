import json, base64, os, io, logging, pandas as pd, streamlit as st
import google.generativeai as genai
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload
from datetime import date, datetime

# --- 0. הגדרות ועיצוב ---
logging.basicConfig(level=logging.INFO)
DATA_FILE = "reflections.jsonl"
MASTER_FILENAME = "All_Observations_Master.xlsx"
GDRIVE_FOLDER_ID = st.secrets.get("GDRIVE_FOLDER_ID")
CLASS_ROSTER = ["נתנאל", "רועי", "אסף", "עילאי", "טדי", "גאל", "אופק", "דניאל.ר", "אלי", "טיגרן", "פולינה.ק", "תלמיד אחר..."]
TAGS_OPTIONS = ["התעלמות מקווים נסתרים", "בלבול בין היטלים", "קושי ברוטציה מנטלית", "טעות בפרופורציות", "קושי במעבר בין היטלים", "שימוש בכלי מדידה", "סיבוב פיזי של המודל", "תיקון עצמי", "עבודה עצמאית שוטפת"]

st.set_page_config(page_title="מערכת תצפית מחקרית - 53.0", layout="wide")

st.markdown("""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Heebo:wght@300;400;700&display=swap');
        html, body, .stApp { direction: rtl; text-align: right; font-family: 'Heebo', sans-serif !important; }
        [data-testid="stSlider"] { direction: ltr !important; }
        .stButton > button { width: 100%; font-weight: bold; border-radius: 12px; height: 3em; }
        .stButton button[kind="primary"] { background-color: #28a745; color: white; }
        .feedback-box { background-color: #f8f9fa; padding: 20px; border-radius: 15px; border: 1px solid #dee2e6; margin: 15px 0; }
    </style>
""", unsafe_allow_html=True)

# --- 1. פונקציות עזר ---
def normalize_name(name):
    if not isinstance(name, str): return ""
    return name.replace(" ", "").replace("־", "").replace("-", "").strip()

@st.cache_resource
def get_drive_service():
    try:
        b64 = st.secrets.get("GDRIVE_SERVICE_ACCOUNT_B64")
        js = base64.b64decode("".join(b64.split())).decode("utf-8")
        creds = Credentials.from_service_account_info(json.loads(js), scopes=["https://www.googleapis.com/auth/drive"])
        return build("drive", "v3", credentials=creds)
    except Exception as e:
        logging.error(f"Drive auth error: {e}")
        return None

@st.cache_data(ttl=30)
def load_full_dataset(_svc):
    df_drive = pd.DataFrame()
    if _svc:
        try:
            res = _svc.files().list(q=f"name='{MASTER_FILENAME}' and trashed=false", supportsAllDrives=True).execute().get('files', [])
            if res:
                req = _svc.files().get_media(fileId=res[0]['id'])
                fh = io.BytesIO(); downloader = MediaIoBaseDownload(fh, req)
                done = False
                while not done: _, done = downloader.next_chunk()
                fh.seek(0); df_drive = pd.read_excel(fh)
                cols = [c for c in df_drive.columns if any(x in c.lower() for x in ["student", "name", "שם", "תלמיד"])]
                if cols: df_drive.rename(columns={cols[0]: "student_name"}, inplace=True)
        except: pass
    df_local = pd.DataFrame()
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                df_local = pd.DataFrame([json.loads(l) for l in f if l.strip()])
        except: pass
    df = pd.concat([df_drive, df_local], ignore_index=True)
    if not df.empty and 'student_name' in df.columns:
        df['student_name'] = df['student_name'].astype(str).str.strip()
        df['name_clean'] = df['student_name'].apply(normalize_name)
    return df

# --- 2. אתחול משתנים ---
svc = get_drive_service()
full_df = load_full_dataset(svc)
if "it" not in st.session_state: st.session_state.it = 0
if "last_selected_student" not in st.session_state: st.session_state.last_selected_student = ""
if "show_success_bar" not in st.session_state: st.session_state.show_success_bar = False
if "last_feedback" not in st.session_state: st.session_state.last_feedback = ""
if "chat_history" not in st.session_state: st.session_state.chat_history = []

# --- 3. ממשק משתמש (טאבים) ---
tab1, tab2, tab3 = st.tabs(["📝 הזנה ומשוב", "🔄 סנכרון", "📊 ניתוח"])

with tab1:
    col_in, col_chat = st.columns([1.2, 1])
    
    with col_in:
        it = st.session_state.it
        student_name = st.selectbox("👤 בחר סטודנט", CLASS_ROSTER, key=f"sel_{it}")
        
        # לוגיקת זיהוי תלמיד
        if student_name != st.session_state.last_selected_student:
            target = normalize_name(student_name)
            match = full_df[full_df['name_clean'] == target] if not full_df.empty else pd.DataFrame()
            if match.empty and not full_df.empty:
                match = full_df[full_df['student_name'].str.contains(student_name, case=False, na=False)]
            st.session_state.show_success_bar = not match.empty
            st.session_state.student_context = match.tail(15).to_string() if not match.empty else ""
            st.session_state.last_selected_student = student_name
            st.session_state.chat_history = []
            st.rerun()

        if st.session_state.show_success_bar:
            st.success(f"✅ נמצאה היסטוריה עבור {student_name}.")
        else:
            st.info(f"ℹ️ {student_name}: אין תצפיות קודמות.")

        st.markdown("---")
        
        # 1. צורת עבודה
        work_method =
