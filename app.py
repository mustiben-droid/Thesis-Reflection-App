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

# -----------------------------
# פונקציית העיצוב
# -----------------------------
def setup_design():
    st.set_page_config(page_title="יומן תצפית", page_icon="🎓", layout="centered")
    
    # התיקון לבעיה שראית בתמונה נמצא כאן - השימוש ב-st.markdown עם שלוש מרכאות
    st.markdown("""
        <style>
            /* 1. ביטול הרווח הריק העליון */
            .block-container {
                padding-top: 2rem !important;
                padding-bottom: 2rem !important;
            }

            /* 2. אילוץ מצב בהיר (Light Mode) */
            [data-testid="stAppViewContainer"] {
                background-color: #f4f6f9 !important;
                color: #000000 !important;
            }
            [data-testid="stHeader"] {
                background-color: #f4f6f9 !important;
            }

            /* 3. עיצוב טקסטים וכותרות */
            h1, h2, h3, h4, h5, h6 {
                color: #4361ee !important;
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                text-align: center !important;
            }
            
            p, div, span, label, li {
                color: #2c3e50 !important;
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            }

            /* 4. עיצוב כרטיסיות נקי */
            [data-testid="stForm"], [data-testid="stVerticalBlock"] > div {
                background-color: #ffffff !important;
                border-radius: 12px;
                padding: 20px;
                border: 1px solid #e0e0e0;
                box-shadow: none !important;
            }

            /* 5. תיקון קריטי - צביעת הרקע של בחירת התלמיד (Selectbox) בלבן */
            .stSelectbox > div > div {
                background-color: #ffffff !important;
                color: #000000 !important;
                border-color: #cccccc !important;
            }
            /* תיקון הטקסט הנבחר שיהיה שחור */
            .stSelectbox div[data-baseweb="select"] div {
                color: #000000 !important;
            }

            /* תיקון שאר תיבות הקלט */
            .stTextInput input, .stTextArea textarea {
                background-color: #ffffff !important;
                color: #000000 !important;
                border: 1px solid #cccccc !important;
                direction: rtl !important;
                text-align: right;
            }
            
            /* תיקון הרשימה הנפתחת עצמה */
            div[data-baseweb="popover"] li, div[data-baseweb="popover"] div {
                 color: #000000 !important;
                 background-color: #ffffff !important;
            }

            /* 6. כפתור שמירה */
            [data-testid="stFormSubmitButton"] > button {
                background-color: #4361ee !important;
                color: white !important;
                border: none;
                width: 100%;
                padding: 12px;
                font-size: 18px;
                border-radius: 8px;
            }

            /* 7. כיווניות RTL */
            html, body { direction: rtl; }
            [data-testid="stSlider"] { direction: rtl; }
            
        </style>
        """, unsafe_allow_html=True)

