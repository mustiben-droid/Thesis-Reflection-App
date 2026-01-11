import json
import base64
import os
import io
from datetime import date, datetime, timedelta
import pandas as pd
import streamlit as st
from google import genai
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload

# --- 1. הגדרות קבועות ---
DATA_FILE = "reflections.jsonl"
GDRIVE_FOLDER_ID = st.secrets.get("GDRIVE_FOLDER_ID")
MASTER_FILENAME = "All_Observations_Master.xlsx"

CLASS_ROSTER = ["נתנאל", "רועי", "אסף", "עילאי", "טדי", "גאל", "אופק", "דניאל.ר", "אלי", "טיגרן", "פולינה.ק", "תלמיד אחר..."]

OBSERVATION_TAGS = [
    "התעלמות מקווים נסתרים", "בלבול בין היטלים", "קושי ברוטציה מנטלית", 
    "טעות בפרופורציות", "קושי במעבר בין היטלים", "שימוש בכלי מדידה", 
    "סיבוב פיזי של המודל", "תיקון עצמי", "עבודה עצמאית שוטפת"
]

# --- 2. עיצוב (CSS) ---
def setup_design():
    st.set_page_config(page_title="יומן תצפית מחקרי", page_icon="🎓", layout="centered")
    st.markdown("""
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Heebo:wght@300;400;700&display=swap');
            html, body, .stApp { direction: rtl; text-align: right; font-family: 'Heebo', sans-serif !important; }
            .stTextInput input, .stTextArea textarea, .stSelectbox > div > div { direction: rtl; text-align: right; }
            .stButton > button { width: 100%; font-weight: bold; border-radius: 10px; }
            [data-testid="stSlider"] { direction: ltr !important; }
            .stRadio > div { flex-direction: row-reverse !important; gap: 20px; }
            div[data-baseweb="select"] > div { direction: rtl; text-align: right; }
        </style>
    """, unsafe_allow_html=True)

# --- 3. פונקציות שירות ---
def get_drive_service():
    try:
        # כאן אנחנו מפענחים את ה-B64 כדי שהקוד יבין את המפתח
        json_str = base64.b64decode(st.secrets["GDRIVE_SERVICE_ACCOUNT_B64"]).decode("utf-8")
        info = json.loads(json_str)
        
        # השורה הזו תדפיס לנו את המייל בתוך האפליקציה כדי שתוכל להעתיק אותו
        st.info(f"📧 כתובת המייל לשיתוף בדרייב: {info.get('client_email')}")
        
        creds = Credentials.from_service_account_info(info, scopes=["https://www.googleapis.com/auth/drive.file"])
        return build("drive", "v3", credentials=creds)
    except Exception as e:
        st.error(f"שגיאה בחיבור לשירות: {e}")
        return None

def upload_image_to_drive(uploaded_file, svc):
    try:
        file_metadata = {'name': uploaded_file.name, 'parents': [GDRIVE_FOLDER_ID]}
        media = MediaIoBaseUpload(io.BytesIO(uploaded_file.getvalue()), mimetype=uploaded_file.type)
        file = svc.files().create(body=file_metadata, media_body=media, fields='id, webViewLink').execute()
        return file.get('webViewLink')
    except Exception as e:
        st.error(f"לא הצלחתי להעלות תמונה. וודא שהתיקייה משותפת עם המייל הכחול למעלה. שגיאה: {e}")
        return None

def process_tags_to_columns(df):
    for tag in OBSERVATION_TAGS:
        df[f"tag_{tag}"] = df['tags'].apply(lambda x: 1 if isinstance(x, str) and tag in x else 0)
    return df

