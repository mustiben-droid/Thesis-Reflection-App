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

# --- 1. הגדרות בסיסיות ---
DATA_FILE = "reflections.jsonl"
GDRIVE_FOLDER_ID = st.secrets.get("GDRIVE_FOLDER_ID")
MASTER_FILENAME = "All_Observations_Master.xlsx"

CLASS_ROSTER = ["נתנאל", "רועי", "אסף", "עילאי", "טדי", "גאל", "אופק", "דניאל.ר", "אלי", "טיגרן", "פולינה.ק", "תלמיד אחר..."]
OBSERVATION_TAGS = ["התעלמות מקווים נסתרים", "בלבול בין היטלים", "קושי ברוטציה מנטלית", "טעות בפרופורציות", "קושי במעבר בין היטלים", "שימוש בכלי מדידה", "סיבוב פיזי של המודל", "תיקון עצמי", "עבודה עצמאית שוטפת"]

# --- 2. פונקציות שירות וחיבור לדרייב ---
def get_drive_service():
    try:
        json_str = base64.b64decode(st.secrets["GDRIVE_SERVICE_ACCOUNT_B64"]).decode("utf-8")
        creds = Credentials.from_service_account_info(json.loads(json_str), scopes=["https://www.googleapis.com/auth/drive.file"])
        return build("drive", "v3", credentials=creds)
    except: return None

def save_txt_to_drive(text, svc, prefix="AI_Analysis"):
    try:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
        filename = f"{prefix}_{timestamp}.txt"
        file_metadata = {'name': filename, 'parents': [GDRIVE_FOLDER_ID]}
        media = MediaIoBaseUpload(io.BytesIO(text.encode("utf-8")), mimetype='text/plain')
        svc.files().create(body=file_metadata, media_body=media, supportsAllDrives=True).execute()
        return True
    except: return False

def update_master_excel(data_to_add, svc):
    try:
        query = f"name = '{MASTER_FILENAME}' and '{GDRIVE_FOLDER_ID}' in parents and trashed = false"
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
        if file_id:
            svc.files().update(fileId=file_id, media_body=media, supportsAllDrives=True).execute()
        else:
            svc.files().create(body={'name': MASTER_FILENAME, 'parents': [GDRIVE_FOLDER_ID]}, media_body=media, supportsAllDrives=True).execute()
        return True
    except: return False

# --- 3. פונקציות AI (עוזר מחקר אקדמי) ---
def chat_with_ai(user_q, entry_data):
    try:
        client = genai.Client(api_key=st.secrets["GOOGLE_API_KEY"])
        context = f"""
        אתה עוזר מחקר אקדמי מומחה לחינוך טכנולוגי והנדסי. 
        החוקר כותב כעת תצפית על התלמיד: {entry_data['name']}.
        נתונים מהתצפית:
        - קשיים: {entry_data['challenge']}
        - פעולות: {entry_data['done']}
        - פרשנות: {entry_data['interpretation']}
        
        הנחיה חשובה: בכל תשובה, נסה לקשר את הממצאים למושגים או תיאוריות אקדמיות (כגון: Scaffolding, Cognitive Load, Mental Rotation, Constructivism). 
        סייע לחוקר לנסח פרשנות מעמיקה שמתאימה לכתיבת תזה.
        """
        response = client.models.generate_content(model="gemini-2.0-flash", contents=context + user_q)
        return response.text
    except Exception as e: return f"שגיאה ב-AI: {e}"

# --- 4. ממשק המשתמש ---
setup_design = lambda: st.set_page_config(page_title="עוזר מחקר לתזה", layout="wide")
setup_design()
st.markdown("<style>body { direction: rtl; text-align: right; }</style>", unsafe_allow_html=True)
st.title("🎓 עוזר מחקר חכם - יומן תצפית")

if "chat_history" not in st.session_state: st.session_state.chat_history = []

tab1, tab2, tab3 = st.tabs(["📝 תצפית וצ'אט אקדמי", "📊 ניהול", "🤖 סיכומים"])
svc = get_drive_service()

