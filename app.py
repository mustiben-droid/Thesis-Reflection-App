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
CLASS_ROSTER = ["נתנאל", "רועי", "אסף", "עילאי", "טדי", "גאל", "אופק", "דניאל.ר", "אלי", "טיגרן", "פולינה.ק", "תלמיד אחר..."]

st.set_page_config(page_title="מערכת תצפית - גרסה 58.0", layout="wide")

st.markdown("""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Heebo:wght@300;400;700&display=swap');
        html, body, .stApp { direction: rtl; text-align: right; font-family: 'Heebo', sans-serif !important; }
        [data-testid="stSlider"] { direction: ltr !important; }
        .stButton > button { width: 100%; font-weight: bold; border-radius: 12px; background-color: #28a745; color: white; height: 3em; }
    </style>
""", unsafe_allow_html=True)

# --- 1. בדיקת תקינות המערכת ---
def check_setup():
    missing = [k for k in ["GOOGLE_API_KEY", "GDRIVE_SERVICE_ACCOUNT_B64"] if not st.secrets.get(k)]
    if missing:
        st.error(f"⚠️ חסרים הגדרות במערכת (Secrets): {', '.join(missing)}")
        st.stop()

check_setup()

# --- 2. פונקציות הגנה על הנתונים (הפתרון לבאגים) ---
def clean_dataframe(df):
    """מנקה עמודות כפולות ומאפס אינדקסים למניעת InvalidIndexError"""
    if df is None or df.empty:
        return pd.DataFrame()
    # הסרת עמודות כפולות (למשל challenge ו-challenge.1)
    df = df.loc[:, ~df.columns.duplicated()].copy()
    # איפוס אינדקס מוחלט - קריטי למניעת קריסות ב-Python 3.13
    df = df.reset_index(drop=True)
    return df

@st.cache_resource
def get_drive_service():
    try:
        b64 = st.secrets.get("GDRIVE_SERVICE_ACCOUNT_B64")
        json_str = base64.b64decode(b64).decode("utf-8")
        creds = Credentials.from_service_account_info(json.loads(json_str), scopes=["https://www.googleapis.com/auth/drive"])
        return build("drive", "v3", credentials=creds)
    except Exception as e:
        st.error(f"שגיאה בחיבור לדרייב: {e}")
        return None

def load_data(svc):
    df_drive = pd.DataFrame()
    if svc:
        try:
            res = svc.files().list(q=f"name = '{MASTER_FILENAME}' and trashed = false", supportsAllDrives=True, includeItemsFromAllDrives=True).execute().get('files', [])
            if res:
                fh = io.BytesIO()
                downloader = MediaIoBaseDownload(fh, svc.files().get_media(fileId=res[0]['id']))
                done = False
                while not done: _, done = downloader.next_chunk()
                fh.seek(0)
                df_drive = pd.read_excel(fh)
                df_drive = clean_dataframe(df_drive)
                # מיפוי שמות עמודות
                mapping = {'score_conv': 'cat_convert_rep', 'score_proj': 'cat_proj_trans', 'score_efficacy': 'cat_self_efficacy'}
                df_drive = df_drive.rename(columns={k: v for k, v in mapping.items() if k in df_drive.columns})
        except: pass

    df_local = pd.DataFrame()
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                df_local = pd.DataFrame([json.loads(l) for l in f if l.strip()])
                df_local = clean_dataframe(df_local)
        except: pass

    if df_drive.empty: return df_local
    if df_local.empty: return df_drive
    
    # איחוד בטוח עם איפוס אינדקסים
    try:
        combined = pd.concat([df_drive, df_local], axis=0, ignore_index=True, sort=False)
        return clean_dataframe(combined)
    except:
        return df_drive

# --- 3. מנגנון AI מהיר ---
def get_ai_insight(prompt_type, context):
    try:
        genai.configure(api_key=st.secrets["GOOGLE_API_KEY"], transport='rest')
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        if prompt_type == "chat":
            p = f"נתח את {context['name']} עפ\"י ההיסטוריה:\n{context['history']}\nשאלה: {context['question']}"
        else: # ניתוח יומי
            p = f"נתח מגמות רוחביות ליום זה (כמותי ואיכותני):\n{context['history']}"
            
        return model.generate_content(p).text
    except Exception as e:
        return f"שגיאת AI: {str(e)[:50]}"

# --- 4. ממשק המערכת ---
if "chat_history" not in st.session_state: st.session_state.chat_history = []
if "daily_analysis" not in st.session_state: st.session_state.daily_analysis = ""

svc = get_drive_service()
full_df = load_data(svc)

