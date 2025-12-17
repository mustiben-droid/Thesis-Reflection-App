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
# פונקציית העיצוב (המתוקנת - נקי, מיושר לאמצע, ללא רווח עליון)
# -----------------------------
def setup_design():
    st.set_page_config(page_title="יומן תצפית", page_icon="🎓", layout="centered")
    
    st.markdown("""
        <style>
            /* 1. ביטול הרווח הריק העליון */
            .block-container {
                padding-top: 2rem !important;
                padding-bottom: 2rem !important;
            }

            /* 2. אילוץ מצב בהיר (Light Mode) באופן גורף */
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
                text-align: center !important; /* יישור כל הכותרות למרכז */
            }
            
            p, div, span, label, li {
                color: #2c3e50 !important;
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            }

            /* 4. עיצוב כרטיסיות נקי ושטוח (בלי גלים/צללים) */
            [data-testid="stForm"], [data-testid="stVerticalBlock"] > div {
                background-color: #ffffff !important;
                border-radius: 12px;
                padding: 20px;
                border: 1px solid #e0e0e0; /* מסגרת עדינה בלבד */
                box-shadow: none !important; /* ביטול הצללים שיוצרים את ה"גלים" */
            }

            /* 5. תיקון צבעים לתיבות הקלט (שיהיו לבנות וקריאות) */
            .stTextInput input, .stTextArea textarea, .stSelectbox div[data-baseweb="select"] {
                background-color: #ffffff !important;
                color: #000000 !important;
                border: 1px solid #cccccc !important;
                direction: rtl !important;
                text-align: right;
            }
            
            /* תיקון צבעים לרשימות נפתחות */
            div[data-baseweb="popover"] li, div[data-baseweb="popover"] div {
                 color: #000000 !important;
                 background-color: #ffffff !important;
            }

            /* 6. כפתור שמירה מעוצב */
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

setup_design()

# --- כותרות מיושרות למרכז ---
st.title("🎓 יומן תצפית")
st.markdown("### מעקב אחר מיומנויות תפיסה מרחבית")

tab1, tab2, tab3 = st.tabs(["📝 רפלקציה", "📊 לוח בקרה", "🤖 סיכום AI"])

# --- לשונית 1: הזנת נתונים ---
with tab1:
    st.info("💡 טיפ: רפלקציה טובה נכתבת בסמוך לזמן השיעור.")
    with st.form("reflection_form"):
        # --- הכותרת החדשה: פרטי התצפית ---
        st.markdown("#### 1. פרטי התצפית") 
        
        col_student, col_lesson = st.columns(2)
        with col_student:
            selected_student = st.selectbox("שם תלמיד", CLASS_ROSTER)
            if selected_student == "תלמיד אחר...":
                student_name = st.text_input("הזן שם תלמיד:")
            else:
                student_name = selected_student
        
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
            planned = st.text_area("🎯 מה תכננתי?", height=100, placeholder="מטרת המטלה...")
            challenge = st.text_area("🔥 קושי מרכזי", height=100, placeholder="תיאור הפער בתפיסה...")
        with col_text2:
            done = st.text_area("✅ מה בוצע בפועל?", height=100, placeholder="תיאור הביצוע...")
        
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
    st.markdown("### 📈 התקדמות הקבוצה")
    df = load_data_as_dataframe()
    
    if df.empty:
        st.warning("עדיין אין נתונים. נא למלא רפלקציות בלשונית הראשונה.")
    else:
        metric_cols = ['cat_convert_rep', 'cat_dims_props', 'cat_proj_trans', 'cat_3d_support']
        heb_names = {'cat_convert_rep': 'המרת ייצוגים', 'cat_dims_props': 'מידות', 'cat_proj_trans': 'היטלים', 'cat_3d_support': 'תמיכה'}
        
        existing_cols = [c for c in metric_cols if c in df.columns]
        if existing_cols:
            st.caption("ממוצע כללי לפי קטגוריות")
            avg_data = df[existing_cols].mean().rename(index=heb_names)
            st.bar_chart(avg_data, color="#4361ee")

        st.divider()

        st.markdown("### 🕵️ מעקב פרטני")
        all_students = df['student_name'].unique() if 'student_name' in df.columns else []
        if len(all_students) > 0:
            selected_student_graph = st.selectbox("בחר נבדק:", all_students)
            student_df = df[df['student_name'] == selected_student_graph].sort_values("date")
            
            m1, m2, m3 = st.columns(3)
            m1.metric("סה״כ תצפיות", len(student_df))
            last_method = student_df.iloc[-1].get('work_method', 'לא ידוע').split(' ')[0]
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
    st.markdown("### 🧠 העוזר המחקרי")
    if st.button("צור סיכום שבועי חכם ✨"):
        entries = load_last_week()
        with st.spinner("ה-AI מנתח את הנתונים..."):
            summary = generate_summary(entries)
            st.markdown(summary)