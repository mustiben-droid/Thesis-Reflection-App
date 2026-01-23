import json, base64, os, io, time, pandas as pd, streamlit as st
import google.generativeai as genai
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload
from datetime import date, datetime

# --- 1. הגדרות ועיצוב ---
DATA_FILE = "reflections.jsonl"
MASTER_FILENAME = "All_Observations_Master.xlsx"
CLASS_ROSTER = ["נתנאל", "רועי", "אסף", "עילאי", "טדי", "גאל", "אופק", "דניאל.ר", "אלי", "טיגרן", "פולינה.ק", "תלמיד אחר..."]
GDRIVE_FOLDER_ID = st.secrets.get("GDRIVE_FOLDER_ID")

st.set_page_config(page_title="מערכת תצפית מחקרית - 69.0", layout="wide")

st.markdown("""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Heebo:wght@300;400;700&display=swap');
        html, body, .stApp { direction: rtl; text-align: right; font-family: 'Heebo', sans-serif !important; }
        [data-testid="stSlider"] { direction: ltr !important; }
        .stButton > button { width: 100%; font-weight: bold; border-radius: 12px; background-color: #28a745; color: white; height: 3em; }
        .stChatMessage { text-align: right; direction: rtl; }
    </style>
""", unsafe_allow_html=True)

# --- 2. פונקציות ניקוי דאטה (מניעת קריסות) ---
def clean_data(df):
    if df is None or df.empty: return pd.DataFrame()
    df.columns = [str(c).strip() for c in df.columns]
    df = df.loc[:, ~df.columns.duplicated()].copy()
    
    # מיפוי שמות עמודות מהקובץ שלך (score -> cat)
    mapping = {
        'score_conv': 'cat_convert_rep', 'score_proj': 'cat_proj_trans', 
        'score_efficacy': 'cat_self_efficacy', 'score_model': 'cat_3d_support',
        'physical_model': 'work_method', 'difficulty': 'exercise_difficulty'
    }
    for old, new in mapping.items():
        if old in df.columns:
            if new not in df.columns: df[new] = df[old]
            else: df[new] = df[new].fillna(df[old])
            
    cols = ['date', 'student_name', 'work_method', 'exercise_difficulty', 'cat_convert_rep', 
            'cat_proj_trans', 'cat_self_efficacy', 'cat_3d_support', 'challenge', 'interpretation', 'images', 'timestamp']
    return df[[c for c in cols if c in df.columns]].copy().reset_index(drop=True)

@st.cache_resource
def get_drive_service():
    try:
        b64 = st.secrets.get("GDRIVE_SERVICE_ACCOUNT_B64")
        creds = Credentials.from_service_account_info(json.loads(base64.b64decode(b64).decode("utf-8")), 
                                                     scopes=["https://www.googleapis.com/auth/drive"])
        return build("drive", "v3", credentials=creds)
    except: return None

def load_all_data(svc):
    all_dfs = []
    if svc:
        try:
            res = svc.files().list(q=f"name = '{MASTER_FILENAME}'").execute().get('files', [])
            if res:
                fh = io.BytesIO()
                downloader = MediaIoBaseDownload(fh, svc.files().get_media(fileId=res[0]['id']))
                done = False
                while not done: _, done = downloader.next_chunk()
                fh.seek(0)
                all_dfs.append(clean_data(pd.read_excel(fh)))
        except: pass
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                all_dfs.append(clean_data(pd.DataFrame([json.loads(l) for l in f if l.strip()])))
        except: pass
    if not all_dfs: return pd.DataFrame()
    return clean_data(pd.concat(all_dfs, ignore_index=True, sort=False))

# --- 3. מנוע ה-AI ---
def run_ai_chat(prompt):
    try:
        genai.configure(api_key=st.secrets["GOOGLE_API_KEY"], transport='rest')
        model = genai.GenerativeModel('gemini-1.5-flash')
        return model.generate_content(prompt).text
    except: return "ה-AI אינו זמין כרגע."

# --- 4. אתחול והרצה ---
svc = get_drive_service()
full_df = load_all_data(svc)

tab1, tab2, tab3 = st.tabs(["📝 הזנה וצ'אט", "🔄 סנכרון", "📊 ניתוח"])

