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
MASTER_FILENAME = "All_Observations_Master.xlsx"

CLASS_ROSTER = ["נתנאל", "רועי", "אסף", "עילאי", "טדי", "גאל", "אופק", "דניאל.ר", "אלי", "טיגרן", "פולינה.ק", "תלמיד אחר..."]
OBSERVATION_TAGS = ["התעלמות מקווים נסתרים", "בלבול בין היטלים", "קושי ברוטציה מנטלית", "טעות בפרופורציות", "קושי במעבר בין היטלים", "שימוש בכלי מדידה", "סיבוב פיזי של המודל", "תיקון עצמי", "עבודה עצמאית שוטפת"]

st.set_page_config(page_title="מערכת תצפית - Master 16.5", layout="wide")

st.markdown("""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Heebo:wght@300;400;700&display=swap');
        html, body, .stApp { direction: rtl; text-align: right; font-family: 'Heebo', sans-serif !important; }
        .stButton > button { width: 100%; font-weight: bold; border-radius: 12px; height: 3em; background-color: #28a745; color: white; }
    </style>
""", unsafe_allow_html=True)

# --- 2. פונקציות Google Drive (גרסה מתוקנת ומאובטחת) ---
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
        res = svc.files().list(q=query, spaces='drive', fields='files(id, name)', supportsAllDrives=True, includeItemsFromAllDrives=True).execute().get('files', [])
        if not res: return None
        
        file_id = res[0]['id']
        request = svc.files().get_media(fileId=file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done: _, done = downloader.next_chunk()
        
        fh.seek(0)
        df = pd.read_excel(fh)
        
        # חיפוש חכם: ניקוי שמות והשוואה גמישה
        search_name = str(student_name).strip()
        # מחפש בעמודת student_name או בכל עמודה שמכילה את השם
        if 'student_name' in df.columns:
            student_data = df[df['student_name'].astype(str).str.strip().str.contains(search_name, case=False, na=False)]
        else:
            mask = df.apply(lambda row: row.astype(str).str.contains(search_name, case=False, na=False).any(), axis=1)
            student_data = df[mask]
        
        if student_data.empty: return None
        
        hist_text = ""
        for _, row in student_data.tail(10).iterrows():
            hist_text += f"תאריך: {row.get('date')} | קושי: {row.get('challenge')} | פרשנות: {row.get('interpretation')}\n"
        return hist_text
    except: return None

def update_master_excel(data_to_add, svc):
    try:
        query = f"name = '{MASTER_FILENAME}' and trashed = false"
        res = svc.files().list(q=query, spaces='drive', supportsAllDrives=True, includeItemsFromAllDrives=True).execute().get('files', [])
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
            file_meta = {'name': MASTER_FILENAME}
            if GDRIVE_FOLDER_ID: file_meta['parents'] = [GDRIVE_FOLDER_ID]
            svc.files().create(body=file_meta, media_body=media, supportsAllDrives=True).execute()
        return True
    except: return False

# --- 3. ממשק המשתמש ---
if "form_iteration" not in st.session_state: st.session_state.form_iteration = 0
if "chat_history" not in st.session_state: st.session_state.chat_history = []

st.title("🎓 מערכת תצפית תזה - Master 16.5")
tab1, tab2, tab3 = st.tabs(["📝 הזנת תצפית", "📊 ניהול נתונים", "🤖 ניתוח מגמות"])
svc = get_drive_service()

with tab1:
    col_in, col_chat = st.columns([1.2, 1])
    with col_in:
        with st.container(border=True):
            it = st.session_state.form_iteration
            c1, c2 = st.columns(2)
            with c1:
                name_sel = st.selectbox("👤 בחר סטודנט", CLASS_ROSTER, key=f"n_{it}")
                student_name = st.text_input("שם חופשי:", key=f"fn_{it}") if name_sel == "תלמיד אחר..." else name_sel
            with c2:
                exercise_type = st.radio("🛠️ סוג תרגול:", ["עם מודל פיזי", "ללא מודל (דף בלבד)"], key=f"et_{it}", horizontal=True)
            
            # חיווי ירוק - בדיקת היסטוריה
            drive_history = ""
            if student_name and svc:
                drive_history = fetch_history_from_drive(student_name, svc)
                if drive_history:
                    st.success(f"✅ נמצאה היסטוריה בדרייב עבור {student_name}. הצ'אט מוכן.")
                else:
                    st.info(f"💡 לא נמצא תיעוד קודם עבור {student_name}.")

            st.markdown("### 📊 מדדים ודירוגים")
            q1, q2 = st.columns(2)
            with q1: num_drawings = st.number_input("כמות שרטוטים", min_value=0, step=1, key=f"nd_{it}")
            with q2: work_duration = st.number_input("זמן עבודה (דק')", min_value=0, step=5, key=f"wd_{it}")

            m1, m2 = st.columns(2)
            with m1:
                score_spatial = st.slider("תפיסה מרחבית (1-5)", 1, 5, 3, key=f"s1_{it}")
                score_views = st.slider("מעבר בין היטלים (1-5)", 1, 5, 3, key=f"s2_{it}")
            with m2:
                score_model = st.slider("שימוש במודל (1-5)", 1, 5, 3, key=f"s3_{it}")
                score_efficacy = st.slider("תחושת מסוגלות (1-5)", 1, 5, 3, key=f"s4_{it}")

            st.divider()
            challenge = st.text_area("🗣️ תיאור קשיים (חובה)", key=f"ch_{it}")
            done = st.text_area("👀 פעולות שבוצעו", key=f"do_{it}")
            interpretation = st.text_area("🧠 פרשנות מחקרית", key=f"int_{it}")
            tags = st.multiselect("🏷️ תגיות", OBSERVATION_TAGS, key=f"t_{it}")
            
            # כפתור העלאת הקבצים שחזר למקומו
            uploaded_files = st.file_uploader("צרף צילומים/שרטוטים", accept_multiple_files=True, key=f"f_{it}")

            if st.button("💾 שמור וסנכרן תצפית"):
                if not challenge.strip(): st.error("חובה למלא תיאור קושי.")
                else:
                    with st.spinner("סנכרן לדרייב..."):
                        links = []
                        if uploaded_files and svc:
                            for f in uploaded_files: links.append(upload_file_to_drive(f, svc))
                        entry = {
                            "date": date.today().isoformat(), "student_name": student_name,
                            "exercise_type": exercise_type, "num_drawings": num_drawings,
                            "work_duration": work_duration, "score_spatial": score_spatial,
                            "score_views": score_views, "score_model": score_model,
                            "score_efficacy": score_efficacy, "challenge": challenge,
                            "done": done, "interpretation": interpretation,
                            "timestamp": datetime.now().strftime("%H:%M:%S"),
                            "file_links": ", ".join(links), "tags": ", ".join(tags)
                        }
                        with open(DATA_FILE, "a", encoding="utf-8") as f: f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                        if svc: update_master_excel([entry], svc)
                        st.success("נשמר!")
                        st.session_state.form_iteration += 1
                        st.rerun()

    with col_chat:
        st.subheader(f"🤖 עוזר מחקר אקדמי")
        chat_cont = st.container(height=600)
        with chat_cont:
            for q, a in st.session_state.chat_history:
                st.markdown(f"**🧐 חוקר:** {q}"); st.info(f"**🤖 AI:** {a}")
        u_input = st.chat_input("שאל על מגמות...")
        if u_input:
            client = genai.Client(api_key=st.secrets["GOOGLE_API_KEY"])
            prompt = f"אתה עוזר מחקר. נתח את הסטודנט {student_name} לפי: {drive_history}. מקורות 2014-2026 APA."
            res = client.models.generate_content(
                model="gemini-2.0-flash", contents=f"{prompt}\n\nשאלה: {u_input}",
                config={'tools': [{'google_search': {}}]} 
            )
            st.session_state.chat_history.append((u_input, res.text)); st.rerun()

with tab2:
    if st.button("🔄 סנכרון מאולץ"):
        if os.path.exists(DATA_FILE) and svc:
            with st.spinner("סנכרן..."):
                all_d = [json.loads(l) for l in open(DATA_FILE, "r", encoding="utf-8")]
                update_master_excel(all_d, svc); st.success("סונכרן!")

with tab3:
    st.header("🤖 ניתוח מגמות אקדמי")
    if st.button("✨ בצע ניתוח עומק רוחבי"):
        if svc:
            query = f"name = '{MASTER_FILENAME}'"
            res = svc.files().list(q=query, spaces='drive', supportsAllDrives=True, includeItemsFromAllDrives=True).execute().get('files', [])
            if res:
                file_id = res[0]['id']; request = svc.files().get_media(fileId=file_id)
                fh = io.BytesIO(); downloader = MediaIoBaseDownload(fh, request)
                done = False
                while not done: _, done = downloader.next_chunk()
                fh.seek(0); df = pd.read_excel(fh)
                data_summary = df.to_string()
                client = genai.Client(api_key=st.secrets["GOOGLE_API_KEY"])
                prompt = f"נתח מגמות (2014-2026) בפורמט APA על בסיס כל המדדים והפרשנויות: {data_summary}"
                response = client.models.generate_content(model="gemini-2.0-flash", contents=prompt, config={'tools': [{'google_search': {}}]} )
                st.markdown(response.text)
