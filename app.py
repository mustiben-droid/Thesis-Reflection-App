import json
import base64
import os
import io
from datetime import date, datetime, timedelta
import pandas as pd
import streamlit as st
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload

# --- הגדרות קבועות ---
DATA_FILE = "reflections.jsonl"
GDRIVE_FOLDER_ID = st.secrets.get("GDRIVE_FOLDER_ID")
MASTER_FILENAME = "All_Observations_Master.xlsx"

# --- פונקציות שירות ---
def get_drive_service():
    try:
        json_str = base64.b64decode(st.secrets["GDRIVE_SERVICE_ACCOUNT_B64"]).decode("utf-8")
        creds = Credentials.from_service_account_info(json.loads(json_str), scopes=["https://www.googleapis.com/auth/drive.file"])
        return build("drive", "v3", credentials=creds)
    except: return None

def update_master_spreadsheet(new_entry, svc):
    """מעדכן קובץ אקסל מרכזי בדרייב עם השורה החדשה."""
    try:
        # 1. חיפוש אם הקובץ כבר קיים בדרייב
        query = f"name = '{MASTER_FILENAME}' and '{GDRIVE_FOLDER_ID}' in parents and trashed = false"
        results = svc.files().list(q=query, fields="files(id)").execute()
        files = results.get('files', [])

        if files:
            # הורדת הקובץ הקיים
            file_id = files[0]['id']
            request = svc.files().get_media(fileId=file_id)
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
            fh.seek(0)
            df = pd.read_excel(fh)
            # הוספת השורה החדשה
            df = pd.concat([df, pd.DataFrame([new_entry])], ignore_index=True)
        else:
            # יצירת קובץ חדש אם לא קיים
            df = pd.DataFrame([new_entry])
            file_id = None

        # שמירה חזרה לזיכרון והעלאה לדרייב
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False)
        output.seek(0)
        
        media = MediaIoBaseUpload(output, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        if file_id:
            svc.files().update(fileId=file_id, media_body=media, supportsAllDrives=True).execute()
        else:
            meta = {'name': MASTER_FILENAME, 'parents': [GDRIVE_FOLDER_ID]}
            svc.files().create(body=meta, media_body=media, supportsAllDrives=True).execute()
        return True
    except Exception as e:
        st.error(f"שגיאה בעדכון האקסל המרכזי: {e}")
        return False

# --- ממשק ---
st.set_page_config(page_title="יומן תצפית", layout="centered")
st.title("🎓 יומן תצפית - שמירה רציפה")

tab1, tab2 = st.tabs(["📝 הזנה", "📊 נתונים"])

with tab1:
    with st.form("entry_form", clear_on_submit=True):
        student = st.selectbox("תלמיד", ["נתנאל", "רועי", "אסף", "עילאי", "טדי", "גאל", "אופק", "דניאל.ר", "אלי", "טיגרן"])
        done = st.text_area("מה בוצע?")
        c_proj = st.select_slider("מדד שליטה", options=[1,2,3,4,5], value=3)
        
        if st.form_submit_button("💾 שמור תצפית ועדכן אקסל בדרייב"):
            entry = {
                "date": date.today().isoformat(),
                "student_name": student,
                "observation": done,
                "score": c_proj,
                "timestamp": datetime.now().strftime("%H:%M:%S")
            }
            
            # שמירה מקומית לגיבוי
            with open(DATA_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            
            # עדכון האקסל בדרייב
            svc = get_drive_service()
            if svc:
                with st.spinner("מעדכן קובץ אקסל מרכזי בדרייב..."):
                    if update_master_spreadsheet(entry, svc):
                        st.success(f"הנתונים נשמרו בדרייב בתוך הקובץ: {MASTER_FILENAME}")
                        st.balloons()
            else:
                st.error("לא ניתן להתחבר לדרייב.")

with tab2:
    st.write("כאן תוכל לראות את הנתונים המצטברים.")
    if os.path.exists(DATA_FILE):
        data = [json.loads(line) for line in open(DATA_FILE, "r", encoding="utf-8")]
        st.table(pd.DataFrame(data).tail(5)) # מציג את 5 האחרונים

# סוף הקוד