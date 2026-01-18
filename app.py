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

# --- 1. הגדרות RTL ועיצוב ---
DATA_FILE = "reflections.jsonl"
GDRIVE_FOLDER_ID = st.secrets.get("GDRIVE_FOLDER_ID") 
# הגדרה קשיחה לשם הקובץ המקורי בלבד
MASTER_FILENAME = "All_Observations_Master.xlsx"

CLASS_ROSTER = ["נתנאל", "רועי", "אסף", "עילאי", "טדי", "גאל", "אופק", "דניאל.ר", "אלי", "טיגרן", "פולינה.ק", "תלמיד אחר..."]
TAGS_OPTIONS = ["התעלמות מקווים נסתרים", "בלבול בין היטלים", "קושי ברוטציה מנטלית", "טעות בפרופורציות", "קושי במעבר בין היטלים", "שימוש בכלי מדידה", "סיבוב פיזי של המודל", "תיקון עצמי", "עבודה עצמאית שוטפת"]

st.set_page_config(page_title="מערכת תצפית - גרסה 17.1", layout="wide")

st.markdown("""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Heebo:wght@300;400;700&display=swap');
        html, body, .stApp { direction: rtl; text-align: right; font-family: 'Heebo', sans-serif !important; }
        .stButton > button { width: 100%; font-weight: bold; border-radius: 12px; height: 3em; background-color: #28a745; color: white; }
        [data-testid="stSlider"] { direction: ltr !important; }
        .stSuccess { background-color: #d4edda; color: #155724; border: 1px solid #c3e6cb; border-radius: 10px; padding: 10px; }
    </style>
""", unsafe_allow_html=True)

# --- 2. פונקציות Google Drive (חיפוש ממוקד קובץ מאסטר) ---
def get_drive_service():
    try:
        json_str = base64.b64decode(st.secrets["GDRIVE_SERVICE_ACCOUNT_B64"]).decode("utf-8")
        creds = Credentials.from_service_account_info(json.loads(json_str), scopes=["https://www.googleapis.com/auth/drive"])
        return build("drive", "v3", credentials=creds)
    except: return None

def fetch_history_from_drive(student_name, svc):
    try:
        # חיפוש ממוקד אך ורק לשם הקובץ המקורי
        query = f"name = '{MASTER_FILENAME}' and trashed = false"
        res = svc.files().list(q=query, spaces='drive', fields='files(id, name)', supportsAllDrives=True, includeItemsFromAllDrives=True).execute().get('files', [])
        
        # סינון ידני נוסף לוודא שאין סיומות של (1) או (2)
        target_file = None
        for f in res:
            if f['name'] == MASTER_FILENAME:
                target_file = f
                break
        
        if not target_file: return None
        
        request = svc.files().get_media(fileId=target_file['id'])
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done: _, done = downloader.next_chunk()
        fh.seek(0)
        df = pd.read_excel(fh)
        
        # התאמה לעמודות בקובץ המאסטר שהעלית
        df['student_name'] = df['student_name'].astype(str).str.strip()
        search_name = str(student_name).strip()
        
        student_data = df[df['student_name'] == search_name]
        if student_data.empty: return None
        
        hist = ""
        for _, row in student_data.tail(10).iterrows():
            # שליפה מהעמודות המקוריות: challenge ו-interpretation
            hist += f"תאריך: {row.get('date')} | קושי: {row.get('challenge')} | פרשנות: {row.get('interpretation')}\n"
        return hist
    except: return None

