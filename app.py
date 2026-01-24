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

st.set_page_config(page_title="מערכת תצפית - 52.0", layout="wide")

st.markdown("""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Heebo:wght@300;400;700&display=swap');
        html, body, .stApp { direction: rtl; text-align: right; font-family: 'Heebo', sans-serif !important; }
        [data-testid="stSlider"] { direction: ltr !important; }
        .stButton > button { width: 100%; font-weight: bold; border-radius: 12px; height: 3em; }
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
                fh = io.BytesIO(); downloader = MediaIoBaseDownload(fh, req)
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
        df['name_clean'] = df['student_name'].astype(str).str.strip().apply(normalize_name)
    return df

# --- 2. אתחול ---
svc = get_drive_service()
full_df = load_full_dataset(svc)
if "it" not in st.session_state: st.session_state.it = 0
if "last_selected_student" not in st.session_state: st.session_state.last_selected_student = ""
if "show_success_bar" not in st.session_state: st.session_state.show_success_bar = False
if "last_feedback" not in st.session_state: st.session_state.last_feedback = ""

# --- 3. ממשק ---
tab1, tab2, tab3 = st.tabs(["📝 הזנה ומשוב", "🔄 סנכרון", "📊 ניתוח"])

with tab1:
    it = st.session_state.it
    student_name = st.selectbox("👤 בחר סטודנט", CLASS_ROSTER, key=f"sel_{it}")
    
    if student_name != st.session_state.last_selected_student:
        target = normalize_name(student_name)
        match = full_df[full_df['name_clean'] == target] if not full_df.empty else pd.DataFrame()
        st.session_state.show_success_bar = not match.empty
        st.session_state.student_context = match.tail(15).to_string() if not match.empty else ""
        st.session_state.last_selected_student = student_name
        st.rerun()

    if st.session_state.show_success_bar:
        st.success(f"✅ נמצאה היסטוריה עבור {student_name}.")
    else:
        st.info(f"ℹ️ {student_name}: אין תצפיות קודמות.")

    st.markdown("---")
   # --- שלב 2: בניית הטופס המעודכן ---
    work_method = st.radio("🛠️ צורת עבודה:", ["🧊 בעזרת גוף מודפס", "🎨 ללא גוף (דמיון)"], key=f"wm_{it}", horizontal=True)

    # --- שלב 2: בניית הטופס המעודכן ---
    work_method = st.radio("🛠️ צורת עבודה:", ["🧊 בעזרת גוף מודפס", "🎨 ללא גוף (דמיון)"], key=f"wm_{it}", horizontal=True)

  st.markdown("### 📊 מדדים כמותיים (1-5)")
    m1, m2 = st.columns(2)
    with m1:
        s1 = st.slider("המרת ייצוגים", 1, 5, 3, key=f"s1_{it}")
        s2 = st.slider("מעבר בין היטלים", 1, 5, 3, key=f"s2_{it}")
    with m2:
        s3 = st.slider("שימוש במודל 3D", 1, 5, 3, key=f"s3_{it}")
        s_diff = st.slider("📉 רמת קושי התרגיל", 1, 5, 3, key=f"sd_{it}")
        # הוספת סליידר פרופורציות:
        s4 = st.slider("📏 פרופורציות ומימדים", 1, 5, 3, key=f"s4_{it}")

    tags = st.multiselect("🏷️ תגיות אבחון", TAGS_OPTIONS, key=f"t_{it}")

    # תיבות טקסט (רק אלו שביקשת)
    ch = st.text_area("🗣️ תצפית שדה (Challenge):", height=150, key=f"ch_{it}", placeholder="מה ראית בפועל?")
    ins = st.text_area("🧠 תובנה/פרשנות (Insight):", height=100, key=f"ins_{it}", placeholder="מה זה מלמד על תהליך החשיבה?")

    # העלאת תמונות
    up_files = st.file_uploader("📷 צרף תמונות (שרטוטים/עבודות)", accept_multiple_files=True, type=['png', 'jpg', 'jpeg'], key=f"up_{it}")

    if st.session_state.last_feedback:
        st.markdown(f'<div class="feedback-box"><b>💡 משוב AI:</b><br>{st.session_state.last_feedback}</div>', unsafe_allow_html=True)

    c_btns = st.columns(2)
    with c_btns[0]:
        if st.button("🔍 בקש רפלקציה (AI)"):
            if ch:
                try:
                    genai.configure(api_key=st.secrets.get("GOOGLE_API_KEY"), transport='rest')
                    model = genai.GenerativeModel('models/gemini-1.5-flash')
                    st.session_state.last_feedback = model.generate_content(f"נתח תצפית אקדמית עבור {student_name}: {ch}").text
                    st.rerun()
                except Exception as e: st.error(f"שגיאת AI: {e}")
            else: st.warning("כתבי תצפית קודם.")
            
    with c_btns[1]:
        if st.button("💾 שמור תצפית", type="primary"):
            if ch:
                with st.spinner("שומר ומעלה נתונים..."):
                    links = []
                    if up_files and svc:
                        for f in up_files:
                            try:
                                f_meta = {'name': f.name, 'parents': [GDRIVE_FOLDER_ID] if GDRIVE_FOLDER_ID else []}
                                media = MediaIoBaseUpload(io.BytesIO(f.getvalue()), mimetype=f.type)
                                res = svc.files().create(body=f_meta, media_body=media, fields='webViewLink', supportsAllDrives=True).execute()
                                links.append(res.get('webViewLink'))
                            except: pass
                    
                    entry = {
                        "date": date.today().isoformat(), "student_name": student_name, "work_method": work_method,
                        "challenge": ch, "insight": ins, "difficulty": s_diff,
                        "cat_convert_rep": int(s1), "cat_proj_trans": int(s2), "cat_3d_support": int(s3),
                        "tags": tags, "file_links": links, "timestamp": datetime.now().isoformat()
                    }
                    with open(DATA_FILE, "a", encoding="utf-8") as f:
                        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                    st.session_state.it += 1
                    st.session_state.last_feedback = ""
                    st.rerun()
                    
            else: st.error("חובה להזין תיאור תצפית.")

    tags = st.multiselect("🏷️ תגיות אבחון", TAGS_OPTIONS, key=f"t_{it}")

    # תיבות טקסט (רק אלו שביקשת)
    ch = st.text_area("🗣️ תצפית שדה (Challenge):", height=150, key=f"ch_{it}", placeholder="מה ראית בפועל?")
    ins = st.text_area("🧠 תובנה/פרשנות (Insight):", height=100, key=f"ins_{it}", placeholder="מה זה מלמד על תהליך החשיבה?")

    # העלאת תמונות
    up_files = st.file_uploader("📷 צרף תמונות (שרטוטים/עבודות)", accept_multiple_files=True, type=['png', 'jpg', 'jpeg'], key=f"up_{it}")

    if st.session_state.last_feedback:
        st.markdown(f'<div class="feedback-box"><b>💡 משוב AI:</b><br>{st.session_state.last_feedback}</div>', unsafe_allow_html=True)

    c_btns = st.columns(2)
    with c_btns[0]:
        if st.button("🔍 בקש רפלקציה (AI)"):
            if ch:
                try:
                    genai.configure(api_key=st.secrets.get("GOOGLE_API_KEY"), transport='rest')
                    model = genai.GenerativeModel('models/gemini-1.5-flash')
                    st.session_state.last_feedback = model.generate_content(f"נתח תצפית אקדמית עבור {student_name}: {ch}").text
                    st.rerun()
                except Exception as e: st.error(f"שגיאת AI: {e}")
            else: st.warning("כתבי תצפית קודם.")
            
    with c_btns[1]:
        if st.button("💾 שמור תצפית", type="primary"):
            if ch:
                with st.spinner("שומר ומעלה נתונים..."):
                    links = []
                    if up_files and svc:
                        for f in up_files:
                            try:
                                f_meta = {'name': f.name, 'parents': [GDRIVE_FOLDER_ID] if GDRIVE_FOLDER_ID else []}
                                media = MediaIoBaseUpload(io.BytesIO(f.getvalue()), mimetype=f.type)
                                res = svc.files().create(body=f_meta, media_body=media, fields='webViewLink', supportsAllDrives=True).execute()
                                links.append(res.get('webViewLink'))
                            except: pass
                    
                    entry = {
                        "date": date.today().isoformat(), "student_name": student_name, "work_method": work_method,
                        "challenge": ch, "insight": ins, "difficulty": s_diff,
                        "cat_convert_rep": int(s1), "cat_proj_trans": int(s2), "cat_3d_support": int(s3),
                        "tags": tags, "file_links": links, "timestamp": datetime.now().isoformat()
                    }
                    with open(DATA_FILE, "a", encoding="utf-8") as f:
                        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                    st.session_state.it += 1
                    st.session_state.last_feedback = ""
                    st.rerun()
            else: st.error("חובה להזין תיאור תצפית.")



