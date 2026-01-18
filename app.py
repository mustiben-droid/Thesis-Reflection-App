import json
import base64
import os
import io
from datetime import date, datetime
import pandas as pd
import streamlit as st
from google import genai
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload

# --- 1. הגדרות ועיצוב RTL ---
DATA_FILE = "reflections.jsonl"
GDRIVE_FOLDER_ID = st.secrets.get("GDRIVE_FOLDER_ID") 
MASTER_FILENAME = "All_Observations_Master.xlsx"

CLASS_ROSTER = ["נתנאל", "רועי", "אסף", "עילאי", "טדי", "גאל", "אופק", "דניאל.ר", "אלי", "טיגרן", "פולינה.ק", "תלמיד אחר..."]
TAGS_OPTIONS = ["התעלמות מקווים נסתרים", "בלבול בין היטלים", "קושי ברוטציה מנטלית", "טעות בפרופורציות", "קושי במעבר בין היטלים", "שימוש בכלי מדידה", "סיבוב פיזי של המודל", "תיקון עצמי", "עבודה עצמאית שוטפת"]

st.set_page_config(page_title="מערכת תצפית - גרסה 16.8", layout="wide")

st.markdown("""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Heebo:wght@300;400;700&display=swap');
        html, body, .stApp { direction: rtl; text-align: right; font-family: 'Heebo', sans-serif !important; }
        .stButton > button { width: 100%; font-weight: bold; border-radius: 12px; height: 3em; background-color: #28a745; color: white; }
        [data-testid="stSlider"] { direction: ltr !important; }
    </style>
""", unsafe_allow_html=True)

# --- 2. פונקציות Google Drive (מותאמות למבנה הקובץ שלך) ---
def get_drive_service():
    try:
        json_str = base64.b64decode(st.secrets["GDRIVE_SERVICE_ACCOUNT_B64"]).decode("utf-8")
        creds = Credentials.from_service_account_info(json.loads(json_str), scopes=["https://www.googleapis.com/auth/drive"])
        return build("drive", "v3", credentials=creds)
    except: return None

def upload_file_to_drive(uploaded_file, svc):
    try:
        file_metadata = {'name': uploaded_file.name}
        if GDRIVE_FOLDER_ID: file_metadata['parents'] = [GDRIVE_FOLDER_ID]
        media = MediaIoBaseUpload(io.BytesIO(uploaded_file.getvalue()), mimetype=uploaded_file.type)
        file = svc.files().create(body=file_metadata, media_body=media, fields='id, webViewLink', supportsAllDrives=True).execute()
        return file.get('webViewLink')
    except: return "Error"

def fetch_history_from_drive(student_name, svc):
    try:
        query = f"name = '{MASTER_FILENAME}' and trashed = false"
        res = svc.files().list(q=query, spaces='drive', supportsAllDrives=True, includeItemsFromAllDrives=True).execute().get('files', [])
        if not res: return None
        file_id = res[0]['id']; request = svc.files().get_media(fileId=file_id)
        fh = io.BytesIO(); downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done: _, done = downloader.next_chunk()
        fh.seek(0); df = pd.read_excel(fh)
        
        # חיפוש גמיש בנתונים (מתעלם מרווחים)
        df['student_name'] = df['student_name'].astype(str).str.strip()
        student_data = df[df['student_name'].str.contains(student_name.strip(), na=False, case=False)]
        
        if student_data.empty: return None
        
        hist = ""
        for _, row in student_data.tail(10).iterrows():
            hist += f"תאריך: {row.get('date')} | מודל: {row.get('physical_model')} | קושי: {str(row.get('challenge'))[:100]}... | פרשנות: {str(row.get('interpretation'))[:100]}...\n"
        return hist
    except: return None

