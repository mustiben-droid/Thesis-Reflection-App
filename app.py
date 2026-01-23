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
        # ניקוי תווים ופיענוח
        js = base64.b64decode("".join(b64.split())).decode("utf-8")
        info = json.loads(js)
        creds = Credentials.from_service_account_info(info, scopes=["https://www.googleapis.com/auth/drive"])
        return build("drive", "v3", credentials=creds)
    except Exception as e:
        st.error(f"שגיאה בחיבור לדרייב: {e}")
        return None

svc = get_drive_service()

# --- 3. טעינת נתונים (Master File) ---
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
    except:
        return pd.DataFrame()

full_df = load_data()

# --- 4. ממשק המשתמש (טאבים) ---
tab1, tab2, tab3 = st.tabs(["📝 תיעוד תצפית", "🔄 סנכרון", "📊 ניתוח ומגמות"])

with tab1:
    st.header("📝 תיעוד תצפית וצילום")
    
    # שליפת רשימת סטודנטים קיימת מהאקסל
    student_list = []
    if not full_df.empty and 'student_name' in full_df.columns:
        student_list = sorted(full_df['student_name'].dropna().unique().tolist())
    
    col1, col2 = st.columns(2)
    with col1:
        # זיהוי סטודנט
        mode = st.radio("סטודנט:", ["בחר מרשימה", "הוסף שם חדש"], horizontal=True)
        if mode == "בחר מרשימה" and student_list:
            s_name = st.selectbox("שם הסטודנט:", student_list)
        else:
            s_name = st.text_input("הקלד שם סטודנט:")
            
        obs_date = st.date_input("תאריך התצפית:", date.today())
        
        st.write("---")
        st.subheader("📊 מדדי תפקוד")
        level = st.slider("רמת תפקוד / הצלחה (1-10):", 1, 10, 5)
        difficulty = st.slider("רמת קושי של המשימה (1-10):", 1, 10, 5)

    with col2:
        challenge = st.text_area("תיאור התצפית (Challenge):", placeholder="תארי מה קרה במפגש...")
        insight = st.text_area("תובנה מחקרית (Insight):", placeholder="מה המשמעות של התצפית הזו?")
        tags = st.multiselect("תגיות נושאיות:", ["קוגניטיבי", "רגשי", "חברתי", "שפתי", "מוטורי", "טכני"])

    # העלאת תמונות
    st.write("---")
    st.subheader("📷 תיעוד ויזואלי")
    img_file = st.camera_input("צלם תוצר או רגע מהתצפית") or st.file_uploader("או העלה קובץ תמונה", type=['png', 'jpg', 'jpeg'])

    if st.button("💾 שמור תצפית באופן זמני"):
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
                "image_data": img_b64, # נשמר זמנית כטקסט עד הסנכרון
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            # שמירה לקובץ מקומי
            with open(DATA_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(new_entry, ensure_ascii=False) + "\n")
            st.success(f"התצפית על {s_name} נשמרה במכשיר. אל תשכחי לסנכרן בטאב 2!")
        else:
            st.error("חובה למלא שם סטודנט ותיאור תצפית.")

with tab2:
    st.header("🔄 סנכרון וגיבוי לדרייב")
    st.write("פעולה זו תעלה את כל התצפיות והתמונות הממתינות לאקסל המרכזי בדרייב.")
    
    if st.button("🚀 בצע סנכרון עכשיו"):
        if os.path.exists(DATA_FILE):
            try:
                with st.spinner("מעלה נתונים ומעבד תמונות..."):
                    with open(DATA_FILE, "r", encoding="utf-8") as f:
                        lines = [json.loads(line) for line in f if line.strip()]
                    
                    final_entries = []
                    for entry in lines:
                        # טיפול בתמונה: העלאה לדרייב וקבלת לינק
                        img_link = ""
                        if entry.get("image_data") and svc:
                            try:
                                img_bytes = base64.b64decode(entry["image_data"])
                                media = MediaIoBaseUpload(io.BytesIO(img_bytes), mimetype='image/jpeg')
                                file_meta = {
                                    'name': f"img_{entry['student_name']}_{entry['timestamp']}.jpg",
                                    'parents': [GDRIVE_FOLDER_ID] if GDRIVE_FOLDER_ID else []
                                }
                                drive_file = svc.files().create(body=file_meta, media_body=media, supportsAllDrives=True).execute()
                                img_link = f"https://drive.google.com/uc?id={drive_file.get('id')}"
                            except: pass
                        
                        # ניקוי ה-B64 הכבד ובניית השורה הסופית
                        entry['image_link'] = img_link
                        entry.pop('image_data', None)
                        final_entries.append(entry)

                    new_df = pd.DataFrame(final_entries)
                    
                    # איחוד עם המאסטר
                    if not full_df.empty:
                        combined_df = pd.concat([full_df, new_df], ignore_index=True)
                    else:
                        combined_df = new_df
                    
                    combined_df = combined_df.drop_duplicates(subset=['student_name', 'timestamp'], keep='last')
                    
                    # העלאת האקסל המעודכן
                    buf = io.BytesIO()
                    with pd.ExcelWriter(buf, engine='openpyxl') as w:
                        combined_df.to_excel(w, index=False)
                    buf.seek(0)
                    
                    res = svc.files().list(q=f"name='{MASTER_FILENAME}'", supportsAllDrives=True).execute().get('files', [])
                    media_excel = MediaIoBaseUpload(buf, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                    
                    if res:
                        svc.files().update(fileId=res[0]['id'], media_body=media_excel, supportsAllDrives=True).execute()
                    else:
                        meta = {'name': MASTER_FILENAME, 'parents': [GDRIVE_FOLDER_ID] if GDRIVE_FOLDER_ID else []}
                        svc.files().create(body=meta, media_body=media_excel, supportsAllDrives=True).execute()
                    
                    os.remove(DATA_FILE)
                    st.success("✅ הסנכרון הושלם בהצלחה! האקסל והתמונות בדרייב.")
                    time.sleep(1)
                    st.rerun()
            except Exception as e:
                st.error(f"תקלה בסנכרון: {e}")
        else:
            st.info("אין נתונים חדשים הממתינים לסנכרון.")

with tab3:
    st.header("📊 ניתוח מגמות ו-AI")
    if not full_df.empty:
        # פילטרים
        col_f1, col_f2 = st.columns(2)
        with col_f1:
            sel_student = st.selectbox("סנן לפי סטודנט:", ["כולם"] + student_list)
        
        view_df = full_df if sel_student == "כולם" else full_df[full_df['student_name'] == sel_student]
        
        st.dataframe(view_df)
        
        # ניתוח AI
        st.write("---")
        if st.button("🧠 הפק ניתוח איכותני עמוק (Gemini)"):
            with st.spinner("מנתח תהליכי למידה..."):
                try:
                    genai.configure(api_key=st.secrets["GOOGLE_API_KEY"], transport='rest')
                    model = genai.GenerativeModel('gemini-1.5-flash')
                    
                    # לוקחים את 5 התצפיות האחרונות כהקשר
                    context = view_df.tail(5).to_string()
                    prompt = f"נתח את מגמות הלמידה וההתפתחות של הסטודנט {sel_student} על בסיס הנתונים הבאים בעברית אקדמית: {context}"
                    
                    res = model.generate_content(prompt).text
                    st.markdown("### 📝 סיכום מחקרי:")
                    st.info(res)
                except Exception as e:
                    st.error(f"שגיאה בניתוח AI: {e}")
    else:
        st.info("אין נתונים להצגה. סנכרני נתונים בטאב 2.")
