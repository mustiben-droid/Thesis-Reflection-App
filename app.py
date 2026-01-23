import json, base64, os, io, time, pandas as pd, streamlit as st
import google.generativeai as genai
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload
from datetime import date, datetime

# --- 0. הגדרות ועיצוב ---
DATA_FILE = "reflections.jsonl"
MASTER_FILENAME = "All_Observations_Master.xlsx"
CLASS_ROSTER = ["נתנאל", "רועי", "אסף", "עילאי", "טדי", "גאל", "אופק", "דניאל.ר", "אלי", "טיגרן", "פולינה.ק", "תלמיד אחר..."]
TAGS_OPTIONS = ["התעלמות מקווים נסתרים", "בלבול בין היטלים", "קושי ברוטציה מנטלית", "טעות בפרופורציות", "קושי במעבר בין היטלים", "שימוש בכלי מדידה", "סיבוב פיזי של המודל", "תיקון עצמי", "עבודה עצמאית שוטפת"]
GDRIVE_FOLDER_ID = st.secrets.get("GDRIVE_FOLDER_ID")

st.set_page_config(page_title="מערכת תצפית - 75.0", layout="wide")

st.markdown("""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Heebo:wght@300;400;700&display=swap');
        html, body, .stApp { direction: rtl; text-align: right; font-family: 'Heebo', sans-serif !important; }
        [data-testid="stSlider"] { direction: ltr !important; }
        .stButton > button { width: 100%; font-weight: bold; border-radius: 12px; background-color: #28a745; color: white; height: 3em; }
    </style>
""", unsafe_allow_html=True)

# --- 1. מודול טעינה ומיזוג עמודות ---
def normalize_name(name):
    if not isinstance(name, str): return ""
    return name.replace(" ", "").replace(".", "").replace("־", "").replace("-", "").strip()

def robust_map_columns(df):
    if df is None or df.empty: return pd.DataFrame()
    df.columns = [str(c).strip() for c in df.columns]
    
    # מיפוי: מפתח = שם יעד בקוד, ערך = שמות אפשריים באקסל שלך
    mapping = {
        'cat_convert_rep': ['cat_convert_rep', 'score_conv', 'score_spatial'],
        'cat_proj_trans': ['cat_proj_trans', 'score_proj', 'score_views'],
        'cat_self_efficacy': ['cat_self_efficacy', 'score_efficacy'],
        'cat_3d_support': ['cat_3d_support', 'score_model'],
        'work_method': ['work_method', 'physical_model'],
        'exercise_difficulty': ['exercise_difficulty', 'difficulty']
    }
    
    for target, sources in mapping.items():
        for s in sources:
            if s in df.columns:
                if target not in df.columns:
                    df[target] = df[s]
                else:
                    # אם עמודת היעד קיימת אך ריקה, מלא אותה מהמקור
                    df[target] = df[target].fillna(df[s])
    
    if 'student_name' not in df.columns:
        possible = [c for c in df.columns if "student" in c.lower() or "name" in c.lower()]
        if possible: df.rename(columns={possible[0]: 'student_name'}, inplace=True)
    
    return df

@st.cache_resource
def get_drive_service():
    try:
        b64 = st.secrets.get("GDRIVE_SERVICE_ACCOUNT_B64")
        creds = Credentials.from_service_account_info(json.loads(base64.b64decode(b64).decode("utf-8")), 
                                                     scopes=["https://www.googleapis.com/auth/drive"])
        return build("drive", "v3", credentials=creds)
    except: return None

def load_full_dataset(svc):
    all_dfs = []
    if svc:
        try:
            res = svc.files().list(q=f"name = '{MASTER_FILENAME}'", supportsAllDrives=True, includeItemsFromAllDrives=True).execute().get('files', [])
            if res:
                fh = io.BytesIO()
                downloader = MediaIoBaseDownload(fh, svc.files().get_media(fileId=res[0]['id']))
                done = False
                while not done: _, done = downloader.next_chunk()
                fh.seek(0)
                all_dfs.append(robust_map_columns(pd.read_excel(fh)))
        except: pass
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                all_dfs.append(robust_map_columns(pd.DataFrame([json.loads(l) for l in f if l.strip()])))
        except: pass
    
    if not all_dfs: return pd.DataFrame()
    df = pd.concat(all_dfs, ignore_index=True, sort=False)
    if 'student_name' in df.columns:
        df['name_clean'] = df['student_name'].apply(normalize_name)
    return df

def get_ai_response(context):
    try:
        genai.configure(api_key=st.secrets["GOOGLE_API_KEY"], transport='rest')
        model = genai.GenerativeModel('gemini-1.5-flash')
        p = f"Analyze Student {context.get('name')}:\nHistory: {context.get('history')}\nQuestion: {context.get('question')}"
        return model.generate_content(p).text
    except: return "ה-AI אינו זמין כרגע."

# --- 2. ניהול מצב ---
if "it" not in st.session_state: st.session_state.it = 0
if "chat_history" not in st.session_state: st.session_state.chat_history = []
if "last_selected" not in st.session_state: st.session_state.last_selected = ""
if "show_strip" not in st.session_state: st.session_state.show_strip = False

svc = get_drive_service()
full_df = load_full_dataset(svc)

