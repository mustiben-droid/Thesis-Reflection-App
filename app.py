import json, base64, os, io, logging, pandas as pd, streamlit as st
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

st.set_page_config(page_title="מערכת תצפית - 49.0", layout="wide")

st.markdown("""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Heebo:wght@300;400;700&display=swap');
        html, body, .stApp { direction: rtl; text-align: right; font-family: 'Heebo', sans-serif !important; }
        [data-testid="stSlider"] { direction: ltr !important; }
        .stButton > button { width: 100%; font-weight: bold; border-radius: 12px; height: 3em; }
        .stButton button[kind="primary"] { background-color: #28a745; color: white; }
        .feedback-box { background-color: #f8f9fa; padding: 20px; border-radius: 15px; border: 1px solid #dee2e6; margin: 15px 0; }
    </style>
""", unsafe_allow_html=True)

# --- 1. פונקציות עזר ---
def normalize_name(name):
    if not isinstance(name, str): return ""
    return name.replace(" ", "").replace("־", "").replace("-", "").strip()

@st.cache_resource
def get_drive_service():
    try:
        b64 = st.secrets.get("GDRIVE_SERVICE_ACCOUNT_B64")
        js = base64.b64decode("".join(b64.split())).decode("utf-8")
        creds = Credentials.from_service_account_info(json.loads(js), scopes=["https://www.googleapis.com/auth/drive"])
        return build("drive", "v3", credentials=creds)
    except: return None

@st.cache_data(ttl=30)
def load_full_dataset(_svc):
    df_drive = pd.DataFrame()
    if _svc:
        try:
            res = _svc.files().list(q=f"name='{MASTER_FILENAME}' and trashed=false", supportsAllDrives=True).execute().get('files', [])
            if res:
                req = _svc.files().get_media(fileId=res[0]['id'])
                fh = io.BytesIO()
                downloader = MediaIoBaseDownload(fh, req)
                done = False
                while not done: _, done = downloader.next_chunk()
                fh.seek(0); df_drive = pd.read_excel(fh)
                cols = [c for c in df_drive.columns if any(x in c.lower() for x in ["student", "name", "שם", "תלמיד"])]
                if cols: df_drive.rename(columns={cols[0]: "student_name"}, inplace=True)
        except: pass
    
    df_local = pd.DataFrame()
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                df_local = pd.DataFrame([json.loads(l) for l in f if l.strip()])
        except: pass

    df = pd.concat([df_drive, df_local], ignore_index=True)
    if not df.empty and 'student_name' in df.columns:
        df['student_name'] = df['student_name'].astype(str).str.strip()
        df['name_clean'] = df['student_name'].apply(normalize_name)
    return df

# --- 2. אתחול ---
svc = get_drive_service()
full_df = load_full_dataset(svc)

if "it" not in st.session_state: st.session_state.it = 0
if "chat_history" not in st.session_state: st.session_state.chat_history = []
if "last_selected_student" not in st.session_state: st.session_state.last_selected_student = ""
if "show_success_bar" not in st.session_state: st.session_state.show_success_bar = False
if "last_feedback" not in st.session_state: st.session_state.last_feedback = ""

# --- 3. ממשק ---
tab1, tab2, tab3 = st.tabs(["📝 הזנה ומשוב", "🔄 סנכרון", "📊 ניתוח"])

