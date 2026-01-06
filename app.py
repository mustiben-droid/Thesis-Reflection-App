import json
import base64
import os
import io
from datetime import date, datetime, timedelta
import pandas as pd
import streamlit as st
from google import genai
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload

# --- 1. הגדרות קבועות ---
DATA_FILE = "reflections.jsonl"
GDRIVE_FOLDER_ID = st.secrets.get("GDRIVE_FOLDER_ID")
MASTER_FILENAME = "All_Observations_Master.xlsx"

CLASS_ROSTER = ["נתנאל", "רועי", "אסף", "עילאי", "טדי", "גאל", "אופק", "דניאל.ר", "אלי", "טיגרן", "תלמיד אחר..."]

OBSERVATION_TAGS = [
    "התעלמות מקווים נסתרים", "בלבול בין היטלים", "קושי ברוטציה מנטלית", 
    "טעות בפרופורציות", "קושי במעבר בין היטלים", "שימוש בכלי מדידה", 
    "סיבוב פיזי של המודל", "תיקון עצמי", "עבודה עצמאית שוטפת"
]

TASK_TYPES = ["מעבר דו-מימד לתלת-מימד", "בניית מודל משרטוט", "שרטוט היטל שלישי", "רוטציה מנטלית", "אחר..."]

# --- 2. עיצוב (CSS) ---
def setup_design():
    st.set_page_config(page_title="יומן תצפית מחקרי", page_icon="🎓", layout="centered")
    st.markdown("""
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Heebo:wght@300;400;700&display=swap');
            html, body, .stApp { direction: rtl; text-align: right; font-family: 'Heebo', sans-serif !important; }
            .stTextInput input, .stTextArea textarea, .stSelectbox > div > div { direction: rtl; text-align: right; }
            .stButton > button { width: 100%; font-weight: bold; border-radius: 10px; }
            [data-testid="stSlider"] { direction: ltr !important; }
        </style>
    """, unsafe_allow_html=True)

# --- 3. פונקציות שירות ועיבוד נתונים ---
def get_drive_service():
    try:
        json_str = base64.b64decode(st.secrets["GDRIVE_SERVICE_ACCOUNT_B64"]).decode("utf-8")
        creds = Credentials.from_service_account_info(json.loads(json_str), scopes=["https://www.googleapis.com/auth/drive.file"])
        return build("drive", "v3", credentials=creds)
    except: return None

def process_tags_to_columns(df):
    """הופך את רשימת התגיות לעמודות נפרדות של 0 ו-1 (ניתוח כמותני)"""
    for tag in OBSERVATION_TAGS:
        df[f"tag_{tag}"] = df['tags'].apply(lambda x: 1 if isinstance(x, str) and tag in x else 0)
    return df

