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

# --- 1. הגדרות קבועות ועיצוב ---
DATA_FILE = "reflections.jsonl"
GDRIVE_FOLDER_ID = st.secrets.get("GDRIVE_FOLDER_ID") 
MASTER_FILENAME = "All_Observations_Master.xlsx"

CLASS_ROSTER = ["נתנאל", "רועי", "אסף", "עילאי", "טדי", "גאל", "אופק", "דניאל.ר", "אלי", "טיגרן", "פולינה.ק", "תלמיד אחר..."]
OBSERVATION_TAGS = ["התעלמות מקווים נסתרים", "בלבול בין היטלים", "קושי ברוטציה מנטלית", "טעות בפרופורציות", "קושי במעבר בין היטלים", "שימוש בכלי מדידה", "סיבוב פיזי של המודל", "תיקון עצמי", "עבודה עצמאית שוטפת"]

st.set_page_config(page_title="עוזר מחקר לתזה", layout="wide")

st.markdown("""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Heebo:wght@300;400;700&display=swap');
        html, body, .stApp { direction: rtl; text-align: right; font-family: 'Heebo', sans-serif !important; }
        .stTextInput input, .stTextArea textarea, .stSelectbox > div > div { direction: rtl; text-align: right; }
        [data-testid="stSlider"] { direction: ltr !important; }
        .stButton > button { width: 100%; font-weight: bold; border-radius: 10px; }
        .stInfo { border-right: 5px solid #007bff; border-left: none; }
    </style>
""", unsafe_allow_html=True)

# --- 2. פונקציות שירות ודרייב ---
def get_drive_service():
    try:
        json_str = base64.b64decode(st.secrets["GDRIVE_SERVICE_ACCOUNT_B64"]).decode("utf-8")
        creds = Credentials.from_service_account_info(json.loads(json_str), scopes=["https://www.googleapis.com/auth/drive.file"])
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

