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
TAGS_OPTIONS = ["התעלמות מקווים נסתרים", "בלבול בין היטלים", "קושי ברוטציה מנטלית", "טעות בפרופורציות", "קושי במעבר בין היטלים", "שימוש בכלי מדידה", "סיבוב פיזי של המודל", "תיקון עצמי", "עבודה עצמאית שוטפת"]

st.set_page_config(page_title="מערכת תצפית - גרסה 31.0", layout="wide")

st.markdown("""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Heebo:wght@300;400;700&display=swap');
        html, body, .stApp { direction: rtl; text-align: right; font-family: 'Heebo', sans-serif !important; }
        .stTextInput input, .stTextArea textarea, .stSelectbox > div > div { direction: rtl; text-align: right; }
        [data-testid="stSlider"] { direction: ltr !important; }
        .stButton > button { width: 100%; font-weight: bold; border-radius: 12px; height: 3em; background-color: #28a745; color: white; }
        .feedback-box { background-color: #fff3cd; color: #856404; padding: 15px; border-radius: 10px; border: 1px solid #ffeeba; margin-bottom: 20px; font-size: 0.95em; }
    </style>
""", unsafe_allow_html=True)

# --- 2. פונקציות Google Drive ---
def get_drive_service():
    try:
        json_str = base64.b64decode(st.secrets["GDRIVE_SERVICE_ACCOUNT_B64"]).decode("utf-8")
        creds = Credentials.from_service_account_info(json.loads(json_str), scopes=["https://www.googleapis.com/auth/drive"])
        return build("drive", "v3", credentials=creds)
    except: return None

def save_summary_to_drive(content, svc):
    try:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
        filename = f"Research_Summary_{timestamp}.txt"
        file_metadata = {'name': filename}
        if GDRIVE_FOLDER_ID: file_metadata['parents'] = [GDRIVE_FOLDER_ID]
        media = MediaIoBaseUpload(io.BytesIO(content.encode('utf-8')), mimetype='text/plain')
        svc.files().create(body=file_metadata, media_body=media, fields='id', supportsAllDrives=True).execute()
        return filename
    except: return None

def load_master_from_drive_internal(svc):
    try:
        query = f"name = '{MASTER_FILENAME}' and trashed = false"
        res = svc.files().list(q=query, spaces='drive', supportsAllDrives=True, includeItemsFromAllDrives=True).execute().get('files', [])
        target = next((f for f in res if f['name'] == MASTER_FILENAME), None)
        if not target: return None, None
        request = svc.files().get_media(fileId=target['id'])
        fh = io.BytesIO(); downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done: _, done = downloader.next_chunk()
        fh.seek(0); return pd.read_excel(fh), target['id']
    except: return None, None

def update_master_in_drive(new_data_df, svc):
    try:
        existing_df, file_id = load_master_from_drive_internal(svc)
        if existing_df is not None:
            # מניעת כפילויות בעדכון און-ליין (Keep Last)
            df = pd.concat([existing_df, new_data_df], ignore_index=True).drop_duplicates(subset=['student_name', 'timestamp'], keep='last')
        else: df = new_data_df
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

def fetch_history_from_drive(student_name, svc):
    try:
        df, _ = load_master_from_drive_internal(svc)
        if df is None: return ""
        target = str(student_name).strip()
        df['student_name'] = df['student_name'].astype(str).str.strip()
        student_data = df[df['student_name'].str.contains(target, na=False, case=False)]
        if student_data.empty: return ""
        hist = ""
        for _, row in student_data.tail(5).fillna("").iterrows():
            hist += f"תאריך: {row.get('date')} | קושי: {row.get('challenge')} | פרשנות: {row.get('interpretation')}\n"
        return hist
    except: return ""

