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

# ניסיון ייבוא של הסוכן החכם - אם הקובץ חסר, האפליקציה לא תקרוס
try:
    from ai_engine import render_ai_agent_tab
except ImportError:
    def render_ai_agent_tab(df):
        st.warning("⚠️ קובץ ai_engine.py לא נמצא. הטאב הזה מושבת.")

# ==========================================
# --- 0. הגדרות מערכת ועיצוב ---
# ==========================================
DATA_FILE = "reflections.jsonl"
MASTER_FILENAME = "All_Observations_Master.xlsx"

# משיכת מזהי תיקיות מה-Secrets
GDRIVE_FOLDER_ID = st.secrets.get("GDRIVE_FOLDER_ID", "")
INTERVIEW_FOLDER_ID = "1NQz2UZ6BfAURfN4a8h4_qSkyY-_gxhxP"
MASTER_FILE_ID = st.secrets.get("MASTER_FILE_ID", "")

CLASS_ROSTER = ["נתנאל", "רועי", "אסף", "עילאי", "טדי", "גאל", "אופק", "דניאל.ר", "אלי", "טיגרן", "פולינה.ק", "תלמיד אחר..."]
TAGS_OPTIONS = ["התעלמות מקווים נסתרים", "בלבול בין היטלים", "קושי ברוטציה מנטלית", "טעות בפרופורציות", "קושי במעבר בין היטלים", "שימוש בכלי מדידה", "סיבוב פיזי של המודל", "תיקון עצמי", "עבודה עצמאית שוטפת"]

st.set_page_config(page_title="מערכת תצפית מחקרית - 54.0", layout="wide")

st.markdown("""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Heebo:wght@300;400;700&display=swap');
        html, body, .stApp { direction: rtl; text-align: right; font-family: 'Heebo', sans-serif !important; }
        [data-testid="stSlider"] { direction: ltr !important; }
        .stButton > button { width: 100%; border-radius: 12px; font-weight: bold; }
        .feedback-box { background-color: #f8f9fa; padding: 15px; border-radius: 12px; border: 1px solid #dee2e6; color: #333; }
    </style>
""", unsafe_allow_html=True)

# ==========================================
# --- 1. פונקציות לוגיקה ---
# ==========================================

def normalize_name(name):
    if not isinstance(name, str): return ""
    import re
    return re.sub(r'[^א-תa-zA-Z0-9]', '', name.replace(" ", "")).strip()

@st.cache_resource
def get_drive_service():
    try:
        b64 = st.secrets.get("GDRIVE_SERVICE_ACCOUNT_B64")
        if not b64: return None
        js = base64.b64decode("".join(b64.split())).decode("utf-8")
        creds = Credentials.from_service_account_info(json.loads(js), scopes=["https://www.googleapis.com/auth/drive"])
        return build("drive", "v3", credentials=creds)
    except Exception:
        return None

@st.cache_data(ttl=300)
def load_full_dataset(_svc):
    df_drive = pd.DataFrame()
    if _svc and MASTER_FILE_ID:
        try:
            req = _svc.files().get_media(fileId=MASTER_FILE_ID)
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, req)
            done = False
            while not done:
                _, done = downloader.next_chunk()
            fh.seek(0)
            df_drive = pd.read_excel(fh)
        except Exception: pass

    df_local = pd.DataFrame()
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                df_local = pd.DataFrame([json.loads(l) for l in f if l.strip()])
        except Exception: pass

    df = pd.concat([df_drive, df_local], ignore_index=True)
    if not df.empty:
        df = df.drop_duplicates(subset=['student_name', 'timestamp'], keep='last')
        if 'student_name' in df.columns:
            df['name_clean'] = df['student_name'].astype(str).apply(normalize_name)
    return df

def call_gemini(prompt, audio_bytes=None):
    try:
        api_key = st.secrets.get("GOOGLE_API_KEY")
        if not api_key: return "שגיאה: חסר API Key ב-Secrets"
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
        
        if audio_bytes:
            audio_base64 = base64.b64encode(audio_bytes).decode('utf-8')
            payload = {
                "contents": [{
                    "parts": [
                        {"text": prompt},
                        {"inlineData": {"mimeType": "audio/wav", "data": audio_base64}}
                    ]
                }]
            }
        else:
            payload = {"contents": [{"parts": [{"text": prompt}]}]}

        res = requests.post(url, json=payload, timeout=90)
        return res.json()['candidates'][0]['content']['parts'][0]['text']
    except Exception as e:
        return f"שגיאת AI: {str(e)}"

# ==========================================
# --- 2. ממשק משתמש (Tabs) ---
# ==========================================

