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

# --- הגדרות קבועות ---
DATA_FILE = "reflections.jsonl"
GDRIVE_FOLDER_ID = st.secrets.get("GDRIVE_FOLDER_ID")

# רשימת התלמידים הקבועה
CLASS_ROSTER = [
    "נתנאל",
    "רועי",
    "אסף",
    "עילאי",
    "תלמיד אחר..." 
]

# רשימת התגיות (תגיות מהירות לניתוח) - מעודכן
OBSERVATION_TAGS = [
    # כשלים ואתגרים
    "התעלמות מקווים נסתרים",
    "בלבול בין היטלים (צד/פנים/על)",
    "קושי ברוטציה מנטלית",
    "טעות בפרופורציות/מידות",
    "מעבר בין היטלים",
    
    # אסטרטגיות עבודה
    "שימוש בכלי מדידה",
    "סיבוב פיזי של המודל",
    "שימוש בתנועות ידיים (Embodiment)",
    "ספירת משבצות",
    "תיקון עצמי",
    
    # התנהגות
    "בקשת אישור תכופה",
    "ויתור/תסכול",
    "עבודה עצמאית שוטפת",
    "הבנה אינטואיטיבית מהירה"
]

# -----------------------------
# פונקציית העיצוב (CSS)
# -----------------------------
def setup_design():
    st.set_page_config(page_title="יומן תצפית", page_icon="🎓", layout="centered")
    
    st.markdown("""
        <style>
            /* הגדרות בסיס */
            .stApp, [data-testid="stAppViewContainer"] { background-color: #ffffff !important; }
            .block-container { padding-top: 1rem !important; padding-bottom: 5rem !important; max-width: 100% !important; }
            [data-testid="stForm"], [data-testid="stVerticalBlock"] > div { background-color: transparent !important; border: none !important; box-shadow: none !important; padding: 0 !important; }
            
            h1, h2, h3, h4, h5, h6 { color: #4361ee !important; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; text-align: center !important; }
            p, label, span, div { color: #2c3e50 !important; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
            
            [data-testid="stSlider"] { direction: rtl; padding-bottom: 10px; width: 100%; }
            [data-testid="stSlider"] label p { font-size: 18px !important; font-weight: 600 !important; margin-bottom: 5px !important; }
            [data-testid="stThumbValue"] { font-size: 16px !important; font-weight: bold !important; }

            /* תיקון צבעים לתפריטים ותגיות */
            .stSelectbox > div > div, .stMultiSelect > div > div { 
                background-color: #f8f9fa !important; 
                border: 1px solid #e0e0e0 !important; 
                border-radius: 8px !important; 
                color: #000000 !important;
            }
            
            /* תפריטים נפתחים */
            div[data-baseweb="popover"], div[data-baseweb="menu"], ul[role="listbox"] {
                background-color: #ffffff !important;
                color: #000000 !important;
            }
            div[role="option"] { color: #000000 !important; background-color: #ffffff !important; }
            div[role="option"]:hover { background-color: #eef2ff !important; color: #000000 !important; }

            /* תגיות נבחרות (Chips) */
            span[data-baseweb="tag"] {
                background-color: #eef2ff !important;
                border: 1px solid #4361ee !important;
            }
            span[data-baseweb="tag"] span {
                color: #4361ee !important; 
                font-weight: bold;
            }

            .stTextInput input, .stTextArea textarea { background-color: #f8f9fa !important; border: 1px solid #e0e0e0 !important; border-radius: 8px !important; direction: rtl !important; text-align: right; color: #000000 !important; }
            
            /* תיקון העלאת קבצים */
            [data-testid="stFileUploader"] { padding: 10px; background-color: #f8f9fa; border-radius: 8px; }
            [data-testid="stFileUploader"] section { background-color: #ffffff !important; }
            [data-testid="stFileUploader"] small, [data-testid="stFileUploader"] span, [data-testid="stFileUploader"] div { color: #000000 !important; }
            [data-testid="stFileUploader"] button { color: #000000 !important; background-color: #e0e0e0 !important; border-color: #cccccc !important; }

            [data-testid="stFormSubmitButton"] > button { background-color: #4361ee !important; color: white !important; border: none; width: 100%; padding: 15px; font-size: 20px; font-weight: bold; border-radius: 12px; margin-top: 20px; box-shadow: 0 4px 6px rgba(67, 97, 238, 0.3); }

            html, body { direction: rtl; }
        </style>
    """, unsafe_allow_html=True)

