import json, base64, os, io, time, logging, pandas as pd, streamlit as st
import google.generativeai as genai
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload
from datetime import date, datetime

# --- 0. הגדרות ועיצוב ---
logging.basicConfig(level=logging.INFO)
DATA_FILE = "reflections.jsonl"
MASTER_FILENAME = "All_Observations_Master.xlsx"
GDRIVE_FOLDER_ID = st.secrets.get("GDRIVE_FOLDER_ID")
CLASS_ROSTER = ["נתנאל", "רועי", "אסף", "עילאי", "טדי", "גאל", "אופק", "דניאל.ר", "אלי", "טיגרן", "פולינה.ק", "תלמיד אחר..."]
TAGS_OPTIONS = ["התעלמות מקווים נסתרים", "בלבול בין היטלים", "קושי ברוטציה מנטלית", "טעות בפרופורציות", "קושי במעבר בין היטלים", "שימוש בכלי מדידה", "סיבוב פיזי של המודל", "תיקון עצמי", "עבודה עצמאית שוטפת"]

st.set_page_config(page_title="מערכת תצפית - גרסה סופית 45.2", layout="wide")

st.markdown("""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Heebo:wght@300;400;700&display=swap');
        html, body, .stApp { direction: rtl; text-align: right; font-family: 'Heebo', sans-serif !important; }
        [data-testid="stSlider"] { direction: ltr !important; }
        .stButton > button { width: 100%; font-weight: bold; border-radius: 12px; background-color: #28a745; color: white; height: 3em; }
        .feedback-box { background-color: #f0f2f6; padding: 20px; border-radius: 15px; border: 1px solid #d1d3d8; margin: 15px 0; color: #1f2937; }
    </style>
""", unsafe_allow_html=True)

# --- 1. פונקציות עזר ---
def normalize_name(name):
    if not isinstance(name, str): return ""
    return name.replace(" ", "").replace(".", "").replace("־", "").replace("-", "").strip()

@st.cache_resource
def get_drive_service():
    try:
        b64 = st.secrets.get("GDRIVE_SERVICE_ACCOUNT_B64")
        if not b64: return None
        js = base64.b64decode("".join(b64.split())).decode("utf-8")
        creds = Credentials.from_service_account_info(json.loads(js), scopes=["https://www.googleapis.com/auth/drive"])
        return build("drive", "v3", credentials=creds)
    except: return None

@st.cache_data(ttl=60)
def load_full_dataset(_svc):
    df_drive = pd.DataFrame()
    if _svc:
        try:
            res = _svc.files().list(q=f"name='{MASTER_FILENAME}'", supportsAllDrives=True).execute().get('files', [])
            if res:
                req = _svc.files().get_media(fileId=res[0]['id'])
                fh = io.BytesIO()
                downloader = MediaIoBaseDownload(fh, req)
                done = False
                while not done: _, done = downloader.next_chunk()
                fh.seek(0); df_drive = pd.read_excel(fh)
                possible = [c for c in df_drive.columns if any(x in c.lower() for x in ["student", "name", "שם", "תלמיד"])]
                if possible: df_drive.rename(columns={possible[0]: "student_name"}, inplace=True)
        except: pass
    
    df_local = pd.DataFrame()
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                df_local = pd.DataFrame([json.loads(l) for l in f if l.strip()])
        except: pass

    df = pd.concat([df_drive, df_local], ignore_index=True)
    if not df.empty and 'student_name' in df.columns:
        df = df.dropna(subset=['student_name'])
        df['name_clean'] = df['student_name'].astype(str).apply(normalize_name)
    return df

def get_ai_response(prompt_type, context_data):
    api_key = st.secrets.get("GOOGLE_API_KEY")
    if not api_key: return "מפתח API חסר"
    try:
        genai.configure(api_key=api_key, transport='rest')
        model = genai.GenerativeModel('gemini-1.5-flash')
        if prompt_type == "chat":
            p = f"נתח תצפיות של {context_data['name']}:\n{context_data['history']}\nשאלה: {context_data['question']}"
        else:
            p = f"תן משוב אקדמי קצר על התצפית: {context_data['challenge']}"
        return model.generate_content(p).text
    except: return "שגיאת AI"

# --- 2. אתחול נתונים ---
svc = get_drive_service()
full_df = load_full_dataset(svc)

# --- 3. ממשק משתמש ---
tab1, tab2, tab3 = st.tabs(["📝 הזנה ומשוב", "🔄 סנכרון", "📊 ניתוח"])

