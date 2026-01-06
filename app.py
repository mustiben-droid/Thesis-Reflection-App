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

CLASS_ROSTER = ["נתנאל", "רועי", "אסף", "עילאי", "טדי", "גאל", "אופק", "דניאל.ר", "אלי", "טיגרן", "תלמיד אחר..."]
OBSERVATION_TAGS = [
    "התעלמות מקווים נסתרים", "בלבול בין היטלים", "קושי ברוטציה מנטלית",
    "טעות בפרופורציות/מידות", "קושי במעבר בין היטלים", "שימוש בכלי מדידה",
    "סיבוב פיזי של המודל", "שימוש בתנועות ידיים (Embodiment)", "ספירת משבצות",
    "תיקון עצמי", "בקשת אישור תכופה", "ויתור/תסכול", "עבודה עצמאית שוטפת"
]

# --- 2. עיצוב (CSS) ---
def setup_design():
    st.set_page_config(page_title="יומן תצפית", page_icon="🎓", layout="centered")
    st.markdown("""
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Heebo:wght@300;400;700&display=swap');
            html, body, .stApp { background-color: #ffffff !important; direction: rtl; text-align: right; font-family: 'Heebo', sans-serif !important; }
            .stTextInput input, .stTextArea textarea, .stSelectbox > div > div { direction: rtl; text-align: right; }
            .stButton > button { width: 100%; font-weight: bold; border-radius: 10px; }
            [data-testid="stSlider"] { direction: ltr !important; }
            [data-testid="stForm"] { background-color: #ffffff; padding: 20px; border-radius: 15px; border: 1px solid #e0e0e0; box-shadow: 0 4px 10px rgba(0,0,0,0.05); }
        </style>
    """, unsafe_allow_html=True)

# --- 3. פונקציות שירות ודרייב ---
def get_drive_service():
    try:
        json_str = base64.b64decode(st.secrets["GDRIVE_SERVICE_ACCOUNT_B64"]).decode("utf-8")
        creds = Credentials.from_service_account_info(json.loads(json_str), scopes=["https://www.googleapis.com/auth/drive.file"])
        return build("drive", "v3", credentials=creds)
    except: return None

