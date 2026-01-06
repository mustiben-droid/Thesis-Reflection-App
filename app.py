import json
import base64
import os
import io
from datetime import date, datetime, timedelta
import pandas as pd
import streamlit as st
from google import genai

# --- Google Drive Imports ---
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# --- 1. הגדרות קבועות ---
DATA_FILE = "reflections.jsonl"
GDRIVE_FOLDER_ID = st.secrets.get("GDRIVE_FOLDER_ID")

# --- רשימת התלמידים המעודכנת ---
CLASS_ROSTER = [
    "נתנאל", "רועי", "אסף", "עילאי", "טדי", "גאל", "אופק", "דניאל.ר", "אלי", "טיגרן", "תלמיד אחר..." 
]

OBSERVATION_TAGS = [
    "התעלמות מקווים נסתרים", "בלבול בין היטלים (צד/פנים/על)", "קושי ברוטציה מנטלית",
    "טעות בפרופורציות/מידות", "קושי במעבר בין היטלים", "שימוש בכלי מדידה",
    "סיבוב פיזי של המודל", "שימוש בתנועות ידיים (Embodiment)", "ספירת משבצות",
    "תיקון עצמי", "בקשת אישור תכופה", "ויתור/תסכול", "עבודה עצמאית שוטפת", "הבנה אינטואיטיבית מהירה"
]

# --- 2. עיצוב (CSS) ---
def setup_design():
    st.set_page_config(page_title="יומן תצפית", page_icon="🎓", layout="centered")
    st.markdown("""
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Heebo:wght@300;400;700&display=swap');
            :root { --background-color: #ffffff; --text-color: #000000; }
            html, body, .stApp { background-color: #ffffff !important; color: #000000 !important; font-family: 'Heebo', sans-serif !important; direction: rtl; text-align: right; }
            .block-container { padding-top: 1rem; padding-bottom: 5rem; max-width: 100%; }
            h1, h2, h3, h4, h5, h6, p, label, span, div, small { color: #000000 !important; text-align: right; }
            h1 { text-align: center !important; }
            .stTextInput input, .stTextArea textarea, .stSelectbox > div > div { background-color: #ffffff !important; color: black !important; border: 1px solid #ced4da !important; border-radius: 8px; direction: rtl; text-align: right; }
            .stButton > button, .stDownloadButton > button { background-color: #f0f2f6 !important; color: black !important; border: 1px solid #b0b0b0 !important; width: 100%; font-weight: bold; }
            [data-testid="stFormSubmitButton"] > button { background: linear-gradient(90deg, #4361ee 0%, #3a0ca3 100%) !important; color: white !important; border: none; }
            [data-testid="stSlider"] { direction: ltr !important; text-align: left !important; }
            [data-testid="stForm"] { background-color: #ffffff; padding: 15px; border-radius: 15px; box-shadow: 0 4px 15px rgba(0,0,0,0.05); border: 1px solid #e0e0e0; }
        </style>
    """, unsafe_allow_html=True)

