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

CLASS_ROSTER = [
    "נתנאל", "רועי", "אסף", "עילאי", "טדי", "גאל", "אופק", "דניאל.ר", "אלי", "טיגרן", "תלמיד אחר..." 
]

OBSERVATION_TAGS = [
    "התעלמות מקווים נסתרים", "בלבול בין היטלים", "קושי ברוטציה מנטלית",
    "טעות בפרופורציות/מידות", "קושי במעבר בין היטלים", "שימוש בכלי מדידה",
    "סיבוב פיזי של המודל", "שימוש בתנועות ידיים (Embodiment)", "ספירת משבצות",
    "תיקון עצמי", "בקשת אישור תכופה", "ויתור/תסכול", "עבודה עצמאית שוטפת"
]

# --- 2. עיצוב (CSS) ---
def setup_design():
    st.set_page_config(page_title="יומן תצפית", page_icon="🎓", layout="centered")
    st.markdown("""
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Heebo:wght@300;400;700&display=swap');
            html, body, .stApp {
                background-color: #ffffff !important;
                direction: rtl; 
                text-align: right;
                font-family: 'Heebo', sans-serif !important;
            }
            .stButton > button { width: 100%; font-weight: bold; border-radius: 10px; }
            [data-testid="stSlider"] { direction: ltr !important; }
            .stTabs [data-baseweb="tab-list"] { direction: rtl; }
        </style>
    """, unsafe_allow_html=True)

# --- 3. פונקציות ליבה ---
def get_drive_service():
    try:
        json_str = base64.b64decode(st.secrets["GDRIVE_SERVICE_ACCOUNT_B64"]).decode("utf-8")
        creds = Credentials.from_service_account_info(json.loads(json_str), scopes=["https://www.googleapis.com/auth/drive.file"])
        return build("drive", "v3", credentials=creds)
    except: return None

def save_reflection(entry: dict):
    with open(DATA_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

def load_data_as_dataframe():
    """טוען הכל מהקובץ המקומי."""
    if not os.path.exists(DATA_FILE): return pd.DataFrame()
    data = []
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                try:
                    e = json.loads(line)
                    if e.get("type") == "reflection": data.append(e)
                except: continue
    df = pd.DataFrame(data)
    # הפיכת עמודות הדירוג למספרים
    score_cols = [c for c in df.columns if "cat_" in c]
    for col in score_cols: df[col] = pd.to_numeric(df[col], errors='coerce')
    return df

# --- 4. ממשק המשתמש ---
setup_design()
st.title("🎓 יומן תצפית - ניהול תזה")

tab1, tab2, tab3 = st.tabs(["📝 רפלקציה חדשה", "📊 התקדמות וייצוא", "🤖 עוזר מחקרי"])

with tab1:
    with st.form("main_form", clear_on_submit=True):
        st.subheader("הזנת תצפית")
        c1, c2 = st.columns(2)
        with c1:
            sel = st.selectbox("👤 שם תלמיד", CLASS_ROSTER)
            student_name = st.text_input("שם חופשי:") if sel == "תלמיד אחר..." else sel
        with c2:
            lesson = st.text_input("📚 מזהה שיעור")
        
        tags = st.multiselect("🏷️ תגיות נצפות", OBSERVATION_TAGS)
        done = st.text_area("👀 מה בוצע בפועל? (תיאור הפעולה)")
        interpretation = st.text_area("💡 פרשנות המורה (מה זה אומר על התפיסה המרחבית?)")
        
        st.markdown("---")
        st.write("מדדי הצלחה (1-5):")
        c_proj = st.select_slider("📐 שליטה במעבר בין היטלים", options=[1,2,3,4,5], value=3)
        c_eff = st.select_slider("💪 רמת מסוגלות עצמית נצפית", options=[1,2,3,4,5], value=3)
        
        if st.form_submit_button("💾 שמור תצפית"):
            entry = {
                "type": "reflection", "student_name": student_name, "lesson_id": lesson,
                "tags": tags, "done": done, "interpretation": interpretation,
                "cat_proj_trans": c_proj, "cat_self_efficacy": c_eff,
                "date": date.today().isoformat(), "timestamp": datetime.now().isoformat()
            }
            save_reflection(entry)
            st.success(f"התצפית של {student_name} נשמרה בהצלחה!")
            st.balloons()

with tab2:
    st.header("📊 ניהול נתונים")
    df = load_data_as_dataframe()
    
    if not df.empty:
        st.subheader("📥 ייצוא כל הנתונים לאקסל")
        st.write(f"במערכת קיימות **{len(df)}** תצפיות מצטברות.")
        
        # יצירת קובץ ה-Excel המרוכז
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='All_Data')
        
        st.download_button(
            label="✅ לחץ כאן להורדת הקובץ המלא (Excel)",
            data=output.getvalue(),
            file_name=f"Thesis_Observations_{date.today()}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        
        st.markdown("---")
        st.subheader("📈 גרף התקדמות אישי")
        student = st.selectbox("בחר תלמיד לצפייה:", df['student_name'].unique())
        st_df = df[df['student_name'] == student].sort_values("date")
        st.line_chart(st_df.set_index("date")[['cat_proj_trans', 'cat_self_efficacy']])
        
        st.markdown("---")
        st.subheader("📂 פעולות נוספות")
        if st.button("🔄 סנכרן את כל התיקים ב-Drive"):
            st.info("מבצע סנכרון תיקים אישיים ל-Drive...")
            # פונקציית סנכרון תיקים
    else:
        st.info("עדיין אין נתונים. מלא תצפית אחת לפחות כדי לראות את כפתור הייצוא.")

with tab3:
    st.header("🤖 עוזר מחקרי AI")
    st.write("כאן תוכל לשאול שאלות על המגמות של התלמידים.")
    # (כאן ייכנס הקוד של Gemini כשידרש)

# סוף הקוד