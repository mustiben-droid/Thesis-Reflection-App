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

# --- 1. הגדרות קבועות ועיצוב ---
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

# --- 2. פונקציות שירות ודרייב ---
def get_drive_service():
    try:
        json_str = base64.b64decode(st.secrets["GDRIVE_SERVICE_ACCOUNT_B64"]).decode("utf-8")
        creds = Credentials.from_service_account_info(json.loads(json_str), scopes=["https://www.googleapis.com/auth/drive.file"])
        return build("drive", "v3", credentials=creds)
    except: return None

def upload_file_to_drive(uploaded_file, svc, folder_id=GDRIVE_FOLDER_ID):
    try:
        file_metadata = {'name': uploaded_file.name}
        if folder_id: file_metadata['parents'] = [folder_id]
        media = MediaIoBaseUpload(io.BytesIO(uploaded_file.getvalue() if hasattr(uploaded_file, 'getvalue') else uploaded_file), mimetype='text/plain' if isinstance(uploaded_file, bytes) else 'auto')
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

def chat_with_academic_ai(user_q, entry_data, history):
    try:
        client = genai.Client(api_key=st.secrets["GOOGLE_API_KEY"])
        instruction = f"אתה עוזר מחקר אקדמי. סטודנט: {entry_data['name']}. מדדים (1-5): תפיסה {entry_data['score_spatial']}, היטלים {entry_data['score_views']}, מודל {entry_data['score_model']}, מסוגלות {entry_data['score_efficacy']}. מודל: {entry_data['model_status']}. חוקים: מקורות 2014-2026 בלבד, ציטוטים בגוף הטקסט."
        full_context = instruction + "\n\n"
        for q, a in history: full_context += f"חוקר: {q}\nעוזר: {a}\n\n"
        full_context += f"חוקר: {user_q}"
        response = client.models.generate_content(model="gemini-2.0-flash", contents=full_context)
        return response.text
    except Exception as e: return f"שגיאה: {str(e)}"

# --- 3. ניהול מצב האפליקציה (Reset) ---
if "form_iteration" not in st.session_state: st.session_state.form_iteration = 0
if "chat_history" not in st.session_state: st.session_state.chat_history = []

def reset_form():
    st.session_state.form_iteration += 1
    st.session_state.chat_history = []

# --- 4. ממשק המשתמש ---
st.title("🎓 יומן תצפית מחקרי חכם")

tab1, tab2, tab3 = st.tabs(["📝 תצפית ושיחה", "📊 ניהול נתונים", "🤖 סיכום מגמות"])
svc = get_drive_service()