def update_master_excel(data_to_add, svc):
    try:
        query = f"name = '{MASTER_FILENAME}' and trashed = false"
        if GDRIVE_FOLDER_ID: query += f" and '{GDRIVE_FOLDER_ID}' in parents"
        res = svc.files().list(q=query, supportsAllDrives=True, includeItemsFromAllDrives=True).execute().get('files', [])
        new_df = pd.DataFrame(data_to_add)
        if res:
            file_id = res[0]['id']
            request = svc.files().get_media(fileId=file_id)
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done: _, done = downloader.next_chunk()
            fh.seek(0)
            existing_df = pd.read_excel(fh)
            df = pd.concat([existing_df, new_df]).drop_duplicates(subset=['timestamp', 'student_name'], keep='last')
        else:
            df = new_df
            file_id = None
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False)
        output.seek(0)
        media = MediaIoBaseUpload(output, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        if file_id: svc.files().update(fileId=file_id, media_body=media, supportsAllDrives=True).execute()
        else:
            file_meta = {'name': MASTER_FILENAME}
            if GDRIVE_FOLDER_ID: file_meta['parents'] = [GDRIVE_FOLDER_ID]
            svc.files().create(body=file_meta, media_body=media, supportsAllDrives=True).execute()
        return True
    except: return False

# --- 3. עוזר מחקר אקדמי (Gemini) ---
def chat_with_academic_ai(user_q, entry_data, history):
    try:
        client = genai.Client(api_key=st.secrets["GOOGLE_API_KEY"])
        spatial = entry_data.get('score_spatial', 3)
        views = entry_data.get('score_views', 3)
        model_eff = entry_data.get('score_model', 3)
        efficacy = entry_data.get('score_efficacy', 3)
        
        instruction = f"""
        אתה עוזר מחקר אקדמי מומחה. מנתח תצפית על {entry_data.get('name', 'תלמיד')}.
        מדדים (1-5): תפיסה {spatial}, היטלים {views}, שימוש במודל {model_eff}, מסוגלות {efficacy}.
        מודל פיזי: {entry_data.get('model_status', 'לא ידוע')}.
        חוקים: השתמש במקורות אקדמיים משנת 2014-2026 בלבד, שלב ציטוטים (שם חוקר, שנה) בגוף הטקסט ורשום רשימה ביבליוגרפית בסוף.
        """
        full_context = instruction + "\n\n"
        for q, a in history: full_context += f"חוקר: {q}\nעוזר: {a}\n\n"
        full_context += f"חוקר: {user_q}"
        response = client.models.generate_content(model="gemini-2.0-flash", contents=full_context)
        return response.text
    except Exception as e: return f"שגיאה ב-AI: {str(e)}"

# --- 4. ניהול מצב האפליקציה (Reset) ---
if "form_iteration" not in st.session_state: st.session_state.form_iteration = 0
if "chat_history" not in st.session_state: st.session_state.chat_history = []

def reset_form():
    st.session_state.form_iteration += 1
    st.session_state.chat_history = []

# --- 5. ממשק המשתמש ---
st.title("🎓 יומן תצפית מחקרי חכם")

tab1, tab2, tab3 = st.tabs(["📝 תצפית ושיחה", "📊 ניהול נתונים", "🤖 סיכום מגמות"])
svc = get_drive_service()

with tab1:
    col_in, col_chat = st.columns([1.3, 1])
    with col_in:
        with st.container(border=True):
            st.subheader("1. פרטי התצפית")
            it = st.session_state.form_iteration
            name_sel = st.selectbox("👤 בחר תלמיד", CLASS_ROSTER, key=f"n_{it}")
            student_name = st.text_input("שם חופשי:", key=f"fn_{it}") if name_sel == "תלמיד אחר..." else name_sel
            
            c1, c2 = st.columns(2)
            with c1: difficulty = st.select_slider("רמת קושי המטלה", options=[1, 2, 3], value=2, key=f"d_{it}")
            with c2: model_status = st.radio("סטטוס מודל פיזי:", ["ללא מודל", "מודל חלקי", "מודל מלא"], horizontal=True, key=f"ms_{it}")
            
            st.divider()
            st.subheader("2. מדדים (1 משמאל, 5 מימין)")
            m1, m2 = st.columns(2)
            with m1:
                score_spatial = st.slider("יכולת תפיסה מרחבית", 1, 5, 3, key=f"s_sp_{it}")
                score_views = st.slider("מעבר בין היטלים", 1, 5, 3, key=f"s_vi_{it}")
            with m2:
                score_model = st.slider("שימוש יעיל במודל", 1, 5, 3, key=f"s_mo_{it}")
                score_efficacy = st.slider("מסוגלות עצמית", 1, 5, 3, key=f"s_ef_{it}")

            st.divider()
            st.subheader("3. תיעוד איכותני וקבצים")
            uploaded_files = st.file_uploader("העלה צילום/וידאו", accept_multiple_files=True, key=f"f_{it}")
            tags = st.multiselect("🏷️ תגיות", OBSERVATION_TAGS, key=f"t_{it}")
            challenge = st.text_area("🗣️ ציטוטים וקשיים", key=f"ch_{it}")
            done = st.text_area("👀 פעולות שבוצעו", key=f"do_{it}")
            interpretation = st.text_area("💡 פרשנות", key=f"in_{it}")
            
            if st.button("💾 שמור תצפית ואפס טופס"):
                links = []
                if uploaded_files and svc:
                    for f in uploaded_files: links.append(upload_file_to_drive(f, svc))
                
                entry = {
                    "type": "reflection", "date": date.today().isoformat(), "student_name": student_name,
                    "difficulty": difficulty, "model_status": model_status, 
                    "score_spatial": score_spatial, "score_views": score_views,
                    "score_model": score_model, "score_efficacy": score_efficacy,
                    "challenge": challenge, "done": done, "interpretation": interpretation, 
                    "tags": ", ".join(tags), "timestamp": datetime.now().strftime("%H:%M:%S"),
                    "file_links": ", ".join(links)
                }
                with open(DATA_FILE, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                if svc: update_master_excel([entry], svc)
                st.success("נשמר בהצלחה.")
                reset_form()
                st.rerun()

    with col_chat:
        st.subheader("🤖 עוזר מחקר אקדמי")
        chat_cont = st.container(height=550)
        with chat_cont:
            for q, a in st.session_state.chat_history:
                st.markdown(f"**🧐 חוקר:** {q}"); st.info(f"**🤖 AI:** {a}")
        
        u_input = st.chat_input("שאל את העוזר...")
        if u_input:
            curr = {"name": student_name, "model_status": model_status, "challenge": challenge, "score_spatial": score_spatial, "score_views": score_views, "score_model": score_model, "score_efficacy": score_efficacy, "done": done, "interpretation": interpretation}
            ans = chat_with_academic_ai(u_input, curr, st.session_state.chat_history)
            st.session_state.chat_history.append((u_input, ans))
            st.rerun()

with tab2:
    if st.button("🔄 סנכרון מלא לדרייב"):
        if os.path.exists(DATA_FILE) and svc:
            all_d = [json.loads(l) for l in open(DATA_FILE, "r", encoding="utf-8")]
            update_master_excel(all_d, svc); st.success("סונכרן!")

with tab3:
    st.header("🤖 סיכום מגמות אקדמי")
    if st.button("✨ בצע ניתוח מגמות (10 תצפיות אחרונות)"):
        if os.path.exists(DATA_FILE):
            obs = [json.loads(l) for l in open(DATA_FILE, "r", encoding="utf-8")][-10:]
            if obs:
                with st.spinner("מנתח..."):
                    txt = "\n".join([f"תלמיד: {o['student_name']}, קושי: {o['challenge']}, תפיסה: {o.get('score_spatial', 3)}, מודל: {o['model_status']}" for o in obs])
                    res = genai.Client(api_key=st.secrets["GOOGLE_API_KEY"]).models.generate_content(model="gemini-2.0-flash", contents=f"נתח מגמות (2014-2026):\n{txt}")
                    st.session_state.current_summary = res.text
            else: st.warning("אין נתונים.")
    if "current_summary" in st.session_state: st.markdown(st.session_state.current_summary)

# --- סוף קוד ---