import json, base64, os, io, time, logging, pandas as pd, streamlit as st
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

st.set_page_config(page_title="מערכת תצפית - זיהוי משופר", layout="wide")

st.markdown("""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Heebo:wght@300;400;700&display=swap');
        html, body, .stApp { direction: rtl; text-align: right; font-family: 'Heebo', sans-serif !important; }
        [data-testid="stSlider"] { direction: ltr !important; }
        .stButton > button { width: 100%; font-weight: bold; border-radius: 12px; background-color: #28a745; color: white; height: 3em; }
        .feedback-box { background-color: #fff3cd; padding: 15px; border-radius: 10px; border: 1px solid #ffeeba; margin-top: 10px; }
    </style>
""", unsafe_allow_html=True)

# --- 1. פונקציות עזר ---
def normalize_name(name):
    if not isinstance(name, str): return ""
    # ניקוי תווים מיוחדים ורווחים כפולים
    return name.replace(" ", "").replace(".", "").replace("־", "").replace("-", "").strip()

@st.cache_resource
def get_drive_service():
    try:
        b64 = st.secrets.get("GDRIVE_SERVICE_ACCOUNT_B64")
        js = base64.b64decode("".join(b64.split())).decode("utf-8")
        creds = Credentials.from_service_account_info(json.loads(js), scopes=["https://www.googleapis.com/auth/drive"])
        return build("drive", "v3", credentials=creds)
    except: return None

@st.cache_data(ttl=60)
def load_full_dataset(svc):
    df_drive = pd.DataFrame()
    if svc:
        try:
            res = svc.files().list(q=f"name='{MASTER_FILENAME}'", supportsAllDrives=True).execute().get('files', [])
            if res:
                req = svc.files().get_media(fileId=res[0]['id'])
                fh = io.BytesIO()
                downloader = MediaIoBaseDownload(fh, req)
                done = False
                while not done: _, done = downloader.next_chunk()
                fh.seek(0); df_drive = pd.read_excel(fh)
                # וידוא עמודת שם
                possible = [c for c in df_drive.columns if any(x in c.lower() for x in ["student", "name", "שם", "תלמיד"])]
                if possible: df_drive.rename(columns={possible[0]: "student_name"}, inplace=True)
        except: pass
    
    df_local = pd.DataFrame()
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                df_local = pd.DataFrame([json.loads(l) for l in f if l.strip()])
        except: pass

    df = pd.concat([df_drive, df_local], ignore_index=True)
    if not df.empty and 'student_name' in df.columns:
        df = df.dropna(subset=['student_name'])
        df['name_clean'] = df['student_name'].astype(str).apply(normalize_name)
    return df

svc = get_drive_service()
full_df = load_full_dataset(svc)

# --- 2. ממשק המשתמש ---
tab1, tab2, tab3 = st.tabs(["📝 הזנה ומשוב", "🔄 סנכרון", "📊 ניתוח"])

with tab1:
    col_in, col_chat = st.columns([1.2, 1])
    with col_in:
        # אתחול משתני מצב
        if "last_selected_student" not in st.session_state: st.session_state.last_selected_student = ""
        if "show_success_bar" not in st.session_state: st.session_state.show_success_bar = False
        if "it" not in st.session_state: st.session_state.it = 0

        student_name = st.selectbox("👤 בחר סטודנט", CLASS_ROSTER, key=f"sel_{st.session_state.it}")
        
        # --- לוגיקת זיהוי חכמה (הסליידר הירוק) ---
        if student_name != st.session_state.last_selected_student:
            target = normalize_name(student_name)
            match = pd.DataFrame()
            if not full_df.empty:
                # חיפוש לפי שם נקי או חיפוש חלקי (למקרה שיש שם משפחה באקסל)
                match = full_df[full_df['name_clean'] == target]
                if match.empty:
                    match = full_df[full_df['student_name'].str.contains(student_name, case=False, na=False)]
            
            if not match.empty:
                st.session_state.show_success_bar = True
                st.session_state.student_context = match.tail(10).to_string()
            else:
                st.session_state.show_success_bar = False
                st.session_state.student_context = ""
            
            st.session_state.last_selected_student = student_name
            st.rerun()

        if st.session_state.show_success_bar:
            st.success(f"✅ נמצאה היסטוריה עבור {student_name}. הסוכן מעודכן.")
        else:
            st.info(f"ℹ️ {student_name}: אין תצפיות קודמות.")

        st.markdown("---")
        # שאר השדות שלך (planned, challenge וכו') כאן...
        challenge = st.text_area("🗣️ תיאור התצפית (Challenge):", key=f"ch_{st.session_state.it}")
        
        if st.button("💾 שמור תצפית"):
            # לוגיקת שמירה...
            st.session_state.it += 1
            st.rerun()

# --- 3. סיידבר ודיבוג (הוחזר) ---
st.sidebar.title("🔍 ניהול ודיבוג")
if st.sidebar.button("📊 הצג רשימת שמות באקסל"):
    if not full_df.empty:
        st.sidebar.write("השמות שהמערכת מזהה באקסל:")
        st.sidebar.write(full_df['student_name'].unique().tolist())
    else:
        st.sidebar.error("האקסל לא נטען או ריק")

if st.sidebar.button("🔄 רענן נתונים (Refresh)"):
    st.cache_data.clear()
    st.rerun()

st.sidebar.write("מצב חיבור לדרייב:", "✅" if svc else "❌")
