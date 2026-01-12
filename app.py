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

CLASS_ROSTER = ["נתנאל", "רועי", "אסף", "עילאי", "טדי", "גאל", "אופק", "דניאל.ר", "אלי", "טיגרן", "פולינה.ק", "תלמיד אחר..."]

OBSERVATION_TAGS = [
    "התעלמות מקווים נסתרים", "בלבול בין היטלים", "קושי ברוטציה מנטלית", 
    "טעות בפרופורציות", "קושי במעבר בין היטלים", "שימוש בכלי מדידה", 
    "סיבוב פיזי של המודל", "תיקון עצמי", "עבודה עצמאית שוטפת"
]

# --- 2. עיצוב ---
def setup_design():
    st.set_page_config(page_title="יומן תצפית מחקרי", page_icon="🎓", layout="centered")
    st.markdown("""
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Heebo:wght@300;400;700&display=swap');
            html, body, .stApp { direction: rtl; text-align: right; font-family: 'Heebo', sans-serif !important; }
            .stTextInput input, .stTextArea textarea, .stSelectbox > div > div { direction: rtl; text-align: right; }
            .stButton > button { width: 100%; font-weight: bold; border-radius: 10px; }
            [data-testid="stSlider"] { direction: ltr !important; }
            .stRadio > div { flex-direction: row-reverse !important; gap: 20px; }
        </style>
    """, unsafe_allow_html=True)

# --- 3. פונקציות שירות ודרייב ---
def get_drive_service():
    try:
        json_str = base64.b64decode(st.secrets["GDRIVE_SERVICE_ACCOUNT_B64"]).decode("utf-8")
        info = json.loads(json_str)
        creds = Credentials.from_service_account_info(info, scopes=["https://www.googleapis.com/auth/drive.file"])
        return build("drive", "v3", credentials=creds)
    except:
        return None

def upload_image_to_drive(uploaded_file, svc):
    try:
        file_metadata = {'name': uploaded_file.name, 'parents': [GDRIVE_FOLDER_ID]}
        media = MediaIoBaseUpload(io.BytesIO(uploaded_file.getvalue()), mimetype=uploaded_file.type)
        file = svc.files().create(body=file_metadata, media_body=media, fields='id, webViewLink', supportsAllDrives=True).execute()
        return file.get('webViewLink')
    except:
        return None

def load_data_from_drive(svc):
    try:
        query = f"name = '{MASTER_FILENAME}' and '{GDRIVE_FOLDER_ID}' in parents and trashed = false"
        res = svc.files().list(q=query, supportsAllDrives=True, includeItemsFromAllDrives=True).execute().get('files', [])
        if res:
            file_id = res[0]['id']
            request = svc.files().get_media(fileId=file_id)
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done: _, done = downloader.next_chunk()
            fh.seek(0)
            df = pd.read_excel(fh)
            # שמירה מקומית כדי שה-AI יוכל לקרוא
            if os.path.exists(DATA_FILE): os.remove(DATA_FILE)
            for _, row in df.iterrows():
                save_local(row.to_dict())
            return True
        return False
    except:
        return False

