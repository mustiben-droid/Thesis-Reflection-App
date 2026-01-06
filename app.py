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

CLASS_ROSTER = ["נתנאל", "רועי", "אסף", "עילאי", "טדי", "גאל", "אופק", "דניאל.ר", "אלי", "טיגרן", "תלמיד אחר..."]
OBSERVATION_TAGS = ["התעלמות מקווים נסתרים", "בלבול בין היטלים", "קושי ברוטציה מנטלית", "טעות בפרופורציות", "קושי במעבר בין היטלים", "שימוש בכלי מדידה", "סיבוב פיזי של המודל", "תיקון עצמי", "עבודה עצמאית שוטפת"]

# --- 2. עיצוב ---
def setup_design():
    st.set_page_config(page_title="יומן תצפית", layout="centered")
    st.markdown("""
        <style>
            html, body, .stApp { direction: rtl; text-align: right; }
            .stButton > button { width: 100%; border-radius: 8px; font-weight: bold; }
            [data-testid="stSlider"] { direction: ltr !important; }
        </style>
    """, unsafe_allow_html=True)

# --- 3. פונקציות נתונים ---
def save_reflection(entry: dict):
    with open(DATA_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

def load_data_as_dataframe():
    if not os.path.exists(DATA_FILE): return pd.DataFrame()
    data = []
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                try:
                    e = json.loads(line)
                    if e.get("type") == "reflection": data.append(e)
                except: continue
    return pd.DataFrame(data)

def get_drive_service():
    try:
        json_creds = base64.b64decode(st.secrets["GDRIVE_SERVICE_ACCOUNT_B64"]).decode("utf-8")
        creds = Credentials.from_service_account_info(json.loads(json_creds), scopes=["https://www.googleapis.com/auth/drive.file"])
        return build("drive", "v3", credentials=creds)
    except: return None

# --- 4. ממשק ---
setup_design()
st.title("🎓 יומן תצפית")

tab1, tab2, tab3 = st.tabs(["📝 רפלקציה", "📊 התקדמות", "🤖 עוזר AI"])

with tab1:
    with st.form("main_form", clear_on_submit=True):
        sel = st.selectbox("👤 תלמיד", CLASS_ROSTER)
        name = st.text_input("שם:") if sel == "תלמיד אחר..." else sel
        done = st.text_area("👀 מה בוצע?")
        c_proj = st.select_slider("📐 רמת שליטה בהיטלים", options=[1,2,3,4,5], value=3)
        if st.form_submit_button("💾 שמור"):
            entry = {"type": "reflection", "student_name": name, "done": done, "cat_proj_trans": c_proj, "date": date.today().isoformat()}
            save_reflection(entry)
            st.success("נשמר!")

with tab2:
    st.header("📊 ניהול נתונים")
    
    # טעינת הנתונים
    df = load_data_as_dataframe()
    
    # --- הכפתור המבוקש (תמיד יופיע אם יש קובץ נתונים) ---
    if not df.empty:
        st.subheader("📥 ייצוא נתונים")
        st.write(f"נמצאו {len(df)} תצפיות שמורות במערכת.")
        
        # יצירת הקובץ להורדה
        towrite = io.BytesIO()
        df.to_excel(towrite, index=False, engine='openpyxl')
        towrite.seek(0)
        
        st.download_button(
            label="✅ לחץ כאן להורדת כל התצפיות (Excel)",
            data=towrite,
            file_name=f"observation_data_{date.today()}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    else:
        st.info("עדיין אין נתונים שמורים. ברגע שתשמור תצפית אחת, כפתור ההורדה יופיע כאן.")

    st.divider()
    if st.button("📂 עדכן את כל התיקים בדרייב"):
        st.write("מבצע עדכון...")
        # כאן תרוץ פונקציית העדכון לדרייב

with tab3:
    st.write("עוזר ה-AI יהיה זמין כאן לניתוח הנתונים.")

# סוף הקוד