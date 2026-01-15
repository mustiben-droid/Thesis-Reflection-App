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

# --- 1. הגדרות ועיצוב ---
DATA_FILE = "reflections.jsonl"
GDRIVE_FOLDER_ID = st.secrets.get("GDRIVE_FOLDER_ID") 
MASTER_FILENAME = "All_Observations_Master.xlsx"

CLASS_ROSTER = ["נתנאל", "רועי", "אסף", "עילאי", "טדי", "גאל", "אופק", "דניאל.ר", "אלי", "טיגרן", "פולינה.ק", "תלמיד אחר..."]
OBSERVATION_TAGS = ["התעלמות מקווים נסתרים", "בלבול בין היטלים", "קושי ברוטציה מנטלית", "טעות בפרופורציות", "קושי במעבר בין היטלים", "שימוש בכלי מדידה", "סיבוב פיזי של המודל", "תיקון עצמי", "עבודה עצמאית שוטפת"]

st.set_page_config(page_title="עוזר מחקר לתזה", layout="wide")

st.markdown("""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Heebo:wght@300;400;700&display=swap');
        html, body, .stApp { direction: rtl; text-align: right; font-family: 'Heebo', sans-serif !important; }
        .stTextInput input, .stTextArea textarea, .stSelectbox > div > div { direction: rtl; text-align: right; }
        [data-testid="stSlider"] { direction: ltr !important; }
        .stButton > button { width: 100%; font-weight: bold; border-radius: 10px; }
    </style>
""", unsafe_allow_html=True)

# --- 2. פונקציות שירות (דרייב וקבצים) ---
def get_drive_service():
    try:
        json_str = base64.b64decode(st.secrets["GDRIVE_SERVICE_ACCOUNT_B64"]).decode("utf-8")
        creds = Credentials.from_service_account_info(json.loads(json_str), scopes=["https://www.googleapis.com/auth/drive.file"])
        return build("drive", "v3", credentials=creds)
    except: return None

# הפונקציה שחיפשת להעלאת קבצים
def upload_file_to_drive(uploaded_file, svc):
    try:
        file_metadata = {'name': uploaded_file.name}
        if GDRIVE_FOLDER_ID: file_metadata['parents'] = [GDRIVE_FOLDER_ID]
        media = MediaIoBaseUpload(io.BytesIO(uploaded_file.getvalue()), mimetype=uploaded_file.type)
        file = svc.files().create(body=file_metadata, media_body=media, fields='id, webViewLink', supportsAllDrives=True).execute()
        return file.get('webViewLink')
    except: return "Error"

def update_master_excel(data_to_add, svc):
    try:
        query = f"name = '{MASTER_FILENAME}' and trashed = false"
        if GDRIVE_FOLDER_ID: query += f" and '{GDRIVE_FOLDER_ID}' in parents"
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
        if file_id: svc.files().update(fileId=file_id, media_body=media, supportsAllDrives=True).execute()
        else:
            file_meta = {'name': MASTER_FILENAME}
            if GDRIVE_FOLDER_ID: file_meta['parents'] = [GDRIVE_FOLDER_ID]
            svc.files().create(body=file_meta, media_body=media, supportsAllDrives=True).execute()
        return True
    except: return False

def save_analysis_to_drive(analysis_text, svc):
    try:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename = f"ניתוח_מגמות_{timestamp}.txt"
        file_metadata = {'name': filename}
        if GDRIVE_FOLDER_ID: file_metadata['parents'] = [GDRIVE_FOLDER_ID]
        text_stream = io.BytesIO(analysis_text.encode("utf-8"))
        media = MediaIoBaseUpload(text_stream, mimetype="text/plain")
        file = svc.files().create(body=file_metadata, media_body=media, fields='id, webViewLink', supportsAllDrives=True).execute()
        return file.get('webViewLink')
    except: return None

# --- 3. לוגיקת AI וזיכרון היסטורי ---
def get_student_history(student_name):
    if not os.path.exists(DATA_FILE): return ""
    history_lines = []
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        for line in f:
            obs = json.loads(line)
            if obs.get("student_name") == student_name:
                history_lines.append(f"תאריך {obs.get('date')}: קושי: {obs.get('challenge')}. ציונים: תפיסה {obs.get('score_spatial')}, מעבר היטלים {obs.get('score_views')}.")
    return "\n".join(history_lines)

def chat_with_academic_ai(user_q, entry_data, history, student_full_history=""):
    try:
        client = genai.Client(api_key=st.secrets["GOOGLE_API_KEY"])
        instruction = f"אתה עוזר מחקר. נתח התקדמות עבור {entry_data.get('name')}. היסטוריה: {student_full_history}. חוקים: מקורות 2014-2026 בלבד, ציטוטים בטקסט."
        full_context = instruction + "\n\n"
        for q, a in history: full_context += f"חוקר: {q}\nעוזר: {a}\n\n"
        full_context += f"חוקר: {user_q}"
        response = client.models.generate_content(model="gemini-2.0-flash", contents=full_context)
        return response.text
    except Exception as e: return f"Error: {str(e)}"