tab1, tab2, tab3 = st.tabs(["📝 הזנה", "🔄 סנכרון", "📊 ניתוח ומגמות"])

# --- Tab 1: הזנה ---
with tab1:
    col_in, col_chat = st.columns([1.2, 1])
    with col_in:
        name = st.selectbox("👤 בחר סטודנט", CLASS_ROSTER)
        c1, c2 = st.columns(2)
        with c1:
            s1 = st.slider("המרה", 1, 5, 3)
            s2 = st.slider("היטלים", 1, 5, 3)
        with c2:
            s4 = st.slider("מסוגלות", 1, 5, 3)
            method = st.radio("🛠️ תרגול:", ["🧊 גוף מודפס", "🎨 דמיון"])
        
        challenge = st.text_area("🗣️ תיאור התצפית")
        if st.button("💾 שמור"):
            if challenge:
                entry = {"date": date.today().isoformat(), "student_name": name, "challenge": challenge, "cat_convert_rep": s1, "cat_proj_trans": s2, "cat_self_efficacy": s4, "timestamp": datetime.now().isoformat()}
                with open(DATA_FILE, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                st.success("נשמר!"); time.sleep(0.5); st.rerun()

    with col_chat:
        st.subheader(f"🤖 צ'אט: {name}")
        chat_box = st.container(height=350)
        for q, a in st.session_state.chat_history:
            chat_box.chat_message("user").write(q); chat_box.chat_message("assistant").write(a)
        u_q = st.chat_input("שאל...")
        if u_q:
            match = full_df[full_df['student_name'] == name] if not full_df.empty else pd.DataFrame()
            ans = get_ai_insight("chat", {"name": name, "history": match.tail(10).to_string(), "question": u_q})
            st.session_state.chat_history.append((u_q, ans)); st.rerun()

# --- Tab 2: סנכרון ---
with tab2:
    st.header("🔄 סנכרון מאגר")
    if st.button("🚀 סנכרן לדרייב"):
        if os.path.exists(DATA_FILE):
            try:
                with st.spinner("מעלה נתונים..."):
                    with open(DATA_FILE, "r", encoding="utf-8") as f: locals_ = [json.loads(l) for l in f if l.strip()]
                    df_m = pd.concat([full_df, pd.DataFrame(locals_)], ignore_index=True).drop_duplicates(subset=['student_name', 'timestamp'], keep='last')
                    buf = io.BytesIO()
                    with pd.ExcelWriter(buf, engine='openpyxl') as w: df_m.to_excel(w, index=False)
                    buf.seek(0)
                    query = f"name = '{MASTER_FILENAME}' and trashed = false"
                    res = svc.files().list(q=query, supportsAllDrives=True).execute().get('files', [])
                    media = MediaIoBaseUpload(buf, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                    if res: svc.files().update(fileId=res[0]['id'], media_body=media, supportsAllDrives=True).execute()
                    else: svc.files().create(body={'name': MASTER_FILENAME, 'parents': [st.secrets.get("GDRIVE_FOLDER_ID")]}, media_body=media, supportsAllDrives=True).execute()
                    os.remove(DATA_FILE); st.success("סונכרן!"); time.sleep(1); st.rerun()
            except Exception as e: st.error(f"שגיאה: {e}")

# --- Tab 3: ניתוח משולב ---
with tab3:
    st.header("📊 ניתוח מחקרי")
    if not full_df.empty:
        mode = st.radio("רמת ניתוח:", ["אישי", "יומי"], horizontal=True)
        if mode == "אישי":
            sel = st.selectbox("סטודנט", full_df['student_name'].unique())
            sd = full_df[full_df['student_name'] == sel].sort_values('timestamp')
            st.line_chart(sd.set_index('date')[['cat_convert_rep', 'cat_proj_trans']])
            q_ai = st.text_area("בקשה מה-AI (למשל: סכם מגמות):")
            if st.button("✨ הפק ניתוח"):
                with st.spinner("מנתח..."):
                    res = get_ai_insight("chat", {"name": sel, "history": sd.to_string(), "question": q_ai if q_ai else "סכם מגמות"})
                    st.info(res)
                    st.download_button("📥 הורד", res, file_name=f"{sel}.txt")
        else:
            day = st.selectbox("תאריך", sorted(full_df['date'].unique(), reverse=True))
            day_d = full_df[full_df['date'] == day]
            st.write(f"ממוצעים ליום {day}:")
            st.dataframe(day_d[['cat_convert_rep', 'cat_proj_trans', 'cat_self_efficacy']].mean())
            if st.button("✨ ניתוח רוחבי"):
                with st.spinner("מנתח..."):
                    res = get_ai_insight("daily", {"history": day_d.to_string()})
                    st.success(res)