with tab1:
    col_in, col_chat = st.columns([1.3, 1])
    with col_in:
        with st.container(border=True):
            st.subheader("1. פרטי התצפית")
            name_sel = st.selectbox("👤 בחר תלמיד", CLASS_ROSTER, key=f"name_{st.session_state.form_iteration}")
            student_name = st.text_input("שם חופשי:", key=f"free_name_{st.session_state.form_iteration}") if name_sel == "תלמיד אחר..." else name_sel
            
            c1, c2 = st.columns(2)
            with c1: difficulty = st.select_slider("רמת קושי המטלה", options=[1, 2, 3], value=2, key=f"diff_{st.session_state.form_iteration}")
            with c2: model_status = st.radio("סטטוס מודל פיזי:", ["ללא מודל", "מודל חלקי", "מודל מלא"], horizontal=True, key=f"mod_stat_{st.session_state.form_iteration}")
            
            st.divider()
            st.subheader("2. מדדים (1 משמאל, 5 מימין)")
            m1, m2 = st.columns(2)
            with m1:
                score_spatial = st.slider("יכולת תפיסה מרחבית", 1, 5, 3, key=f"s1_{st.session_state.form_iteration}")
                score_views = st.slider("מעבר בין היטלים", 1, 5, 3, key=f"s2_{st.session_state.form_iteration}")
            with m2:
                score_model = st.slider("שימוש יעיל במודל", 1, 5, 3, key=f"s3_{st.session_state.form_iteration}")
                score_efficacy = st.slider("מסוגלות עצמית", 1, 5, 3, key=f"s4_{st.session_state.form_iteration}")

            st.divider()
            st.subheader("3. קבצים ותיעוד")
            uploaded_files = st.file_uploader("העלה צילום/וידאו", accept_multiple_files=True, key=f"files_{st.session_state.form_iteration}")
            tags = st.multiselect("🏷️ תגיות", OBSERVATION_TAGS, key=f"tags_{st.session_state.form_iteration}")
            challenge = st.text_area("🗣️ ציטוטים וקשיים", key=f"chal_{st.session_state.form_iteration}")
            done = st.text_area("👀 פעולות שבוצעו", key=f"done_{st.session_state.form_iteration}")
            interpretation = st.text_area("💡 פרשנות", key=f"interp_{st.session_state.form_iteration}")
            
            if st.button("💾 שמור תצפית ואפס טופס"):
                file_links = []
                if uploaded_files and svc:
                    for f in uploaded_files:
                        link = upload_file_to_drive(f, svc)
                        file_links.append(link)
                
                entry = {
                    "type": "reflection", "date": date.today().isoformat(), "student_name": student_name,
                    "difficulty": difficulty, "model_status": model_status, 
                    "score_spatial": score_spatial, "score_views": score_views,
                    "score_model": score_model, "score_efficacy": score_efficacy,
                    "challenge": challenge, "done": done, "interpretation": interpretation, 
                    "tags": ", ".join(tags), "timestamp": datetime.now().strftime("%H:%M:%S"),
                    "file_links": ", ".join(file_links)
                }
                with open(DATA_FILE, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                if svc: update_master_excel([entry], svc)
                st.success(f"התצפית נשמרה. הטופס התאפס.")
                reset_form()
                st.rerun()

    with col_chat:
        st.subheader("🤖 עוזר מחקר אקדמי")
        chat_cont = st.container(height=550)
        with chat_cont:
            for q, a in st.session_state.chat_history:
                st.markdown(f"**🧐 חוקר:** {q}")
                st.info(f"**🤖 AI:** {a}")
        
        u_input = st.chat_input("שאל על התצפית הנוכחית...")
        if u_input:
            curr_data = {"name": student_name, "model_status": model_status, "challenge": challenge, "score_spatial": score_spatial, "score_views": score_views, "score_efficacy": score_efficacy, "done": done, "interpretation": interpretation}
            ans = chat_with_academic_ai(u_input, curr_data, st.session_state.chat_history)
            st.session_state.chat_history.append((u_input, ans))
            st.rerun()

with tab2:
    st.header("📊 ניהול נתונים")
    if st.button("🔄 סנכרון מלא לדרייב"):
        if os.path.exists(DATA_FILE) and svc:
            all_d = [json.loads(l) for l in open(DATA_FILE, "r", encoding="utf-8")]
            update_master_excel(all_d, svc)
            st.success("סונכרן!")

with tab3:
    st.header("🤖 סיכום מגמות אקדמי")
    st.write("ה-AI ינתח את 10 התצפיות האחרונות ויזהה תובנות למחקר.")
    
    if st.button("✨ בצע ניתוח מגמות (מקורות 2014-2026)"):
        if os.path.exists(DATA_FILE):
            all_observations = [json.loads(l) for l in open(DATA_FILE, "r", encoding="utf-8")]
            last_10 = all_observations[-10:]
            if last_10:
                with st.spinner("מנתח נתונים ומצליב מקורות..."):
                    context_text = "\n".join([f"תלמיד: {o['student_name']}, קושי: {o['challenge']}, מדד תפיסה: {o['score_spatial']}, מודל: {o['model_status']}" for o in last_10])
                    client = genai.Client(api_key=st.secrets["GOOGLE_API_KEY"])
                    prompt = f"נתח את המגמות בתצפיות הבאות. השתמש במקורות אקדמיים משנת 2014-2026 בלבד. התייחס לקשר בין שימוש במודלים לתפיסה מרחבית ומסוגלות עצמית:\n{context_text}"
                    res = client.models.generate_content(model="gemini-2.0-flash", contents=prompt)
                    st.session_state.current_summary = res.text
            else: st.warning("אין מספיק תצפיות לסיכום.")

    if "current_summary" in st.session_state:
        st.markdown("---")
        st.markdown(st.session_state.current_summary)
        if st.button("💾 שמור סיכום זה כקובץ TXT בדרייב"):
            if svc:
                summary_bytes = st.session_state.current_summary.encode('utf-8')
                # יצירת אובייקט דמוי קובץ להעלאה
                class MockFile:
                    def __init__(self, content): self.content = content; self.name = f"Summary_{datetime.now().strftime('%Y-%m-%d_%H-%M')}.txt"; self.type = "text/plain"
                    def getvalue(self): return self.content
                
                link = upload_file_to_drive(MockFile(summary_bytes), svc)
                st.success(f"הסיכום נשמר בדרייב! קישור: {link}")

# --- סוף קוד ---