# --- 3. ממשק המשתמש ---
if "it" not in st.session_state: st.session_state.it = 0
if "chat_history" not in st.session_state: st.session_state.chat_history = []
if "student_context" not in st.session_state: st.session_state.student_context = ""
if "last_obs_feedback" not in st.session_state: st.session_state.last_obs_feedback = ""
if "current_obs_timestamp" not in st.session_state: st.session_state.current_obs_timestamp = ""
if "last_selected_student" not in st.session_state: st.session_state.last_selected_student = ""

svc = get_drive_service()
st.title("🎓 מערכת תצפית תזה חכמה - 31.0")
tab1, tab2, tab3 = st.tabs(["📝 הזנה ומשוב", "🔄 סנכרון", "🤖 ניתוח מגמות"])

with tab1:
    col_in, col_chat = st.columns([1.2, 1])
    with col_in:
        with st.container(border=True):
            it = st.session_state.it
            c1, c2 = st.columns(2)
            with c1:
                name_sel = st.selectbox("👤 בחר סטודנט", CLASS_ROSTER, key=f"n_{it}")
                student_name = st.text_input("שם חופשי:", key=f"fn_{it}") if name_sel == "תלמיד אחר..." else name_sel
                
                if student_name != st.session_state.last_selected_student:
                    st.session_state.chat_history = []
                    st.session_state.student_context = fetch_history_from_drive(student_name, svc) if (student_name and svc) else ""
                    st.session_state.last_selected_student = student_name
            with c2:
                work_method = st.radio("🛠️ סוג תרגול:", ["🧊 בעזרת גוף מודפס", "🎨 ללא גוף (דמיון)"], key=f"wm_{it}", horizontal=True)

            q1, q2 = st.columns(2)
            with q1: drawings_count = st.number_input("כמות שרטוטים", min_value=0, step=1, key=f"dc_{it}")
            with q2: duration_min = st.number_input("זמן עבודה (דקות)", min_value=0, step=5, key=f"dm_{it}")

            st.markdown("### 📊 מדדים (1-5)")
            m1, m2 = st.columns(2)
            with m1:
                cat_convert_rep = st.slider("המרת ייצוגים", 1, 5, 3, key=f"s1_{it}")
                cat_dims_props = st.slider("פרופורציות", 1, 5, 3, key=f"s2_{it}")
                cat_proj_trans = st.slider("מעבר בין היטלים", 1, 5, 3, key=f"s3_{it}")
            with m2:
                cat_3d_support = st.slider("שימוש במודל", 1, 5, 3, key=f"s4_{it}")
                cat_self_efficacy = st.slider("מסוגלות", 1, 5, 3, key=f"s5_{it}")

            st.divider()
            tags = st.multiselect("🏷️ תגיות אבחון", TAGS_OPTIONS, key=f"t_{it}")
            challenge = st.text_area("🗣️ תיאור קשיים ותצפית (מה ראית?)", key=f"ch_{it}")
            interpretation = st.text_area("🧠 פרשנות מחקרית (מה זה אומר?)", key=f"int_{it}")

            if st.session_state.last_obs_feedback:
                st.markdown(f'<div class="feedback-box"><b>💡 משוב לחיזוק התיעוד:</b><br>{st.session_state.last_obs_feedback}</div>', unsafe_allow_html=True)

            btn_label = "💾 עדכן שמירה ונתח שוב" if st.session_state.last_obs_feedback else "💾 שמור תצפית וקבל משוב"
            if st.button(btn_label):
                if not challenge or not interpretation:
                    st.error("חובה למלא תיאור ופרשנות.")
                else:
                    if not st.session_state.current_obs_timestamp:
                        st.session_state.current_obs_timestamp = datetime.now().isoformat()
                    
                    entry = {
                        "date": date.today().isoformat(), "student_name": student_name, "work_method": work_method,
                        "drawings_count": drawings_count, "duration_min": duration_min, "challenge": challenge,
                        "interpretation": interpretation, "cat_convert_rep": cat_convert_rep, "cat_dims_props": cat_dims_props,
                        "cat_proj_trans": cat_proj_trans, "cat_3d_support": cat_3d_support, "cat_self_efficacy": cat_self_efficacy,
                        "tags": str(tags), "timestamp": st.session_state.current_obs_timestamp
                    }
                    with open(DATA_FILE, "a", encoding="utf-8") as f:
                        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                    
                    # ניתוח איכותני מיידי
                    client = genai.Client(api_key=st.secrets["GOOGLE_API_KEY"])
                    feedback_prompt = f"מנחה תזה: בדוק אם התיאור 'מה ראיתי' והפרשנות מספקים עבור התגיות {tags}. אם חסר פירוט על פעולה פיזית או רגשית, ציין זאת ב-2 שורות. תצפית: {challenge}"
                    res = client.models.generate_content(model="gemini-2.0-flash", contents=feedback_prompt)
                    st.session_state.last_obs_feedback = res.text
                    st.success("נשמר מקומית. ניתן לתקן ולשמור שוב או לסיים.")
                    st.rerun()

            if st.button("✅ סיימתי עם הסטודנט - נקה טופס"):
                st.session_state.last_obs_feedback = ""
                st.session_state.current_obs_timestamp = ""
                st.session_state.it += 1
                st.rerun()

    with col_chat:
        st.subheader(f"🤖 יועץ פדגוגי: {student_name}")
        chat_cont = st.container(height=400)
        for q, a in st.session_state.chat_history:
            with chat_cont: st.chat_message("user").write(q); st.chat_message("assistant").write(a)
        user_q = st.chat_input("שאל על מגמות הסטודנט...")
        if user_q:
            client = genai.Client(api_key=st.secrets["GOOGLE_API_KEY"])
            prompt = f"נתח את {student_name} לפי היסטוריה: {st.session_state.student_context}. שאלה: {user_q}"
            res = client.models.generate_content(model="gemini-2.0-flash", contents=prompt)
            st.session_state.chat_history.append((user_q, res.text)); st.rerun()