# -----------------------------
# פונקציות לוגיקה
# -----------------------------
def get_google_api_key() -> str:
    return st.secrets.get("GOOGLE_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""

def get_drive_service():
    if not GDRIVE_FOLDER_ID or not st.secrets.get("GDRIVE_SERVICE_ACCOUNT_B64"): return None
    try:
        SCOPES = ["https://www.googleapis.com/auth/drive.file"]
        service_account_json_str = base64.b64decode(st.secrets["GDRIVE_SERVICE_ACCOUNT_B64"]).decode("utf-8")
        creds = Credentials.from_service_account_info(json.loads(service_account_json_str), scopes=SCOPES)
        return build("drive", "v3", credentials=creds)
    except Exception as e:
        st.error(f"Drive connect failed: {e}"); return None

def save_reflection(entry: dict) -> dict:
    with open(DATA_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return {"status": "saved", "date": entry["date"]}

def load_data_as_dataframe():
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
    if not df.empty and "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"])
    return df

def load_last_week():
    if not os.path.exists(DATA_FILE): return []
    today = date.today()
    week_ago = today - timedelta(days=6)
    out = []
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip(): continue
            e = json.loads(line)
            if e.get("type") == "weekly_summary": continue
            try:
                d = date.fromisoformat(e.get("date", today.isoformat()))
            except: continue
            if week_ago <= d <= today: out.append(e)
    return out

# --- העלאת קבצים לדרייב (עם תמיכה בתיקיות משותפות) ---
def upload_file_to_drive(file_obj, filename, mime_type, drive_service):
    media = MediaIoBaseUpload(file_obj, mimetype=mime_type)
    file_metadata = {'name': filename, 'parents': [GDRIVE_FOLDER_ID], 'mimeType': mime_type}
    drive_service.files().create(body=file_metadata, media_body=media, supportsAllDrives=True).execute()

# --- סיכום מחקרי ---
def generate_summary(entries: list) -> str:
    if not entries: return "לא נמצאו נתונים."
    full_text = "\n".join([str(e) for e in entries])
    prompt = f"""
    אתה עוזר מחקר אקדמי. נתח את הנתונים לפי הקטגוריות:
    1. המרת ייצוגים.
    2. מידות ופרופורציות.
    3. מעבר בין היטלים.
    4. שימוש בגוף מודפס (מניפולציה פיזית).
    5. מסוגלות עצמית.
    
    נתונים: {full_text}
    """
    api_key = get_google_api_key()
    if not api_key: return "חסר מפתח"
    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(model="gemini-2.0-flash", contents=prompt, config={"temperature": 0.2})
        return response.text
    except Exception as e: return f"Error: {e}"

# -----------------------------
# ממשק ראשי (Main UI)
# -----------------------------

setup_design()

st.title("🎓 יומן תצפית")
st.markdown("### מעקב אחר מיומנויות תפיסה מרחבית")

tab1, tab2, tab3 = st.tabs(["📝 רפלקציה", "📊 התקדמות וייצוא", "🧠 עוזר מחקרי"])

# --- לשונית 1: הזנת נתונים ---
with tab1:
    with st.form("reflection_form"):
        st.markdown("#### 1. פרטי התצפית") 
        col_student, col_lesson = st.columns(2)
        with col_student:
            selected_student = st.selectbox("👤 שם תלמיד", CLASS_ROSTER)
            student_name = st.text_input("✍️ הזן שם תלמיד:") if selected_student == "תלמיד אחר..." else selected_student
        with col_lesson:
            lesson_id = st.text_input("📚 שיעור מס'", placeholder="לדוגמה: היטלים 1")

        st.markdown("#### 2. אופן העבודה")
        work_method = st.radio("🛠️ כיצד התבצע השרטוט?", ["🎨 ללא גוף (דמיון)", "🧊 בעזרת גוף פיזי"], horizontal=True)

        st.markdown("#### 3. תיאור תצפית")
        
        # --- תגיות מהירות (מעודכן) ---
        selected_tags = st.multiselect("🏷️ תגיות מהירות (ניתן לבחור כמה):", OBSERVATION_TAGS)
        
        col_text1, col_text2 = st.columns(2)
        with col_text1:
            planned = st.text_area("📋 תיאור המטלה", height=100, placeholder="מה נדרש לעשות?")
            challenge = st.text_area("🗣️ ציטוטים / תגובות", height=100, placeholder="ציטוטים, שפת גוף...")
        with col_text2:
            done = st.text_area("👀 פעולות שנצפו", height=100, placeholder="מה הוא עשה בפועל?")
        
        # --- העלאת תמונה ---
        st.markdown("#### 📷 תיעוד ויזואלי")
        uploaded_image = st.file_uploader("צרף צילום שרטוט/ג