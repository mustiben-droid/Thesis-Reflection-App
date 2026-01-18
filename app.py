import json
import base64
import os
import io
from datetime import date, datetime
import pandas as pd
import streamlit as st
from google import genai
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload

# --- 1. הגדרות RTL ועיצוב ---
DATA_FILE = "reflections.jsonl"
MASTER_FILENAME = "All_Observations_Master.xlsx"
GDRIVE_FOLDER_ID = st.secrets.get("GDRIVE_FOLDER_ID")

CLASS_ROSTER = ["נתנאל", "רועי", "אסף", "עילאי", "טדי", "גאל", "אופק", "דניאל.ר", "אלי", "טיגרן", "פולינה.ק", "תלמיד אחר..."]
TAGS_OPTIONS = ["התעלמות מקווים נסתרים", "בלבול בין היטלים", "קושי ברוטציה מנטלית", "טעות בפרופורציות", "קושי במעבר בין היטלים", "שימוש בכלי מדידה", "סיבוב פיזי של המודל", "תיקון עצמי", "עבודה עצמאית שוטפת"]

st.set_page_config(page_title="מערכת תצפית אקדמית - Master 20.0", layout="wide")

st.markdown("""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Heebo:wght@300;400;700&display=swap');
        html, body, .stApp { direction: rtl; text-align: right; font-family: 'Heebo', sans-serif !important; }
        .stButton > button { width: 100%; font-weight: bold; border-radius: 12px; height: 3em; background-color: #28a745; color: white; }
        [data-testid="stSlider"] { direction: ltr !important; }
        .stSuccess { border-radius: 10px; padding: 10px; background-color: #d4edda; color: #155724; }
    </style>
""", unsafe_allow_html=True)

# --- 2. פונקציות Google Drive ---
def get_drive_service():
    try:
        json_str = base64.b64decode(st.secrets["GDRIVE_SERVICE_ACCOUNT_B64"]).decode("utf-8")
        creds = Credentials.from_service_account_info(json.loads(json_str), scopes=["https://www.googleapis.com/auth/drive"])
        return build("drive", "v3", credentials=creds)
    except: return None

def load_master_from_drive(svc):
    try:
        query = f"name = '{MASTER_FILENAME}' and trashed = false"
        res = svc.files().list(q=query, spaces='drive', supportsAllDrives=True, includeItemsFromAllDrives=True).execute().get('files', [])
        target = next((f for f in res if f['name'] == MASTER_FILENAME), None)
        if not target: return None, None
        request = svc.files().get_media(fileId=target['id'])
        fh = io.BytesIO(); downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done: _, done = downloader.next_chunk()
        fh.seek(0)
        return pd.read_excel(fh), target['id']
    except: return None, None

