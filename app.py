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

# --- 1. הגדרות ועיצוב ---
DATA_FILE = "reflections.jsonl"
GDRIVE_FOLDER_ID = st.secrets.get("GDRIVE_FOLDER_ID")
MASTER_FILENAME = "All_Observations_Master.xlsx"

CLASS_ROSTER = ["נתנאל", "רועי", "אסף", "עילאי", "טדי", "גאל", "אופק", "דניאל.ר", "אלי", "טיגרן", "פולינה.ק", "תלמיד אחר..."]
OBSERVATION_TAGS = ["התעלמות מקווים נסתרים", "בלבול בין היטלים", "קושי ברוטציה מנטלית", "טעות בפרופורציות", "קושי במעבר בין היטלים", "שימוש בכלי מדידה", "סיבוב פיזי של המודל", "תיקון עצמי", "עבודה עצמאית שוטפת"]

st.set_page_config(page_title="עוזר מחקר לתזה", layout="wide")
st.markdown("<style>body { direction: rtl; text-align: right; }</style>", unsafe_allow_html=True)

# --- 2. פונקציות שירות ודרייב ---
def get_drive_service():
    try:
        json_str = base64.b64decode(st.secrets["GDRIVE_SERVICE_ACCOUNT_B64"]).decode("utf-8")
        creds = Credentials.from_service_account_info(json.loads(json_str), scopes=["https://www.googleapis.com/auth/drive.file"])
        return build("drive", "v3", credentials=creds)
    except: return None

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
        if file_id: svc.files().update(fileId=file_id, media_body=media, supportsAllDrives=True).execute()
        else: svc.files().create(body={'name': MASTER_FILENAME, 'parents': [GDRIVE_FOLDER_ID]}, media_body=media, supportsAllDrives=True).execute()
        return True
    except: return False

# --- 3. עוזר מחקר אקדמי עם ציטוטים בתוך הטקסט ---
def chat_with_academic_ai(user_q, entry_data, history):
    try:
        client = genai.Client(api_key=st.secrets["GOOGLE_API_KEY"])
        
        instruction = f"""
        אתה עוזר מחקר אקדמי בכיר. החוקר צופה בתלמיד {entry_data['name']}.
        נתונים: {entry_data['challenge']}, פעולות: {entry_data['done']}, פרשנות: {entry_data['interpretation']}.
        
        הנחיות קשיחות:
        1. חובה לשלב ציטוטים של מקורות אקדמיים בתוך הטקסט בסגנון (שם החוקר, שנה).
        2. התמקד בחוקרים כגון: Sweller (עומס קוגניטיבי), Mayer (למידה מולטימדיאלית), Maier (תפיסה מרחבית), Paivio (קידוד כפול).
        3. ענה בצורה המשכית לשיחה הקודמת.
        4. בסוף התשובה, רשום רשימה ביבליוגרפית קצרה של המקורות שהוזכרו בתשובה.
        """
        
        full_context = instruction + "\n\n"
        for q, a in history:
            full_context += f"חוקר: {q}\nעוזר: {a}\n\n"
        full_context += f"חוקר: {user_q}"
        
        response = client.models.generate_content(model="gemini-2.0-flash", contents=full_context)
        return response.text
    except Exception as e: return f"שגיאה: {str(e)}"

# --- 4. ממשק המשתמש ---
st.title("🎓 עוזר מחקר עם ציטוטים אקדמיים")

if "chat_history" not in st.session_state: 
    st.session_state.chat_history = []

tab1, tab2, tab3 = st.tabs(["📝 תצפית ושיחה", "📊 ניהול", "🤖 סיכומים"])
svc = get_drive_service()

with tab1:
    col_input, col_ai = st.columns([1.2, 1])
    
    with col_input:
        with st.container(border=True):
            st.subheader("תיעוד תצפית")
            name_sel = st.selectbox("👤 תלמיד", CLASS_ROSTER)
            student_name = st.text_input("שם חופשי:") if name_sel == "תלמיד אחר..." else name_sel
            
            tags = st.multiselect("🏷️ תגיות", OBSERVATION_TAGS)
            challenge = st.text_area("🗣️ ציטוטים וקשיים", key="challenge_box")
            done = st.text_area("👀 פעולות שבוצעו", key="done_box")
            interpretation = st.text_area("💡 פרשנות/קוד איכותני", key="interp_box")
            
            if st.button("💾 שמור תצפית סופית"):
                entry = {"type": "reflection", "date": date.today().isoformat(), "student_name": student_name,
                         "challenge": challenge, "done": done, "interpretation": interpretation, 
                         "tags": ", ".join(tags), "timestamp": datetime.now().strftime("%H:%M:%S")}
                with open(DATA_FILE, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                if svc: update_master_excel([entry], svc)
                st.balloons()
                st.success("נשמר בהצלחה!")

    with col_ai:
        st.subheader("🤖 ניתוח אקדמי משולב מקורות")
        chat_container = st.container(height=500)
        with chat_container:
            for q, a in st.session_state.chat_history:
                st.markdown(f"**🧐 חוקר:** {q}")
                st.info(f"**🤖 AI:** {a}")
        
        user_input = st.chat_input("שאל את העוזר על התיאוריות...")
        if user_input:
            current_data = {"name": student_name, "challenge": challenge, "done": done, "interpretation": interpretation}
            ans = chat_with_academic_ai(user_input, current_data, st.session_state.chat_history)
            st.session_state.chat_history.append((user_input, ans))
            st.rerun()

# --- סוף קוד ---