import streamlit as st
import pandas as pd
import json
import base64
import os
import io
import time
import requests
from datetime import date, datetime
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload
from streamlit_mic_recorder import mic_recorder

# וודא שהקובץ ai_engine.py קיים באותה תיקייה
try:
    from ai_engine import render_ai_agent_tab
except ImportError:
    def render_ai_agent_tab(df):
        st.error("קובץ ai_engine.py לא נמצא")

# ==========================================
# --- 0. הגדרות מערכת ועיצוב ---
# ==========================================
DATA_FILE = "reflections.jsonl"
MASTER_FILENAME = "All_Observations_Master.xlsx"
GDRIVE_FOLDER_ID = st.secrets.get("GDRIVE_FOLDER_ID")
INTERVIEW_FOLDER_ID = "1NQz2UZ6BfAURfN4a8h4_qSkyY-_gxhxP"

CLASS_ROSTER = ["נתנאל", "רועי", "אסף", "עילאי", "טדי", "גאל", "אופק", "דניאל.ר", "אלי", "טיגרן", "פולינה.ק", "תלמיד אחר..."]
TAGS_OPTIONS = ["התעלמות מקווים נסתרים", "בלבול בין היטלים", "קושי ברוטציה מנטלית", "טעות בפרופורציות", "קושי במעבר בין היטלים", "שימוש בכלי מדידה", "סיבוב פיזי של המודל", "תיקון עצמי", "עבודה עצמאית שוטפת"]

st.set_page_config(page_title="מערכת תצפית מחקרית - 54.0", layout="wide")

# עיצוב CSS
st.markdown("""
    <style>
        direction: rtl;
        text-align: right;
        [data-testid="stSlider"] { direction: ltr !important; }
        .feedback-box { background-color: #f8f9fa; padding: 20px; border-radius: 15px; border: 1px solid #dee2e6; color: #333; }
    </style>
""", unsafe_allow_html=True)

# ==========================================
# --- 1. פונקציות עזר ---
# ==========================================

def normalize_name(name):
    if not isinstance(name, str): return ""
    import re
    name = name.replace(" ", "")
    return re.sub(r'[^א-תa-zA-Z0-9]', '', name).strip()

@st.cache_resource
def get_drive_service():
    try:
        b64 = st.secrets.get("GDRIVE_SERVICE_ACCOUNT_B64")
        if not b64: return None
        js = base64.b64decode("".join(b64.split())).decode("utf-8")
        creds = Credentials.from_service_account_info(json.loads(js), scopes=["https://www.googleapis.com/auth/drive"])
        return build("drive", "v3", credentials=creds)
    except: return None

@st.cache_data(ttl=300)
def load_full_dataset(_svc):
    df_drive = pd.DataFrame()
    file_id = st.secrets.get("MASTER_FILE_ID")
    if _svc and file_id:
        try:
            req = _svc.files().get_media(fileId=file_id)
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, req)
            done = False
            while not done:
                _, done = downloader.next_chunk()
            fh.seek(0)
            df_drive = pd.read_excel(fh)
        except Exception as e:
            st.error(f"שגיאה בטעינת דרייב: {e}")

    df_local = pd.DataFrame()
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                df_local = pd.DataFrame([json.loads(l) for l in f if l.strip()])
        except: pass

    df = pd.concat([df_drive, df_local], ignore_index=True)
    if not df.empty:
        df = df.drop_duplicates(subset=['student_name', 'timestamp'], keep='last')
        if 'student_name' in df.columns:
            df['name_clean'] = df['student_name'].apply(normalize_name)
    return df

def call_gemini(prompt, audio_bytes=None):
    try:
        api_key = st.secrets.get("GOOGLE_API_KEY")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
        if audio_bytes:
            audio_base64 = base64.b64encode(audio_bytes).decode('utf-8')
            payload = {"contents": [{"parts": [{"text": prompt}, {"inlineData": {"mimeType": "audio/wav", "data": audio_base64}}]}]}
        else:
            payload = {"contents": [{"parts": [{"text": prompt}]}]}
        res = requests.post(url, json=payload, timeout=90)
        return res.json()['candidates'][0]['content']['parts'][0]['text']
    except Exception as e:
        return f"שגיאת AI: {str(e)}"

def drive_upload_bytes(svc, content, filename, folder_id, is_text=False):
    try:
        mime = 'text/plain' if is_text else 'audio/wav'
        if is_text and isinstance(content, str): content = content.encode('utf-8')
        media = MediaIoBaseUpload(io.BytesIO(content), mimetype=mime, resumable=True)
        file_metadata = {'name': filename, 'parents': [folder_id]}
        f = svc.files().create(body=file_metadata, media_body=media, fields='id, webViewLink', supportsAllDrives=True).execute()
        return f.get('webViewLink')
    except Exception as e:
        st.error(f"שגיאת העלאה: {e}")
        return None

