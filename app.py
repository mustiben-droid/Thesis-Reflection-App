import json
import base64
import os
import io
from datetime import date, datetime, timedelta
import pandas as pd

import streamlit as st
from google import genai
# from google.genai.errors import APIError 

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
# פונקציית העיצוב החדשה והצבעונית 🎨
# -----------------------------
def setup_design():
    # הגדרת כותרת הדף ואייקון בדפדפן
    st.set_page_config(page_title="יומן מחקר", page_icon="🎓", layout="centered")
    
    st.markdown("""
        <style>
            /* כיוון ימין-שמאל גלובלי */
            html, body, [data-testid="stAppViewContainer"] {
                direction: rtl;
                background-color: #f8f9fa; /* רקע אפור בהיר מאוד לכל האפליקציה */
            }
            
            /* עיצוב שדות טקסט */
            input, textarea, [data-testid="stTextarea"], [data-testid="stSelectbox"] { 
                direction: rtl !important; 
                text_align: right; 
            }
            
            /* עיצוב כותרות בצבע כחול-סגול */
            h1, h2, h3 {
                color: #4361ee !important;
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            }
            
            /* אפקט "כרטיסייה" לטופס ולטאבים */
            [data-testid="stForm"], [data-testid="stVerticalBlock"] > div {
                background-color: white;
                padding: 20px;
                border-radius: 15px;
                box-shadow: 0 4px 6px rgba(0,0,0,0.1); /* צל עדין */
                margin-bottom: 20px;
            }
            
            /* כפתור שמירה בולט */
            [data-testid="stFormSubmitButton"] > button {
                background-color: #4361ee;
                color: white;
                border-radius: 10px;
                width: 100%;
                font-weight: bold;
                border: none;
            }
            [data-testid="stFormSubmitButton"] > button:hover {
                background-color: #3f37c9;
                color: white;
            }

            /* יישור טאבים */
            .stTabs [data-baseweb="tab-list"] { 
                justify-content: center; 
                gap: 10px;
            }
            .stTabs [data-baseweb="tab"] {
                background-color: #e0e7ff;
                border-radius: 5px;
                padding: 10px 20px;
            }
            .stTabs [aria-selected="true"] {
                background-color: #4361ee !important;
                color: white !important;
            }
            
            /* תיקון כיוון לסליידרים */
            [data-testid="stSlider"] { direction: rtl; }
            
        </style>
        """, unsafe_allow_html=True)

# -----------------------------
# פונקציות לוגיקה (ללא שינוי)
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
    if not entries: return "אין נתונים."
    full_text = "רשומות רפלקציה:\n" + "\n".join([str(e) for e in entries])
    prompt = f"נתח את הרשומות האלו וסכם מגמות, הישגים והמלצות:\n{full_text}"
    api_key = get_google_api_key()
    if not api_key: return "חסר מפתח API"
    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(model="gemini-2.0-flash", contents=prompt)
        return response.text
    except Exception as e: return f"שגיאה ב-AI: {e}"

# -----------------------------
# ממשק ראשי (Main UI)
# -----------------------------

# הפעלת העיצוב החדש
setup_design()

st.title("🎓 יומן תצפית ומחקר")
st.markdown("### מעקב אחר התפתחות תפיסה מרחבית בכיתה ה'")

# יצירת לשוניות עם אייקונים
tab1, tab2, tab3 = st.tabs(["📝 רפלקציה", "📊 לוח בקרה", "🤖 סיכום AI"])

