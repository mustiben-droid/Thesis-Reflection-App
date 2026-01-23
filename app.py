import json
import base64
import os
import io
import logging
from datetime import date, datetime
import pandas as pd
import streamlit as st
import google.generativeai as genai
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload

# --- הגדרות לוגים ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- הגדרות קבועות ---
DATA_FILE = "reflections.jsonl"
MASTER_FILENAME = "All_Observations_Master.xlsx"
GDRIVE_FOLDER_ID = st.secrets.get("GDRIVE_FOLDER_ID")
CLASS_ROSTER = ["נתנאל", "רועי", "אסף", "עילאי", "טדי", "גאל", "אופק", "דניאל.ר", "אלי", "טיגרן", "פולינה.ק", "תלמיד אחר..."]
TAGS_OPTIONS = ["התעלמות מקווים נסתרים", "בלבול בין היטלים", "קושי ברוטציה מנטלית", "טעות בפרופורציות", "קושי במעבר בין היטלים", "שימוש בכלי מדידה", "סיבוב פיזי של המודל", "תיקון עצמי", "עבודה עצמאית שוטפת"]

st.set_page_config(page_title="מערכת תצפית - גרסה 34.2", layout="wide")

# --- RTL Styling ---
st.markdown("""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Heebo:wght@300;400;700&display=swap');
        html, body, .stApp { direction: rtl; text-align: right; font-family: 'Heebo', sans-serif !important; }
        .stTextInput input, .stTextArea textarea, .stSelectbox > div > div { direction: rtl; text-align: right; }
        [data-testid="stSlider"] { direction: ltr !important; }
        .stButton > button { width: 100%; font-weight: bold; border-radius: 12px; height: 3em; background-color: #28a745; color: white; }
        .feedback-box { background-color: #fff3cd; color: #856404; padding: 15px; border-radius: 10px; border: 1px solid #ffeeba; margin-bottom: 20px; font-size: 0.95em; }
    </style>
""", unsafe_allow_html=True)

# --- פונקציות תשתית ו-Google Drive ---

@st.cache_resource
def get_drive_service():
    try:
        b64 = st.secrets.get("GDRIVE_SERVICE_ACCOUNT_B64")
        if not b64: return None
        json_str = base64.b64decode(b64).decode("utf-8")
        creds = Credentials.from_service_account_info(json.loads(json_str), scopes=["https://www.googleapis.com/auth/drive"])
        return build("drive", "v3", credentials=creds)
    except Exception:
        logger.exception("Drive Service Error")
        return None

def upload_file_to_drive(uploaded_file, svc):
    try:
        if not svc or uploaded_file is None: return None
        file_metadata = {'name': uploaded_file.name, 'parents': [GDRIVE_FOLDER_ID] if GDRIVE_FOLDER_ID else []}
        media = MediaIoBaseUpload(io.BytesIO(uploaded_file.getvalue()), mimetype=uploaded_file.type)
        file = svc.files().create(body=file_metadata, media_body=media, fields='id, webViewLink', supportsAllDrives=True).execute()
        return file.get('webViewLink')
    except Exception:
        logger.exception("Upload Error")
        return None

@st.cache_data(ttl=300)
def load_master_from_drive(svc_id):
    svc = get_drive_service()
    try:
        query = f"name = '{MASTER_FILENAME}' and trashed = false"
        res = svc.files().list(q=query, spaces='drive', supportsAllDrives=True).execute().get('files', [])
        target = next((f for f in res if f['name'] == MASTER_FILENAME), None)
        if not target: return None, None
        request = svc.files().get_media(fileId=target['id'])
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done: _, done = downloader.next_chunk()
        fh.seek(0)
        return pd.read_excel(fh), target['id']
    except Exception:
        return None, None

