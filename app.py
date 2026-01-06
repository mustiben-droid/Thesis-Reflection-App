import json
import base64
import os
import io
from datetime import date, datetime, timedelta
import pandas as pd
import streamlit as st
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload

# --- 1. הגדרות קבועות ---
DATA_FILE = "reflections.jsonl"
GDRIVE_FOLDER_ID = st.secrets.get("GDRIVE_FOLDER_ID")
MASTER_FILENAME = "All_Observations_Master.xlsx"

CLASS_ROSTER = [
    "נתנאל", "רועי", "אסף", "עילאי", "טדי", "גאל", "אופק", "דניאל.ר", "אלי", "טיגרן", "תלמיד אחר..." 
]

OBSERVATION_TAGS = [
    "התעלמות מקווים נסתרים", "בלבול בין היטלים (צד/פנים/על)", "קושי ברוטציה מנטלית",
    "טעות בפרופורציות/מידות", "קושי במעבר בין היטלים", "שימוש בכלי מדידה",
    "סיבוב פיזי של המודל", "שימוש בתנועות ידיים (Embodiment)", "ספירת משבצות",
    "תיקון עצמי", "בקשת אישור תכופה", "ויתור/תסכול", "עבודה עצמאית שוטפת", "הבנה אינטואיטיבית מהירה"
]

# --- 2. עיצוב (CSS) - מחזיר את המראה הישן והאהוב ---
def setup_design():
    st.set_page_config(page_title="יומן תצפית", page_icon="🎓", layout="centered")
    st.markdown("""
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Heebo:wght@300;400;700&display=swap');
            html, body, .stApp {
                background-color: #ffffff !important;
                color: #000000 !important;
                font-family: 'Heebo', sans-serif !important;
                direction: rtl; 
                text-align: right;
            }
            .stTextInput input, .stTextArea textarea, .stSelectbox > div > div {
                direction: rtl; text-align: right;
            }
            .stButton > button { width: 100%; font-weight: bold; border-radius: 10px; }
            [data-testid="stSlider"] { direction: ltr !important; }
            [data-testid="stForm"] { 
                background-color: #ffffff; padding: 20px; border-radius: 15px; 
                border: 1px solid #e0e0e0; box-shadow: 0 4px 10px rgba(0,0,0,0.05);
            }
        </style>
    """, unsafe_allow_html=True)

# --- 3. פונקציות שירות וחיבור לדרייב ---
def get_drive_service():
    try:
        json_str = base64.b64decode(st.secrets["GDRIVE_SERVICE_ACCOUNT_B64"]).decode("utf-8")
        creds = Credentials.from_service_account_info(json.loads(json_str), scopes=["https://www.googleapis.com/auth/drive.file"])
        return build("drive", "v3", credentials=creds)
    except: return None

