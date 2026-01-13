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

# --- 2. עיצוב הממשק ---
def setup_design():
    st.set_page_config(page_title="עוזר מחקר לתזה", page_icon="🎓", layout="wide")
    st.markdown("""
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Heebo:wght@300;400;700&display=swap');
            html, body, .stApp { direction: rtl; text-align: right; font-family: 'Heebo', sans-serif !important; }
            .stTextInput input, .stTextArea textarea, .stSelectbox > div > div { direction: rtl; text-align: right; }
            .stButton > button { width: 100%; font-weight: bold; border-radius: 10px; }
            .chat-msg { background-color: #f8f9fa; border-radius: 10px; padding: 15px; margin-bottom: 10px; border-right: 5px solid #007bff; }
        </style>
    """, unsafe_allow_html=True)

# --- 3. פונקציות שירות וגוגל דרייב ---
def get_drive_service():
    try:
        json_str = base64.b64decode(st.secrets["GDRIVE_SERVICE_ACCOUNT_B64"]).decode("utf-8")
        info = json.loads(json_str)
        creds = Credentials.from_service_account_info(info, scopes=["https://www.googleapis.com/auth/drive.file"])
        return build("drive", "v3", credentials=creds)
    except: return None

def save_to_drive(summary_text, svc):
    try:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
        filename = f"AI_Research_Analysis_{timestamp}.txt"
        file_metadata = {'name': filename, 'parents': [GDRIVE_FOLDER_ID]}
        media = MediaIoBaseUpload(io.BytesIO(summary_text.encode("utf-8")), mimetype='text/plain')
        svc.files().create(body=file_metadata, media_body=media, supportsAllDrives=True).execute()
        return True
    except: return False

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
    except: return False

# --- 4. פונקציות AI - עוזר מחקר וסיכום ---
def chat_with_ai(user_query, current_entry):
    try:
        client = genai.Client(api_key=st.secrets["GOOGLE_API_KEY"])
        context = f"אתה עוזר מחקר לתזה בחינוך טכנולוגי. החוקר כותב כעת על {current_entry['student_name']}.\n"
        context += f"מידע נוכחי: קשיים: {current_entry['challenge']}, פעולות: {current_entry['done']}, פרשנות: {current_entry['interpretation']}\n"
        res = client.models.generate_content(model="gemini-2.0-flash", contents=context + user_query)
        return res.text
    except Exception as e: return f"שגיאה: {e}"

def generate_final_report(entries):
    if not entries: return None
    full_text = "נתונים לניתוח:\n"
    for e in entries:
        full_text += f"- תלמיד: {e.get('student_name')}, קשיים: {e.get('challenge')}, פרשנות: {e.get('interpretation')}\n"
    try:
        client = genai.Client(api_key=st.secrets["GOOGLE_API_KEY"])
        res = client.models.generate_content(model="gemini-2.0-flash", contents="נתח את המגמות המחקריות הבאות:\n" + full_text)
        return res.text
    except: return None

# --- 5. ממשק המשתמש ---
setup_design()
st.title("🎓 עוזר מחקר חכם - יומן תצפית")
tab1, tab2, tab3 = st.tabs(["📝 תצפית וצ'אט מחקרי", "📊 ניהול נתונים", "🤖 סיכומים"])
svc = get_drive_service()

with tab1:
    col_input, col_ai = st.columns([1.5, 1])
    
    with col_input:
        with st.form("main_form", clear_on_submit=True):
            st.subheader("פרטי התצפית")
            sel = st.selectbox("👤 שם תלמיד", CLASS_ROSTER)
            student_name = st.text_input("שם חופשי:") if sel == "תלמיד אחר..." else sel
            
            c1, c2 = st.columns(2)
            with c1: difficulty = st.select_slider("רמת קושי המטלה", options=[1, 2, 3], value=2)
            with c2: physical_model = st.radio("שימוש במודל:", ["ללא", "חלקי", "מלא"], horizontal=True)
            
            tags = st.multiselect("🏷️ תגיות נצפות", OBSERVATION_TAGS)
            
            planned = st.text_area("📋 תיאור המטלה")
            challenge = st.text_area("🗣️ ציטוטים וקשיים")
            done = st.text_area("👀 פעולות שבוצעו")
            interpretation = st.text_area("💡 פרשנות איכותנית (השערות מחקריות)")
            
            if st.form_submit_button("💾 שמור תצפית"):
                entry = {
                    "type": "reflection", "date": date.today().isoformat(), "student_name": student_name,
                    "physical_model": physical_model, "planned": planned, "challenge": challenge, 
                    "done": done, "interpretation": interpretation, "tags": ", ".join(tags), 
                    "timestamp": datetime.now().strftime("%H:%M:%S")
                }
                with open(DATA_FILE, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                if svc: update_master_excel([entry], svc)
                st.balloons()
                st.success(f"התצפית על {student_name} נשמרה בהצלחה!")

    with col_ai:
        st.subheader("🤖 התייעצות עם עוזר המחקר")
        if "chat_history" not in st.session_state: st.session_state.chat_history = []
        
        user_q = st.text_input("שאל על התצפית הנוכחית:", placeholder="למשל: האם הטעות כאן מעידה על קושי מרחבי?")
        if st.button("שלח שאלה"):
            curr = {"student_name": student_name, "challenge": challenge, "done": done, "interpretation": interpretation}
            with st.spinner("מנתח..."):
                ans = chat_with_ai(user_q, curr)
                st.session_state.chat_history.append((user_q, ans))
        
        for q, a in reversed(st.session_state.chat_history):
            st.markdown(f"**🧐 אתה:** {q}")
            st.info(f"**🤖 עוזר:** {a}")
            st.divider()

with tab2:
    st.header("📊 ניהול נתונים")
    if st.button("🔄 סנכרן הכל לאקסל"):
        if os.path.exists(DATA_FILE) and svc:
            all_data = [json.loads(l) for l in open(DATA_FILE, "r", encoding="utf-8") if json.loads(l).get("type")=="reflection"]
            update_master_excel(all_data, svc)
            st.success("סנכרון הושלם!")

with tab3:
    st.header("🤖 סיכומים ושמירה לדרייב")
    if st.button("✨ בצע סיכום 10 תצפיות אחרונות ושמור אוטומטית לדרייב"):
        if os.path.exists(DATA_FILE):
            all_ents = [json.loads(l) for l in open(DATA_FILE, "r", encoding="utf-8") if json.loads(l).get("type")=="reflection"]
            with st.spinner("מייצר דוח..."):
                summary = generate_final_report(all_ents[-10:])
                if summary:
                    st.markdown(summary)
                    if svc and save_to_drive(summary, svc):
                        st.success("✅ קובץ הסיכום נשמר בתיקיית הדרייב שלך!")
        else: st.warning("אין נתונים בזיכרון.")