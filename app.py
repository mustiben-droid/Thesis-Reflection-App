import json
import base64
import os
import io
import time
import pandas as pd
import streamlit as st
import google.generativeai as genai
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload
from datetime import date, datetime

# --- 0. הגדרות ועיצוב ---
DATA_FILE = "reflections.jsonl"
MASTER_FILENAME = "All_Observations_Master.xlsx"
GDRIVE_FOLDER_ID = st.secrets.get("GDRIVE_FOLDER_ID")
CLASS_ROSTER = ["נתנאל", "רועי", "אסף", "עילאי", "טדי", "גאל", "אופק", "דניאל.ר", "אלי", "טיגרן", "פולינה.ק", "תלמיד אחר..."]

st.set_page_config(page_title="מערכת תצפית - 57.0", layout="wide")

st.markdown("""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Heebo:wght@300;400;700&display=swap');
        html, body, .stApp { direction: rtl; text-align: right; font-family: 'Heebo', sans-serif !important; }
        [data-testid="stSlider"] { direction: ltr !important; }
        .stButton > button { width: 100%; font-weight: bold; border-radius: 12px; background-color: #28a745; color: white; height: 3em; }
    </style>
""", unsafe_allow_html=True)

# --- 1. פונקציות עזר לניקוי נתונים (מניעת InvalidIndexError) ---
def safe_clean_df(df):
    if df is None or df.empty:
        return pd.DataFrame()
    # הסרת עמודות כפולות (הגורם המרכזי לקריסה)
    df = df.loc[:, ~df.columns.duplicated()].copy()
    # איפוס אינדקס למניעת התנגשויות
    df = df.reset_index(drop=True)
    return df

@st.cache_resource
def get_drive_service():
    try:
        b64 = st.secrets.get("GDRIVE_SERVICE_ACCOUNT_B64")
        if not b64: return None
        json_str = base64.b64decode(b64).decode("utf-8")
        creds = Credentials.from_service_account_info(json.loads(json_str), scopes=["https://www.googleapis.com/auth/drive"])
        return build("drive", "v3", credentials=creds)
    except: return None

def load_full_dataset(svc):
    df_drive = pd.DataFrame()
    if svc:
        try:
            res = svc.files().list(q=f"name = '{MASTER_FILENAME}' and trashed = false", 
                                 supportsAllDrives=True, includeItemsFromAllDrives=True).execute().get('files', [])
            if res:
                fh = io.BytesIO()
                downloader = MediaIoBaseDownload(fh, svc.files().get_media(fileId=res[0]['id']))
                done = False
                while not done: _, done = downloader.next_chunk()
                fh.seek(0)
                df_drive = pd.read_excel(fh)
                df_drive = safe_clean_df(df_drive)
                # מיפוי עמודות
                mapping = {'score_conv': 'cat_convert_rep', 'score_proj': 'cat_proj_trans', 'score_model': 'cat_3d_support', 'score_efficacy': 'cat_self_efficacy'}
                df_drive = df_drive.rename(columns=mapping)
        except: pass

    df_local = pd.DataFrame()
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                lines = [json.loads(l) for l in f if l.strip()]
                if lines:
                    df_local = pd.DataFrame(lines)
                    df_local = safe_clean_df(df_local)
        except: pass

    # איחוד הנתונים - כאן קרתה השגיאה, כעת עם הגנה
    if df_drive.empty and df_local.empty: return pd.DataFrame()
    if df_drive.empty: return df_local
    if df_local.empty: return df_drive

    try:
        combined = pd.concat([df_drive, df_local], axis=0, ignore_index=True, sort=False)
        return safe_clean_df(combined)
    except Exception as e:
        st.error(f"שגיאת איחוד נתונים: {e}")
        return df_drive

# --- 2. מנגנון AI (מהיר וחסין) ---
def get_ai_response(prompt_type, context):
    api_key = st.secrets.get("GOOGLE_API_KEY")
    if not api_key: return "⚠️ מפתח API חסר"
    genai.configure(api_key=api_key, transport='rest')
    model = genai.GenerativeModel('gemini-1.5-flash')
    try:
        prompt = f"נתח את {context.get('name')}:\n{str(context.get('history'))[:3000]}\nשאלה: {context.get('question')}"
        return model.generate_content(prompt).text
    except: return "ה-AI עמוס כרגע."

