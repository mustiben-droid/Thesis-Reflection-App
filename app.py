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

# רשימת התגיות
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
# פונקציית העיצוב (CSS מתוקן לסליידרים)
# -----------------------------
def setup_design():
    st.set_page_config(page_title="יומן תצפית", page_icon="🎓", layout="centered")
    
    st.markdown("""
        <style>
            /* 1. איפוס כללי */
            .stApp, [data-testid="stAppViewContainer"] { background-color: #ffffff !important; }
            .block-container { padding-top: 1rem !important; padding-bottom: 5rem !important; max-width: 100% !important; }
            
            /* 2. כותרות וטקסטים */
            h1, h2, h3, h4, h5, h6 { color: #4361ee !important; font-family: sans-serif; text-align: center !important; }
            p, label, span, div { color: #000000 !important; }
            
            /* 3. תגיות (Multiselect) */
            .stMultiSelect > div > div {
                background-color: #f0f2f6 !important;
                border: 1px solid #d1d5db !important;
                color: black !important;
            }
            span[data-baseweb="tag"] {
                background-color: #fff9c4 !important;
                border: 1px solid #fbc02d !important;
            }
            span[data-baseweb="tag"] span {
                color: #000000 !important;
                font-weight: bold !important;
            }
            span[data-baseweb="tag"] svg {
                fill: #000000 !important;
            }
            ul[data-baseweb="menu"], li[role="option"] {
                background-color: #ffffff !important;
                color: #000000 !important;
            }

            /* 4. מצלמה / העלאת קובץ */
            [data-testid="stFileUploader"] {
                background-color: #f0f2f6 !important;
                border-radius: 10px;
                padding: 10px;
            }
            [data-testid="stFileUploader"] section {
                background-color: #ffffff !important;
                border: 1px dashed #4361ee !important;
            }
            [data-testid="stFileUploader"] span, 
            [data-testid="stFileUploader"] small, 
            [data-testid="stFileUploader"] div {
                color: #000000 !important;
            }
            [data-testid="stFileUploader"] button {
                background-color: #e0e0e0 !important;
                color: #000000 !important;
                border: 1px solid #9e9e9e !important;
            }

            /* 5. תיקון סליידרים (Sliders) - התיקון המרכזי כאן */
            
            /* המספר שזז עם הסליידר (Thumb Value) */
            div[data-testid="stThumbValue"] {
                color: #ffffff !important;       /* טקסט לבן */
                background-color: #4361ee !important; /* רקע כחול בולט */
                font-size: 20px !important;      /* פונט גדול */
                font-weight: bold !important;
                padding: 5px 10px !important;    /* רווח מסביב למספר */
                border-radius: 8px !important;   /* פינות עגולות */
                opacity: 1 !important;           /* תמיד נראה לעין */
                margin-top: -10px !important;    /* הרמה קלה למעלה */
            }
            
            /* הפס של הסליידר עצמו */
            div[data-baseweb="slider"] {
                padding-top: 15px !important; /* מרווח כדי שהמספר לא יחתך */
            }

            /* 6. שאר האלמנטים */
            .stSelectbox > div > div, .stTextInput input, .stTextArea textarea {
                background-color: #f5f5f5 !important;
                color: #000000 !important;
                border: 1px solid #cccccc !important;
            }
            
            [data-testid="stFormSubmitButton"] > button { 
                background-color: #4361ee !important; 
                color: white !important; 
                border: none; 
                width: 100%; 
                padding: 15px; 
                font-size: 20px; 
                font-weight: bold; 
                border-radius: 12px; 
                margin-top: 20px; 
            }

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

# --- העלאת קבצים לדרייב ---
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
            task_difficulty = st.selectbox("⚖️ רמת קושי המטלה", ["בסיסי", "בינוני", "מתקדם"])

        st.markdown("#### 2. אופן העבודה")
        work_method = st.radio("🛠️ כיצד התבצע השרטוט?", ["🎨 ללא גוף (דמיון)", "🧊 בעזרת גוף פיזי"], horizontal=True)

        st.markdown("#### 3. תיאור תצפית")
        
        # --- תגיות מהירות ---
        selected_tags = st.multiselect("🏷️ תגיות מהירות (ניתן לבחור כמה):", OBSERVATION_TAGS)
        
        col_text1, col_text2 = st.columns(2)
        with col_text1:
            planned = st.text_area("📋 תיאור המטלה", height=100, placeholder="מה נדרש לעשות?")
            challenge = st.text_area("🗣️ ציטוטים / תגובות", height=100, placeholder="ציטוטים, שפת גוף...")
        with col_text2:
            done = st.text_area("👀 פעולות שנצפו", height=100, placeholder="מה הוא עשה בפועל?")
        
        # --- העלאת תמונה ---
        st.markdown("#### 📷 תיעוד ויזואלי")
        upload_label = "צרף צילום שרטוט/גוף (מהמצלמה או מהגלריה)"
        uploaded_image = st.file_uploader(upload_label, type=['jpg', 'jpeg', 'png'])

        st.markdown("#### 4. מדדי הערכה (1-5)")
        c1, c2 = st.columns(2)
        with c1:
            cat_convert = st.slider("🔄 המרת ייצוגים", 1, 5, 3)
            cat_dims = st.slider("📏 מידות ופרופורציות", 1, 5, 3)
        with c2:
            cat_proj = st.slider("📐 מעבר בין היטלים", 1, 5, 3)
            cat_3d_support = st.slider("🧊 שימוש בגוף מודפס", 1, 5, 3)
        
        cat_self_efficacy = st.slider("💪 מסוגלות עצמית", 1, 5, 3)

        submitted = st.form_submit_button("💾 שמור תצפית")

        if submitted:
            # 1. שמירת הנתונים
            entry = {
                "type": "reflection", "student_name": student_name, "lesson_id": lesson_id,
                "task_difficulty": task_difficulty, 
                "work_method": work_method, 
                "tags": selected_tags,  
                "planned": planned, "done": done, 
                "challenge": challenge, "cat_convert_rep": cat_convert, 
                "cat_dims_props": cat_dims, "cat_proj_trans": cat_proj, 
                "cat_3d_support": cat_3d_support, "cat_self_efficacy": cat_self_efficacy,
                "date": date.today().isoformat(), "timestamp": datetime.now().isoformat(),
                "has_image": uploaded_image is not None
            }
            save_reflection(entry)
            
            # 2. העלאה לדרייב
            svc = get_drive_service()
            if svc:
                try:
                    # העלאת ה-JSON
                    json_bytes = io.BytesIO(json.dumps(entry, ensure_ascii=False, indent=4).encode('utf-8'))
                    upload_file_to_drive(json_bytes, f"ref-{student_name}-{entry['date']}.json", 'application/json', svc)
                    
                    # העלאת התמונה (אם יש)
                    if uploaded_image:
                        image_bytes = io.BytesIO(uploaded_image.getvalue())
                        upload_file_to_drive(image_bytes, f"img-{student_name}-{entry['date']}.jpg", 'image/jpeg', svc)
                        st.success("📸 התמונה והנתונים נשמרו בדרייב!")
                    else:
                        st.success("✅ הנתונים נשמרו בהצלחה!")
                except Exception as e:
                    st.error(f"שגיאה בגיבוי לענן: {e}")
            else:
                st.warning("נשמר מקומית בלבד (אין חיבור לדרייב).")

# --- לשונית 2: לוח בקרה וייצוא ---
with tab2:
    st.markdown("### 🕵️ מעקב התפתחות וייצוא נתונים")
    df = load_data_as_dataframe()
    
    if df.empty:
        st.warning("⚠️ אין נתונים.")
    else:
        # עיבוד נתונים לפני ייצוא
        export_df = df.copy()
        if "tags" in export_df.columns:
            export_df["tags"] = export_df["tags"].apply(lambda x: ", ".join(x) if isinstance(x, list) else x)

        # --- אזור ייצוא נתונים ---
        st.markdown("#### 📥 ייצוא נתונים למחקר")
        col_ex1, col_ex2 = st.columns(2)
        with col_ex1:
            csv = export_df.to_csv(index=False).encode('utf-8')
            st.download_button("📄 הורד כ-CSV", data=csv, file_name="thesis_data.csv", mime="text/csv", help="פורמט מתאים לתוכנות סטטיסטיות")
        
        with col_ex2:
            try:
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    export_df.to_excel(writer, index=False, sheet_name='Data')
                st.download_button("📊 הורד כ-Excel", data=output.getvalue(), file_name="thesis_data.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            except:
                st.error("נדרשת ספריית openpyxl לאקסל")

        st.divider()

        metric_cols = ['cat_convert_rep', 'cat_dims_props', 'cat_proj_trans', 'cat_3d_support', 'cat_self_efficacy']
        heb_names = {'cat_convert_rep': 'המרת ייצוגים', 'cat_dims_props': 'מידות', 'cat_proj_trans': 'היטלים', 'cat_3d_support': 'שימוש בגוף', 'cat_self_efficacy': 'מסוגלות עצמית'}
        
        all_students = df['student_name'].unique() if 'student_name' in df.columns else []
        if len(all_students) > 0:
            selected_student_graph = st.selectbox("🎓 בחר תלמיד:", all_students)
            student_df = df[df['student_name'] == selected_student_graph].sort_values("date")
            
            if not student_df.empty:
                chart_data = student_df.set_index("date")[metric_cols].rename(columns=heb_names)
                st.line_chart(chart_data)
                
                # הצגת טבלה עם תגיות
                cols_to_show = ['date', 'task_difficulty', 'tags', 'has_image']
                existing_cols = [c for c in cols_to_show if c in student_df.columns]
                st.dataframe(student_df[existing_cols].tail(5), hide_index=True)

# --- לשונית 3: AI ---
with tab3:
    st.markdown("### 🤖 עוזר מחקרי")
    if st.button("✨ צור סיכום שבועי"):
        entries = load_last_week()
        with st.spinner("מנתח..."):
            st.markdown(generate_summary(entries))