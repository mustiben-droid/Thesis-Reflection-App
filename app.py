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

# --- 1. הגדרות ועיצוב RTL ---
DATA_FILE = "reflections.jsonl"
MASTER_FILENAME = "All_Observations_Master.xlsx"
GDRIVE_FOLDER_ID = st.secrets.get("GDRIVE_FOLDER_ID") 

CLASS_ROSTER = ["נתנאל", "רועי", "אסף", "עילאי", "טדי", "גאל", "אופק", "דניאל.ר", "אלי", "טיגרן", "פולינה.ק", "תלמיד אחר..."]
OBSERVATION_TAGS = ["התעלמות מקווים נסתרים", "בלבול בין היטלים", "קושי ברוטציה מנטלית", "טעות בפרופורציות", "קושי במעבר בין היטלים", "שימוש בכלי מדידה", "סיבוב פיזי של המודל", "תיקון עצמי", "עבודה עצמאית שוטפת"]

st.set_page_config(page_title="מערכת תצפית - גרסה 28.0", layout="wide")

st.markdown("""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Heebo:wght@300;400;700&display=swap');
        html, body, .stApp { direction: rtl; text-align: right; font-family: 'Heebo', sans-serif !important; }
        .stTextInput input, .stTextArea textarea, .stSelectbox > div > div { direction: rtl; text-align: right; }
        [data-testid="stSlider"] { direction: ltr !important; }
        .stButton > button { width: 100%; font-weight: bold; border-radius: 12px; height: 3em; background-color: #28a745; color: white; }
    </style>
""", unsafe_allow_html=True)

# --- 2. פונקציות Google Drive ---
def get_drive_service():
    try:
        json_str = base64.b64decode(st.secrets["GDRIVE_SERVICE_ACCOUNT_B64"]).decode("utf-8")
        creds = Credentials.from_service_account_info(json.loads(json_str), scopes=["https://www.googleapis.com/auth/drive"])
        return build("drive", "v3", credentials=creds)
    except: return None

def upload_file_to_drive(uploaded_file, svc):
    try:
        file_metadata = {'name': uploaded_file.name}
        if GDRIVE_FOLDER_ID: file_metadata['parents'] = [GDRIVE_FOLDER_ID]
        media = MediaIoBaseUpload(io.BytesIO(uploaded_file.getvalue()), mimetype=uploaded_file.type)
        file = svc.files().create(body=file_metadata, media_body=media, fields='id, webViewLink', supportsAllDrives=True).execute()
        return file.get('webViewLink')
    except: return "Error"

def fetch_history_from_drive(student_name, svc):
    try:
        query = f"name = '{MASTER_FILENAME}' and trashed = false"
        res = svc.files().list(q=query, spaces='drive', supportsAllDrives=True, includeItemsFromAllDrives=True).execute().get('files', [])
        if not res: return ""
        file_id = res[0]['id']; request = svc.files().get_media(fileId=file_id)
        fh = io.BytesIO(); downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done: _, done = downloader.next_chunk()
        fh.seek(0); df = pd.read_excel(fh)
        target = str(student_name).strip()
        df['student_name'] = df['student_name'].astype(str).str.strip()
        student_data = df[df['student_name'].str.contains(target, na=False, case=False)]
        if student_data.empty: return ""
        hist = ""
        for _, row in student_data.tail(10).fillna("").iterrows():
            hist += f"תאריך: {row.get('date')} | קושי: {row.get('challenge')} | פרשנות: {row.get('interpretation')}\n"
        return hist
    except: return ""

def update_master_in_drive(new_data_df, svc):
    try:
        existing_df, file_id = load_master_from_drive_internal(svc)
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

def load_master_from_drive_internal(svc):
    query = f"name = '{MASTER_FILENAME}' and trashed = false"
    res = svc.files().list(q=query, spaces='drive', supportsAllDrives=True, includeItemsFromAllDrives=True).execute().get('files', [])
    target = next((f for f in res if f['name'] == MASTER_FILENAME), None)
    if not target: return None, None
    request = svc.files().get_media(fileId=target['id'])
    fh = io.BytesIO(); downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done: _, done = downloader.next_chunk()
    fh.seek(0); return pd.read_excel(fh), target['id']

# --- 3. ממשק המשתמש ---
if "it" not in st.session_state: st.session_state.it = 0
if "chat_history" not in st.session_state: st.session_state.chat_history = []
if "student_context" not in st.session_state: st.session_state.student_context = ""
if "last_selected_student" not in st.session_state: st.session_state.last_selected_student = ""

svc = get_drive_service()
st.title("🎓 מערכת תצפית תזה - גרסה 28.0 (דיוק נתונים)")
tab1, tab2, tab3 = st.tabs(["📝 הזנה וצ'אט", "🔄 סנכרון", "🤖 ניתוח"])