def drive_upload_file(svc, file_obj, folder_id):
    try:
        file_content = file_obj.read()
        media = MediaIoBaseUpload(io.BytesIO(file_content), mimetype=file_obj.type, resumable=True)
        file_metadata = {'name': file_obj.name, 'parents': [folder_id]}
        result = svc.files().create(body=file_metadata, media_body=media, fields='id, webViewLink', supportsAllDrives=True).execute()
        return result.get('webViewLink', '')
    except: return ""

def get_student_summary(student_name, full_df):
    if full_df.empty: return "אין נתונים."
    target = normalize_name(student_name)
    student_df = full_df[full_df['name_clean'] == target]
    if student_df.empty: return "תלמיד חדש."
    return f"נמצאו {len(student_df)} תצפיות קודמות."

# ==========================================
# --- 2. ממשקי הטאבים ---
# ==========================================

def render_tab_entry(svc, full_df):
    it = st.session_state.it
    student_name = st.selectbox("👤 בחר סטודנט", CLASS_ROSTER, key=f"sel_{it}")
    
    if student_name != st.session_state.last_selected_student:
        st.session_state.last_selected_student = student_name
        st.rerun()

    col_in, col_chat = st.columns([1.2, 1])
    with col_in:
        c1, c2 = st.columns(2)
        duration = c1.number_input("⏱️ דקות", 0, 200, 45, key=f"d_{it}")
        drawings = c2.number_input("📋 שרטוטים", 0, 10, 1, key=f"dr_{it}")
        
        score_proj = st.slider("📐 המרת ייצוגים", 1, 5, 3, key=f"s1_{it}")
        score_efficacy = st.slider("💪 מסוגלות עצמית", 1, 5, 3, key=f"s6_{it}")
        
        tags = st.multiselect("🏷️ תגיות", TAGS_OPTIONS, key=f"t_{it}")
        field_obs = st.text_area("🗣️ תצפית שדה", key=f"obs_{it}")
        insight = st.text_area("🧠 תובנה", key=f"ins_{it}")
        up_files = st.file_uploader("📷 תמונות", accept_multiple_files=True, key=f"up_{it}")

        if st.button("💾 שמור תצפית", type="primary"):
            if student_name == "תלמיד אחר...":
                st.error("בחר שם תלמיד")
            else:
                with st.spinner("שומר..."):
                    entry = {
                        "student_name": student_name,
                        "timestamp": datetime.now().isoformat(),
                        "duration_min": duration,
                        "score_proj": score_proj,
                        "score_efficacy": score_efficacy,
                        "challenge": field_obs,
                        "insight": insight,
                        "date": date.today().isoformat()
                    }
                    with open(DATA_FILE, "a", encoding="utf-8") as f:
                        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                    st.balloons()
                    st.session_state.it += 1
                    st.rerun()

    with col_chat:
        st.subheader(f"🤖 צ'אט: {student_name}")
        u_q = st.chat_input("שאל על התלמיד...")
        if u_q:
            st.write(f"המשתמש: {u_q}")
            st.write("יועץ: בדוק את נתוני האקסל...")

def render_tab_sync(svc, full_df):
    st.header("🔄 סנכרון")
    if st.button("סנכרן לדרייב"):
        st.info("מתבצע סנכרון...")

def render_tab_analysis(svc, full_df):
    st.header("📊 ניתוח נתונים")
    if not full_df.empty:
        st.line_chart(full_df.set_index('timestamp')[['score_proj']])

def render_tab_interview(svc, full_df):
    st.subheader("🎙️ ראיון עומק")
    student_name = st.selectbox("בחר תלמיד לראיון", CLASS_ROSTER)
    audio = mic_recorder(start_prompt="הקלט", stop_prompt="עצור")
    if audio:
        st.audio(audio['bytes'])
        if st.button("נתח ראיון"):
            res = call_gemini("נתח את האודיו הזה", audio['bytes'])
            st.write(res)

# ==========================================
# --- 3. ריצה ראשית ---
# ==========================================

svc = get_drive_service()
full_df = load_full_dataset(svc)

if "it" not in st.session_state: st.session_state.it = 0
if "last_selected_student" not in st.session_state: st.session_state.last_selected_student = ""

tab1, tab2, tab3, tab4, tab5 = st.tabs(["📝 הזנה", "🔄 סנכרון", "📊 ניתוח", "🎙️ ראיון", "🤖 סוכן"])

with tab1: render_tab_entry(svc, full_df)
with tab2: render_tab_sync(svc, full_df)
with tab3: render_tab_analysis(svc, full_df)
with tab4: render_tab_interview(svc, full_df)
with tab5: render_ai_agent_tab(full_df)

st.sidebar.write(f"חיבור דרייב: {'✅' if svc else '❌'}")