# --- 3. ממשק משתמש ---
if "it" not in st.session_state: st.session_state.it = 0
if "chat_history" not in st.session_state: st.session_state.chat_history = []
if "daily_analysis" not in st.session_state: st.session_state.daily_analysis = ""

svc = get_drive_service()
full_df = load_full_dataset(svc)

tab1, tab2, tab3 = st.tabs(["📝 הזנה", "🔄 סנכרון", "📊 ניתוח"])

with tab1:
    col_in, col_chat = st.columns([1.2, 1])
    with col_in:
        it = st.session_state.it
        name = st.selectbox("👤 בחר סטודנט", CLASS_ROSTER, key=f"sel_{it}")
        c1, c2 = st.columns(2)
        with c1:
            method = st.radio("🛠️ תרגול:", ["🧊 גוף מודפס", "🎨 דמיון"], key=f"wm_{it}")
            s1 = st.slider("המרה", 1, 5, 3, key=f"s1_{it}")
        with c2:
            s2 = st.slider("היטלים", 1, 5, 3, key=f"s2_{it}")
            s4 = st.slider("מסוגלות", 1, 5, 3, key=f"s4_{it}")
        
        challenge = st.text_area("🗣️ תיאור התצפית", key=f"ch_{it}")
        if st.button("💾 שמור תצפית"):
            if challenge:
                entry = {"date": date.today().isoformat(), "student_name": name, "challenge": challenge, "cat_convert_rep": s1, "cat_proj_trans": s2, "cat_self_efficacy": s4, "timestamp": datetime.now().isoformat()}
                with open(DATA_FILE, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                st.success("נשמר!"); time.sleep(0.5); st.session_state.it += 1; st.rerun()

    with col_chat:
        st.subheader(f"🤖 צ'אט: {name}")
        chat_cont = st.container(height=350)
        for q, a in st.session_state.chat_history:
            with chat_cont: st.chat_message("user").write(q); st.chat_message("assistant").write(a)
        u_q = st.chat_input("שאל על הסטודנט...")
        if u_q:
            match = full_df[full_df['student_name'] == name] if not full_df.empty else pd.DataFrame()
            ans = get_ai_response("chat", {"name": name, "history": match.tail(10).to_string(), "question": u_q})
            st.session_state.chat_history.append((u_q, ans)); st.rerun()

with tab2:
    if st.button("🚀 סנכרן לדרייב"):
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, "r", encoding="utf-8") as f: locals_ = [json.loads(l) for l in f if l.strip()]
                df_merged = pd.concat([full_df, pd.DataFrame(locals_)], ignore_index=True).drop_duplicates(subset=['student_name', 'timestamp'], keep='last')
                buf = io.BytesIO()
                with pd.ExcelWriter(buf, engine='openpyxl') as w: df_merged.to_excel(w, index=False)
                buf.seek(0)
                query = f"name = '{MASTER_FILENAME}' and trashed = false"
                res = svc.files().list(q=query, supportsAllDrives=True).execute().get('files', [])
                media = MediaIoBaseUpload(buf, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                if res: svc.files().update(fileId=res[0]['id'], media_body=media, supportsAllDrives=True).execute()
                else: svc.files().create(body={'name': MASTER_FILENAME, 'parents': [GDRIVE_FOLDER_ID] if GDRIVE_FOLDER_ID else []}, media_body=media, supportsAllDrives=True).execute()
                os.remove(DATA_FILE); st.success("סונכרן!"); time.sleep(1); st.rerun()
            except Exception as e: st.error(f"שגיאה: {e}")

with tab3:
    st.header("📊 ניתוח ומגמות")
    if not full_df.empty:
        sel_student = st.selectbox("נתח סטודנט", full_df['student_name'].unique())
        sd = full_df[full_df['student_name'] == sel_student].sort_values('timestamp')
        st.line_chart(sd.set_index('date')[['cat_convert_rep', 'cat_proj_trans']])
        
        if st.button("✨ הפק תובנות AI"):
            with st.spinner("מנתח..."):
                analysis = get_ai_response("chat", {"name": sel_student, "history": sd.to_string(), "question": "סכם מגמות עיקריות"})
                st.info(analysis)
                st.download_button("📥 הורד ניתוח", analysis, file_name=f"Analysis_{sel_student}.txt")