def update_master_in_drive(new_data_df, svc):
    try:
        existing_df, file_id = load_master_from_drive(svc)
        df = pd.concat([existing_df, new_data_df], ignore_index=True) if existing_df is not None else new_data_df
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False)
        output.seek(0); media = MediaIoBaseUpload(output, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        if file_id: svc.files().update(fileId=file_id, media_body=media, supportsAllDrives=True).execute()
        else:
            meta = {'name': MASTER_FILENAME}
            if GDRIVE_FOLDER_ID: meta['parents'] = [GDRIVE_FOLDER_ID]
            svc.files().create(body=meta, media_body=media, supportsAllDrives=True).execute()
        return True
    except: return False

# --- 3. ממשק המשתמש ---
if "it" not in st.session_state: st.session_state.it = 0
if "chat_history" not in st.session_state: st.session_state.chat_history = []
if "drive_context" not in st.session_state: st.session_state.drive_context = ""

svc = get_drive_service()
st.title("🎓 יומן תצפית תזה - גרסה 20.0 (הכול בפנים)")
tab1, tab2, tab3 = st.tabs(["📝 הזנה וצ'אט", "🔄 סנכרון וניהול", "🤖 ניתוח מגמות"])

with tab1:
    col_in, col_chat = st.columns([1.2, 1])
    with col_in:
        with st.container(border=True):
            it = st.session_state.it
            c1, c2 = st.columns(2)
            with c1:
                name_sel = st.selectbox("👤 בחר סטודנט", CLASS_ROSTER, key=f"n_{it}")
                student_name = st.text_input("שם חופשי:", key=f"fn_{it}") if name_sel == "תלמיד אחר..." else name_sel
            with c2:
                work_method = st.radio("🛠️ משתנה מחקר:", ["🧊 בעזרת גוף מודפס", "🎨 ללא גוף (דמיון)"], key=f"wm_{it}", horizontal=True)

            # כפתור טעינת היסטוריה לטובת ה-AI
            if st.button("🔍 טען היסטוריה מהדרייב (לזיהוי וצ'אט)"):
                df, _ = load_master_from_drive(svc)
                if df is not None:
                    df['student_name'] = df['student_name'].astype(str).str.strip()
                    student_info = df[df['student_name'].str.contains(student_name.strip(), na=False, case=False)]
                    if not student_info.empty:
                        st.session_state.drive_context = student_info[['date', 'challenge', 'interpretation']].to_string()
                        st.success(f"✅ נמצאו {len(student_info)} תצפיות קודמות עבור {student_name}.")
                    else: st.info(f"💡 אין היסטוריה קודמת עבור {student_name}.")

            st.markdown("### 📊 מדדים כמותיים (ציונים וזמנים)")
            q1, q2 = st.columns(2)
            with q1: drawings_count = st.number_input("כמות שרטוטים", min_value=0, key=f"dc_{it}")
            with q2: duration_min = st.number_input("זמן עבודה (דקות)", min_value=0, step=5, key=f"dm_{it}")
            
            m1, m2 = st.columns(2)
            with m1:
                cat_convert_rep = st.slider("המרת ייצוגים (1-5)", 1, 5, 3, key=f"s1_{it}")
                cat_dims_props = st.slider("פרופורציות ומידות (1-5)", 1, 5, 3, key=f"s2_{it}")
                cat_proj_trans = st.slider("מעבר בין היטלים (1-5)", 1, 5, 3, key=f"s3_{it}")
            with m2:
                cat_3d_support = st.slider("שימוש במודל עזר (1-5)", 1, 5, 3, key=f"s4_{it}")
                cat_self_efficacy = st.slider("תחושת מסוגלות (1-5)", 1, 5, 3, key=f"s5_{it}")

            st.divider()
            challenge = st.text_area("🗣️ תיאור קשיים (תצפית)", key=f"ch_{it}")
            done = st.text_area("👀 פעולות שבוצעו", key=f"do_{it}")
            interpretation = st.text_area("🧠 פרשנות מחקרית", key=f"int_{it}")
            tags = st.multiselect("🏷️ תגיות אבחון", TAGS_OPTIONS, key=f"t_{it}")

            if st.button("💾 שמור תצפית"):
                if not challenge: st.error("חובה למלא תיאור קושי.")
                else:
                    entry = {
                        "date": date.today().isoformat(), "student_name": student_name,
                        "work_method": work_method, "drawings_count": drawings_count,
                        "duration_min": duration_min, "cat_convert_rep": cat_convert_rep,
                        "cat_dims_props": cat_dims_props, "cat_proj_trans": cat_proj_trans,
                        "cat_3d_support": cat_3d_support, "cat_self_efficacy": cat_self_efficacy,
                        "challenge": challenge, "done": done, "interpretation": interpretation,
                        "tags": str(tags), "timestamp": datetime.now().isoformat()
                    }
                    with open(DATA_FILE, "a", encoding="utf-8") as f:
                        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                    st.success("התצפית נשמרה מקומית. זכור לסנכרן בטאב 2!")
                    st.session_state.it += 1
                    st.rerun()

    with col_chat:
        st.subheader(f"🤖 עוזר מחקר חכם")
        chat_cont = st.container(height=500)
        for q, a in st.session_state.chat_history:
            with chat_cont: st.chat_message("user").write(q); st.chat_message("assistant").write(a)
        
        user_q = st.chat_input("שאל על הסטודנט...")
        if user_q:
            client = genai.Client(api_key=st.secrets["GOOGLE_API_KEY"])
            prompt = f"נתח את {student_name} על בסיס היסטוריית דרייב:\n{st.session_state.drive_context}\nשאלה: {user_q}. צטט APA 7, מקורות 2014-2026."
            res = client.models.generate_content(model="gemini-2.0-flash", contents=prompt, config={'tools': [{'google_search': {}}]} )
            st.session_state.chat_history.append((user_q, res.text)); st.rerun()

with tab2:
    st.header("🔄 מרכז סנכרון")
    if os.path.exists(DATA_FILE):
        local_df = pd.read_json(DATA_FILE, lines=True)
        st.dataframe(local_df.tail(10))
        if st.button("🚀 סנכרן את כל הנתונים החדשים לדרייב"):
            with st.spinner("מעדכן מאסטר..."):
                all_entries = [json.loads(l) for l in open(DATA_FILE, "r", encoding="utf-8")]
                if update_master_in_drive(pd.DataFrame(all_entries), svc):
                    st.success("הסנכרון הושלם בהצלחה!")
    else: st.info("אין נתונים חדשים להצגה.")

with tab3:
    st.header("🤖 ניתוח מגמות רוחבי")
    if st.button("✨ בצע ניתוח עומק אקדמי מכל הנתונים"):
        if svc:
            with st.spinner("סורק את כל קובץ המאסטר..."):
                df, _ = load_master_from_drive(svc)
                if df is not None:
                    summary = df[['student_name', 'work_method', 'cat_proj_trans', 'interpretation', 'challenge']].to_string()
                    client = genai.Client(api_key=st.secrets["GOOGLE_API_KEY"])
                    prompt = f"בצע ניתוח מגמות אקדמי (2014-2026) בפורמט APA על בסיס הנתונים: {summary}"
                    response = client.models.generate_content(model="gemini-2.0-flash", contents=prompt, config={'tools': [{'google_search': {}}]} )
                    st.markdown(response.text)