with tab1:
    c_in, c_chat = st.columns([1.2, 1])
    with c_in:
        name = st.selectbox("👤 בחר סטודנט", CLASS_ROSTER)
        
        # הסטריפ הירוק
        st_hist = full_df[full_df['student_name'] == name]
        if not st_hist.empty:
            st.success(f"✅ נמצאו {len(st_hist)} תצפיות בדרייב עבור {name}")
        
        col1, col2 = st.columns(2)
        with col1:
            meth = st.radio("🛠️ שיטה", ["🧊 גוף מודפס", "🎨 דמיון"])
            diff = st.select_slider("📉 קושי", ["קל", "בינוני", "קשה"])
            img_file = st.file_uploader("📸 העלאת תמונה", type=['jpg', 'png', 'jpeg'])
        with col2:
            s1 = st.slider("המרה", 1, 5, 3)
            s2 = st.slider("היטלים", 1, 5, 3)
            s3 = st.slider("מודל", 1, 5, 3)
            s4 = st.slider("מסוגלות", 1, 5, 3)

        ch = st.text_area("🗣️ תיאור התצפית")
        interp = st.text_area("🧠 פרשנות מחקרית")

        if st.button("💾 שמור"):
            if ch:
                with st.spinner("שומר..."):
                    img_url = ""
                    if img_file and svc:
                        f_meta = {'name': f"{name}_{date.today()}.jpg", 'parents': [GDRIVE_FOLDER_ID] if GDRIVE_FOLDER_ID else []}
                        media = MediaIoBaseUpload(io.BytesIO(img_file.getvalue()), mimetype='image/jpeg')
                        f_drive = svc.files().create(body=f_meta, media_body=media, fields='webViewLink').execute()
                        img_url = f_drive.get('webViewLink')
                    
                    entry = {"date": str(date.today()), "student_name": name, "work_method": meth, "exercise_difficulty": diff, "cat_convert_rep": s1, "cat_proj_trans": s2, "cat_3d_support": s3, "cat_self_efficacy": s4, "challenge": ch, "interpretation": interp, "images": img_url, "timestamp": datetime.now().isoformat()}
                    with open(DATA_FILE, "a", encoding="utf-8") as f:
                        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                    st.success("נשמר!"); time.sleep(0.5); st.rerun()

    with c_chat:
        st.subheader(f"🤖 צ'אט: {name}")
        if "chat_history" not in st.session_state: st.session_state.chat_history = []
        chat_box = st.container(height=400)
        for m in st.session_state.chat_history:
            chat_box.chat_message(m["role"]).write(m["content"])
            
        if p := st.chat_input("שאל על הסטודנט..."):
            st.session_state.chat_history.append({"role": "user", "content": p})
            chat_box.chat_message("user").write(p)
            ctx = f"היסטוריה של {name}:\n{st_hist.tail(10).to_string()}\nשאלה: {p}"
            ans = run_ai_chat(ctx)
            st.session_state.chat_history.append({"role": "assistant", "content": ans})
            chat_box.chat_message("assistant").write(ans)

with tab2:
    if st.button("🚀 סנכרן הכל לדרייב"):
        if os.path.exists(DATA_FILE):
            with st.spinner("מסנכרן..."):
                with open(DATA_FILE, "r", encoding="utf-8") as f: l_ = [json.loads(l) for l in f if l.strip()]
                final = pd.concat([full_df, pd.DataFrame(l_)], ignore_index=True).drop_duplicates(subset=['student_name', 'timestamp'], keep='last')
                buf = io.BytesIO()
                with pd.ExcelWriter(buf, engine='openpyxl') as w: final.to_excel(w, index=False)
                buf.seek(0)
                res = svc.files().list(q=f"name = '{MASTER_FILENAME}'").execute().get('files', [])
                media = MediaIoBaseUpload(buf, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                if res: svc.files().update(fileId=res[0]['id'], media_body=media).execute()
                else: svc.files().create(body={'name': MASTER_FILENAME, 'parents': [GDRIVE_FOLDER_ID] if GDRIVE_FOLDER_ID else []}, media_body=media).execute()
                os.remove(DATA_FILE); st.success("סונכרן!"); st.rerun()

with tab3:
    if full_df.empty: st.info("אין נתונים.")
    else:
        m = st.radio("סוג ניתוח", ["אישי", "יומי"], horizontal=True)
        if m == "אישי":
            sel = st.selectbox("סטודנט", full_df['student_name'].unique())
            sd = full_df[full_df['student_name'] == sel].sort_values('timestamp')
            st.line_chart(sd.set_index('date')[['cat_convert_rep', 'cat_proj_trans']])
            if st.button("✨ נתח AI"):
                st.info(run_ai_chat(f"נתח את {sel}:\n{sd.to_string()}"))
        else:
            d = st.selectbox("תאריך", sorted(full_df['date'].unique(), reverse=True))
            day_df = full_df[full_df['date'] == d]
            st.write(f"ממוצעים ליום {d}:")
            st.dataframe(day_df.mean(numeric_only=True))