def update_master_excel(data_to_add, svc, overwrite=False):
    try:
        query = f"name = '{MASTER_FILENAME}' and '{GDRIVE_FOLDER_ID}' in parents and trashed = false"
        res = svc.files().list(q=query).execute().get('files', [])
        
        new_df = pd.DataFrame(data_to_add)
        
        if res and not overwrite:
            file_id = res[0]['id']
            request = svc.files().get_media(fileId=file_id)
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done: _, done = downloader.next_chunk()
            fh.seek(0)
            existing_df = pd.read_excel(fh)
            df = pd.concat([existing_df, new_df], ignore_index=True)
        else:
            df = new_df
            file_id = res[0]['id'] if res else None

        # עיבוד תגיות לעמודות סטטיסטיות לפני השמירה
        df = process_tags_to_columns(df)
        
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False)
        output.seek(0)
        
        media = MediaIoBaseUpload(output, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        if file_id: svc.files().update(fileId=file_id, media_body=media).execute()
        else: svc.files().create(body={'name': MASTER_FILENAME, 'parents': [GDRIVE_FOLDER_ID]}, media_body=media).execute()
        return True
    except Exception as e:
        st.error(f"שגיאה בעדכון האקסל: {e}")
        return False

# --- 4. ממשק המשתמש ---
setup_design()
st.title("🎓 יומן תצפית - מהדורת מחקר תזה")

tab1, tab2, tab3 = st.tabs(["📝 רפלקציה", "📊 ניהול נתונים", "💬 צ'אט AI"])

with tab1:
    with st.form("main_form", clear_on_submit=True):
        st.subheader("1. פרטי המטלה")
        c1, c2, c3 = st.columns([2, 2, 1])
        with c1:
            sel = st.selectbox("👤 שם תלמיד", CLASS_ROSTER)
            student_name = st.text_input("שם חופשי:") if sel == "תלמיד אחר..." else sel
        with c2:
            task_type = st.selectbox("🎯 סוג מטלה", TASK_TYPES)
        with c3:
            difficulty = st.select_slider("⚖️ קושי", options=[1, 2, 3], value=2, help="1=קל, 2=בינוני, 3=קשה")

        st.subheader("2. כמות וזמן")
        col_time, col_draw = st.columns(2)
        with col_time:
            work_duration = st.number_input("⏱️ זמן עבודה (דקות)", min_value=0, step=5)
        with col_draw:
            drawings_count = st.number_input("✏️ מספר שרטוטים שבוצעו", min_value=0, step=1)

        tags = st.multiselect("🏷️ תגיות נצפות", OBSERVATION_TAGS)
        
        st.subheader("3. תיאור איכותני")
        ca, cb = st.columns(2)
        with ca:
            planned = st.text_area("📋 תיאור המטלה")
            challenge = st.text_area("🗣️ ציטוטים וקשיים")
        with cb:
            done = st.text_area("👀 פעולות שבוצעו")
            interpretation = st.text_area("💡 פרשנות/קוד איכותני")
        
        uploaded_files = st.file_uploader("📸 העלאת תמונות", accept_multiple_files=True, type=['png', 'jpg', 'jpeg'])
        
        st.subheader("4. מדדי הערכה (1-5)")
        m_cols = st.columns(5)
        m1 = m_cols[0].select_slider("היטלים", options=[1,2,3,4,5], value=3)
        m2 = m_cols[1].select_slider("מרחבית", options=[1,2,3,4,5], value=3)
        m3 = m_cols[2].select_slider("המרת ייצוג", options=[1,2,3,4,5], value=3)
        m4 = m_cols[3].select_slider("מסוגלות", options=[1,2,3,4,5], value=3)
        m5 = m_cols[4].select_slider("מודל", options=[1,2,3,4,5], value=3)

        if st.form_submit_button("💾 שמור תצפית למחקר"):
            # העלאת תמונות וקבלת לינקים (פונקציה קיימת מהגרסאות הקודמות)
            svc = get_drive_service()
            img_links = []
            # ... (לוגיקת העלאת תמונות)
            
            entry = {
                "type": "reflection", "date": date.today().isoformat(), "student_name": student_name,
                "task_type": task_type, "difficulty": difficulty, "duration_min": work_duration, 
                "drawings_count": drawings_count, "tags": ", ".join(tags), 
                "planned": planned, "done": done, "challenge": challenge, "interpretation": interpretation,
                "score_proj": m1, "score_spatial": m2, "score_conv": m3, "score_efficacy": m4, "score_model": m5,
                "timestamp": datetime.now().strftime("%H:%M:%S")
            }
            
            with open(DATA_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            
            if svc: update_master_excel([entry], svc)
            st.success("הנתונים עובדו ונשמרו באקסל המרכזי! ✅")

with tab2:
    st.header("📊 סנכרון ועיבוד")
    if st.button("🔄 רענן וסנכרן את כל ההיסטוריה לאקסל חכם"):
        if os.path.exists(DATA_FILE):
            all_data = [json.loads(line) for line in open(DATA_FILE, "r", encoding="utf-8") if json.loads(line).get("type")=="reflection"]
            svc = get_drive_service()
            if svc:
                update_master_excel(all_data, svc, overwrite=True)
                st.success("כל הנתונים עובדו מחדש עם עמודות סטטיסטיות! ✅")

with tab3:
    st.header("💬 צ'אט מחקרי")
    # ... (ממשק הצ'אט מהגרסה הקודמת)

# --- סוף הקוד ---