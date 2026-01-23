import json, base64, os, io, time, pandas as pd, streamlit as st
import google.generativeai as genai
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload
from datetime import date, datetime

# --- הגדרות דף ---
st.set_page_config(page_title="מערכת תיעוד מחקר איכותני", layout="wide")

# --- משתני סביבה מה-Secrets ---
MASTER_FILENAME = st.secrets.get("MASTER_FILENAME", "All_Observations_Master.xlsx")
GDRIVE_FOLDER_ID = st.secrets.get("GDRIVE_FOLDER_ID", "")
DATA_FILE = "local_data.json"

# --- חיבור ל-Google Drive (שחזור גרסה יציבה) ---
@st.cache_resource
def get_drive_service():
    try:
        if "GDRIVE_SERVICE_ACCOUNT_B64" in st.secrets:
            b64 = st.secrets["GDRIVE_SERVICE_ACCOUNT_B64"]
            js = base64.b64decode(b64).decode("utf-8")
            info = json.loads(js)
            creds = Credentials.from_service_account_info(info, scopes=["https://www.googleapis.com/auth/drive"])
            return build("drive", "v3", credentials=creds)
    except Exception as e:
        st.error(f"שגיאה בחיבור לדרייב: {e}")
    return None

svc = get_drive_service()

# --- טעינת נתונים מהדרייב (Master File) ---
@st.cache_data(ttl=300)
def load_master_data():
    if svc is None: return pd.DataFrame()
    try:
        query = f"name = '{MASTER_FILENAME}' and trashed = false"
        res = svc.files().list(q=query, supportsAllDrives=True).execute().get('files', [])
        if not res: return pd.DataFrame()
        
        request = svc.files().get_media(fileId=res[0]['id'])
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        fh.seek(0)
        return pd.read_excel(fh)
    except Exception as e:
        st.warning(f"לא ניתן היה לטעון את קובץ המאסטר: {e}")
        return pd.DataFrame()

full_df = load_master_data()

# --- ממשק הטאבים ---
tab1, tab2, tab3 = st.tabs(["📝 תיעוד", "🔄 סנכרון", "📊 ניתוח מחקרי"])