tab1, tab2, tab3 = st.tabs(["📝 הזנה וצ'אט", "🔄 סנכרון", "📊 ניתוח מחקרי"])

with tab1:
    c_in, c_chat = st.columns([1.2, 1])
    with c_in:
        it = st.session_state.it
        student_name = st.selectbox("👤 בחר סטודנט", CLASS_ROSTER, key=f"sel_{it}")
        
        # לוגיקת הסטריפ הירוק
        if student_name != st.session_state.last_selected:
            target = normalize_name(student_name)
            match = full_df[full_df['name_clean'] == target] if not full_df.empty else pd.DataFrame()
            st.session_state.show_strip = not match.empty
            st.session_state.last_selected = student_name
            st.session_state.chat_history = []
            st.rerun()

        if st.session_state.show_strip:
            st.success(f"✅ נמצאה היסטוריה עבור {student_name}. המערכת מסונכרנת.")
        else:
            st.info(f"ℹ️ אין תצפיות קודמות ל-{student_name}.")

        c1, c2 = st.columns(2)
        with c1:
            meth = st.radio("🛠️ תרגול:", ["🧊 גוף מודפס", "🎨 דמיון"], key=f"wm_{it}")
            diff = st.select_slider("📉 קושי:", ["קל", "בינוני", "קשה"], key=f"ed_{it}")
        with c2:
            s1 = st.slider("המרה (1-5)", 1, 5, 3, key=f"s1_{it}")
            s2 = st.slider("היטלים (1-5)", 1, 5, 3, key=f"s2_{it}")
            s3 = st.slider("מודל (1-5)", 1, 5, 3, key=f"s3_{it}")
            s4 = st.slider("מסוגלות (1-5)", 1, 5, 3, key=f"s4_{it}")

        tags = st.multiselect("🏷️ תגיות אבחון", TAGS_OPTIONS, key=f"t_{it}")
        challenge = st.text_area("🗣️ תיאור התצפית", key=f"ch_{it}")
        interp = st.text_area("🧠 פרשנות מחקרית", key=f"int_{it}")

        if st.button("💾 שמור תצפית"):
            if challenge:
                entry = {"date": str(date.today()), "student_name": student_name, "work_method": meth, "exercise_difficulty": diff, "cat_convert_rep": s1, "cat_proj_trans": s2, "cat_3d_support": s3, "cat_self_efficacy": s4, "tags": tags, "challenge": challenge, "interpretation": interp, "timestamp": datetime.now().isoformat()}
                with open(DATA_FILE, "a", encoding="utf-8") as f: f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                st.session_state.it += 1
                st.rerun()

    with c_chat:
        st.subheader(f"💬 התכתבות: {student_name}")
        chat_cont = st.container(height=450)
        for q, a in st.session_state.chat_history:
            chat_cont.chat_message("user").write(q); chat_cont.chat_message("assistant").write(a)
        if p := st.chat_input("שאל על הסטודנט..."):
            target = normalize_name(student_name)
            match = full_df[full_df['name_clean'] == target] if not full_df.empty else pd.DataFrame()
            ans = get_ai_response({"name": student_name, "history": match.tail(10).to_string(), "question": p})
            st.session_state.chat_history.append((p, ans)); st.rerun()

with tab2:
    if st.button("🚀 סנכרן הכל לדרייב"):
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, "r", encoding="utf-8") as f: l_ = [json.loads(line) for line in f if line.strip()]
            final = pd.concat([full_df, pd.DataFrame(l_)], ignore_index=True).drop_duplicates(subset=['student_name', 'timestamp'], keep='last')
            buf = io.BytesIO()
            with pd.ExcelWriter(buf, engine='openpyxl') as w: final.to_excel(w, index=False)
            buf.seek(0)
            res = svc.files().list(q=f"name = '{MASTER_FILENAME}'", supportsAllDrives=True).execute().get('files', [])
            media = MediaIoBaseUpload(buf, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            if res: svc.files().update(fileId=res[0]['id'], media_body=media, supportsAllDrives=True).execute()
            else: svc.files().create(body={'name': MASTER_FILENAME, 'parents': [GDRIVE_FOLDER_ID] if GDRIVE_FOLDER_ID else []}, media_body=media, supportsAllDrives=True).execute()
            os.remove(DATA_FILE); st.success("בוצע!"); st.rerun()

with tab3:
    if full_df.empty: 
        st.info("אין נתונים להצגת ניתוח.")
    else:
        st.header("📊 ניתוח מגמות")
        m = st.radio("סוג ניתוח", ["אישי (אורך)", "כיתתי (רוחב)"], horizontal=True)
        
        if m == "אישי (אורך)":
            # סינון סטודנטים שיש להם לפחות שורה אחת של דאטה
            valid_names = [n for n in full_df['student_name'].unique() if pd.notna(n)]
            sel = st.selectbox("בחר סטודנט", valid_names)
            sd = full_df[full_df['student_name'] == sel].sort_values('date')
            
            # בדיקה אילו עמודות כמותיות קיימות ואינן ריקות
            metrics = ['cat_convert_rep', 'cat_proj_trans', 'cat_3d_support', 'cat_self_efficacy']
            available_metrics = [c for c in metrics if c in sd.columns and
