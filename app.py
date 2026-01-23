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
GDRIVE_FOLDER_ID = st.secrets.get("GDRIVE_FOLDER_ID")

st.set_page_config(page_title="מערכת תצפית ומחקר - 65.0", layout="wide")

# עיצוב RTL
st.markdown("""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Heebo:wght@300;400;700&display=swap');
        html, body, .stApp { direction: rtl; text-align: right; font-family: 'Heebo', sans-serif !important; }
        [data-testid="stSlider"] { direction: ltr !important; }
        .stButton > button { width: 100%; font-weight: bold; border-radius: 12px; background-color: #28a745; color: white; height: 3em; }
    </style>
""", unsafe_allow_html=True)

# --- פונקציות עזר וניקוי ---
def research_clean(df):
    if df is None or df.empty: return pd.DataFrame()
    df.columns = [str(c).strip() for c in df.columns]
    df = df.loc[:, ~df.columns.duplicated()].copy()
    remap = {
        'score_conv': 'cat_convert_rep', 'score_proj': 'cat_proj_trans', 
        'score_efficacy': 'cat_self_efficacy', 'score_model': 'cat_3d_support'
    }
    df = df.rename(columns={k: v for k, v in remap.items() if k in df.columns})
    needed = [
        'date', 'student_name', 'work_method', 'exercise_difficulty', 
        'cat_convert_rep', 'cat_proj_trans', 'cat_self_efficacy', 'cat_3d_support', 
        'challenge', 'interpretation', 'images', 'timestamp'
    ]
    df = df[[c for c in needed if c in df.columns]].copy()
    return df.reset_index(drop=True)

@st.cache_resource
def get_drive():
    try:
        b64 = st.secrets.get("GDRIVE_SERVICE_ACCOUNT_B64")
        creds = Credentials.from_service_account_info(json.loads(base64.b64decode(b64).decode("utf-8")), 
                                                     scopes=["https://www.googleapis.com/auth/drive"])
        return build("drive", "v3", credentials=creds)
    except: return None

def upload_image_to_drive(svc, uploaded_file, folder_id):
    try:
        file_metadata = {'name': uploaded_file.name, 'parents': [folder_id] if folder_id else []}
        media = MediaIoBaseUpload(io.BytesIO(uploaded_file.getvalue()), mimetype='image/jpeg')
        file = svc.files().create(body=file_metadata, media_body=media, fields='id, webViewLink').execute()
        return file.get('webViewLink')
    except: return ""

def load_data(svc):
    df_d, df_l = pd.DataFrame(), pd.DataFrame()
    if svc:
        try:
            res = svc.files().list(q=f"name = '{MASTER_FILENAME}' and trashed = false").execute().get('files', [])
            if res:
                fh = io.BytesIO()
                downloader = MediaIoBaseDownload(fh, svc.files().get_media(fileId=res[0]['id']))
                done = False
                while not done: _, done = downloader.next_chunk()
                fh.seek(0)
                df_d = research_clean(pd.read_excel(fh))
        except: pass
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                df_l = research_clean(pd.DataFrame([json.loads(l) for l in f if l.strip()]))
        except: pass
    
    if df_d.empty: return df_l
    if df_local.empty: return df_d
    return research_clean(pd.concat([df_d, df_l], ignore_index=True, sort=False))

# --- התחלת אפליקציה ---
svc = get_drive()
full_df = load_data(svc)

st.title("🎓 מערכת תצפית ומחקר - 65.0")
t1, t2, t3 = st.tabs(["📝 הזנה", "🔄 סנכרון", "📊 ניתוח"])

