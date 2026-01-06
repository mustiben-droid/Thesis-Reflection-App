import json
import base64
import os
import io
from datetime import date, datetime
import pandas as pd
import streamlit as st
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# --- הגדרות ---
GDRIVE_FOLDER_ID = st.secrets.get("GDRIVE_FOLDER_ID")
MASTER_FILENAME = "All_Observations_Master.xlsx"

def get_drive_service():
    try:
        json_str = base64.b64decode(st.secrets["GDRIVE_SERVICE_ACCOUNT_B64"]).decode("utf-8")
        creds = Credentials.from_service_account_info(json.loads(json_str), scopes=["https://www.googleapis.com/auth/drive.file"])
        return build("drive", "v3", credentials=creds)
    except: return None

def sync_all_from_drive():
    """סורק את כל קבצי ה-JSON בדרייב ומאחד אותם לאקסל אחד."""
    svc = get_drive_service()
    if not svc: return "שגיאת חיבור לדרייב"
    
    # חיפוש כל קבצי ה-JSON בתיקייה
    query = f"'{GDRIVE_FOLDER_ID}' in parents and mimeType = 'application/json' and trashed = false"
    results = svc.files().list(q=query, fields="files(id, name)").execute()
    files = results.get('files', [])
    
    if not files: return "לא נמצאו קבצי נתונים (JSON) בדרייב"
    
    all_data = []
    for f in files:
        content = svc.files().get_media(fileId=f['id']).execute()
        try:
            data = json.loads(content)
            all_data.append(data)
        except: continue
    
    if all_data:
        df = pd.DataFrame(all_data)
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False)
        output.seek(0)
        
        # שמירת האקסל המאוחד לדרייב
        media = MediaIoBaseUpload(output, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        meta = {'name': MASTER_FILENAME, 'parents': [GDRIVE_FOLDER_ID]}
        
        # בדיקה אם האקסל כבר קיים כדי לעדכן אותו במקום ליצור חדש
        exist_query = f"name = '{MASTER_FILENAME}' and '{GDRIVE_FOLDER_ID}' in parents and trashed = false"
        exist_res = svc.files().list(q=exist_query).execute().get('files', [])
        
        if exist_res:
            svc.files().update(fileId=exist_res[0]['id'], media_body=media, supportsAllDrives=True).execute()
        else:
            svc.files().create(body=meta, media_body=media, supportsAllDrives=True).execute()
            
        return f"הצלחה! אוחדו {len(all_data)} תצפיות לקובץ אקסל אחד בדרייב."
    return "לא נמצאו נתונים תקינים."

# --- ממשק פשוט לבדיקה ---
st.title("🔄 שחזור ואיחוד נתונים מהדרייב")

if st.button("🚀 סרוק דרייב ואחד את כל התצפיות לאקסל"):
    with st.spinner("סורק קבצים..."):
        message = sync_all_from_drive()
        st.success(message)

# סוף הקוד