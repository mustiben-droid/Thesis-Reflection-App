import json, base64, os, io, time, pandas as pd, streamlit as st
import google.generativeai as genai
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload
from datetime import date, datetime

# --- הגדרות ---
DATA_FILE = "reflections.jsonl"
MASTER_FILENAME = "All_Observations_Master.xlsx"
CLASS_ROSTER = ["נתנאל", "רועי", "אסף", "עילאי", "טדי", "גאל", "אופק", "דניאל.ר", "אלי", "טיגרן", "פולינה.ק", "תלמיד אחר..."]

st.set_page_config(page_title="מערכת תצפית - 61.0", layout="wide")

# --- פונקציית הניקוי האגרסיבית (מבוסס על מבנה הקובץ שלך) ---
def clean_research_data(df):
    if df is None or df.empty:
        return pd.DataFrame()
    
    # 1. השארת עמודות רלוונטיות בלבד כדי למנוע כפילויות ואינדקסים שגויים
    essential_cols = [
        'date', 'student_name', 'challenge', 'interpretation', 'timestamp',
        'cat_convert_rep', 'cat_proj_trans', 'cat_self_efficacy', 'work_method', 'exercise_difficulty'
    ]
    
    # בדיקה אילו מהעמודות קיימות (כי לפעמים באקסל השם הוא score_conv)
    rename_dict = {
        'score_conv': 'cat_convert_rep',
        'score_proj': 'cat_proj_trans',
        'score_efficacy': 'cat_self_efficacy'
    }
    df = df.rename(columns=rename_dict)
    
    # סינון רק של מה שקיים ורלוונטי
    existing_cols = [c for c in essential_cols if c in df.columns]
    df = df[existing_cols].copy()
    
    # 2. הסרת שורות ריקות לגמרי
    df = df.dropna(subset=['student_name', 'date'], how='all')
    
    # 3. איפוס אינדקס סופי
    df = df.reset_index(drop=True)
    return df

@st.cache_resource
def get_drive_svc():
    try:
        b64 = st.secrets.get("GDRIVE_SERVICE_ACCOUNT_B64")
        creds = Credentials.from_service_account_info(
            json.loads(base64.b64decode(b64).decode("utf-8")), 
            scopes=["https://www.googleapis.com/auth/drive"]
        )
        return build("drive", "v3", credentials=creds)
    except: return None

def load_all_data(svc):
    df_d = pd.DataFrame()
    if svc:
        try:
            res = svc.files().list(q=f"name = '{MASTER_FILENAME}' and trashed = false").execute().get('files', [])
            if res:
                fh = io.BytesIO()
                downloader = MediaIoBaseDownload(fh, svc.files().get_media(fileId=res[0]['id']))
                done = False
                while not done: _, done = downloader.next_chunk()
                fh.seek(0)
                df_d = pd.read_excel(fh)
                df_d = clean_research_data(df_d)
        except: pass

    df_l = pd.DataFrame()
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                df_l = pd.DataFrame([json.loads(l) for l in f if l.strip()])
                df_l = clean_research_data(df_l)
        except: pass

    if df_d.empty: return df_l
    if df_l.empty: return df_d
    
    try:
        combined = pd.concat([df_d, df_local], axis=0, ignore_index=True)
        return clean_research_data(combined)
    except: return df_d

def get_ai_analysis(mode, ctx):
    try:
        genai.configure(api_key=st.secrets["GOOGLE_API_KEY"], transport='rest')
        model = genai.GenerativeModel('gemini-1.5-flash')
        prompt = f"נתח את {ctx['name']}:\n{str(ctx['history'])[:3500]}\nשאלה: {ctx.get('q', 'סכם מגמות')}"
        return model.generate_content(prompt).text
    except: return "ה-AI אינו זמין כרגע"

# --- ממשק ---
svc = get_drive_svc()
df = load_all_data(svc)

st.title("🎓 מערכת תצפית ומחקר - גרסה 61.0")
tab1, tab2, tab3 = st.tabs(["📝 הזנה", "🔄 סנכרון", "📊 ניתוח"])

with tab1:
    col1, col2 = st.columns([1, 1])
    with col1:
        name = st.selectbox("בחר סטודנט", CLASS_ROSTER)
        s1 = st.slider("המרה (1-5)", 1, 5, 3)
        s2 = st.slider("היטלים (1-5)", 1, 5, 3)
        ch = st.text_area("תיאור התצפית")
        if st.button("💾 שמור תצפית"):
            if ch:
                entry = {
                    "date": date.today().isoformat(), "student_name": name, 
                    "challenge": ch, "cat_convert_rep": s1, "cat_proj_trans": s2, 
                    "timestamp": datetime.now().isoformat()
                }
                with open(DATA_FILE, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                st.success("נשמר!"); time.sleep(0.5); st.rerun()

with tab2:
    if st.button("🚀 סנכרן לדרייב"):
        if os.path.exists(DATA_FILE):
            with st.spinner("מעבד נתונים..."):
                with open(DATA_FILE, "r", encoding="utf-8") as f: l_ = [json.loads(l) for l in f if l.strip()]
                final = pd.concat([df, pd.DataFrame(l_)], ignore_index=True).drop_duplicates(subset=['student_name', 'timestamp'], keep='last')
                buf = io.BytesIO()
                with pd.ExcelWriter(buf, engine='openpyxl') as w: final.to_excel(w, index=False)
                buf.seek(0)
                res = svc.files().list(q=f"name = '{MASTER_FILENAME}'").execute().get('files', [])
                media = MediaIoBaseUpload(buf, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                if res: svc.files().update(fileId=res[0]['id'], media_body=media).execute()
                else: svc.files().create(body={'name': MASTER_FILENAME}, media_body=media).execute()
                os.remove(DATA_FILE); st.success("סונכרן בהצלחה!"); st.rerun()

with tab3:
    if not df.empty:
        mode = st.radio("בחר ניתוח:", ["אישי", "יומי רוחבי"], horizontal=True)
        if mode == "אישי":
            sel = st.selectbox("סטודנט", df['student_name'].unique())
            sd = df[df['student_name'] == sel].sort_values('date')
            st.line_chart(sd.set_index('date')[['cat_convert_rep', 'cat_proj_trans']])
            q = st.text_input("מה תרצה לשאול את ה-AI?")
            if st.button("הפק תובנות"):
                st.info(get_ai_analysis("chat", {"name": sel, "history": sd.to_string(), "q": q}))
        else:
            d = st.selectbox("תאריך", sorted(df['date'].unique(), reverse=True))
            day_df = df[df['date'] == d]
            st.write(f"ממוצעים ליום {d}:")
            st.dataframe(day_df.mean(numeric_only=True))
            if st.button("נתח את כלל הכיתה"):
                st.success(get_ai_analysis("daily", {"name": "הכיתה", "history": day_df.to_string()}))
