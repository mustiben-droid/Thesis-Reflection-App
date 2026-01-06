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
            
            html, body, .stApp {
                background-color: #ffffff !important;
                color: #000000 !important;
                font-family: 'Heebo', sans-serif !important;
                direction: rtl; 
                text-align: right;
            }

            .block-container { padding-top: 1rem; padding-bottom: 5rem; max-width: 100%; }

            h1, h2, h3, h4, h5, h6, p, label, span, div, small { 
                color: #000000 !important; 
                text-align: right; 
            }
            h1 { text-align: center !important; }

            .stTextInput input, .stTextArea textarea, .stSelectbox > div > div {
                background-color: #ffffff !important;
                color: black !important;
                border: 1px solid #ced4da !important;
                border-radius: 8px;
                direction: rtl;
                text-align: right;
            }

            .stButton > button, .stDownloadButton > button {
                background-color: #f0f2f6 !important;
                color: black !important;
                border: 1px solid #b0b0b0 !important;
                width: 100%;
                font-weight: bold;
            }
            [data-testid="stFormSubmitButton"] > button {
                background: linear-gradient(90deg, #4361ee 0%, #3a0ca3 100%) !important;
                color: white !important;
                border: none;
            }

            [data-testid="stSlider"] {
                direction: ltr !important;
                text-align: left !important;
            }

            [data-testid="stForm"] {
                background-color: #ffffff;
                padding: 15px;
                border-radius: 15px;
                box-shadow: 0 4px 15px rgba(0,0,0,0.05);
                border: 1px solid #e0e0e0;
            }
            
            .stChatMessage { direction: rtl; text-align: right; background-color: #f9f9f9; }
            [data-testid="stChatMessageContent"] p { color: black !important; }
        </style>
    """, unsafe_allow_html=True)

# --- 3. פונקציות עזר ---

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
        st.error(f"שגיאת דרייב: {e}")
        return None

def save_reflection(entry: dict) -> dict:
    with open(DATA_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return {"status": "saved", "date": entry["date"]}

def load_data_as_dataframe():
    """טוען את כל הנתונים המצטברים מהקובץ המקומי."""
    columns = ["date", "student_name", "lesson_id", "task_difficulty", "work_method", "tags", "planned", "done", "interpretation", "challenge", "cat_convert_rep", "cat_dims_props", "cat_proj_trans", "cat_3d_support", "cat_self_efficacy"]
    if not os.path.exists(DATA_FILE): return pd.DataFrame(columns=columns)
    data = []
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip(): continue
            try:
                entry = json.loads(line)
                if entry.get("type") == "reflection": data.append(entry)
            except: continue
    df = pd.DataFrame(data)
    if df.empty: return pd.DataFrame(columns=columns)
    
    # ניקוי וסידור הנתונים
    if "date" in df.columns: df["date"] = pd.to_datetime(df["date"]).dt.date
    # המרת דירוגים למספרים לטובת חישובים באקסל
    score_cols = [c for c in df.columns if "cat_" in c]
    for col in score_cols: df[col] = pd.to_numeric(df[col], errors='coerce')
    
    return df

def load_last_week():
    if not os.path.exists(DATA_FILE): return []
    today = date.today()
    week_ago = today - timedelta(days=6)
    out = []
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip(): continue
            try:
                e = json.loads(line)
                if e.get("type") == "weekly_summary": continue
                d = date.fromisoformat(e.get("date", today.isoformat()))
                if week_ago <= d <= today: out.append(e)
            except: continue
    return out

# --- 4. פונקציות דרייב ---

def upload_file_to_drive(file_obj, filename, mime_type, drive_service):
    media = MediaIoBaseUpload(file_obj, mimetype=mime_type)
    file_metadata = {'name': filename, 'parents': [GDRIVE_FOLDER_ID], 'mimeType': mime_type}
    drive_service.files().create(body=file_metadata, media_body=media, supportsAllDrives=True).execute()

def update_student_excel_in_drive(student_name, drive_service):
    try:
        df = load_data_as_dataframe()
        if df.empty: return False
        student_df = df[df['student_name'] == student_name]
        if student_df.empty: return False
        filename = f"Master_{student_name}.xlsx"
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            student_df.to_excel(writer, index=False, sheet_name='History')
        query = f"name = '{filename}' and '{GDRIVE_FOLDER_ID}' in parents and trashed = false"
        results = drive_service.files().list(q=query, fields="files(id, name)").execute()
        files = results.get('files', [])
        media = MediaIoBaseUpload(io.BytesIO(output.getvalue()), mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", resumable=True)
        if not files:
            file_metadata = {'name': filename, 'parents': [GDRIVE_FOLDER_ID]}
            drive_service.files().create(body=file_metadata, media_body=media).execute()
        else:
            drive_service.files().update(fileId=files[0]['id'], media_body=media).execute()
        return True
    except: return False

def restore_from_drive():
    svc = get_drive_service()
    if not svc: return False
    try:
        query = f"'{GDRIVE_FOLDER_ID}' in parents and mimeType='application/json' and trashed=false"
        results = svc.files().list(q=query, orderBy="createdTime desc").execute()
        files = results.get('files', [])
        if not files: return False
        existing_data = set()
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                for line in f: existing_data.add(line.strip())
        restored_count = 0
        for file in files:
            file_content = svc.files().get_media(fileId=file['id']).execute().decode('utf-8')
            try:
                json_obj = json.loads(file_content)
                json_line = json.dumps(json_obj, ensure_ascii=False)
                if json_line not in existing_data:
                    with open(DATA_FILE, "a", encoding="utf-8") as f: f.write(json_line + "\n")
                    existing_data.add(json_line)
                    restored_count += 1
            except: pass
        return restored_count > 0
    except: return False

# --- 5. פונקציות AI ---

def generate_summary(entries: list) -> str:
    if not entries: return "אין נתונים."
    readable = [f"תלמיד: {e.get('student_name')} | תיאור: {e.get('done')} | פרשנות: {e.get('interpretation')}" for e in entries]
    full_text = "\n".join(readable)
    prompt = f"כתוב דוח סיכום שבועי בעברית לתזה על סמך הנתונים הבאים:\n{full_text}"
    api_key = get_google_api_key()
    if not api_key: return "חסר מפתח API."
    try:
        client = genai.Client(api_key=api_key)
        return client.models.generate_content(model="gemini-2.0-flash", contents=prompt).text
    except Exception as e: return f"שגיאה: {e}"

def chat_with_data(user_query, context_data):
    api_key = get_google_api_key()
    prompt = f"ענה על סמך הנתונים בלבד: {context_data}\nשאלה: {user_query}"
    try:
        client = genai.Client(api_key=api_key)
        return client.models.generate_content(model="gemini-2.0-flash", contents=prompt).text
    except: return "שגיאה."

def render_slider_metric(label, key):
    st.markdown(f"<div style='text-align: right; font-weight: bold;'>{label}</div>", unsafe_allow_html=True)
    val = st.select_slider("", options=[1, 2, 3, 4, 5], value=3, key=key, label_visibility="collapsed")
    return val

# -----------------------------
# 6. ממשק ראשי
# -----------------------------
setup_design()
st.title("🎓 יומן תצפית")

tab1, tab2, tab3 = st.tabs(["📝 רפלקציה", "📊 התקדמות", "🤖 עוזר מחקרי"])

# --- טאב 1: רפלקציה ---
with tab1:
    with st.form("reflection_form", clear_on_submit=True):
        st.markdown("#### 1. פרטי התצפית") 
        col1, col2 = st.columns(2)
        with col1:
            selected_student = st.selectbox("👤 שם תלמיד", CLASS_ROSTER)
            student_name = st.text_input("✍️ הזן שם:") if selected_student == "תלמיד אחר..." else selected_student
        with col2:
            lesson_id = st.text_input("📚 שיעור")
            task_difficulty = st.selectbox("⚖️ קושי", ["בסיסי", "בינוני", "מתקדם"])
        
        work_method = st.radio("🛠️ אופן עבודה", ["🎨 ללא גוף (דמיון)", "🧊 בעזרת גוף מודפס"], horizontal=True)
        selected_tags = st.multiselect("🏷️ תגיות:", OBSERVATION_TAGS)
        
        c1, c2 = st.columns(2)
        with c1:
            planned = st.text_area("📋 המטלה")
            challenge = st.text_area("🗣️ ציטוטים")
        with c2:
            done = st.text_area("👀 פעולות")
            interpretation = st.text_area("💡 פרשנות")
            
        uploaded_images = st.file_uploader("📷 תמונות", type=['jpg', 'jpeg', 'png'], accept_multiple_files=True)
        
        st.markdown("#### 4. מדדים")
        cat_convert = render_slider_metric("🔄 המרת ייצוגים", "m1")
        cat_dims = render_slider_metric("📏 מידות", "m2")
        cat_proj = render_slider_metric("📐 מעבר היטלים", "m3")
        cat_3d_support = render_slider_metric("🧊 שימוש בגוף", "m4")
        cat_self_efficacy = render_slider_metric("💪 מסוגלות עצמית", "m5")

        if st.form_submit_button("💾 שמור תצפית"):
            entry = {
                "type": "reflection", "student_name": student_name, "lesson_id": lesson_id, "task_difficulty": task_difficulty, 
                "work_method": work_method, "tags": selected_tags, "planned": planned, "done": done, "challenge": challenge, 
                "interpretation": interpretation, "cat_convert_rep": cat_convert, "cat_dims_props": cat_dims, 
                "cat_proj_trans": cat_proj, "cat_3d_support": cat_3d_support, "cat_self_efficacy": cat_self_efficacy,
                "date": date.today().isoformat(), "timestamp": datetime.now().isoformat(), "has_image": bool(uploaded_images)
            }
            save_reflection(entry)
            svc = get_drive_service()
            if svc:
                json_bytes = io.BytesIO(json.dumps(entry, ensure_ascii=False, indent=4).encode('utf-8'))
                upload_file_to_drive(json_bytes, f"ref-{student_name}-{entry['date']}.json", 'application/json', svc)
                if uploaded_images:
                    for i, img in enumerate(uploaded_images):
                        upload_file_to_drive(io.BytesIO(img.getvalue()), f"img-{student_name}-{entry['date']}_{i+1}.jpg", img.type, svc)
                update_student_excel_in_drive(student_name, svc)
            st.success("נשמר בהצלחה!")

# --- טאב 2: התקדמות (כאן נמצא החידוש) ---
with tab2:
    st.markdown("### 📊 לוח בקרה וניהול נתונים")
    df = load_data_as_dataframe()
    
    # --- כפתור הורדה מרוכז לכל ההיסטוריה ---
    if not df.empty:
        st.markdown("#### 📥 ייצוא כל התצפיות לאקסל")
        st.info(f"במערכת קיימות {len(df)} תצפיות מצטברות.")
        
        # הכנת קובץ אקסל בזיכרון
        excel_all = io.BytesIO()
        with pd.ExcelWriter(excel_all, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='All_Observations')
        
        st.download_button(
            label="📥 הורד את כל היסטוריית התצפיות (Excel)",
            data=excel_all.getvalue(),
            file_name=f"Full_Observations_Export_{date.today()}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        
        st.divider()
        st.markdown("#### 🔄 סנכרון וניהול תיקים")
        if st.button("🔄 סנכרן נתונים מהדרייב (שחזור)"):
            if restore_from_drive(): st.rerun()
        
        if st.button("📂 עדכן את כל התיקים האישיים בדרייב"):
            svc = get_drive_service()
            if svc:
                all_students = df['student_name'].unique()
                for name in all_students: update_student_excel_in_drive(name, svc)
                st.success("כל התיקים האישיים עודכנו בדרייב!")

        st.divider()
        st.markdown("#### 📈 גרף התקדמות אישי")
        student = st.selectbox("בחר תלמיד לצפייה:", df['student_name'].unique())
        st_df = df[df['student_name'] == student].sort_values("date")
        st.line_chart(st_df.set_index("date")[['cat_proj_trans', 'cat_self_efficacy']])
    else:
        st.info("אין עדיין נתונים במערכת.")

# --- טאב 3: AI ---
with tab3:
    st.markdown("### 🤖 עוזר מחקרי (AI)")
    if st.button("✨ צור סיכום שבועי"):
        entries = load_last_week()
        if entries: st.markdown(generate_summary(entries))
        else: st.warning("אין נתונים מהשבוע האחרון.")
    
    st.divider()
    if "messages" not in st.session_state: st.session_state.messages = []
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]): st.markdown(msg["content"])
    if p := st.chat_input("שאל על הנתונים:"):
        st.session_state.messages.append({"role": "user", "content": p})
        with st.chat_message("user"): st.markdown(p)
        ans = chat_with_data(p, df.to_string())
        with st.chat_message("assistant"): st.markdown(ans)
        st.session_state.messages.append({"role": "assistant", "content": ans})

# סוף הקוד