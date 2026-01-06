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
            html, body, .stApp { direction: rtl; text-align: right; font-family: 'Heebo', sans-serif !important; }
            .stTextInput input, .stTextArea textarea, .stSelectbox > div > div { direction: rtl; text-align: right; }
            .stButton > button { width: 100%; font-weight: bold; border-radius: 10px; }
            [data-testid="stSlider"] { direction: ltr !important; }
            .chat-msg { padding: 10px; border-radius: 10px; margin-bottom: 10px; }
            .user-msg { background-color: #f0f2f6; text-align: right; }
            .ai-msg { background-color: #e8f4fd; text-align: right; border-right: 5px solid #2196f3; }
        </style>
    """, unsafe_allow_html=True)

# --- 3. פונקציות דרייב ---
def get_drive_service():
    try:
        json_str = base64.b64decode(st.secrets["GDRIVE_SERVICE_ACCOUNT_B64"]).decode("utf-8")
        creds = Credentials.from_service_account_info(json.loads(json_str), scopes=["https://www.googleapis.com/auth/drive.file"])
        return build("drive", "v3", credentials=creds)
    except: return None

def upload_image_to_drive(uploaded_file, folder_id, svc):
    file_metadata = {'name': uploaded_file.name, 'parents': [folder_id]}
    media = MediaIoBaseUpload(io.BytesIO(uploaded_file.getvalue()), mimetype=uploaded_file.type)
    file = svc.files().create(body=file_metadata, media_body=media, fields='id, webViewLink').execute()
    return file.get('webViewLink')

def update_master_excel(data_to_add, svc, overwrite=False):
    try:
        query = f"name = '{MASTER_FILENAME}' and '{GDRIVE_FOLDER_ID}' in parents and trashed = false"
        res = svc.files().list(q=query).execute().get('files', [])
        if res and not overwrite:
            file_id = res[0]['id']
            request = svc.files().get_media(fileId=file_id)
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done: _, done = downloader.next_chunk()
            fh.seek(0)
            df = pd.read_excel(fh)
            df = pd.concat([df, pd.DataFrame(data_to_add)], ignore_index=True)
        else:
            df = pd.DataFrame(data_to_add)
            file_id = res[0]['id'] if res else None
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer: df.to_excel(writer, index=False)
        output.seek(0)
        media = MediaIoBaseUpload(output, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        if file_id: svc.files().update(fileId=file_id, media_body=media).execute()
        else: svc.files().create(body={'name': MASTER_FILENAME, 'parents': [GDRIVE_FOLDER_ID]}, media_body=media).execute()
        return True
    except: return False

def save_local(entry):
    with open(DATA_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

# --- 4. ממשק המשתמש ---
setup_design()
st.title("🎓 יומן תצפית - הממשק המלא והחכם")

tab1, tab2, tab3 = st.tabs(["📝 רפלקציה", "📊 נתונים", "💬 צ'אט AI"])

with tab1:
    with st.form("main_form", clear_on_submit=True):
        st.subheader("פרטי התצפית")
        c1, c2 = st.columns(2)
        with c1:
            sel = st.selectbox("👤 שם תלמיד", CLASS_ROSTER)
            student_name = st.text_input("שם חופשי:") if sel == "תלמיד אחר..." else sel
        with c2: lesson_id = st.text_input("📚 מזהה שיעור")
        
        tags = st.multiselect("🏷️ תגיות", OBSERVATION_TAGS)
        
        ca, cb = st.columns(2)
        with ca:
            planned = st.text_area("📋 המטלה שניתנה")
            challenge = st.text_area("🗣️ ציטוטים/קשיים")
        with cb:
            done = st.text_area("👀 פעולות שבוצעו")
            interpretation = st.text_area("💡 פרשנות המורה")
        
        uploaded_files = st.file_uploader("📸 העלאת תמונות מהשיעור", accept_multiple_files=True, type=['png', 'jpg', 'jpeg'])
        
        st.subheader("מדדים (1-5)")
        m1 = st.select_slider("🔄 המרת ייצוגים", options=[1,2,3,4,5], value=3)
        m2 = st.select_slider("📐 מעבר היטלים", options=[1,2,3,4,5], value=3)

        if st.form_submit_button("💾 שמור תצפית"):
            svc = get_drive_service()
            img_links = []
            if svc and uploaded_files:
                with st.spinner("מעלה תמונות לדרייב..."):
                    for f in uploaded_files:
                        img_links.append(upload_image_to_drive(f, GDRIVE_FOLDER_ID, svc))
            
            entry = {
                "type": "reflection", "date": date.today().isoformat(), "student_name": student_name,
                "lesson_id": lesson_id, "tags": ", ".join(tags), "planned": planned, 
                "done": done, "challenge": challenge, "interpretation": interpretation,
                "score_conv": m1, "score_proj": m2, "images": ", ".join(img_links),
                "timestamp": datetime.now().strftime("%H:%M:%S")
            }
            save_local(entry)
            if svc: update_master_excel([entry], svc)
            st.success("נשמר בהצלחה! ✅")

with tab2:
    st.header("📊 ניהול היסטוריה")
    if st.button("📤 סנכרן את כל העבר לאקסל בדרייב"):
        if os.path.exists(DATA_FILE):
            all_data = [json.loads(line) for line in open(DATA_FILE, "r", encoding="utf-8") if json.loads(line).get("type")=="reflection"]
            svc = get_drive_service()
            if svc: update_master_excel(all_data, svc, overwrite=True)
            st.success("הסנכרון הושלם!")

with tab3:
    st.header("💬 צ'אט עם עוזר המחקר")
    if "messages" not in st.session_state: st.session_state.messages = []

    # הצגת היסטוריית הצ'אט
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    if prompt := st.chat_input("שאל אותי על הנתונים שלך..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"): st.markdown(prompt)

        # הכנת ההקשר מתוך הנתונים
        context = ""
        if os.path.exists(DATA_FILE):
            entries = [json.loads(l) for l in open(DATA_FILE, "r", encoding="utf-8") if json.loads(l).get("type")=="reflection"]
            context = "להלן נתוני התצפיות שלך:\n" + "\n".join([str(e) for e in entries[-20:]]) # 20 אחרונים

        with st.chat_message("assistant"):
            try:
                client = genai.Client(api_key=st.secrets["GOOGLE_API_KEY"])
                full_prompt = f"אתה עוזר מחקר אקדמי. בהתבסס על הנתונים הבאים:\n{context}\nענה על השאלה: {prompt}"
                response = client.models.generate_content(model="gemini-2.0-flash", contents=full_prompt)
                st.markdown(response.text)
                st.session_state.messages.append({"role": "assistant", "content": response.text})
            except Exception as e: st.error(f"שגיאה: {e}")

# סוף הקוד