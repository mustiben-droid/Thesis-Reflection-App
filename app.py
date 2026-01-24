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

st.set_page_config(page_title="מערכת תצפית מחקרית - 46.0", layout="wide")

st.markdown("""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Heebo:wght@300;400;700&display=swap');
        html, body, .stApp { direction: rtl; text-align: right; font-family: 'Heebo', sans-serif !important; }
        [data-testid="stSlider"] { direction: ltr !important; }
        .stButton > button { width: 100%; font-weight: bold; border-radius: 12px; height: 3em; }
        .stButton button[kind="primary"] { background-color: #28a745; color: white; }
        .feedback-box { 
            background: linear-gradient(135deg, #fdfbfb 0%, #ebedee 100%); 
            padding: 20px; border-radius: 15px; border: 1px solid #ddd; margin: 15px 0; color: #333;
            box-shadow: 0 4px 6px rgba(0,0,0,0.05);
        }
        .feedback-box h4 { color: #2c3e50; margin-top:0; }
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

@st.cache_data(ttl=60)
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

def get_ai_response(prompt_type, context_data):
    api_key = st.secrets.get("GOOGLE_API_KEY")
    if not api_key: return "⚠️ מפתח API חסר"
    try:
        genai.configure(api_key=api_key, transport='rest')
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        if prompt_type == "reflection":
            prompt = f"""
            אתה פרופ' דן רוזנברג, מנחה תזה בכיר בחינוך טכנולוגי.
            נתח את התצפית שכתבה הסטודנטית על {context_data['student_name']}:
            "{context_data['challenge']}"
            
            1. תן ציון איכות מחקרי (1-5).
            2. הצע נוסח אקדמי משופר (3 שורות) לפרק הממצאים.
            3. ציין אם חסר מידע אובייקטיבי.
            """
        elif prompt_type == "chat":
            prompt = f"נתח היסטוריה מחקרית: {str(context_data['history'])[:4000]}. שאלה: {context_data['question']}"
        else: # analysis
            prompt = f"בצע ניתוח תמות (Thematic Analysis) אקדמי על התצפיות הבאות: {context_data['text']}"
            
        return model.generate_content(prompt).text
    except Exception as e: return f"שגיאת AI: {str(e)[:100]}"

# --- 2. אתחול נתונים ---
svc = get_drive_service()
full_df = load_full_dataset(svc)

if "it" not in st.session_state: st.session_state.it = 0
if "chat_history" not in st.session_state: st.session_state.chat_history = []
if "last_selected_student" not in st.session_state: st.session_state.last_selected_student = ""
if "show_success_bar" not in st.session_state: st.session_state.show_success_bar = False
if "last_feedback" not in st.session_state: st.session_state.last_feedback = ""

# --- 3. ממשק משתמש ---
st.title("🎓 מנחה מחקר חכם - גרסה 46.0")
tab1, tab2, tab3 = st.tabs(["📝 הזנה ומשוב", "🔄 סנכרון", "📊 ניתוח"])

with tab1:
    col_in, col_chat = st.columns([1.2, 1])
    with col_in:
        it = st.session_state.it
        student_name = st.selectbox("👤 בחר סטודנט", CLASS_ROSTER, key=f"sel_{it}")
        
        # --- לוגיקת הסליידר הירוק (זיהוי תלמיד) ---
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
            st.success(f"✅ נמצאה היסטוריה עבור {student_name}. הסוכן מעודכן.")
        else:
            st.info(f"ℹ️ {student_name}: אין תצפיות קודמות במערכת.")

        st.markdown("---")
        # --- שדות הזנה מלאים ---
        pl = st.text_area("📋 תכנון למפגש (Planned):", key=f"pl_{it}")
        do = st.text_area("✅ מה בוצע בפועל (Done):", key=f"do_{it}")
        ch = st.text_area("🗣️ תצפית שדה (Challenge):", height=120, key=f"ch_{it}")
        ins = st.text_area("🧠 תובנה/פרשנות (Insight):", key=f"ins_{it}")
        nxt = st.text_area("⏭️ שלב הבא (Next Step):", key=f"nxt_{it}")

        st.markdown("### 📊 מדדים כמותיים (1-5)")
        m1, m2 = st.columns(2)
        with m1:
            s1 = st.slider("המרת ייצוגים", 1, 5, 3, key=f"s1_{it}")
            s2 = st.slider("מעבר בין היטלים", 1, 5, 3, key=f"s2_{it}")
        with m2:
            s3 = st.slider("שימוש במודל 3D", 1, 5, 3, key=f"s3_{it}")
            s4 = st.slider("פרופורציות ומימדים", 1, 5, 3, key=f"s4_{it}")

        tags = st.multiselect("🏷️ תגיות אבחון", TAGS_OPTIONS, key=f"t_{it}")

        if st.session_state.last_feedback:
            st.markdown(f'<div class="feedback-box"><h4>💡 משוב פרופ\' רוזנברג</h4>{st.session_state.last_feedback}</div>', unsafe_allow_html=True)

        c_btns = st.columns(2)
        with c_btns[0]:
            if st.button("🔍 בקש רפלקציה (AI)"):
                if ch: 
                    with st.spinner("המנחה מנתח..."):
                        st.session_state.last_feedback = get_ai_response("reflection", {"student_name": student_name, "challenge": ch})
                        st.rerun()
                else: st.warning("כתבי תצפית קודם.")
        with c_btns[1]:
            if st.button("💾 שמור תצפית", type="primary"):
                if not ch: st.error("חובה להזין תיאור.")
                else:
                    entry = {
                        "date": date.today().isoformat(), "student_name": student_name, "planned": pl, "done": do,
                        "challenge": ch, "insight": ins, "next_step": nxt,
                        "cat_convert_rep": int(s1), "cat_proj_trans": int(s2), 
                        "cat_3d_support": int(s3), "cat_dims_props": int(s4),
                        "tags": tags, "timestamp": datetime.now().isoformat()
                    }
                    with open(DATA_FILE, "a", encoding="utf-8") as f:
                        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                    st.session_state.it += 1; st.session_state.last_feedback = ""; st.rerun()

    with col_chat:
        st.subheader(f"🤖 יועץ: {student_name}")
        chat_cont = st.container(height=450)
        for q, a in st.session_state.chat_history:
            with chat_cont:
                st.chat_message("user").write(q); st.chat_message("assistant").write(a)
        u_q = st.chat_input("שאל את הסוכן...")
        if u_q:
            resp = get_ai_response("chat", {"name": student_name, "history": st.session_state.student_context, "question": u_q})
            st.session_state.chat_history.append((u_q, resp)); st.rerun()

with tab2:
    st.header("🔄 סנכרון לדרייב")
    if os.path.exists(DATA_FILE) and st.button("🚀 סנכרן הכל לדרייב"):
        try:
            with st.spinner("מעלה נתונים..."):
                with open(DATA_FILE, "r", encoding="utf-8") as f:
                    locals_ = [json.loads(l) for l in f if l.strip()]
                df_m = pd.concat([full_df, pd.DataFrame(locals_)], ignore_index=True).drop_duplicates(subset=['student_name', 'timestamp'], keep='last')
                buf = io.BytesIO()
                with pd.ExcelWriter(buf, engine='openpyxl') as w: df_m.to_excel(w, index=False)
                buf.seek(0)
                res = svc.files().list(q=f"name='{MASTER_FILENAME}'", supportsAllDrives=True).execute().get('files', [])
                media = MediaIoBaseUpload(buf, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                if res:
                    svc.files().update(fileId=res[0]['id'], media_body=media, supportsAllDrives=True).execute()
                else:
                    file_metadata = {'name': MASTER_FILENAME}
                    if GDRIVE_FOLDER_ID: file_metadata['parents'] = [GDRIVE_FOLDER_ID]
                    svc.files().create(body=file_metadata, media_body=media, supportsAllDrives=True).execute()
                os.remove(DATA_FILE); st.success("הנתונים סונכרנו!"); st.cache_data.clear(); st.rerun()
        except Exception as e: st.error(f"שגיאה: {e}")

with tab3:
    st.header("📊 ניתוח מחקרי")
    if not full_df.empty:
        mode = st.radio("סוג ניתוח:", ["👤 אישי", "📅 שבועי"], horizontal=True)
        if mode == "👤 אישי":
            sel_s = st.selectbox("בחר סטודנט:", ["כולם"] + sorted(full_df['student_name'].unique().tolist()))
            v_df = full_df if sel_s == "כולם" else full_df[full_df['student_name'] == sel_s]
            st.dataframe(v_df.sort_values(by='date', ascending=False), use_container_width=True)
        else:
            df_an = full_df.copy()
            df_an['date'] = pd.to_datetime(df_an['date'], errors='coerce')
            df_an['week'] = df_an['date'].dt.strftime('%Y - שבוע %U')
            sel_week = st.selectbox("בחר שבוע:", sorted(df_an['week'].dropna().unique(), reverse=True))
            w_df = df_an[df_an['week'] == sel_week]
            st.dataframe(w_df)
            if st.button("✨ הפק ניתוח תמות"):
                txt = "".join([f"תצפית: {r.get('challenge','')} | תובנה: {r.get('insight','')}\n" for _, r in w_df.iterrows()])
                res = get_ai_response("analysis", {"text": txt})
                st.info(res)

# --- Sidebar & Debug ---
st.sidebar.title("🛠️ ניהול ודיבוג")
if st.sidebar.button("🔍 הצג מידע דיבוג"):
    st.sidebar.write("**עמודות:**", full_df.columns.tolist() if not full_df.empty else "ריק")
    if not full_df.empty:
        st.sidebar.write("**שמות מזוהים:**", full_df['student_name'].unique().tolist())
if st.sidebar.button("🔄 רענן נתונים"):
    st.cache_data.clear(); st.rerun()
st.sidebar.write("מצב חיבור לדרייב:", "✅" if svc else "❌")