with tab1:
    col_form, col_chat = st.columns([1.5, 1])
    
    with col_form:
        st.subheader("תיעוד תצפית חיה")
        name_sel = st.selectbox("👤 בחר תלמיד לתצפית", CLASS_ROSTER, key="student_sel")
        student_name = st.text_input("שם חופשי:") if name_sel == "תלמיד אחר..." else name_sel
        
        c1, c2 = st.columns(2)
        with c1: difficulty = st.select_slider("רמת קושי", options=[1, 2, 3], value=2)
        with c2: model_use = st.radio("שימוש במודל:", ["ללא", "חלקי", "מלא"], horizontal=True)
        
        tags = st.multiselect("🏷️ תגיות", OBSERVATION_TAGS)
        
        # שדות טקסט חיים (מחוץ ל-Form כדי שה-AI יראה אותם)
        challenge = st.text_area("🗣️ ציטוטים וקשיים", key="challenge_box")
        done = st.text_area("👀 פעולות שבוצעו", key="done_box")
        interpretation = st.text_area("💡 פרשנות/קוד איכותני", key="interp_box")
        
        if st.button("💾 שמור תצפית סופית"):
            entry = {
                "type": "reflection", "date": date.today().isoformat(), "student_name": student_name,
                "difficulty": difficulty, "physical_model": model_use, "challenge": challenge,
                "done": done, "interpretation": interpretation, "tags": ", ".join(tags),
                "timestamp": datetime.now().strftime("%H:%M:%S")
            }
            with open(DATA_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            if svc: update_master_excel([entry], svc)
            st.balloons()
            st.success(f"התצפית על {student_name} נשמרה בהצלחה!")

    with col_chat:
        st.subheader("🤖 עוזר מחקר (תיאוריות ומקורות)")
        st.write(f"מנתח כעת את: **{student_name}**")
        
        user_input = st.text_input("שאל על התצפית (AI יחבר לתיאוריה):")
        if st.button("שלח שאלה ל-AI"):
            current_data = {"name": student_name, "challenge": challenge, "done": done, "interpretation": interpretation}
            with st.spinner(f"מבצע הצלבה עם מקורות אקדמיים..."):
                ans = chat_with_ai(user_input, current_data)
                st.session_state.chat_history.append((user_input, ans))
        
        for q, a in reversed(st.session_state.chat_history):
            st.markdown(f"**🧐 חוקר:** {q}")
            st.info(f"**🤖 עוזר:** {a}")
            st.divider()

with tab2:
    st.header("📊 ניהול נתונים")
    if st.button("🔄 סנכרן הכל לאקסל בדרייב"):
        if os.path.exists(DATA_FILE) and svc:
            all_data = [json.loads(l) for l in open(DATA_FILE, "r", encoding="utf-8") if json.loads(l).get("type")=="reflection"]
            update_master_excel(all_data, svc)
            st.success("סנכרון הושלם!")

with tab3:
    st.header("🤖 סיכומי AI")
    if st.button("✨ בצע סיכום שבועי ושמור לדרייב"):
        if os.path.exists(DATA_FILE):
            all_ents = [json.loads(l) for l in open(DATA_FILE, "r", encoding="utf-8") if json.loads(l).get("type")=="reflection"]
            if all_ents:
                with st.spinner("מייצר דוח אקדמי מסכם..."):
                    summary_context = "\n".join([f"תלמיד: {e['student_name']}, קשיים: {e['challenge']}, פרשנות: {e['interpretation']}" for e in all_ents[-10:]])
                    try:
                        client = genai.Client(api_key=st.secrets["GOOGLE_API_KEY"])
                        res = client.models.generate_content(model="gemini-2.0-flash", contents="נתח את המגמות המחקריות הבאות בהקשר של חינוך הנדסי:\n" + summary_context)
                        report = res.text
                        st.markdown(report)
                        if svc and save_txt_to_drive(report, svc, "Research_Weekly_Summary"):
                            st.success("✅ הסיכום נשמר אוטומטית בדרייב!")
                        st.download_button("📥 הורד למחשב", data=report, file_name="Summary.txt")
                    except Exception as e: st.error(str(e))
            else: st.warning("אין נתונים בזיכרון.")

# --- סוף קוד ---