with tab1:
    col_in, col_chat = st.columns([1.2, 1])
    with col_in:
        if "it" not in st.session_state: st.session_state.it = 0
        if "last_selected_student" not in st.session_state: st.session_state.last_selected_student = ""
        if "show_success_bar" not in st.session_state: st.session_state.show_success_bar = False
        if "chat_history" not in st.session_state: st.session_state.chat_history = []

        student_name = st.selectbox("👤 בחר סטודנט", CLASS_ROSTER, key=f"sel_{st.session_state.it}")
        
        # לוגיקת סליידר ירוק
        if student_name != st.session_state.last_selected_student:
            target = normalize_name(student_name)
            match = full_df[full_df['name_clean'] == target] if not full_df.empty else pd.DataFrame()
            if match.empty and not full_df.empty:
                match = full_df[full_df['student_name'].str.contains(student_name, case=False, na=False)]
            
            st.session_state.show_success_bar = not match.empty
            st.session_state.student_context = match.tail(10).to_string() if not match.empty else ""
            st.session_state.last_selected_student = student_name
            st.session_state.chat_history = []
            st.rerun()

        if st.session_state.show_success_bar:
            st.success(f"✅ נמצאה היסטוריה עבור {student_name}.")
        else:
            st.info(f"ℹ️ {student_name}: אין תצפיות קודמות.")

        st.markdown("---")
        pl = st.text_area("📋 תכנון (Planned):", key=f"pl_{st.session_state.it}")
        do = st.text_area("✅ בוצע (Done):", key=f"do_{st.session_state.it}")
        ch = st.text_area("🗣️ תצפית (Challenge):", height=100, key=f"ch_{st.session_state.it}")
        ins = st.text_area("🧠 תובנה (Insight):", key=f"ins_{st.session_state.it}")
        nxt = st.text_area("⏭️ שלב הבא (Next Step):", key=f"nxt_{st.session_state.it}")

        st.markdown("### 📊 מדדים (1-5)")
        m1, m2 = st.columns(2)
        with m1:
            s1 = st.slider("המרת ייצוגים", 1, 5, 3, key=f"s1_{st.session_state.it}")
            s2 = st.slider("מעבר בין היטלים", 1, 5, 3, key=f"s2_{st.session_state.it}")
        with m2:
            s3 = st.slider("שימוש במודל", 1, 5, 3, key=f"s3_{st.session_state.it}")
            s4 = st.slider("מסוגלות עצמית", 1, 5, 3, key=f"s4_{st.session_state.it}")

        tgs = st.multiselect("🏷️ תגיות", TAGS_OPTIONS, key=f"t_{st.session_state.it}")

        if st.button("💾 שמור תצפית"):
            if not ch: st.error("חובה להזין תצפית")
            else:
                entry = {
                    "date": date.today().isoformat(), "student_name": student_name,
                    "planned": pl, "done": do, "challenge": ch, "insight": ins, "next_step": nxt,
                    "cat_convert_rep": int(s1), "cat_proj_trans": int(s2), 
                    "cat_3d_support": int(s3), "cat_self_efficacy": int(s4),
                    "tags": tgs, "timestamp": datetime.now().isoformat()
                }
                with open(DATA_FILE, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                st.session_state.it += 1; st.rerun()

    with col_chat:
        st.subheader(f"🤖 יועץ: {student_name}")
        for q, a in st.session_state.chat_history:
            st.chat_message("user").write(q); st.chat_message("assistant").write(a)
        u_q = st.chat_input("שאל...")
        if u_q:
            resp = get_ai_response("chat", {"name": student_name, "history": st.session_state.student_context, "question": u_q})
            st.session_state.chat_history.append((u_q, resp)); st.rerun()

with tab2:
    if st.button("🚀 סנכרן לדרייב"):
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                locals_ = [json.loads(l) for l in f if l.strip()]
            df_m = pd.concat([full_df, pd.DataFrame(locals_)], ignore_index=True).drop_duplicates(subset=['student_name', 'timestamp'], keep='last')
            buf = io.BytesIO()
            with pd.ExcelWriter(buf, engine='openpyxl') as w: df_m.to_excel(w, index=False)
            buf.seek(0)
            res = svc.files().list(q=f"name='{MASTER_FILENAME}'", supportsAllDrives=True).execute().get('files', [])
            media = MediaIoBaseUpload(buf, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            if res: svc.files().update(fileId=res[0]['id'], media_body=media, supportsAllDrives=True).execute()
            else: svc.files().create(body={'name': MASTER_FILENAME, 'parents': [GDRIVE_FOLDER_ID] if GDRIVE_FOLDER_ID else []}, media_body=media, supportsAllDrives=True).execute()
            os.remove(DATA_FILE); st.success("סונכרן!"); st.cache_data.clear(); st.rerun()

with tab3:
    st.header("📊 ניתוח מחקרי")
    if not full_df.empty:
        # ניתוח שבועי
        df_an = full_df.copy()
        df_an['date'] = pd.to_datetime(df_an['date'], errors='coerce')
        df_an['week'] = df_an['date'].dt.strftime('%Y - שבוע %U')
        weeks = sorted(df_an['week'].dropna().unique(), reverse=True)
        sel_week = st.selectbox("בחר שבוע לניתוח:", weeks)
        w_df = df_an[df_an['week'] == sel_week]
        st.dataframe(w_df)

        if st.button("✨ הפק ניתוח תמות"):
            with st.spinner("מנתח..."):
                txt = "".join([f"תצפית: {r.get('challenge','')} | תובנה: {r.get('insight','')}\n" for _, r in w_df.iterrows()])
                st.info(get_ai_response("analysis", {"challenge": txt}))

# --- סיידבר דיבוג ---
st.sidebar.title("🔍 דיבוג")
if st.sidebar.button("📊 הצג שמות באקסל"):
    st.sidebar.write(full_df['student_name'].unique().tolist() if not full_df.empty else "אין נתונים")
if st.sidebar.button("🔄 רענן"):
    st.cache_data.clear(); st.rerun()