# --- לשונית 1: הזנת נתונים ---
with tab1:
    st.info("💡 טיפ: רפלקציה טובה נכתבת בסמוך לזמן השיעור.")
    with st.form("reflection_form"):
        st.markdown("#### 1. פרטי המקרה")
        
        col_student, col_lesson = st.columns(2)
        with col_student:
            selected_student = st.selectbox("שם תלמיד", CLASS_ROSTER)
            student_name = st.text_input("הזן שם תלמיד:") if selected_student == "תלמיד אחר..." else selected_student
        
        with col_lesson:
            lesson_id = st.text_input("שיעור מס'", placeholder="לדוגמה: היטלים 1")

        st.markdown("#### 2. אופן העבודה")
        work_method = st.radio(
            "כיצד התבצע השרטוט?",
            ["🎨 ללא גוף מודפס (דמיון/דף)", "🧊 בעזרת גוף מודפס (פיזי)"],
            horizontal=True
        )

        st.markdown("#### 3. הלב של הרפלקציה")
        col_text1, col_text2 = st.columns(2)
        with col_text1:
            planned = st.text_area("🎯 מה תכננתי?", height=100, placeholder="מטרת השיעור הייתה...")
            challenge = st.text_area("🔥 קושי מרכזי", height=100, placeholder="איפה התלמיד נתקע?")
        with col_text2:
            done = st.text_area("✅ מה בוצע בפועל?", height=100, placeholder="בפועל התלמיד עשה...")
        
        st.markdown("#### 4. מדדי הערכה (1-5)")
        c1, c2 = st.columns(2)
        with c1:
            cat_convert = st.slider("🔄 המרת ייצוגים", 1, 5, 3)
            cat_dims = st.slider("📏 מידות ופרופורציות", 1, 5, 3)
        with c2:
            cat_proj = st.slider("📐 מעבר בין היטלים", 1, 5, 3)
            cat_3d_support = st.slider("🆘 מידת תמיכה נדרשת", 1, 5, 3)

        submitted = st.form_submit_button("שמור רפלקציה ביומן")

        if submitted:
            entry = {
                "type": "reflection", "student_name": student_name, "lesson_id": lesson_id,
                "work_method": work_method, "planned": planned, "done": done, 
                "challenge": challenge, "cat_convert_rep": cat_convert, 
                "cat_dims_props": cat_dims, "cat_proj_trans": cat_proj, 
                "cat_3d_support": cat_3d_support, "date": date.today().isoformat(),
                "timestamp": datetime.now().isoformat()
            }
            save_reflection(entry)
            st.success(f"🎉 המידע על {student_name} נשמר בהצלחה!")
            svc = get_drive_service()
            if svc:
                try:
                    upload_reflection_to_drive(entry, svc)
                except: pass

# --- לשונית 2: גרפים ---
with tab2:
    st.markdown("### 📈 התקדמות הכיתה")
    df = load_data_as_dataframe()
    
    if df.empty:
        st.warning("עדיין אין נתונים. נא למלא רפלקציות בלשונית הראשונה.")
    else:
        metric_cols = ['cat_convert_rep', 'cat_dims_props', 'cat_proj_trans', 'cat_3d_support']
        heb_names = {'cat_convert_rep': 'המרת ייצוגים', 'cat_dims_props': 'מידות', 'cat_proj_trans': 'היטלים', 'cat_3d_support': 'תמיכה'}
        
        existing_cols = [c for c in metric_cols if c in df.columns]
        if existing_cols:
            st.caption("ממוצע כיתתי כללי לפי קטגוריות")
            avg_data = df[existing_cols].mean().rename(index=heb_names)
            st.bar_chart(avg_data, color="#4361ee") # צבע כחול לגרף

        st.divider()

        st.markdown("### 🕵️ מעקב פרטני")
        all_students = df['student_name'].unique() if 'student_name' in df.columns else []
        if len(all_students) > 0:
            selected_student_graph = st.selectbox("בחר תלמיד:", all_students)
            student_df = df[df['student_name'] == selected_student_graph].sort_values("date")
            
            # הצגת כרטיסיות מידע (Metrics)
            m1, m2, m3 = st.columns(3)
            m1.metric("סה״כ שיעורים", len(student_df))
            last_method = student_df.iloc[-1].get('work_method', 'לא ידוע').split(' ')[0] # לוקח את המילה הראשונה
            m2.metric("שיטה אחרונה", last_method)
            m3.metric("תאריך אחרון", str(student_df.iloc[-1]['date'].date()))

            if existing_cols:
                chart_data = student_df.set_index("date")[existing_cols]
                chart_data.columns = [heb_names.get(c, c) for c in chart_data.columns]
                st.line_chart(chart_data)
            
            st.caption("היסטוריית דיווחים")
            st.dataframe(student_df[['date', 'work_method', 'challenge']].tail(5), hide_index=True, use_container_width=True)

# --- לשונית 3: AI ---
with tab3:
    st.markdown("### 🧠 העוזר המחקרי שלך")
    st.info("ה-AI יסרוק את השבוע האחרון ויחפש דפוסים בנתונים.")
    if st.button("צור סיכום שבועי חכם ✨"):
        entries = load_last_week()
        with st.spinner("ה-AI מנתח את הנתונים..."):
            summary = generate_summary(entries)
            st.markdown(summary)