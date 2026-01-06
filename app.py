import json
import base64
import os
import io
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
        creds = Credentials.from_service_account_info(json.loads(json_str), scopes=["https://www.googleapis.com/auth/drive"])
        return build("drive", "v3", credentials=creds)
    except Exception as e:
        st.error(f"שגיאת חיבור: {e}")
        return None

def debug_and_sync():
    svc = get_drive_service()
    if not svc: return
    
    st.write(f"🔍 בודק את תיקייה: `{GDRIVE_FOLDER_ID}`")
    
    # חיפוש כל הקבצים בתיקייה ללא הגבלת סוג (כדי לראות מה יש שם)
    query = f"'{GDRIVE_FOLDER_ID}' in parents and trashed = false"
    results = svc.files().list(q=query, fields="files(id, name, mimeType)", supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
    files = results.get('files', [])
    
    if not files:
        st.warning("⚠️ לא נמצאו קבצים כלל בתיקייה הזו בדרייב.")
        return

    st.write(f"מצאתי {len(files)} קבצים בתיקייה. מנתח נתונים...")
    
    all_data = []
    for f in files:
        # אנחנו מחפשים קבצי JSON שהם התצפיות ששמרת בעבר
        if "json" in f['mimeType'] or f['name'].endswith(".json"):
            try:
                content = svc.files().get_media(fileId=f['id']).execute()
                data = json.loads(content)
                # אם זה קובץ תצפית תקין, נוסיף אותו
                if isinstance(data, dict):
                    all_data.append(data)
            except:
                continue

    if all_data:
        st.success(f"✅ הצלחתי לאסוף {len(all_data)} תצפיות!")
        df = pd.DataFrame(all_data)
        
        # יצירת האקסל
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False)
        output.seek(0)
        
        # העלאה לדרייב
        media = MediaIoBaseUpload(output, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        meta = {'name': MASTER_FILENAME, 'parents': [GDRIVE_FOLDER_ID]}
        
        try:
            svc.files().create(body=meta, media_body=media, supportsAllDrives=True).execute()
            st.balloons()
            st.success(f"🌟 הקובץ `{MASTER_FILENAME}` נוצר בהצלחה בדרייב!")
        except Exception as e:
            st.error(f"שגיאה ביצירת האקסל: {e}")
    else:
        st.error("❌ לא נמצאו קבצי תצפיות (JSON) בתיקייה, למרות שיש בה קבצים אחרים.")

# --- ממשק ---
st.title("🛠️ אבחון וסינכרון נתונים")
if st.button("התחל אבחון וחיבור נתונים"):
    debug_and_sync()

# סוף הקוד