with tab1:
    col_in, col_chat = st.columns([1.2, 1])
    with col_in:
        with st.container(border=True):
            it = st.session_state.it
            c1, c2 = st.columns(2)
            with c1:
                name_sel = st.selectbox("👤 בחר סטודנט", CLASS_ROSTER, key=f"n_{it}")
                student_name = st.text_input("שם חופשי:", key=f"fn_{it}") if name_sel == "תלמיד אחר..." else name_sel
                
                # ניקוי זיכרון הצ'אט אם הסטודנט הוחלף
                if student_name != st.session_state.last_selected_student:
                    st.session_state.chat_history = []
                    st.session_state.student_context = ""
                    st.session_state.last_selected_student = student_name

                # טעינת היסטוריה
                drive_history = fetch_history_from_drive(student_name, svc) if (student_name and svc) else ""
                if drive_history:
                    st.success(f"✅ נתוני {student_name} נטענו.")
                    st.session_state.student_context = drive_history

            with c2:
                work_method = st.radio("🛠️ סוג תרגול:", ["🧊 בעזרת גוף מודפס", "🎨 ללא גוף (דמיון)"], key=f"wm_{it}", horizontal=True)

            st.markdown("### 📊 מדדים כמותיים")
            q1, q2 = st.columns(2)
            with q1: drawings_count = st.number_input("כמות שרטוטים", min_value=0, step=1, key=f"dc_{it}")
            with q2: duration_min = st.number_input("זמן עבודה (דקות)", min_value=0, step=5, key=f"dm_{it}")

            m1, m2 = st.columns(2)
            with m1:
                cat_convert_rep = st.slider("המרת ייצוגים", 1, 5, 3, key=f"s1_{it}")
                cat_dims_props = st.slider("פרופורציות", 1, 5, 3, key=f"s2_{it}")
                cat_proj_trans = st.slider("מעבר בין היטלים", 1, 5, 3, key=f"s3_{it}")
            with m2:
                cat_3d_support = st.slider("שימוש במודל", 1, 5, 3, key=f"s4_{it}")
                cat_self_efficacy = st.slider("מסוגלות", 1, 5, 3, key=f"s5_{it}")

            st.divider()
            tags = st.multiselect("🏷️ תגיות אבחון", OBSERVATION_TAGS, key=f"t_{it}")
            challenge = st.text_area("🗣️ תיאור קשיים ותצפית", key=f"ch_{it}")
            done = st.text_area("👀 פעולות שבוצעו", key=f"do_{it}")
            interpretation = st.text_area("🧠 פרשנות מחקרית", key=f"int_{it}")
            uploaded_files = st.file_uploader("📷 צרף תמונות", accept_multiple_files=True, key=f"up_{it}")

            if st.button("💾 שמור תצפית"):
                if not challenge: st.error("חובה למלא תיאור קושי.")
                else:
                    links = []
                    if uploaded_files and svc:
                        for f in uploaded_files: links.append(upload_file_to_drive(f, svc))
                    entry = {
                        "date": date.today().isoformat(), "student_name": student_name,
                        "work_method": work_method, "drawings_count": drawings_count,
                        "duration_min": duration_min, "challenge": challenge,
                        "interpretation": interpretation, "done": done,
                        "cat_convert_rep": cat_convert_rep, "cat_dims_props": cat_dims_props,
                        "cat_proj_trans": cat_proj_trans, "cat_3d_support": cat_3d_support,
                        "cat_self_efficacy": cat_self_efficacy, "tags": str(tags),
                        "file_links": ", ".join(links), "timestamp": datetime.now().isoformat()
                    }
                    with open(DATA_FILE, "a", encoding="utf-8") as f:
                        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                    st.success("נשמר מקומית.")
                    st.session_state.it += 1
                    st.rerun()

    with col_chat:
        st.subheader(f"🤖 עוזר מחקר חכם")
        chat_cont = st.container(height=500)
        for q, a in st.session_state.chat_history:
            with chat_cont: st.chat_message("user").write(q); st.chat_message("assistant").write(a)
        user_q = st.chat_input("שאל על הסטודנט הנבחר...")
        if user_q:
            client = genai.Client(api_key=st.secrets["GOOGLE_API_KEY"])
            # Prompt נקי ללא חיפוש חיצוני וללא המצאת רפרנסים
            prompt = f"""
            אתה עוזר מחקר המנתח תצפיות על סטודנט יחיד: {student_name}.
            הסתמך אך ורק על נתוני התצפית הבאים:
            {st.session_state.student_context}
            
            אל תחפש מקורות חיצוניים ואל תמציא רפרנסים אקדמיים. 
            ספק תובנות המבוססות על המגמות שאתה רואה בנתונים שסופקו לך בלבד.
            שאלה: {user_q}
            """
            res = client.models.generate_content(model="gemini-2.0-flash", contents=prompt)
            st.session_state.chat_history.append((user_q, res.text)); st.rerun()

with tab2:
    st.header("🔄 מרכז סנכרון")
    if os.path.exists(DATA_FILE):
        if st.button("🚀 עדכן את הדרייב", use_container_width=True):
            all_entries = [json.loads(l) for l in open(DATA_FILE, "r", encoding="utf-8")]
            if update_master_in_drive(pd.DataFrame(all_entries), svc):
                st.success("הסנכרון הושלם!")
    else: st.write("✨ הכל מעודכן.")

with tab3:
    st.header("🤖 ניתוח מגמות")
    if st.button("✨ בצע ניתוח עומק"):
        if svc:
            df, _ = load_master_from_drive_internal(svc)
            if df is not None:
                summary = df.to_string()
                client = genai.Client(api_key=st.secrets["GOOGLE_API_KEY"])
                prompt = f"נתח מגמות בנתונים אלו וספק תובנות מחקריות. אל תמציא רפרנסים: {summary}"
                response = client.models.generate_content(model="gemini-2.0-flash", contents=prompt)
                st.markdown(response.text)