def update_master_excel(data_to_add, svc):
    try:
        query = f"name = '{MASTER_FILENAME}' and trashed = false"
        res = svc.files().list(q=query, spaces='drive', supportsAllDrives=True, includeItemsFromAllDrives=True).execute().get('files', [])
        new_df = pd.DataFrame(data_to_add)
        if res:
            file_id = res[0]['id']; request = svc.files().get_media(fileId=file_id)
            fh = io.BytesIO(); downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done: _, done = downloader.next_chunk()
            fh.seek(0); existing_df = pd.read_excel(fh)
            df = pd.concat([existing_df, new_df]).drop_duplicates(subset=['timestamp', 'student_name'], keep='last')
        else:
            df = new_df
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer: df.to_excel(writer, index=False)
        output.seek(0); media = MediaIoBaseUpload(output, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        if res: svc.files().update(fileId=file_id, media_body=media, supportsAllDrives=True).execute()
        else:
            meta = {'name': MASTER_FILENAME}
            if GDRIVE_FOLDER_ID: meta['parents'] = [GDRIVE_FOLDER_ID]
            svc.files().create(body=meta, media_body=media, supportsAllDrives=True).execute()
        return True
    except: return False

# --- 3. ממשק המשתמש ---
if "it" not in st.session_state: st.session_state.it = 0
if "chat" not in st.session_state: st.session_state.chat = []

st.title("🎓 יומן תצפית - גרסה 16.8 (סנכרון מלא)")
svc = get_drive_service()
tab1, tab2, tab3 = st.tabs(["📝 הזנה", "📊 ניהול", "🤖 מגמות"])

with tab1:
    col_in, col_chat = st.columns([1.2, 1])
    with col_in:
        with st.container(border=True):
            it = st.session_state.it
            c1, c2 = st.columns(2)
            with c1:
                name_sel = st.selectbox("👤 סטודנט", CLASS_ROSTER, key=f"n_{it}")
                student_name = st.text_input("שם חופשי:", key=f"fn_{it}") if name_sel == "תלמיד אחר..." else name_sel
            with c2:
                physical_model = st.radio("🛠️ סוג תרגול", ["עם מודל פיזי", "ללא מודל"], key=f"pm_{it}", horizontal=True)
            
            # החיווי הירוק שמוודא שרועי נמצא
            history = fetch_history_from_drive(student_name, svc) if (student_name and svc) else None
            if history: st.success(f"✅ היסטוריה עבור {student_name} נטענה.")
            
            st.markdown("### 📊 מדדים כמותיים (1-5)")
            q1, q2 = st.columns(2)
            with q1: drawings_count = st.number_input("כמות שרטוטים", min_value=0, key=f"dc_{it}")
            with q2: duration_min = st.number_input("זמן (דקות)", min_value=0, step=5, key=f"dm_{it}")
            
            m1, m2 = st.columns(2)
            with m1:
                score_spatial = st.slider("תפיסה מרחבית", 1, 5, 3, key=f"s1_{it}")
                score_views = st.slider("מעבר בין היטלים", 1, 5, 3, key=f"s2_{it}")
            with m2:
                score_model = st.slider("שימוש במודל", 1, 5, 3, key=f"s3_{it}")
                score_efficacy = st.slider("תחושת מסוגלות", 1, 5, 3, key=f"s4_{it}")

            st.divider()
            challenge = st.text_area("🗣️ קשיים", key=f"ch_{it}")
            interpretation = st.text_area("🧠 פרשנות מחקרית", key=f"int_{it}")
            tags = st.multiselect("🏷️ תגיות", TAGS_OPTIONS, key=f"t_{it}")
            
            # העלאת קבצים חזרה!
            uploaded_files = st.file_uploader("📷 העלה צילומים", accept_multiple_files=True, key=f"up_{it}")

            if st.button("💾 שמור סנכרון מלא"):
                if not challenge: st.error("חובה לתאר קשיים.")
                else:
                    links = []
                    if uploaded_files and svc:
                        for f in uploaded_files: links.append(upload_file_to_drive(f, svc))
                    entry = {
                        "date": date.today().isoformat(), "student_name": student_name,
                        "physical_model": physical_model, "drawings_count": drawings_count,
                        "duration_min": duration_min, "score_spatial": score_spatial,
                        "score_views": score_views, "score_model": score_model,
                        "score_efficacy": score_efficacy, "challenge": challenge,
                        "interpretation": interpretation, "tags": ", ".join(tags),
                        "file_links": ", ".join(links), "timestamp": datetime.now().strftime("%H:%M:%S")
                    }
                    if svc: update_master_excel([entry], svc)
                    st.success("נשמר בהצלחה!")
                    st.session_state.it += 1
                    st.rerun()

    with col_chat:
        st.subheader(f"🤖 עוזר מחקר: {student_name}")
        chat_cont = st.container(height=550)
        for q, a in st.session_state.chat:
            with chat_cont: st.markdown(f"**🧐 חוקר:** {q}"); st.info(f"**🤖 AI:** {a}")
        
        u_input = st.chat_input("שאל על המגמות של הסטודנט...")
        if u_input:
            client = genai.Client(api_key=st.secrets["GOOGLE_API_KEY"])
            prompt = f"אתה עוזר מחקר. נתח את {student_name} לפי היסטוריה: {history}. מקורות 2014-2026 APA 7."
            res = client.models.generate_content(model="gemini-2.0-flash", contents=f"{prompt}\n{u_input}", config={'tools': [{'google_search': {}}]} )
            st.session_state.chat.append((u_input, res.text)); st.rerun()