def update_master_excel(data_to_add, svc, overwrite=False):
    """מעדכן את האקסל המרכזי בדרייב (רשימת מילונים)."""
    try:
        query = f"name = '{MASTER_FILENAME}' and '{GDRIVE_FOLDER_ID}' in parents and trashed = false"
        results = svc.files().list(q=query, fields="files(id)").execute()
        files = results.get('files', [])

        if files and not overwrite:
            file_id = files[0]['id']
            request = svc.files().get_media(fileId=file_id)
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
            fh.seek(0)
            df = pd.read_excel(fh)
            df = pd.concat([df, pd.DataFrame(data_to_add)], ignore_index=True)
        else:
            df = pd.DataFrame(data_to_add)
            file_id = files[0]['id'] if files else None

        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False)
        output.seek(0)
        
        media = MediaIoBaseUpload(output, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        if file_id:
            svc.files().update(fileId=file_id, media_body=media, supportsAllDrives=True).execute()
        else:
            meta = {'name': MASTER_FILENAME, 'parents': [GDRIVE_FOLDER_ID]}
            svc.files().create(body=meta, media_body=media, supportsAllDrives=True).execute()
        return True
    except Exception as e:
        st.error(f"שגיאה בעדכון הדרייב: {e}")
        return False

# --- 4. ממשק המשתמש ---
setup_design()
st.title("🎓 יומן תצפית - הממשק המלא")

tab1, tab2 = st.tabs(["📝 רפלקציה חדשה", "📊 ניהול נתונים וסנכרון"])

with tab1:
    with st.form("main_form", clear_on_submit=True):
        st.subheader("1. פרטי התצפית")
        col1, col2 = st.columns(2)
        with col1:
            sel = st.selectbox("👤 שם תלמיד", CLASS_ROSTER)
            student_name = st.text_input("הזן שם:") if sel == "תלמיד אחר..." else sel
        with col2:
            lesson_id = st.text_input("📚 מזהה שיעור / נושא")
        
        st.subheader("2. אופן העבודה")
        work_method = st.radio("🛠️ כלי עבודה", ["🎨 ללא גוף (דמיון)", "🧊 בעזרת גוף מודפס"], horizontal=True)
        selected_tags = st.multiselect("🏷️ תגיות נצפות", OBSERVATION_TAGS)

        st.subheader("3. תיאור ופרשנות")
        c_a, c_b = st.columns(2)
        with c_a:
            planned = st.text_area("📋 המטלה שניתנה")
            challenge = st.text_area("🗣️ ציטוטים או קשיים מילוליים")
        with c_b:
            done = st.text_area("👀 פעולות נצפות (מה בוצע?)")
            interpretation = st.text_area("💡 פרשנות המורה (תובנות)")

        st.subheader("4. מדדים (1-5)")
        m1 = st.select_slider("🔄 המרת ייצוגים", options=[1,2,3,4,5], value=3)
        m2 = st.select_slider("📐 מעבר בין היטלים", options=[1,2,3,4,5], value=3)
        m3 = st.select_slider("💪 מסוגלות עצמית", options=[1,2,3,4,5], value=3)

        if st.form_submit_button("💾 שמור תצפית ועדכן דרייב"):
            entry = {
                "date": date.today().isoformat(),
                "student_name": student_name,
                "lesson_id": lesson_id,
                "work_method": work_method,
                "tags": ", ".join(selected_tags),
                "planned": planned,
                "done": done,
                "challenge": challenge,
                "interpretation": interpretation,
                "score_conversion": m1,
                "score_projection": m2,
                "score_efficacy": m3,
                "timestamp": datetime.now().strftime("%H:%M:%S")
            }
            
            # שמירה מקומית
            with open(DATA_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            
            # עדכון אקסל בדרייב
            svc = get_drive_service()
            if svc:
                if update_master_excel([entry], svc):
                    st.success(f"נשמר בהצלחה! השורה התווספה ל-{MASTER_FILENAME} בדרייב.")
                    st.balloons()
            else: st.warning("נשמר מקומית בלבד (בעיה בחיבור לדרייב).")

with tab2:
    st.header("📊 ניהול היסטוריה")
    st.write("לחץ כאן כדי לוודא שכל התצפיות הישנות שלך נמצאות בקובץ האקסל בדרייב:")
    
    if st.button("📤 סנכרן את כל המידע הקיים לאקסל בדרייב"):
        if os.path.exists(DATA_FILE):
            with st.spinner("מעבד נתונים..."):
                all_data = []
                with open(DATA_FILE, "r", encoding="utf-8") as f:
                    for line in f:
                        if line.strip(): all_data.append(json.loads(line))
                
                svc = get_drive_service()
                if svc and all_data:
                    if update_master_excel(all_data, svc, overwrite=True):
                        st.success(f"סנכרון הושלם! {len(all_data)} תצפיות נמצאות עכשיו בדרייב.")
        else:
            st.info("לא נמצאו נתונים קודמים לסנכרון.")

# סוף הקוד