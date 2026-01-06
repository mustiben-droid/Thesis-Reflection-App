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

# --- 1. הגדרות וחיבורים ---
DATA_FILE = "reflections.jsonl"
GDRIVE_FOLDER_ID = st.secrets.get("GDRIVE_FOLDER_ID")
MASTER_FILENAME = "All_Observations_Master.xlsx"

def get_drive_service():
    try:
        json_str = base64.b64decode(st.secrets["GDRIVE_SERVICE_ACCOUNT_B64"]).decode("utf-8")
        creds = Credentials.from_service_account_info(json.loads(json_str), scopes=["https://www.googleapis.com/auth/drive.file"])
        return build("drive", "v3", credentials=creds)
    except: return None

# --- 2. לוגיקת האקסל המרכזי ---
def update_master_excel(new_entry, svc):
    """מוסיף שורה חדשה לקובץ האקסל המרכזי בדרייב."""
    try:
        query = f"name = '{MASTER_FILENAME}' and '{GDRIVE_FOLDER_ID}' in parents and trashed = false"
        results = svc.files().list(q=query, fields="files(id)").execute()
        files = results.get('files', [])

        if files:
            file_id = files[0]['id']
            request = svc.files().get_media(fileId=file_id)
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
            fh.seek(0)
            df = pd.read_excel(fh)
            df = pd.concat([df, pd.DataFrame([new_entry])], ignore_index=True)
        else:
            df = pd.DataFrame([new_entry])
            file_id = None

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
    except: return False

# --- 3. ממשק משתמש ---
st.set_page_config(page_title="יומן תצפית", layout="centered")
st.title("🎓 יומן תצפית - מחקר תזה")

tab1, tab2 = st.tabs(["📝 הזנה חדשה", "📊 ניהול נתונים"])

with tab1:
    with st.form("observation_form", clear_on_submit=True):
        student = st.selectbox("שם תלמיד", ["נתנאל", "רועי", "אסף", "עילאי", "טדי", "גאל", "אופק", "דניאל.ר", "אלי", "טיגרן", "אחר..."])
        lesson = st.text_input("מזהה שיעור")
        done = st.text_area("מה בוצע בפועל?")
        c_proj = st.select_slider("רמת שליטה (1-5)", options=[1,2,3,4,5], value=3)
        
        if st.form_submit_button("💾 שמור ועדכן דרייב"):
            entry = {
                "date": date.today().isoformat(),
                "student_name": student,
                "lesson_id": lesson,
                "observation": done,
                "score": c_proj,
                "timestamp": datetime.now().strftime("%H:%M:%S")
            }
            
            # שמירה מקומית (גיבוי)
            with open(DATA_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            
            # שמירה לדרייב
            svc = get_drive_service()
            if svc:
                if update_master_excel(entry, svc):
                    st.success(f"הנתונים נשמרו בדרייב בתוך: {MASTER_FILENAME}")
                    st.balloons()
                else: st.error("שגיאה בעדכון האקסל.")

with tab2:
    st.subheader("🔄 סנכרון היסטוריה")
    if st.button("📤 העלה את כל התצפיות הקיימות לאקסל בדרייב"):
        if os.path.exists(DATA_FILE):
            all_entries = [json.loads(line) for line in open(DATA_FILE, "r", encoding="utf-8")]
            svc = get_drive_service()
            if svc and all_entries:
                df_all = pd.DataFrame(all_entries)
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    df_all.to_excel(writer, index=False)
                output.seek(0)
                media = MediaIoBaseUpload(output, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                # בדיקה אם קיים כדי לעדכן/ליצור
                q = f"name = '{MASTER_FILENAME}' and '{GDRIVE_FOLDER_ID}' in parents and trashed=false"
                res = svc.files().list(q=q).execute().get('files', [])
                if res: svc.files().update(fileId=res[0]['id'], media_body=media, supportsAllDrives=True).execute()
                else: svc.files().create(body={'name': MASTER_FILENAME, 'parents': [GDRIVE_FOLDER_ID]}, media_body=media, supportsAllDrives=True).execute()
                st.success("כל ההיסטוריה סונכרנה בהצלחה!")
        else:
            st.warning("לא נמצאו נתונים קודמים לסנכרון.")

# סוף הקוד