def update_master_excel(data_to_add, svc):
    try:
        query = f"name = '{MASTER_FILENAME}' and trashed = false"
        res = svc.files().list(q=query, spaces='drive', supportsAllDrives=True, includeItemsFromAllDrives=True).execute().get('files', [])
        
        target_id = None
        for f in res:
            if f['name'] == MASTER_FILENAME:
                target_id = f['id']
                break

        new_df = pd.DataFrame(data_to_add)
        if target_id:
            request = svc.files().get_media(fileId=target_id)
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done: _, done = downloader.next_chunk()
            fh.seek(0)
            existing_df = pd.read_excel(fh)
            df = pd.concat([existing_df, new_df]).drop_duplicates(subset=['timestamp', 'student_name'], keep='last')
        else:
            df = new_df
            
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer: df.to_excel(writer, index=False)
        output.seek(0)
        media = MediaIoBaseUpload(output, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        
        if target_id:
            svc.files().update(fileId=target_id, media_body=media, supportsAllDrives=True).execute()
        else:
            meta = {'name': MASTER_FILENAME}
            if GDRIVE_FOLDER_ID: meta['parents'] = [GDRIVE_FOLDER_ID]
            svc.files().create(body=meta, media_body=media, supportsAllDrives=True).execute()
        return True
    except: return False

# --- 3. ממשק המשתמש ---
if "it" not in st.session_state: st.session_state.it = 0
if "chat" not in st.session_state: st.session_state.chat = []

st.title("🎓 יומן תצפית - גרסה 17.1 (Master Sync)")
svc = get_drive_service()
tab1, tab2, tab3 = st.tabs(["📝 הזנה וצ'אט", "📊 ניהול", "🤖 מגמות"])

with tab1:
    col_in, col_chat = st.columns([1.2, 1])
    with col_in:
        with st.container(border=True):
            it = st.session_state.it
            c1, c2 = st.columns(2)
            with c1:
                name_sel = st.selectbox("👤 בחר סטודנט", CLASS_ROSTER, key=f"n_{it}")
                student_name = st.text_input("שם חופשי:", key=f"fn_{it}") if name_sel == "תלמיד אחר..." else name_sel
            with c2:
                # שימוש בעמודה המקורית work_method/physical_model
                work_method = st.radio("🛠️ שימוש בגוף?", ["🧊 בעזרת גוף מודפס", "🎨 ללא גוף (דמיון)"], key=f"wm_{it}", horizontal=True)
            
            history = fetch_history_from_drive(student_name, svc) if (student_name and svc) else None
            if history:
                st.success(f"✅ נמצאה היסטוריה עבור {student_name} בקובץ המאסטר.")
            elif student_name:
                st.info(f"🔍 מחפש היסטוריה בדרייב...")

            st.markdown("### 📊 מדדים ודירוגי 1-5")
            q1, q2 = st.columns(2)
            with q1: drawings = st.number_input("כמות שרטוטים", min_value=0, key=f"dc_{it}")
            with q2: duration = st.number_input("זמן עבודה (דקות)", min_value=0, step=5, key=f"dm_{it}")
            
            m1, m2 = st.columns(2)
            with m1:
                score_spatial = st.slider("תפיסה מרחבית", 1, 5, 3, key=f"s1_{it}")
                score_views = st.slider("מעבר בין היטלים", 1, 5, 3, key=f"s2_{it}")
            with m2:
                score_model = st.slider("שימוש במודל", 1, 5, 3, key=f"s3_{it}")
                score_efficacy = st.slider("תחושת מסוגלות", 1, 5, 3, key=f"s4_{it}")

            st.divider()
            challenge = st.text_area("🗣️ תיאור קשיים (חובה)", key=f"ch_{it}")
            interpretation = st.text_area("🧠 פרשנות מחקרית", key=f"int_{it}")
            tags = st.multiselect("🏷️ תגיות", TAGS_OPTIONS, key=f"t_{it}")
            uploaded_files = st.file_uploader("📷 צרף תמונות", accept_multiple_files=True, key=f"up_{it}")

            if st.button("💾 שמור וסנכרן למאסטר"):
                if not challenge: st.error("חובה למלא תיאור קשיים.")
                else:
                    entry = {
                        "date": date.today().isoformat(), "student_name": student_name,
                        "work_method": work_method, "drawings_count": drawings,
                        "duration_min": duration, "score_spatial": score_spatial,
                        "score_views": score_views, "score_model": score_model,
                        "score_efficacy": score_efficacy, "challenge": challenge,
                        "interpretation": interpretation, "tags": ", ".join(tags),
                        "timestamp": datetime.now().strftime("%H:%M:%S")
                    }
                    if svc: update_master_excel([entry], svc)
                    st.success("נשמר בדרייב המרכזי!")
                    st.session_state.it += 1
                    st.rerun()

    with col_chat:
        st.subheader(f"🤖 עוזר מחקר: {student_name}")
        chat_cont = st.container(height=550)
        with chat_cont:
            for q, a in st.session_state.chat:
                st.markdown(f"**🧐 חוקר:** {q}"); st.info(f"**🤖 AI:** {a}")
        u_input = st.chat_input("שאל על הסטודנט...")
        if u_input:
            client = genai.Client(api_key=st.secrets["GOOGLE_API_KEY"])
            prompt = f"נתח את {student_name} לפי היסטוריה: {history}. מקורות 2014-2026 APA 7."
            res = client.models.generate_content(model="gemini-2.0-flash", contents=f"{prompt}\n{u_input}", config={'tools': [{'google_search': {}}]} )
            st.session_state.chat.append((u_input, res.text)); st.rerun()

with tab2:
    st.header("📊 נתונים אחרונים")
    if os.path.exists(DATA_FILE):
        df_local = pd.read_json(DATA_FILE, lines=True)
        st.dataframe(df_local.tail(10))

with tab3:
    st.header("🤖 ניתוח מגמות אקדמי")
    if st.button("✨ ניתוח עומק מכל נתוני המאסטר"):
        if svc:
            query = f"name = '{MASTER_FILENAME}'"
            res = svc.files().list(q=query, spaces='drive').execute().get('files', [])
            target = next((f for f in res if f['name'] == MASTER_FILENAME), None)
            if target:
                request = svc.files().get_media(fileId=target['id'])
                fh = io.BytesIO(); downloader = MediaIoBaseDownload(fh, request)
                done = False
                while not done: _, done = downloader.next_chunk()
                fh.seek(0); df = pd.read_excel(fh)
                summary = df[['student_name', 'work_method', 'score_spatial', 'interpretation']].to_string()
                client = genai.Client(api_key=st.secrets["GOOGLE_API_KEY"])
                prompt = f"נתח מגמות (2014-2026) בפורמט APA על בסיס: {summary}"
                response = client.models.generate_content(model="gemini-2.0-flash", contents=prompt, config={'tools': [{'google_search': {}}]} )
                st.markdown(response.text)