with tab2:
    st.header("🔄 סנכרון לדרייב")
    if os.path.exists(DATA_FILE):
        if st.button("🚀 דחף נתונים למאסטר", use_container_width=True):
            all_entries = [json.loads(l) for l in open(DATA_FILE, "r", encoding="utf-8")]
            if update_master_in_drive(pd.DataFrame(all_entries), svc):
                st.success("הסנכרון הושלם בהצלחה!")
    else: st.write("✨ הכל מעודכן.")

with tab3:
    st.header("🤖 ניתוח מגמות ופרופילים")
    if st.button("✨ ייצר ניתוח עומק סטטיסטי ואיכותני", use_container_width=True):
        if svc:
            with st.spinner("מנתח נתונים..."):
                df, _ = load_master_from_drive_internal(svc)
                if df is not None:
                    # חישוב סטטיסטי
                    score_cols = ['cat_convert_rep', 'cat_dims_props', 'cat_proj_trans', 'cat_self_efficacy', 'duration_min']
                    for col in score_cols: df[col] = pd.to_numeric(df[col], errors='coerce')
                    stats_text = df.groupby('work_method')[score_cols].mean().round(2).to_string()
                    
                    client = genai.Client(api_key=st.secrets["GOOGLE_API_KEY"])
                    prompt = f"""
                    נתח את המחקר:
                    1. השווה ממוצעים: {stats_text}
                    2. בצע 'קידוד איכותני' לרפלקציות: {df[['student_name', 'interpretation', 'challenge']].to_string()}
                    3. בנה 'פרופיל לומד' (טיפולוגיה) לכל סטודנט.
                    4. ספק ביקורת על עקביות התיעוד של החוקר.
                    """
                    response = client.models.generate_content(model="gemini-2.0-flash", contents=prompt)
                    st.markdown(response.text)
                    
                    full_txt = f"סיכום מחקר {datetime.now().strftime('%d/%m/%Y')}\n\n{response.text}\n\nסטטיסטיקה:\n{stats_text}"
                    saved = save_summary_to_drive(full_txt, svc)
                    if saved: st.success(f"נשמר בדרייב: {saved}")