def update_master_in_drive(new_data_df, svc):
    try:
        existing_df, file_id = load_master_from_drive(id(svc))
        df = pd.concat([existing_df, new_data_df], ignore_index=True).drop_duplicates(subset=['student_name', 'timestamp'], keep='last') if existing_df is not None else new_data_df
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False)
        output.seek(0)
        media = MediaIoBaseUpload(output, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        if file_id: svc.files().update(fileId=file_id, media_body=media, supportsAllDrives=True).execute()
        else:
            meta = {'name': MASTER_FILENAME, 'parents': [GDRIVE_FOLDER_ID] if GDRIVE_FOLDER_ID else []}
            svc.files().create(body=meta, media_body=media, supportsAllDrives=True).execute()
        st.cache_data.clear()
        return True
    except Exception:
        logger.exception("Sync Error")
        return False

# --- מנוע ה-AI ---

def get_ai_response(prompt_type, context_data):
    api_key = st.secrets.get("GOOGLE_API_KEY")
    if not api_key: return "שגיאה: חסר מפתח API ב-Secrets."
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-1.5-flash')
        prompts = {
            "feedback": f"אתה מנחה תזה. בצע ביקורת על תצפית: {context_data['challenge']}. תן 2 שורות משוב בונה.",
            "chat": f"עוזר מחקר. היסטוריה של {context_data['name']}: {context_data['history']}. שאלה: {context_data['question']}",
            "analysis": f"נתח מאקרו (סטטיסטיקה): {context_data['stats']} ומיקרו (לפי תלמיד): {context_data['raw']}. בנה פרופילים."
        }
        res = model.generate_content(prompts[prompt_type])
        return res.text
    except Exception as e:
        return f"שגיאה בתקשורת עם ה-AI: {str(e)[:50]}..."

# --- ממשק המשתמש ---

if "it" not in st.session_state: st.session_state.it = 0
if "chat_history" not in st.session_state: st.session_state.chat_history = []
if "student_context" not in st.session_state: st.session_state.student_context = ""
if "last_obs_feedback" not in st.session_state: st.session_state.last_obs_feedback = ""
if "last_selected_student" not in st.session_state: st.session_state.last_selected_student = ""

svc = get_drive_service()
st.title("🎓 מנחה מחקר חכם - 34.2")
tab1, tab2, tab3 = st.tabs(["📝 הזנה ומשוב", "🔄 סנכרון", "🤖 ניתוח מגמות"])

with tab1:
    col_in, col_chat = st.columns([1.2, 1])
    with col_in:
        with st.container(border=True):
            it = st.session_state.it
            c1, c2 = st.columns(2)
            with c1:
                name_sel = st.selectbox("👤 בחר סטודנט", CLASS_ROSTER, key=f"n_{it}")
                student_name = st.text_input("שם חופשי:", key=f"fn_{it}") if name_sel == "תלמיד אחר..." else name_sel
                
                # מנגנון טעינה וסטריפ ירוק
                if student_name != st.session_state.last_selected_student:
                    st.session_state.chat_history = []
                    with st.spinner("טוען היסטוריה..."):
                        df_hist, _ = load_master_from_drive(id(svc))
                        if df_hist is not None:
                            # חיפוש מדויק (Exact Match)
                            student_data = df_hist[df_hist['student_name'].astype(str).str.strip() == student_name.strip()]
                            if not student_data.empty:
                                st.session_state.student_context = student_data.tail(5).to_string()
                                st.success(f"✅ נתוני {student_name} נטענו.")
                            else:
                                st.session_state.student_context = ""
                                st.info(f"🔍 תצפית ראשונה עבור {student_name}.")
                    st.session_state.last_selected_student = student_name

            with c2:
                work_method = st.radio("🛠️ סוג תרגול:", ["🧊 בעזרת גוף מודפס", "🎨 ללא גוף (דמיון)"], key=f"wm_{it}", horizontal=True)
                exercise_diff = st.select_slider("📉 רמת קושי:", options=["קל", "בינוני", "קשה"], value="בינוני", key=f"ed_{it}")

            q1, q2 = st.columns(2)
            with q1: drawings_count = st.number_input("שרטוטים", min_value=0, key=f"dc_{it}")
            with q2: duration_min = st.number_input("דקות", min_value=0, key=f"dm_{it}")

            tags = st.multiselect("🏷️ תגיות אבחון", TAGS_OPTIONS, key=f"t_{it}")
            challenge = st.text_area("🗣️ תיאור", key=f"ch_{it}")
            interpretation = st.text_area("🧠 פרשנות", key=f"int_{it}")
            uploaded_files = st.file_uploader("📷 תמונות", accept_multiple_files=True, type=['png', 'jpg'], key=f"up_{it}")

            if st.session_state.last_obs_feedback:
                st.markdown(f'<div class="feedback-box"><b>💡 משוב AI:</b><br>{st.session_state.last_obs_feedback}</div>', unsafe_allow_html=True)

            if st.button("💾 שמור תצפית"):
                if not challenge: st.error("חובה למלא תיאור.")
                else:
                    ts = datetime.now().isoformat()
                    links = [upload_file_to_drive(f, svc) for f in uploaded_files] if uploaded_files and svc else []
                    entry = {
                        "date": date.today().isoformat(), "student_name": student_name, "work_method": work_method,
                        "exercise_difficulty": exercise_diff, "drawings_count": int(drawings_count), "duration_min": int(duration_min),
                        "challenge": challenge, "interpretation": interpretation, "tags": tags, "file_links": [l for l in links if l], "timestamp": ts,
                        "cat_convert_rep": 3, "cat_proj_trans": 3, "cat_self_efficacy": 3
                    }
                    with open(DATA_FILE, "a", encoding="utf-8") as f:
                        f.write(json.dumps(entry, ensure_ascii=False) + "\n"); f.flush(); os.fsync(f.fileno())
                    
                    st.session_state.last_obs_feedback = get_ai_response("feedback", {"challenge": challenge})
                    st.rerun()

            if st.button("✅ סיימת? נקה"):
                st.session_state.last_obs_feedback = ""; st.session_state.it += 1; st.rerun()

    with col_chat:
        st.subheader(f"🤖 יועץ: {student_name}")
        chat_cont = st.container(height=400)
        for q, a in st.session_state.chat_history:
            with chat_cont: st.chat_message("user").write(q); st.chat_message("assistant").write(a)
        user_q = st.chat_input("שאל...")
        if user_q:
            resp = get_ai_response("chat", {"name": student_name, "history": st.session_state.student_context, "question": user_q})
            st.session_state.chat_history.append((user_q, resp)); st.rerun()

with tab2:
    if os.path.exists(DATA_FILE):
        if st.button("🚀 סנכרן לדרייב"):
            with open(DATA_FILE, "r", encoding="utf-8") as fh: all_entries = [json.loads(l) for l in fh if l.strip()]
            if update_master_in_drive(pd.DataFrame(all_entries), svc): st.success("סונכרן!")