# --- Tab 1: תיעוד תצפית ---
with tab1:
    st.header("📝 תיעוד תצפית חדשה")
    
    col1, col2 = st.columns(2)
    with col1:
        s_name = st.text_input("שם הסטודנט:")
        obs_date = st.date_input("תאריך:", date.today())
    with col2:
        challenge = st.text_area("תיאור התצפית (Challenge):")
        insight_text = st.text_area("פרשנות מחקרית (Insight):")

    if st.button("💾 שמור תצפית מקומית"):
        if s_name and challenge:
            new_data = {
                "student_name": s_name,
                "date": str(obs_date),
                "challenge": challenge,
                "insight": insight_text,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            with open(DATA_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(new_data, ensure_ascii=False) + "\n")
            st.success(f"התצפית על {s_name} נשמרה זמנית. עבור לטאב 'סנכרון' כדי להעלות לדרייב.")
        else:
            st.warning("נא למלא לפחות שם סטודנט ותיאור תצפית.")

# --- Tab 2: סנכרון לדרייב ---
with tab2:
    st.header("🔄 סנכרון נתונים")
    
    if st.button("🚀 בצע סנכרון מלא לדרייב"):
        if svc is None:
            st.error("❌ אין חיבור תקין לדרייב. בדוק את ה-Secrets.")
        elif os.path.exists(DATA_FILE):
            try:
                with st.spinner("מסנכרן נתונים..."):
                    with open(DATA_FILE, "r", encoding="utf-8") as f:
                        local_entries = [json.loads(line) for line in f if line.strip()]
                    
                    new_df = pd.DataFrame(local_entries)
                    
                    # איחוד עם הדאטה הקיים והסרת כפילויות
                    updated_df = pd.concat([full_df, new_df], ignore_index=True)
                    updated_df = updated_df.drop_duplicates(subset=['student_name', 'timestamp'], keep='last')

                    # יצירת קובץ אקסל בזיכרון
                    buf = io.BytesIO()
                    with pd.ExcelWriter(buf, engine='openpyxl') as w:
                        updated_df.to_excel(w, index=False)
                    buf.seek(0)

                    # חיפוש הקובץ בדרייב לעדכון
                    res = svc.files().list(q=f"name = '{MASTER_FILENAME}'", supportsAllDrives=True).execute().get('files', [])
                    media = MediaIoBaseUpload(buf, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

                    if res:
                        svc.files().update(fileId=res[0]['id'], media_body=media, supportsAllDrives=True).execute()
                    else:
                        meta = {'name': MASTER_FILENAME, 'parents': [GDRIVE_FOLDER_ID] if GDRIVE_FOLDER_ID else []}
                        svc.files().create(body=meta, media_body=media, supportsAllDrives=True).execute()

                    os.remove(DATA_FILE)
                    st.success("✅ הסנכרון הסתיים בהצלחה!")
                    time.sleep(1)
                    st.rerun()
            except Exception as e:
                st.error(f"שגיאה במהלך הסנכרון: {e}")
        else:
            st.info("אין נתונים חדשים הממתינים לסנכרון.")

# --- Tab 3: ניתוח מחקרי איכותני ---
with tab3:
    if full_df.empty:
        st.info("אין נתונים זמינים לניתוח. וודא שביצעת סנכרון בטאב 2.")
    else:
        st.header("🧠 ניתוח תמות כיתתי")
        
        # עיבוד תאריכים ושבועות
        df_an = full_df.copy()
        df_an['date'] = pd.to_datetime(df_an['date'], errors='coerce')
        df_an = df_an.dropna(subset=['date'])
        df_an['week'] = df_an['date'].dt.strftime('%Y - שבוע %U')
        
        weeks = sorted(df_an['week'].unique(), reverse=True)
        sel_week = st.selectbox("בחר שבוע לניתוח:", weeks)
        
        w_df = df_an[df_an['week'] == sel_week]
        
        # הצגת נתונים לווידוא
        st.subheader(f"📋 תצפיות שנמצאו לשבוע {sel_week}")
        # וידוא עמודות קיימות בטבלה
        cols_to_show = [c for c in ['student_name', 'challenge', 'insight'] if c in w_df.columns]
        st.dataframe(w_df[cols_to_show])

        if st.button("✨ הפק ניתוח איכותני (Gemini) ושמור לדרייב"):
            if 'insight' not in w_df.columns:
                st.error("לא נמצאה עמודת 'insight' באקסל. וודא שהנתונים נשמרו נכון.")
            else:
                with st.spinner("מנתח תמות וקשרים..."):
                    # בניית ההקשר ל-AI
                    research_text = ""
                    for _, row in w_df.iterrows():
                        research_text += f"סטודנט: {row['student_name']}\n"
                        research_text += f"תצפית: {row['challenge']}\n"
                        research_text += f"תובנה: {row['insight']}\n"
                        research_text += "--- \n"

                    prompt = f"""
                    אתה חוקר אקדמי בכיר. בצע ניתוח תמטי (Thematic Analysis) על נתוני שבוע {sel_week}.
                    זהה דפוסי למידה וקשיים קוגניטיביים שחזרו אצל מספר סטודנטים.
                    נסח פסקה אקדמית לפרק הממצאים בעברית רהוטה ומקצועית.
                    
                    נתונים:
                    {research_text}
                    """

                    try:
                        genai.configure(api_key=st.secrets["GOOGLE_API_KEY"], transport='rest')
                        model = genai.GenerativeModel('gemini-1.5-flash')
                        res = model.generate_content(prompt).text
                        
                        st.markdown("---")
                        st.markdown("### 📝 תוצאות הניתוח:")
                        st.info(res)
                        
                        # שמירה לדרייב כקובץ טקסט
                        if svc:
                            f_name = f"ניתוח_איכותני_{sel_week.replace(' ', '_')}.txt"
                            media = MediaIoBaseUpload(io.BytesIO(res.encode('utf-8')), mimetype='text/plain')
                            svc.files().create(
                                body={'name': f_name, 'parents': [GDRIVE_FOLDER_ID] if GDRIVE_FOLDER_ID else []},
                                media_body=media,
                                supportsAllDrives=True
                            ).execute()
                            st.success(f"✅ הניתוח נשמר בדרייב בשם: {f_name}")
                    except Exception as e:
                        st.error(f"שגיאה בהפקת הניתוח: {e}")

# --- שורת מצב תחתונה ---
st.sidebar.markdown("---")
if svc:
    st.sidebar.success("✅ מחובר ל-Google Drive")
    st.sidebar.write(f"📂 מאסטר: {MASTER_FILENAME}")
    st.sidebar.write(f"📊 שורות במאגר: {len(full_df)}")
else:
    st.sidebar.error("❌ לא מחובר לדרייב")