with t1:
    col1, col2 = st.columns([1,1])
    with col1:
        name = st.selectbox("👤 סטודנט", CLASS_ROSTER)
        meth = st.radio("🛠️ שיטת עבודה", ["🧊 בעזרת גוף מודפס", "🎨 ללא גוף (דמיון)"])
        diff = st.select_slider("📉 רמת קושי", ["קל", "בינוני", "קשה"])
        img_file = st.file_uploader("📸 העלאת תמונת שרטוט", type=['jpg', 'png', 'jpeg'])

    with col2:
        st.write("**📊 מדדי ביצוע (1-5)**")
        s1 = st.slider("המרה (ייצוגים)", 1, 5, 3)
        s2 = st.slider("מעבר בין היטלים", 1, 5, 3)
        s3 = st.slider("שימוש במודל פיזי", 1, 5, 3)
        s4 = st.slider("מסוגלות עצמית", 1, 5, 3)

    ch = st.text_area("🗣️ תיאור התצפית (מה קרה?)")
    interp = st.text_area("🧠 פרשנות מחקרית (תובנות)")

    if st.button("💾 שמור תצפית"):
        if not ch: st.error("חובה להזין תיאור!")
        else:
            with st.spinner("שומר ומעלה..."):
                img_url = ""
                if img_file and svc:
                    img_url = upload_image_to_drive(svc, img_file, GDRIVE_FOLDER_ID)
                
                entry = {
                    "date": str(date.today()), "student_name": name, "work_method": meth, 
                    "exercise_difficulty": diff, "cat_convert_rep": s1, "cat_proj_trans": s2, 
                    "cat_3d_support": s3, "cat_self_efficacy": s4, "challenge": ch, 
                    "interpretation": interp, "images": img_url, "timestamp": datetime.now().isoformat()
                }
                with open(DATA_FILE, "a", encoding="utf-8") as f: f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                st.success("✅ נשמר בהצלחה!"); time.sleep(1); st.rerun()

with t2:
    st.header("🔄 סנכרון מאגר הנתונים")
    if st.button("🚀 סנכרן הכל ל-Google Drive"):
        if os.path.exists(DATA_FILE):
            try:
                with st.spinner("מבצע מיזוג סופי..."):
                    with open(DATA_FILE, "r", encoding="utf-8") as f: l_ = [json.loads(l) for l in f if l.strip()]
                    final = pd.concat([full_df, pd.DataFrame(l_)], ignore_index=True).drop_duplicates(subset=['student_name', 'timestamp'], keep='last')
                    buf = io.BytesIO()
                    with pd.ExcelWriter(buf, engine='openpyxl') as w: final.to_excel(w, index=False)
                    buf.seek(0)
                    res = svc.files().list(q=f"name = '{MASTER_FILENAME}'").execute().get('files', [])
                    media = MediaIoBaseUpload(buf, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                    if res: svc.files().update(fileId=res[0]['id'], media_body=media).execute()
                    else: svc.files().create(body={'name': MASTER_FILENAME, 'parents': [GDRIVE_FOLDER_ID] if GDRIVE_FOLDER_ID else []}, media_body=media).execute()
                    os.remove(DATA_FILE); st.success("✅ הסנכרון הושלם!"); time.sleep(1); st.rerun()
            except Exception as e: st.error(f"שגיאה: {e}")

with t3:
    st.header("📊 ניתוח ומגמות")
    if full_df.empty: st.info("אין מספיק נתונים לניתוח.")
    else:
        mode = st.radio("רמת ניתוח:", ["אישי", "יומי רוחבי"], horizontal=True)
        if mode == "אישי":
            sel = st.selectbox("בחר סטודנט", full_df['student_name'].unique())
            sd = full_df[full_df['student_name'] == sel].sort_values('timestamp')
            st.line_chart(sd.set_index('date')[['cat_convert_rep', 'cat_proj_trans', 'cat_3d_support']])
            req = st.text_input("שאלה ל-AI על הסטודנט:")
            if st.button("✨ הפק תובנות"):
                genai.configure(api_key=st.secrets["GOOGLE_API_KEY"], transport='rest')
                model = genai.GenerativeModel('gemini-1.5-flash')
                res = model.generate_content(f"Analyze student {sel} trends:\n{sd.to_string()}\nRequest: {req}").text
                st.info(res)
        else:
            d = st.selectbox("תאריך", sorted(full_df['date'].unique(), reverse=True))
            day_df = full_df[full_df['date'] == d]
            st.write(f"ממוצעים ליום {d}:")
            st.dataframe(day_df.mean(numeric_only=True))
            if st.button("✨ נתח את כלל הכיתה"):
                genai.configure(api_key=st.secrets["GOOGLE_API_KEY"], transport='rest')
                model = genai.GenerativeModel('gemini-1.5-flash')
                st.success(model.generate_content(f"Analyze class trends for {d}:\n{day_df.to_string()}").text)