def update_master_excel(data_to_add, svc, overwrite=False):
    try:
        query = f"name = '{MASTER_FILENAME}' and '{GDRIVE_FOLDER_ID}' in parents and trashed = false"
        results = svc.files().list(q=query, fields="files(id)").execute()
        files = results.get('files', [])
        if files and not overwrite:
            file_id = files[0]['id']
            request = svc.files().get_media(fileId=file_id)
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done: _, done = downloader.next_chunk()
            fh.seek(0)
            df = pd.read_excel(fh)
            df = pd.concat([df, pd.DataFrame(data_to_add)], ignore_index=True)
        else:
            df = pd.DataFrame(data_to_add)
            file_id = files[0]['id'] if files else None
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer: df.to_excel(writer, index=False)
        output.seek(0)
        media = MediaIoBaseUpload(output, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        if file_id: svc.files().update(fileId=file_id, media_body=media, supportsAllDrives=True).execute()
        else: svc.files().create(body={'name': MASTER_FILENAME, 'parents': [GDRIVE_FOLDER_ID]}, media_body=media, supportsAllDrives=True).execute()
        return True
    except: return False

def save_local(entry):
    with open(DATA_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

# --- 4. פונקציות AI (Gemini) ---
def generate_summary(entries):
    if not entries: return "אין מספיק נתונים מהשבוע האחרון."
    full_text = "אלה רשומות רפלקציה מהשבוע האחרון:\n"
    for e in entries:
        full_text += f"- תלמיד: {e.get('student_name')}, פעולות: {e.get('done')}, קושי: {e.get('challenge')}, פרשנות: {e.get('interpretation')}\n"
    prompt = f"בצע ניתוח של הרפלקציות הבאות עבור עבודת תזה. סכם מגמות, הישגים והמלצות לשבוע הבא:\n{full_text}"
    try:
        client = genai.Client(api_key=st.secrets["GOOGLE_API_KEY"])
        response = client.models.generate_content(model="gemini-2.0-flash", contents=prompt)
        return response.text
    except Exception as e: return f"שגיאה ביצירת סיכום: {e}"

# --- 5. ממשק המשתמש ---
setup_design()
st.title("🎓 יומן תצפית - הגרסה המלאה")

tab1, tab2, tab3 = st.tabs(["📝 רפלקציה", "📊 ניהול נתונים", "🤖 סיכום AI"])

with tab1:
    with st.form("main_form", clear_on_submit=True):
        st.subheader("פרטי התצפית")
        c1, c2 = st.columns(2)
        with c1:
            sel = st.selectbox("👤 שם תלמיד", CLASS_ROSTER)
            student_name = st.text_input("הזן שם:") if sel == "תלמיד אחר..." else sel
        with c2: lesson_id = st.text_input("📚 מזהה שיעור")
        
        work_method = st.radio("🛠️ כלי עבודה", ["🎨 ללא גוף (דמיון)", "🧊 בעזרת גוף מודפס"], horizontal=True)
        tags = st.multiselect("🏷️ תגיות", OBSERVATION_TAGS)
        
        ca, cb = st.columns(2)
        with ca:
            planned = st.text_area("📋 המטלה שניתנה")
            challenge = st.text_area("🗣️ ציטוטים/קשיים")
        with cb:
            done = st.text_area("👀 פעולות שבוצעו")
            interpretation = st.text_area("💡 פרשנות המורה")
        
        st.subheader("מדדים (1-5)")
        m1 = st.select_slider("🔄 המרת ייצוגים", options=[1,2,3,4,5], value=3)
        m2 = st.select_slider("📐 מעבר היטלים", options=[1,2,3,4,5], value=3)
        m3 = st.select_slider("💪 מסוגלות עצמית", options=[1,2,3,4,5], value=3)

        if st.form_submit_button("💾 שמור תצפית"):
            entry = {
                "type": "reflection", "date": date.today().isoformat(), "student_name": student_name,
                "lesson_id": lesson_id, "work_method": work_method, "tags": ", ".join(tags),
                "planned": planned, "done": done, "challenge": challenge, "interpretation": interpretation,
                "score_conv": m1, "score_proj": m2, "score_eff": m3, "timestamp": datetime.now().strftime("%H:%M:%S")
            }
            save_local(entry)
            svc = get_drive_service()
            if svc: update_master_excel([entry], svc)
            st.success("נשמר בדרייב ובמערכת! ✅")

with tab2:
    st.header("📊 ניהול היסטוריה")
    if st.button("📤 סנכרן את כל העבר לקובץ האקסל בדרייב"):
        if os.path.exists(DATA_FILE):
            all_data = [json.loads(line) for line in open(DATA_FILE, "r", encoding="utf-8") if json.loads(line).get("type")=="reflection"]
            svc = get_drive_service()
            if svc and all_data:
                if update_master_excel(all_data, svc, overwrite=True): st.success("כל ההיסטוריה סונכרנה לאקסל! ✅")
    
    st.divider()
    if os.path.exists(DATA_FILE):
        df = pd.DataFrame([json.loads(l) for l in open(DATA_FILE, "r", encoding="utf-8") if json.loads(l).get("type")=="reflection"])
        if not df.empty:
            st.write("תצפיות אחרונות:")
            st.table(df.tail(3)[["date", "student_name", "lesson_id"]])

with tab3:
    st.header("🤖 סיכום AI שבועי")
    if st.button("✨ צור סיכום Gemini לשבוע האחרון"):
        today = date.today()
        week_ago = (today - timedelta(days=7)).isoformat()
        entries = [json.loads(l) for l in open(DATA_FILE, "r", encoding="utf-8") 
                   if json.loads(l).get("type")=="reflection" and json.loads(l).get("date") >= week_ago]
        
        with st.spinner("Gemini מנתח את הנתונים..."):
            summary = generate_summary(entries)
            save_local({"type": "weekly_summary", "date": today.isoformat(), "content": summary})
            st.markdown(summary)
            st.success("הסיכום נשמר בארכיון!")

    st.divider()
    st.subheader("📚 ארכיון סיכומים")
    if os.path.exists(DATA_FILE):
        sums = [json.loads(l) for l in open(DATA_FILE, "r", encoding="utf-8") if json.loads(l).get("type")=="weekly_summary"]
        for s in reversed(sums):
            with st.expander(f"סיכום מתאריך {s['date']}"):
                st.markdown(s['content'])

# סוף הקוד