# -----------------------------
# פונקציות לוגיקה
# -----------------------------
def get_google_api_key() -> str:
    return st.secrets.get("GOOGLE_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""

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

# --- Google Drive & Gemini ---
def get_drive_service():
    if not GDRIVE_FOLDER_ID or not st.secrets.get("GDRIVE_SERVICE_ACCOUNT_B64"): return None
    try:
        SCOPES = ["https://www.googleapis.com/auth/drive.file"]
        service_account_json_str = base64.b64decode(st.secrets["GDRIVE_SERVICE_ACCOUNT_B64"]).decode("utf-8")
        creds = Credentials.from_service_account_info(json.loads(service_account_json_str), scopes=SCOPES)
        return build("drive", "v3", credentials=creds)
    except Exception as e:
        st.error(f"Drive connect failed: {e}"); return None

def upload_reflection_to_drive(entry: dict, drive_service):
    student_name = entry.get("student_name", "unknown").replace(" ", "_")
    file_name = f"ref-{student_name}-{entry.get('date')}.json"
    media = MediaIoBaseUpload(io.BytesIO(json.dumps(entry, ensure_ascii=False, indent=4).encode('utf-8')), mimetype='application/json')
    file_metadata = {'name': file_name, 'parents': [GDRIVE_FOLDER_ID], 'mimeType': 'application/json'}
    drive_service.files().create(body=file_metadata, media_body=media).execute()

def generate_summary(entries: list) -> str:
    if not entries: return "לא נמצאו נתונים לניתוח בטווח הזמן שנבחר."
    
    full_text = "רשומות תצפית גולמיות:\n" + "\n".join([str(e) for e in entries])
    
    # --- הפרומפט האקדמי המלא (כולל מסוגלות עצמית ושימוש בגוף) ---
    prompt = f"""
    אתה עוזר מחקר אקדמי המנתח נתונים איכותניים לתזה בנושא חשיבה מרחבית.
    עליך לנתח את יומני התצפית ולהפיק דוח ממצאים המבוסס אך ורק על חמשת הקטגוריות המוגדרות של המחקר.
    
    השתמש בהגדרות הבאות לניתוח התצפיות:

    1. המרת ייצוגים (Conversion):
       - הגדרה: יכולת לבודד מבט ספציפי מתוך תלת-ממד (וההפך).
       - מה לחפש: זיהוי נכון של מבטים, שרטוט תלת-ממדי, מעבר מדו-ממד לתלת-ממד.

    2. מידות ופרופורציות (Measurement & Proportions):
       - הגדרה: יכולת לפרש מידות ולשמור על יחסים נכונים.
       - מה לחפש: ספירת משבצות, שימוש בסרגל, השוואה ויזואלית של גדלים.

    3. מעבר בין היטלים (View Transition):
       - הגדרה: שמירה על רציפות נקודות בין מבטים.
       - מה לחפש: קווי עזר, התאמה בין היטלים, בדיקת עקביות.

    4. שימוש בגוף מודפס (Use of Printed Body):
       - הגדרה: מידת ההסתמכות והשימוש האקטיבי בגוף הפיזי.
       - מה לחפש: האם התלמיד החזיק את הגוף? סובב אותו? האם השתמש בו רק לבדיקה או לכל אורך הדרך?
       - סקאלה: משימוש אפסי ועד שימוש אינטנסיבי ומתמיד.

    5. מסוגלות עצמית ולמידה עצמאית (Self-Efficacy & Independence):
       - הגדרה: המידה שבה התלמיד לומד לבד ופותר בעיות ללא עזרת המורה.
       - מה לחפש: ניסיונות עצמאיים, תיקון טעויות לבד, מיעוט פניות למורה, ביטויים של ביטחון.

    הוראות לכתיבת הדוח:
    - כתוב בעברית אקדמית.
    - עבור כל קטגוריה, כתוב פסקה המסכמת את הממצאים שעלו מהתצפיות השבוע.
    - שלב ציטוטים או דוגמאות ספציפיות מתוך הנתונים כדי לבסס את הטענות.
    - נסה לזהות קשרים: האם שימוש מוגבר בגוף מודפס (קטגוריה 4) קשור לעלייה במסוגלות העצמית (קטגוריה 5)?

    הנתונים לניתוח:
    {full_text}
    """
    
    api_key = get_google_api_key()
    if not api_key: return "שגיאה: חסר מפתח API"
    
    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model="gemini-2.0-flash", 
            contents=prompt,
            config={"temperature": 0.2} 
        )
        return response.text
    except Exception as e: return f"שגיאה בניתוח ה-AI: {e}"

# -----------------------------
# ממשק ראשי (Main UI)
# -----------------------------

setup_design()

st.title("🎓 יומן תצפית אינטראקטיבי")
st.markdown("### מעקב אחר מיומנויות תפיסה מרחבית")

tab1, tab2, tab3 = st.tabs(["📝 רפלקציה", "📊 התקדמות אישית", "🧠 עוזר מחקרי (AI)"])

# --- לשונית 1: הזנת נתונים ---
with tab1:
    st.info("💡 טיפ: מומלץ למלא את התצפית תוך כדי או מיד אחרי השיעור.")
    with st.form("reflection_form"):
        st.markdown("#### 1. פרטי התצפית") 
        
        col_student, col_lesson = st.columns(2)
        with col_student:
            selected_student = st.selectbox("👤 שם תלמיד", CLASS_ROSTER)
            if selected_student == "תלמיד אחר...":
                student_name = st.text_input("✍️ הזן שם תלמיד:")
            else:
                student_name = selected_student
        
        with col_lesson:
            lesson_id = st.text_input("📚 שיעור מס'", placeholder="לדוגמה: היטלים 1")

        st.markdown("#### 2. אופן העבודה")
        work_method = st.radio(
            "🛠️ כיצד התבצע השרטוט?",
            ["🎨 ללא גוף מודפס (דמיון/דף)", "🧊 בעזרת גוף מודפס (פיזי)"],
            horizontal=True
        )

        st.markdown("#### 3. תיאור תצפית")
        col_text1, col_text2 = st.columns(2)
        with col_text1:
            planned = st.text