def update_master_excel(data_to_add, svc, overwrite=False):
    try:
        query = f"name = '{MASTER_FILENAME}' and '{GDRIVE_FOLDER_ID}' in parents and trashed = false"
        res = svc.files().list(q=query).execute().get('files', [])
        new_df = pd.DataFrame(data_to_add)
        if res and not overwrite:
            file_id = res[0]['id']
            request = svc.files().get_media(fileId=file_id)
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done: _, done = downloader.next_chunk()
            fh.seek(0)
            existing_df = pd.read_excel(fh)
            df = pd.concat([existing_df, new_df], ignore_index=True)
        else:
            df = new_df
            file_id = res[0]['id'] if res else None
        df = process_tags_to_columns(df)
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer: df.to_excel(writer, index=False)
        output.seek(0)
        media = MediaIoBaseUpload(output, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        if file_id: svc.files().update(fileId=file_id, media_body=media).execute()
        else: svc.files().create(body={'name': MASTER_FILENAME, 'parents': [GDRIVE_FOLDER_ID]}, media_body=media).execute()
        return True
    except: return False

def save_local(entry):
    with open(DATA_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

def generate_weekly_summary(entries):
    if not entries: return "אין מספיק נתונים לסיכום."
    full_text = "נתוני תצפיות מהשבוע האחרון:\n"
    for e in entries:
        full_text += f"- תלמיד: {e.get('student_name')}, מודל פיזי: {e.get('physical_model')}, פעולות: {e.get('done')}, קושי: {e.get('challenge')}\n"
    prompt = f"נתח את הרפלקציות הבאות עבור מחקר תזה. סכם מגמות והמלצות:\n{full_text}"
    try:
        client = genai.Client(api_key=st.secrets["GOOGLE_API_KEY"])
        response = client.models.generate_content(model="gemini-2.0-flash", contents=prompt)
        return response.text
    except Exception as e: return f"שגיאה: {e}"

# --- 4. ממשק המשתמש ---
setup_design()
st.title("🎓 יומן תצפית - מהדורת מחקר מלאה")

tab1, tab2, tab3 = st.tabs(["📝 רפלקציה", "📊 ניהול נתונים", "🤖 עוזר AI"])

with tab1:
    svc = get_drive_service() # זה ידפיס את המייל למעלה
    
    with st.form("main_form", clear_on_submit=True):
        st.subheader("1. פרטי התצפית")
        c1, c2 = st.columns([3, 2])
        with c1:
            sel = st.selectbox("👤 שם תלמיד", CLASS_ROSTER)
            student_name = st.text_input("שם חופשי:") if sel == "תלמיד אחר..." else sel
        with c2:
            difficulty = st.select_slider("⚖️ רמת קושי המטלה", options=[1, 2, 3], value=2)

        st.write("**שימוש במודל תלת-ממדי (גוף מודפס):**")
        physical_model = st.radio(
            "בחר את אופן השימוש במודל במטלה זו:",
            ["ללא מודל (עבודה מנטלית בלבד)", "שימוש במודל מודפס כעזר", "שימוש אינטנסיבי במודל"],
            index=0,
            horizontal=True
        )

        st.subheader("2. כמות וזמן")
        col_t, col_d = st.columns(2)
        with col_t: work_duration = st.number_input("⏱️ זמן עבודה (דקות)", min_value=0, step=5)
        with col_d: drawings_count = st.number_input("✏️ מספר שרטוטים", min_value=0, step=1)

        tags = st.multiselect("🏷️ תגיות נצפות", OBSERVATION_TAGS)
        
        ca, cb = st.columns(2)
        with ca:
            planned = st.text_area("📋 תיאור המטלה / נושא")
            challenge = st.text_area("🗣️ ציטוטים וקשיים")
        with cb:
            done = st.text_area("👀 פעולות שבוצעו")
            interpretation = st.text_area("💡 פרשנות/קוד איכותני")
        
        uploaded_files = st.file_uploader("📸 העלאת תמונות", accept_multiple_files=True, type=['png', 'jpg', 'jpeg'])
        
        st.subheader("4. מדדי הערכה (1-5)")
        m_cols = st.columns(5)
        m1 = m_cols[0].select_slider("היטלים", options=[1,2,3,4,5], value=3)
        m2 = m_cols[1].select_slider("מרחבית", options=[1,2,3,4,5], value=3)
        m3 = m_cols[2].select_slider("המרת ייצוג", options=[1,2,3,4,5], value=3)
        m4 = m_cols[3].select_slider("מסוגלות", options=[1,2,3,4,5], value=3)
        m5 = m_cols[4].select_slider("מודל", options=[1,2,3,4,5], value=3)

        if st.form_submit_button("💾 שמור תצפית"):
            img_links = []
            if svc and uploaded_files:
                for f in uploaded_files: 
                    link = upload_image_to_drive(f, svc)
                    if link: img_links.append(link)
            
            entry = {
                "type": "reflection", "date": date.today().isoformat(), "student_name": student_name,
                "physical_model": physical_model, "difficulty": difficulty, "duration_min": work_duration, 
                "drawings_count": drawings_count, "tags": ", ".join(tags), "planned": planned, "done": done, 
                "challenge": challenge, "interpretation": interpretation, "score_proj": m1, "score_spatial": m2, 
                "score_conv": m3, "score_efficacy": m4, "score_model": m5, "images": ", ".join(img_links),
                "timestamp": datetime.now().strftime("%H:%M:%S")
            }
            save_local(entry)
            if svc: update_master_excel([entry], svc)
            st.success("נשמר בהצלחה! ✅")

with tab2:
    st.header("📊 ניהול וסנכרון")
    if st.button("🔄 סנכרן את כל ההיסטוריה לאקסל בדרייב"):
        if os.path.exists(DATA_FILE):
            all_data = [json.loads(l) for l in open(DATA_FILE, "r", encoding="utf-8") if json.loads(l).get("type")=="reflection"]
            if svc:
                update_master_excel(all_data, svc, overwrite=True)
                st.success("הסנכרון הושלם! ✅")

with tab3:
    st.header("🤖 כלי AI למחקר")
    if st.button("✨ צור סיכום Gemini לשבוע האחרון"):
        today = date.today()
        week_ago = (today - timedelta(days=7)).isoformat()
        if os.path.exists(DATA_FILE):
            entries = [json.loads(l) for l in open(DATA_FILE, "r", encoding="utf-8") 
                       if json.loads(l).get("type")=="reflection" and json.loads(l).get("date") >= week_ago]
            with st.spinner("מנתח נתונים..."):
                summary = generate_weekly_summary(entries)
                save_local({"type": "weekly_summary", "date": today.isoformat(), "content": summary})
                st.markdown(summary)

    st.divider()
    if "messages" not in st.session_state: st.session_state.messages = []
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]): st.markdown(msg["content"])

    if pr := st.chat_input("שאל על הנתונים..."):
        st.session_state.messages.append({"role": "user", "content": pr})
        with st.chat_message("user"): st.markdown(pr)
        context = ""
        if os.path.exists(DATA_FILE):
            ents = [json.loads(l) for l in open(DATA_FILE, "r", encoding="utf-8") if json.loads(l).get("type")=="reflection"]
            context = "נתונים:\n" + "\n".join([str(e) for e in ents[-10:]])
        with st.chat_message("assistant"):
            try:
                client = genai.Client(api_key=st.secrets["GOOGLE_API_KEY"])
                res = client.models.generate_content(model="gemini-2.0-flash", contents=f"{context}\nשאלה: {pr}")
                st.markdown(res.text)
                st.session_state.messages.append({"role": "assistant", "content": res.text})
            except Exception as e: st.error(str(e))

    st.divider()
    st.subheader("📚 ארכיון סיכומים שבועיים")
    if os.path.exists(DATA_FILE):
        sums = [json.loads(l) for l in open(DATA_FILE, "r", encoding="utf-8") if json.loads(l).get("type")=="weekly_summary"]
        for s in reversed(sums):
            with st.expander(f"סיכום מתאריך {s['date']}"): st.markdown(s['content'])

# --- סוף הקוד המלא - מיועד לשימוש במחקר תזה ---