with tab1:
    col_in, col_chat = st.columns([1.2, 1])
    with col_in:
        it = st.session_state.it
        student_name = st.selectbox("👤 בחר סטודנט", CLASS_ROSTER, key=f"sel_{it}")
        
        if student_name != st.session_state.last_selected_student:
            target = normalize_name(student_name)
            match = full_df[full_df['name_clean'] == target] if not full_df.empty else pd.DataFrame()
            if match.empty and not full_df.empty:
                match = full_df[full_df['student_name'].str.contains(student_name, case=False, na=False)]
            st.session_state.show_success_bar = not match.empty
            st.session_state.student_context = match.tail(15).to_string() if not match.empty else ""
            st.session_state.last_selected_student = student_name
            st.session_state.chat_history = []
            st.rerun()

        if st.session_state.show_success_bar:
            st.success(f"✅ נמצאה היסטוריה עבור {student_name}.")
        else:
            st.info(f"ℹ️ {student_name}: אין תצפיות קודמות.")

        st.markdown("---")
        work_method = st.radio("🛠️ צורת עבודה:", ["🧊 בעזרת גוף מודפס", "🎨 ללא גוף (דמיון)"], key=f"wm_{it}", horizontal=True)
        
        c1, c2 = st.columns(2)
        with c1:
            pl = st.text_area("📋 תכנון (Planned):", key=f"pl_{it}")
            ch = st.text_area("🗣️ תצפית שדה (Challenge):", height=100, key=f"ch_{it}")
            nxt = st.text_area("⏭️ שלב הבא (Next Step):", key=f"nxt_{it}")
        with c2:
            do = st.text_area("✅ בוצע (Done):", key=f"do_{it}")
            ins = st.text_area("🧠 תובנה/פרשנות (Insight):", key=f"ins_{it}")

        st.markdown("### 📊 מדדים (1-5)")
        m1, m2 = st.columns(2)
        with m1:
            s1 = st.slider("המרת ייצוגים", 1, 5, 3, key=f"s1_{it}")
            s2 = st.slider("מעבר בין היטלים", 1, 5, 3, key=f"s2_{it}")
        with m2:
            s3 = st.slider("שימוש במודל 3D", 1, 5, 3, key=f"s3_{it}")
            s4 = st.slider("פרופורציות ומימדים", 1, 5, 3, key=f"s4_{it}")

        tags = st.multiselect("🏷️ תגיות אבחון", TAGS_OPTIONS, key=f"t_{it}")

        if st.session_state.last_feedback:
            st.markdown(f'<div class="feedback-box"><b>💡 משוב AI:</b><br>{st.session_state.last_feedback}</div>', unsafe_allow_html=True)

        c_btns = st.columns(2)
        with c_btns[0]:
            if st.button("🔍 בקש רפלקציה (AI)"):
                if ch:
                    genai.configure(api_key=st.secrets.get("GOOGLE_API_KEY"), transport='rest')
                    model = genai.GenerativeModel('gemini-1.5-flash')
                    st.session_state.last_feedback = model.generate_content(f"נתח תצפית אקדמית עבור {student_name}: {ch}").text
                    st.rerun()
        with c_btns[1]:
            if st.button("💾 שמור תצפית", type="primary"):
                if ch:
                    entry = {"date": date.today().isoformat(), "student_name": student_name, "work_method": work_method, "planned": pl, "done": do, "challenge": ch, "insight": ins, "next_step": nxt, "cat_convert_rep": int(s1), "cat_proj_trans": int(s2), "cat_3d_support": int(s3), "cat_dims_props": int(s4), "tags": tags, "timestamp": datetime.now().isoformat()}
                    with open(DATA_FILE, "a", encoding="utf-8") as f: f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                    st.session_state.it += 1; st.session_state.last_feedback = ""; st.rerun()

    with col_chat:
        st.subheader(f"🤖 יועץ: {student_name}")
        chat_cont = st.container(height=450)
        for q, a in st.session_state.chat_history:
            with chat_cont: st.chat_message("user").write(q); st.chat_message("assistant").write(a)
        u_q = st.chat_input("שאל...")
        if u_q:
            genai.configure(api_key=st.secrets.get("GOOGLE_API_KEY"), transport='rest')
            model = genai.GenerativeModel('gemini-1.5-flash')
            resp = model.generate_content(f"נתח היסטוריה: {st.session_state.student_context}. שאלה: {u_q}").text
            st.session_state.chat_history.append((u_q, resp)); st.rerun()

with tab2:
    if st.button("🚀 סנכרן הכל לדרייב"):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f: locals_ = [json.loads(l) for l in f if l.strip()]
            df_m = pd.concat([full_df, pd.DataFrame(locals_)], ignore_index=True).drop_duplicates(subset=['student_name', 'timestamp'], keep='last')
            buf = io.BytesIO()
            with pd.ExcelWriter(buf, engine='openpyxl') as w: df_m.to_excel(w, index=False)
            buf.seek(0)
            res = svc.files().list(q=f"name='{MASTER_FILENAME}'", supportsAllDrives=True).execute().get('files', [])
            media = MediaIoBaseUpload(buf, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            if res: svc.files().update(fileId=res[0]['id'], media_body=media, supportsAllDrives=True).execute()
            else: svc.files().create(body={'name': MASTER_FILENAME, 'parents': [GDRIVE_FOLDER_ID] if GDRIVE_FOLDER_ID else []}, media_body=media, supportsAllDrives=True).execute()
            os.remove(DATA_FILE); st.success("סונכרן!"); st.cache_data.clear(); st.rerun()
        except Exception as e: st.error(f"שגיאת סנכרון: {e}")

with tab3:
    st.header("📊 ניתוח מחקרי")
    df_v = load_full_dataset(svc)
    if not df_v.empty:
        mode = st.radio("סוג ניתוח:", ["👤 אישי", "📅 שבועי"], horizontal=True)
        if mode == "👤 אישי":
            sel = st.selectbox("בחר סטודנט:", ["כולם"] + sorted(df_v['student_name'].unique().tolist()))
            st.dataframe(df_v if sel == "כולם" else df_v[df_v['student_name'] == sel], use_container_width=True)
        else:
            df_v['date'] = pd.to_datetime(df_v['date'], errors='coerce')
            df_v['week'] = df_v['date'].dt.strftime('%Y - שבוע %U')
            sel_w = st.selectbox("בחר שבוע:", sorted(df_v['week'].dropna().unique(), reverse=True))
            w_df = df_v[df_v['week'] == sel_w]
            st.dataframe(w_df)
            if st.button("✨ הפק ניתוח שבועי ושמור לדרייב"):
                with st.spinner("מנתח..."):
                    genai.configure(api_key=st.secrets.get("GOOGLE_API_KEY"), transport='rest')
                    model = genai.GenerativeModel('gemini-1.5-flash')
                    txt = "".join([f"תצפית: {r.get('challenge','')} | תובנה: {r.get('insight','')}\n" for _, r in w_df.iterrows()])
                    response = model.generate_content(f"נתח תמות אקדמיות לשבוע {sel_w}: {txt}").text
                    st.info(response)
                    f_name = f"ניתוח_{sel_w}.txt"
                    media = MediaIoBaseUpload(io.BytesIO(response.encode('utf-8')), mimetype='text/plain')
                    svc.files().create(body={'name': f_name, 'parents': [GDRIVE_FOLDER_ID] if GDRIVE_FOLDER_ID else []}, media_body=media, supportsAllDrives=True).execute()
                    st.success(f"נשמר כ-{f_name}")
