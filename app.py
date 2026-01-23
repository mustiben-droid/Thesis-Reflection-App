import json, base64, os, io, time, pandas as pd, streamlit as st
import google.generativeai as genai
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload
from datetime import date, datetime

# --- 1. הגדרות דף ---
st.set_page_config(page_title="מערכת תיעוד מחקר - גרסה מלאה", layout="wide")

MASTER_FILENAME = st.secrets.get("MASTER_FILENAME", "All_Observations_Master.xlsx")
GDRIVE_FOLDER_ID = st.secrets.get("GDRIVE_FOLDER_ID", "")
DATA_FILE = "local_data.json"

# --- 2. חיבור ל-Google Drive ---
@st.cache_resource
def get_drive_service():
    try:
        b64 = st.secrets["GDRIVE_SERVICE_ACCOUNT_B64"]
        js = base64.b64decode("".join(b64.split())).decode("utf-8")
        info = json.loads(js)
        creds = Credentials.from_service_account_info(info, scopes=["https://www.googleapis.com/auth/drive"])
        return build("drive", "v3", credentials=creds)
    except: return None

svc = get_drive_service()

# --- 3. טעינת נתונים ---
@st.cache_data(ttl=300)
def load_data():
    if svc is None: return pd.DataFrame()
    try:
        res = svc.files().list(q=f"name='{MASTER_FILENAME}'", supportsAllDrives=True).execute().get('files', [])
        if not res: return pd.DataFrame()
        req = svc.files().get_media(fileId=res[0]['id'])
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, req)
        done = False
        while not done: _, done = downloader.next_chunk()
        fh.seek(0)
        return pd.read_excel(fh)
    except: return pd.DataFrame()

full_df = load_data()

# --- 4. ממשק המשתמש ---
tab1, tab2, tab3 = st.tabs(["📝 תיעוד תצפית", "🔄 סנכרון", "📊 ניתוח ומגמות"])

with tab1:
    st.header("📝 תיעוד תצפית וצילום")
    
    # שליפת רשימת סטודנטים קיימת מהאקסל
    student_list = sorted(full_df['student_name'].unique().tolist()) if not full_df.empty else []
    
    col1, col2 = st.columns(2)
    with col1:
        # זיהוי סטודנט - בחירה מרשימה או הוספה
        mode = st.radio("סטודנט:", ["בחר קיים", "הוסף חדש"], horizontal=True)
        if mode == "בחר קיים" and student_list:
            s_name = st.selectbox("שם הסטודנט:", student_list)
        else:
            s_name = st.text_input("שם סטודנט חדש:")
            
        obs_date = st.date_input("תאריך:", date.today())
        
        # סליידרים של דירוג (הוחזרו)
        st.write("---")
        level = st.slider("רמת תפקוד / הצלחה (1-10):", 1, 10, 5)
        difficulty = st.slider("רמת קושי של המשימה:", 1, 10, 5)

    with col2:
        challenge = st.text_area("תיאור התצפית (Challenge):", placeholder="מה קרה?")
        insight = st.text_area("תובנה מחקרית (Insight):", placeholder="מה זה אומר?")
        tags = st.multiselect("תגיות נושאיות:", ["קוגניטיבי", "רגשי", "חברתי", "טכני", "אחר"])

    # העלאת תמונות (הוחזר)
    st.write("---")
    img_file = st.camera_input("📷 צלם תוצר/תצפית") or st.file_uploader("📂 העלאת תמונה", type=['png', 'jpg', 'jpeg'])

    if st.button("💾 שמור תצפית (מקומית)"):
        if s_name and challenge:
            img_b64 = ""
            if img_file:
                img_b64 = base64.b64encode(img_file.read()).decode()
            
            new_entry = {
                "student_name": s_name,
                "date": str(obs_date),
                "challenge": challenge,
                "insight": insight,
                "level": level,
                "difficulty": difficulty,
                "tags": ", ".join(tags),
                "image": img_b64,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            with open(DATA_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(new_entry, ensure_ascii=False) + "\n")
            st.success("התצפית נשמרה בהצלחה! עברי לטאב סנכרון.")
        else:
            st.error("חובה למלא שם סטודנט ותיאור תצפית.")

with tab2:
    st.header("🔄 סנכרון לדרייב")
    if st.button("🚀 בצע סנכרון מלא"):
        if os.path.exists(DATA_FILE):
            try:
                with st.spinner("מעלה נתונים ותמונות..."):
                    with open(DATA_FILE, "r", encoding="utf-8") as f:
                        lines = [json.loads(line) for line in f if line.strip()]
                    
                    for entry in lines:
                        # שמירת תמונה לדרייב אם קיימת
                        img_id = ""
                        if entry.get("image") and svc:
                            img_data = base64.b64decode(entry["image"])
                            media = MediaIoBaseUpload(io.BytesIO(img_data), mimetype='image/jpeg')
                            file_meta = {
                                'name': f"img_{entry['student_name']}_{entry['timestamp']}.jpg",
                                'parents': [GDRIVE_FOLDER_ID] if GDRIVE_FOLDER_ID else []
                            }
                            f_obj = svc.files().create(body=file_meta, media_body=media, supportsAllDrives=True).execute()
                            img_id = f_obj.get('id')
                        
                        entry['image_link'] = f"https://drive.google.com/uc?id={img_id}" if img_id else ""
                        entry.pop('image', None) # מוחק את ה-b64 הכבד

                    new_df = pd.DataFrame(lines)
                    final_df = pd.concat([full_df, new_df], ignore_index=True).drop_duplicates(subset=['student_name', 'timestamp'], keep='last')
                    
                    buf = io.BytesIO()
                    with pd.ExcelWriter(buf, engine='openpyxl') as w:
                        final_df.to_excel(w, index=False)
                    buf.seek(0)
                    
                    res = svc.files().list(q=f"name='{MASTER_FILENAME}'", supportsAllDrives=True).execute().get('files', [])
                    media = MediaIoBaseUpload(buf, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                    if res:
                        svc.files().update(fileId=res[0]['id'], media_body=media, supportsAllDrives=True).execute()
                    
                    os.remove(DATA_FILE)
                    st.success("הסנכרון הסתיים!")
                    st.rerun()
            except Exception as e: st.error(f"שגיאה: {e}")
        else: st.info("אין נתונים לסנכרון.")

with tab3:
    st.header("📊 ניתוח מגמות ו-AI")
    if not full_df.empty:
        # פילטרים מהירים (הוחזר)
        selected_student = st.selectbox("בחר סטודנט למעקב:", ["כולם"] + student_list)
        view_df = full_df if selected_student == "כולם" else full_df[full_df['student_name'] == selected_student]
        
        st.dataframe(view_df)
        
        if st.button("🧠 הפק ניתוח איכותני עמוק"):
            genai.configure(api_key=st.secrets["GOOGLE_API_KEY"], transport='rest')
            model = genai.GenerativeModel('gemini-1.5-flash')
            context = view_df.tail(5).to_string()
            res = model.generate_content(f"נתח את המגמות של הסטודנט {selected_student} על בסיס הנתונים הבאים בעברית אקדמית: {context}").text
            st.info(res)