def render_tab_entry(svc, full_df):
    it = st.session_state.it
    student_name = st.selectbox("👤 בחר סטודנט", CLASS_ROSTER, key=f"sel_{it}")
    
    # בדיקת היסטוריה מהירה
    target = normalize_name(student_name)
    has_history = not full_df[full_df['name_clean'] == target].empty if not full_df.empty else False
    
    if has_history:
        st.success(f"✅ נמצאה היסטוריה עבור {student_name}")
    else:
        st.info(f"ℹ️ {student_name}: אין תצפיות קודמות")

    col_in, col_chat = st.columns([1.2, 1])
    
    with col_in:
        c1, c2 = st.columns(2)
        duration = c1.number_input("⏱️ זמן עבודה (דקות)", 0, 180, 45, key=f"dur_{it}")
        drawings = c2.number_input("📋 מספר שרטוטים", 0, 20, 1, key=f"drw_{it}")
        
        st.markdown("### 📊 מדדים (1-5)")
        s1, s2 = st.columns(2)
        score_proj = s1.slider("📐 המרת ייצוגים", 1, 5, 3, key=f"s1_{it}")
        score_efficacy = s2.slider("💪 מסוגלות עצמית", 1, 5, 3, key=f"s2_{it}")
        
        tags = st.multiselect("🏷️ תגיות", TAGS_OPTIONS, key=f"t_{it}")
        obs = st.text_area("🗣️ תצפית (Challenge)", key=f"obs_{it}")
        ins = st.text_area("🧠 תובנה (Insight)", key=f"ins_{it}")
        
        if st.button("💾 שמור תצפית", type="primary"):
            if student_name == "תלמיד אחר...":
                st.error("אנא בחר שם תלמיד תקין")
            else:
                entry = {
                    "student_name": student_name,
                    "date": date.today().isoformat(),
                    "duration_min": duration,
                    "drawings_count": drawings,
                    "score_proj": score_proj,
                    "score_efficacy": score_efficacy,
                    "challenge": obs,
                    "insight": ins,
                    "tags": str(tags),
                    "timestamp": datetime.now().isoformat()
                }
                with open(DATA_FILE, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                st.balloons()
                st.session_state.it += 1
                st.rerun()

    1. איפה להדביק?

חפש בתוך הקובץ הראשי (main.py) את הפונקציה render_tab_entry.
בתוך הפונקציה הזו, חפש את השורה:
with col_chat:

מחק את כל מה שמופיע מתחת ל-with col_chat: (כרגע יש שם כנראה רק כפתור "בקש ניתוח AI") והדבק במקומו את הקוד הבא.

2. הקוד להדבקה:

    with col_chat:
        st.subheader(f"🤖 שיחה חכמה: {student_name}")
        
        # ניהול היסטוריית צ'אט מקומית לטאב התצפית
        if "entry_chat_history" not in st.session_state:
            st.session_state.entry_chat_history = []

        # כפתור ניקוי שיחה
        if st.button("🗑️ נקה שיחה"):
            st.session_state.entry_chat_history = []
            st.rerun()

        # תצוגת ההודעות במיכל גולל
        chat_placeholder = st.container(height=350)
        with chat_placeholder:
            for msg in st.session_state.entry_chat_history:
                with st.chat_message(msg["role"]):
                    st.markdown(msg["content"])

        # קלט מהמשתמש
        if user_msg := st.chat_input("שאל את הבוט על התלמיד או התובנה...", key="entry_bot_input"):
            # הוספת הודעת המשתמש להיסטוריה
            st.session_state.entry_chat_history.append({"role": "user", "content": user_msg})
            
            # יצירת הקשר (Context) לבוט - שואב את הנתונים מהטופס שמעל
            context = f"""
            אתה עוזר מחקר פדגוגי. 
            סטודנט נוכחי: {student_name}
            תובנה נוכחית שכתב המורה: {ins}
            תצפית (אתגרים): {obs}
            מדדים: המרת ייצוגים={score_proj}, מסוגלות={score_efficacy}
            
            השאלה של המורה: {user_msg}
            אנא ענה בעברית מקצועית ומעודדת.
            """
            
            with chat_placeholder:
                with st.chat_message("user"):
                    st.markdown(user_msg)
                
                with st.chat_message("assistant"):
                    with st.spinner("מנתח..."):
                        # קריאה לפונקציה call_gemini הקיימת ב-main.py
                        response = call_gemini(context)
                        st.markdown(response)
                        st.session_state.entry_chat_history.append({"role": "assistant", "content": response})


def render_tab_interview(svc, full_df):
    st.subheader("🎙️ הקלטת ראיון עומק")
    student = st.selectbox("בחר תלמיד לראיון", CLASS_ROSTER, key="int_student")
    audio_data = mic_recorder(start_prompt="התחל הקלטה ⏺️", stop_prompt="עצור ונתח ⏹️")
    
    if audio_data:
        st.audio(audio_data['bytes'])
        if st.button("✨ נתח ראיון"):
            with st.spinner("ג'ימיני מנתח את האודיו..."):
                res = call_gemini(f"תמלל ונתח את הראיון ההנדסי של {student}", audio_data['bytes'])
                st.markdown(f'<div class="feedback-box">{res}</div>', unsafe_allow_html=True)

# ==========================================
# --- 3. Main Runner ---
# ==========================================

# אתחול מצב (Session State)
if "it" not in st.session_state: st.session_state.it = 0

svc = get_drive_service()
full_df = load_full_dataset(svc)

tab1, tab2, tab3, tab4 = st.tabs(["📝 תצפית", "📊 ניתוח", "🎙️ ראיון", "🤖 סוכן"])

with tab1:
    render_tab_entry(svc, full_df)

with tab2:
    st.header("📊 מגמות")
    if not full_df.empty:
        st.dataframe(full_df.tail(10))
    else:
        st.info("אין נתונים להצגה")

with tab3:
    render_tab_interview(svc, full_df)

with tab4:
    render_ai_agent_tab(full_df)

# סיידבר
st.sidebar.title("⚙️ בקרה")
st.sidebar.write(f"חיבור דרייב: {'✅' if svc else '❌'}")
if st.sidebar.button("🔄 רענן הכל"):
    st.cache_data.clear()
    st.rerun()