def update_master_excel(data_to_add, svc):
    try:
        query = f"name = '{MASTER_FILENAME}' and '{GDRIVE_FOLDER_ID}' in parents and trashed = false"
        res = svc.files().list(q=query, supportsAllDrives=True, includeItemsFromAllDrives=True).execute().get('files', [])
        new_df = pd.DataFrame(data_to_add)
        if res:
            file_id = res[0]['id']
            request = svc.files().get_media(fileId=file_id)
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done: _, done = downloader.next_chunk()
            fh.seek(0)
            existing_df = pd.read_excel(fh)
            df = pd.concat([existing_df, new_df]).drop_duplicates(subset=['timestamp', 'student_name'], keep='last')
        else:
            df = new_df
            file_id = None
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False)
        output.seek(0)
        media = MediaIoBaseUpload(output, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        if file_id:
            svc.files().update(fileId=file_id, media_body=media, supportsAllDrives=True).execute()
        else:
            svc.files().create(body={'name': MASTER_FILENAME, 'parents': [GDRIVE_FOLDER_ID]}, media_body=media, supportsAllDrives=True).execute()
        return True
    except:
        return False

def save_local(entry):
    with open(DATA_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

def generate_ai_report(entries):
    if not entries: return None
    full_text = ""
    for e in entries:
        full_text += f"תלמיד: {e.get('student_name')}, קשיים: {e.get('challenge')}, פעולות: {e.get('done')}\n"
    prompt = f"נתח את התצפיות הבאות עבור מחקר תזה בשרטוט טכני. סכם מגמות והמלצות:\n{full_text}"
    try:
        client = genai.Client(api_key=st.secrets["GOOGLE_API_KEY"])
        response = client.models.generate_content(model="gemini-2.0-flash", contents=prompt)
        return response.text
    except:
        return "שגיאה בייצור הסיכום."

# --- 4. ממשק משתמש ---
setup_design()
st.title("🎓 יומן תצפית - מהדורת מחקר")
tab1, tab2, tab3 = st.tabs(["📝 רפלקציה", "📊 ניהול", "🤖 AI"])
svc = get_drive_service()

with tab1:
    with st.form("main_form", clear_on_submit=True):
        st.subheader("1. פרטי התצפית")
        c1, c2 = st.columns([3, 2])
        with c1:
            sel = st.selectbox("👤 שם תלמיד", CLASS_ROSTER)
            student_name = st.text_input("שם חופשי:") if sel == "תלמיד אחר..." else sel
        with c2:
            difficulty = st.select_slider("רמה", options=[1, 2, 3], value=2)
        
        physical_model = st.radio("שימוש במודל:", ["ללא", "חלקי", "מלא"], horizontal=True)
        tags = st.multiselect("🏷️ תגיות", OBSERVATION_TAGS)
        challenge = st.text_area("🗣️ קשיים")
        done = st.text_area("👀 פעולות")
        uploaded_files = st.file_uploader("📸 תמונות", accept_multiple_files=True, type=['png', 'jpg', 'jpeg'])

        if st.form_submit_button("💾 שמור תצפית"):
            with st.spinner("שומר..."):
                img_links = []
                if svc and uploaded_files:
                    for f in uploaded_files:
                        link = upload_image_to_drive(f, svc)
                        if link: img_links.append(link)
                
                entry = {
                    "type": "reflection", "date": date.today().isoformat(), "student_name": student_name,
                    "physical_model": physical_model, "challenge": challenge, "done": done,
                    "tags": ", ".join(tags), "images": ", ".join(img_links),
                    "timestamp": datetime.now().strftime("%H:%M:%S")
                }
                save_local(entry)
                if svc: update_master_excel([entry], svc)
                st.balloons()
                st.success(f"התצפית על {student_name} נשמרה!")

with tab2:
    st.header("ניהול נתונים")
    if st.button("🔄 סנכרן נתונים לאקסל"):
        if os.path.exists(DATA_FILE) and svc:
            all_data = [json.loads(l) for l in open(DATA_FILE, "r", encoding="utf-8") if json.loads(l).get("type")=="reflection"]
            update_master_excel(all_data, svc)
            st.success("סנכרון הושלם!")
    
    st.divider()
    if st.button("📥 טען נתונים מהדרייב ל-AI (חובה לפני סיכום)"):
        if svc:
            with st.spinner("מושך נתונים מהאקסל..."):
                if load_data_from_drive(svc):
                    st.success("הנתונים נטענו! עכשיו אפשר לעבור לטאב AI ולסכם.")
                else:
                    st.error("לא נמצא קובץ אקסל לסנכרון.")

with tab3:
    st.header("🤖 AI")
    if st.button("✨ סכם 10 תצפיות אחרונות"):
        if os.path.exists(DATA_FILE):
            all_ents = [json.loads(l) for l in open(DATA_FILE, "r", encoding="utf-8")]
            summary = generate_ai_report(all_ents[-10:])
            if summary:
                st.markdown(summary)
                st.download_button("📥 הורד קובץ סיכום", data=summary, file_name=f"Summary_{date.today()}.txt")
        else:
            st.warning("הזיכרון ריק. עבור לטאב 'ניהול' ולחץ על 'טען נתונים מהדרייב'.")

# --- סוף הקוד המלא - מיועד לשימוש במחקר תזה ---