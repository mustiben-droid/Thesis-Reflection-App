import json, base64, os, io, time, pandas as pd, streamlit as st
import google.generativeai as genai
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload
from datetime import date, datetime

# --- 1. הגדרות בסיסיות ---
st.set_page_config(page_title="מערכת תיעוד מחקר איכותני", layout="wide")

MASTER_FILENAME = st.secrets.get("MASTER_FILENAME", "All_Observations_Master.xlsx")
GDRIVE_FOLDER_ID = st.secrets.get("GDRIVE_FOLDER_ID", "")
DATA_FILE = "local_data.json"

# --- 2. חיבור ל-Google Drive ---
@st.cache_resource
def get_drive_service():
    try:
        if "GDRIVE_SERVICE_ACCOUNT_B64" in st.secrets:
            b64 = st.secrets["GDRIVE_SERVICE_ACCOUNT_B64"]
            # ניקוי תווים בלתי נראים
            clean_b64 = "".join(b64.split()).strip()
            js = base64.b64decode(clean_b64).decode("utf-8")
            info = json.loads(js)
            creds = Credentials.from_service_account_info(info, scopes=["https://www.googleapis.com/auth/drive"])
            return build("drive", "v3", credentials=creds)
    except Exception as e:
        st.error(f"שגיאה בחיבור לדרייב: {e}")
    return None

svc = get_drive_service()

# --- 3. טעינת נתונים מהדרייב ---
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
        st.sidebar.warning(f"קובץ המאסטר לא נטען: {e}")
        return pd.DataFrame()

full_df = load_master_data()

# --- 4. ממשק הטאבים ---
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
            st.success(f"התצפית נשמרה. עבור לטאב 'סנכרון' כדי להעלות לדרייב.")
        else:
            st.warning("נא למלא שם ותיאור תצפית.")

# --- Tab 2: סנכרון לדרייב ---
with tab2:
    st.header("🔄 סנכרון נתונים")
    if st.button("🚀 בצע סנכרון עכשיו"):
        if svc is None:
            st.error("אין חיבור לדרייב. בדוק את ה-Secrets.")
        elif os.path.exists(DATA_FILE):
            try:
                with st.spinner("מעלה נתונים לדרייב..."):
                    with open(DATA_FILE, "r", encoding="utf-8") as f:
                        local_entries = [json.loads(line) for line in f if line.strip()]
                    
                    new_df = pd.DataFrame(local_entries)
                    updated_df = pd.concat([full_df, new_df], ignore_index=True).drop_duplicates(subset=['student_name', 'timestamp'], keep='last')

                    buf = io.BytesIO()
                    with pd.ExcelWriter(buf, engine='openpyxl') as w:
                        updated_df.to_excel(w, index=False)
                    buf.seek(0)

                    res = svc.files().list(q=f"name = '{MASTER_FILENAME}'", supportsAllDrives=True).execute().get('files', [])
                    media = MediaIoBaseUpload(buf, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

                    if res:
                        svc.files().update(fileId=res[0]['id'], media_body=media, supportsAllDrives=True).execute()
                    else:
                        meta = {'name': MASTER_FILENAME, 'parents': [GDRIVE_FOLDER_ID] if GDRIVE_FOLDER_ID else []}
                        svc.files().create(body=meta, media_body=media, supportsAllDrives=True).execute()

                    os.remove(DATA_FILE)
                    st.success("✅ סונכרן בהצלחה!")
                    time.sleep(1)
                    st.rerun()
            except Exception as e:
                st.error(f"שגיאה בסנכרון: {e}")
        else:
            st.info("אין נתונים חדשים לסנכרון.")

# --- Tab 3: ניתוח מחקרי ---
with tab3:
    if full_df.empty:
        st.info("אין נתונים לניתוח. בצע סנכרון קודם.")
    else:
        st.header("🧠 ניתוח תמות (AI)")
        df_an = full_df.copy()
        df_an['date'] = pd.to_datetime(df_an['date'], errors='coerce')
        df_an = df_an.dropna(subset=['date'])
        df_an['week'] = df_an['date'].dt.strftime('%Y - שבוע %U')
        
        weeks = sorted(df_an['week'].unique(), reverse=True)
        sel_week = st.selectbox("בחר שבוע לניתוח:", weeks)
        w_df = df_an[df_an['week'] == sel_week]
        
        st.dataframe(w_df[['student_name', 'challenge', 'insight']] if 'insight' in w_df.columns else w_df)

        if st.button("✨ הפק ניתוח איכותני ושמור לדרייב"):
            with st.spinner("ג'ימיני מנתח..."):
                research_text = ""
                for _, row in w_df.iterrows():
                    research_text += f"סטודנט: {row.get('student_name','')} | תצפית: {row.get('challenge','')} | תובנה: {row.get('insight','')}\n---\n"

                try:
                    genai.configure(api_key=st.secrets["GOOGLE_API_KEY"], transport='rest')
                    model = genai.GenerativeModel('gemini-1.5-flash')
                    res = model.generate_content(f"אתה חוקר אקדמי. נתח תמות בשבוע {sel_week}: {research_text}").text
                    
                    st.markdown("### תוצאות הניתוח:")
                    st.info(res)
                    
                    if svc:
                        f_name = f"ניתוח_{sel_week.replace(' ', '_')}.txt"
                        media = MediaIoBaseUpload(io.BytesIO(res.encode('utf-8')), mimetype='text/plain')
                        svc.files().create(body={'name': f_name, 'parents': [GDRIVE_FOLDER_ID] if GDRIVE_FOLDER_ID else []}, media_body=media, supportsAllDrives=True).execute()
                        st.success(f"הניתוח נשמר בדרייב בשם {f_name}")
                except Exception as e:
                    st.error(f"שגיאה בניתוח: {e}")

# --- Sidebar ---
st.sidebar.markdown("---")
st.sidebar.write("מצב חיבור לדרייב:", "✅ מחובר" if svc else "❌ לא מחובר")
if not full_df.empty:
    st.sidebar.write(f"📊 שורות במאסטר: {len(full_df)}")