# --- 4. ממשק המשתמש ---
if "form_iteration" not in st.session_state: st.session_state.form_iteration = 0
if "chat_history" not in st.session_state: st.session_state.chat_history = []

def reset_form():
    st.session_state.form_iteration += 1
    st.session_state.chat_history = []

st.title("🎓 יומן תצפית חכם למחקר")
tab1, tab2, tab3 = st.tabs(["📝 תצפית ושיחה", "📊 ניהול נתונים", "🤖 סיכום מגמות"])
svc = get_drive_service()

with tab1:
    col_in, col_chat = st.columns([1.3, 1])
    with col_in:
        with st.container(border=True):
            it = st.session_state.form_iteration
            name_sel = st.selectbox("👤 בחר סטודנט", CLASS_ROSTER, key=f"n_{it}")
            student_name = st.text_input("שם חופשי:", key=f"fn_{it}") if name_sel == "תלמיד אחר..." else name_sel
            history_sum = get_student_history(student_name)
            if history_sum: st.info(f"📜 נמצאו תצפיות קודמות על {student_name}.")

            c1, c2 = st.columns(2)
            with c1: difficulty = st.select_slider("קושי", options=[1, 2, 3], value=2, key=f"d_{it}")
            with c2: model_status = st.radio("מודל:", ["ללא מודל", "מודל חלקי", "מודל מלא"], horizontal=True, key=f"ms_{it}")
            
            st.divider()
            m1, m2 = st.columns(2)
            with m1:
                score_spatial = st.slider("תפיסה מרחבית", 1, 5, 3, key=f"s1_{it}")
                score_views = st.slider("מעבר בין היטלים", 1, 5, 3, key=f"s2_{it}")
            with m2:
                score_model = st.slider("שימוש במודל", 1, 5, 3, key=f"s3_{it}")
                score_efficacy = st.slider("מסוגלות", 1, 5, 3, key=f"s4_{it}")

            st.divider()
            challenge = st.text_area("🗣️ קשיים", key=f"ch_{it}")
            done = st.text_area("👀 פעולות", key=f"do_{it}")
            interpretation = st.text_area("💡 פרשנות", key=f"in_{it}")
            tags = st.multiselect("🏷️ תגיות", OBSERVATION_TAGS, key=f"t_{it}")
            uploaded_files = st.file_uploader("קבצים", accept_multiple_files=True, key=f"f_{it}")

            if st.button("💾 שמור תצפית"):
                links = []
                if uploaded_files and svc:
                    for f in uploaded_files: links.append(upload_file_to_drive(f, svc))
                entry = {
                    "type": "reflection", "date": date.today().isoformat(), "student_name": student_name,
                    "difficulty": difficulty, "model_status": model_status, "score_spatial": score_spatial,
                    "score_views": score_views, "score_model": score_model, "score_efficacy": score_efficacy,
                    "challenge": challenge, "done": done, "interpretation": interpretation, 
                    "tags": ", ".join(tags), "timestamp": datetime.now().strftime("%H:%M:%S"), "file_links": ", ".join(links)
                }
                with open(DATA_FILE, "a", encoding="utf-8") as f: f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                if svc: update_master_excel([entry], svc)
                st.success("נשמר.")
                reset_form()
                st.rerun()

    with col_chat:
        st.subheader(f"🤖 צ'אט: {student_name}")
        chat_cont = st.container(height=500)
        with chat_cont:
            for q, a in st.session_state.chat_history:
                st.markdown(f"**🧐 חוקר:** {q}"); st.info(f"**🤖 AI:** {a}")
        u_input = st.chat_input("שאל...")
        if u_input:
            curr = {"name": student_name, "model_status": model_status, "score_spatial": score_spatial, "score_views": score_views}
            ans = chat_with_academic_ai(u_input, curr, st.session_state.chat_history, history_sum)
            st.session_state.chat_history.append((u_input, ans))
            st.rerun()

with tab2:
    if st.button("🔄 סנכרון לדרייב"):
        if os.path.exists(DATA_FILE) and svc:
            all_d = [json.loads(l) for l in open(DATA_FILE, "r", encoding="utf-8")]
            update_master_excel(all_d, svc); st.success("סונכרן!")

with tab3:
    st.header("🤖 ניתוח מגמות רוחבי")
    if st.button("✨ בצע ניתוח מגמות ושמור בדרייב"):
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                obs = [json.loads(l) for l in f][-15:]
            if obs:
                with st.spinner("מנתח..."):
                    txt = "\n".join([f"תלמיד: {o.get('student_name')}, תפיסה: {o.get('score_spatial')}, קושי: {o.get('challenge')}" for o in obs])
                    client = genai.Client(api_key=st.secrets["GOOGLE_API_KEY"])
                    res = client.models.generate_content(model="gemini-2.0-flash", contents=f"נתח מגמות (2014-2026). ציין שמות תלמידים ספציפיים:\n{txt}")
                    analysis_result = res.text
                    st.session_state.current_summary = analysis_result
                    if svc:
                        link = save_analysis_to_drive(analysis_result, svc)
                        if link: st.success(f"הניתוח נשמר בדרייב!")
            else: st.warning("אין נתונים.")
    if "current_summary" in st.session_state: st.markdown(st.session_state.current_summary)