# --- 3. פונקציות עזר וטעינת נתונים ---
def get_google_api_key() -> str:
    return st.secrets.get("GOOGLE_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""

def get_drive_service():
    if not GDRIVE_FOLDER_ID or not st.secrets.get("GDRIVE_SERVICE_ACCOUNT_B64"): return None
    try:
        SCOPES = ["https://www.googleapis.com/auth/drive.file"]
        service_account_json_str = base64.b64decode(st.secrets["GDRIVE_SERVICE_ACCOUNT_B64"]).decode("utf-8")
        creds = Credentials.from_service_account_info(json.loads(service_account_json_str), scopes=SCOPES)
        return build("drive", "v3", credentials=creds)
    except: return None

def save_reflection(entry: dict) -> dict:
    with open(DATA_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return {"status": "saved", "date": entry["date"]}

def load_data_as_dataframe():
    """טוען את כל הנתונים המצטברים לטובת ייצוא מרוכז."""
    if not os.path.exists(DATA_FILE): return pd.DataFrame()
    data = []
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip(): continue
            try:
                entry = json.loads(line)
                if entry.get("type") == "reflection": data.append(entry)
            except: continue
    df = pd.DataFrame(data)
    if not df.empty:
        if "date" in df.columns: df["date"] = pd.to_datetime(df["date"]).dt.date
        score_cols = [c for c in df.columns if "cat_" in c]
        for col in score_cols: df[col] = pd.to_numeric(df[col], errors='coerce')
    return df

# --- 4. פונקציות דרייב (כולל תמיכה בכונן משותף) ---
def upload_file_to_drive(file_obj, filename, mime_type, drive_service):
    media = MediaIoBaseUpload(file_obj, mimetype=mime_type)
    file_metadata = {'name': filename, 'parents': [GDRIVE_FOLDER_ID]}
    drive_service.files().create(body=file_metadata, media_body=media, supportsAllDrives=True).execute()

def update_student_excel_in_drive(student_name, drive_service):
    try:
        df = load_data_as_dataframe()
        student_df = df[df['student_name'] == student_name]
        if student_df.empty: return False
        filename = f"Master_{student_name}.xlsx"
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            student_df.to_excel(writer, index=False, sheet_name='History')
        query = f"name = '{filename}' and '{GDRIVE_FOLDER_ID}' in parents and trashed = false"
        results = drive_service.files().list(q=query, fields="files(id, name)", supportsAllDrives=True, includeItemsFromAllDrives=True, corpora='allDrives').execute()
        files = results.get('files', [])
        media = MediaIoBaseUpload(io.BytesIO(output.getvalue()), mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        if not files:
            drive_service.files().create(body={'name': filename, 'parents': [GDRIVE_FOLDER_ID]}, media_body=media, supportsAllDrives=True).execute()
        else:
            drive_service.files().update(fileId=files[0]['id'], media_body=media, supportsAllDrives=True).execute()
        return True
    except: return False

# --- 5. ממשק ראשי ---
setup_design()
st.title("🎓 יומן תצפית")

tab1, tab2, tab3 = st.tabs(["📝 רפלקציה", "📊 התקדמות", "🤖 עוזר מחקרי"])

with tab1:
    with st.form("reflection_form", clear_on_submit=True):
        st.markdown("#### 1. פרטי התצפית")
        c1, c2 = st.columns(2)
        with c1:
            sel = st.selectbox("👤 תלמיד", CLASS_ROSTER)
            student_name = st.text_input("✍️ שם:") if sel == "תלמיד אחר..." else sel
        with c2:
            lesson_id = st.text_input("📚 שיעור")
            task_diff = st.selectbox("⚖️ קושי", ["בסיסי", "בינוני", "מתקדם"])
        
        work_method = st.radio("🛠️", ["🎨 ללא גוף (דמיון)", "🧊 בעזרת גוף מודפס"], horizontal=True)
        tags = st.multiselect("🏷️ תגיות", OBSERVATION_TAGS)
        
        col_a, col_b = st.columns(2)
        with col_a:
            planned = st.text_area("📋 המטלה")
            challenge = st.text_area("🗣️ ציטוטים")
        with col_b:
            done = st.text_area("👀 פעולות")
            interpretation = st.text_area("💡 פרשנות")
        
        imgs = st.file_uploader("📷 תמונות", type=['jpg', 'png'], accept_multiple_files=True)
        
        st.markdown("#### 4. מדדים")
        c_conv = st.select_slider("🔄 המרת ייצוגים", options=[1,2,3,4,5], value=3)
        c_proj = st.select_slider("📐 מעבר היטלים", options=[1,2,3,4,5], value=3)
        c_eff = st.select_slider("💪 מסוגלות", options=[1,2,3,4,5], value=3)

        if st.form_submit_button("💾 שמור"):
            entry = {
                "type": "reflection", "student_name": student_name, "lesson_id": lesson_id, "date": date.today().isoformat(),
                "planned": planned, "done": done, "interpretation": interpretation, "cat_proj_trans": c_proj, "cat_self_efficacy": c_eff
            }
            save_reflection(entry)
            svc = get_drive_service()
            if svc:
                upload_file_to_drive(io.BytesIO(json.dumps(entry).encode('utf-8')), f"ref-{student_name}-{entry['date']}.json", 'application/json', svc)
                update_student_excel_in_drive(student_name, svc)
            st.success("נשמר!")

with tab2:
    st.markdown("### 📊 לוח בקרה וייצוא")
    df = load_data_as_dataframe()
    
    if not df.empty:
        # --- החידוש: כפתור הורדה מרוכז ---
        st.markdown("#### 📥 הורדה מרוכזת של כל התצפיות")
        st.info(f"במערכת קיימות {len(df)} תצפיות מצטברות.")
        
        output_all = io.BytesIO()
        with pd.ExcelWriter(output_all, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='All_Observations')
        
        st.download_button(
            label="📥 הורד את כל ההיסטוריה (Excel)",
            data=output_all.getvalue(),
            file_name=f"Full_Data_{date.today()}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        st.divider()
        # --- (שאר הממשק של טאב 2 נשמר) ---
        st.markdown("#### 📂 ניהול תיקים")
        if st.button("🔄 עדכן את כל התיקים בדרייב"):
            svc = get_drive_service()
            if svc:
                for name in df['student_name'].unique(): update_student_excel_in_drive(name, svc)
                st.success("עודכן!")
    else:
        st.info("אין נתונים.")

with tab3:
    st.markdown("### 🤖 עוזר AI")
    # (כאן נמצא הקוד של טאב 3 כפי שהיה קודם)

# סוף הקוד