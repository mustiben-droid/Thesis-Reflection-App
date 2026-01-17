import json
import base64
import os
import io
from datetime import date, datetime
import pandas as pd
import streamlit as st
from google import genai
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload

# --- 1. הגדרות ועיצוב RTL ---
DATA_FILE = "reflections.jsonl"
GDRIVE_FOLDER_ID = st.secrets.get("GDRIVE_FOLDER_ID") 
MASTER_FILENAME = "All_Observations_Master.xlsx"

CLASS_ROSTER = ["נתנאל", "רועי", "אסף", "עילאי", "טדי", "גאל", "אופק", "דניאל.ר", "אלי", "טיגרן", "פולינה.ק", "תלמיד אחר..."]
OBSERVATION_TAGS = ["התעלמות מקווים נסתרים", "בלבול בין היטלים", "קושי ברוטציה מנטלית", "טעות בפרופורציות", "קושי במעבר בין היטלים", "שימוש בכלי מדידה", "סיבוב פיזי של המודל", "תיקון עצמי", "עבודה עצמאית שוטפת"]

st.set_page_config(page_title="עוזר מחקר אקדמי - גרסה סופית לתזה", layout="wide")

st.markdown("""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Heebo:wght@300;400;700&display=swap');
        html, body, .stApp { direction: rtl; text-align: right; font-family: 'Heebo', sans-serif !important; }
        .stTextInput input, .stTextArea textarea, .stSelectbox > div > div { direction: rtl; text-align: right; }
        [data-testid="stSlider"] { direction: ltr !important; }
        .stButton > button { width: 100%; font-weight: bold; border-radius: 10px; }
    </style>
""", unsafe_allow_html=True)

# --- 2. פונקציות Google Drive ---
def get_drive_service():
    try:
        json_str = base64.b64decode(st.secrets["GDRIVE_SERVICE_ACCOUNT_B64"]).decode("utf-8")
        creds = Credentials.from_service_account_info(json.loads(json_str), scopes=["https://www.googleapis.com/auth/drive.file"])
        return build("drive", "v3", credentials=creds)
    except: return None

def upload_file_to_drive(uploaded_file, svc):
    try:
        file_metadata = {'name': uploaded_file.name}
        if GDRIVE_FOLDER_ID: file_metadata['parents'] = [GDRIVE_FOLDER_ID]
        media = MediaIoBaseUpload(io.BytesIO(uploaded_file.getvalue()), mimetype=uploaded_file.type)
        file = svc.files().create(body=file_metadata, media_body=media, fields='id, webViewLink', supportsAllDrives=True).execute()
        return file.get('webViewLink')
    except: return "Error"

def fetch_history_from_drive(student_name, svc):
    try:
        query = f"name = '{MASTER_FILENAME}' and trashed = false"
        if GDRIVE_FOLDER_ID: query += f" and '{GDRIVE_FOLDER_ID}' in parents"
        res = svc.files().list(q=query, supportsAllDrives=True, includeItemsFromAllDrives=True).execute().get('files', [])
        if not res: return ""
        file_id = res[0]['id']; request = svc.files().get_media(fileId=file_id)
        fh = io.BytesIO(); downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done: _, done = downloader.next_chunk()
        fh.seek(0); df = pd.read_excel(fh)
        student_data = df[df['student_name'].str.contains(student_name, na=False, case=False)]
        if student_data.empty: return ""
        hist = ""
        for _, row in student_data.tail(15).iterrows():
            hist += f"תאריך: {row.get('date')} | קושי: {row.get('challenge')} | שרטוטים: {row.get('num_drawings', 0)} | זמן: {row.get('work_duration', 0)} | פעולות: {row.get('done')}\n"
        return hist
    except: return ""

def update_master_excel(data_to_add, svc):
    try:
        query = f"name = '{MASTER_FILENAME}' and trashed = false"
        if GDRIVE_FOLDER_ID: query += f" and '{GDRIVE_FOLDER_ID}' in parents"
        res = svc.files().list(q=query, supportsAllDrives=True, includeItemsFromAllDrives=True).execute().get('files', [])
        new_df = pd.DataFrame(data_to_add)
        if res:
            file_id = res[0]['id']; request = svc.files().get_media(fileId=file_id)
            fh = io.BytesIO(); downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done: _, done = downloader.next_chunk()
            fh.seek(0); existing_df = pd.read_excel(fh)
            df = pd.concat([existing_df, new_df]).drop_duplicates(subset=['timestamp', 'student_name'], keep='last')
        else:
            df = new_df; file_id = None
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer: df.to_excel(writer, index=False)
        output.seek(0); media = MediaIoBaseUpload(output, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        if file_id: svc.files().update(fileId=file_id, media_body=media, supportsAllDrives=True).execute()
        else:
            file_meta = {'name': MASTER_FILENAME}
            if GDRIVE_FOLDER_ID: file_meta['parents'] = [GDRIVE_FOLDER_ID]
            svc.files().create(body=file_meta, media_body=media, supportsAllDrives=True).execute()
        return True
    except: return False

# --- 3. ממשק המשתמש ---
if "form_iteration" not in st.session_state: st.session_state.form_iteration = 0
if "chat_history" not in st.session_state: st.session_state.chat_history = []

st.title("🎓 יומן תצפית - סנכרון דרייב וחיפוש אקדמי")
tab1, tab2, tab3 = st.tabs(["📝 תצפית ושיחה", "📊 ניהול נתונים", "🤖 סיכום מגמות"])
svc = get_drive_service()

with tab1:
    col_in, col_chat = st.columns([1.1, 1.1])
    with col_in:
        with st.container(border=True):
            it = st.session_state.form_iteration
            name_sel = st.selectbox("👤 בחר סטודנט", CLASS_ROSTER, key=f"n_{it}")
            student_name = st.text_input("שם חופשי:", key=f"fn_{it}") if name_sel == "תלמיד אחר..." else name_sel
            drive_history = fetch_history_from_drive(student_name, svc) if (student_name and svc) else ""
            if drive_history: st.success(f"✅ היסטוריה של {student_name} נטענה.")

            st.markdown("### 📊 מדדים כמותיים")
            q1, q2 = st.columns(2)
            with q1: num_drawings = st.number_input("כמות שרטוטים", min_value=0, step=1, key=f"nd_{it}")
            with q2: work_duration = st.number_input("זמן עבודה (דק')", min_value=0, step=5, key=f"wd_{it}")

            st.divider()
            challenge = st.text_area("🗣️ תיאור קשיים (חובה)", key=f"ch_{it}")
            done = st.text_area("👀 פעולות שבוצעו", key=f"do_{it}")
            tags = st.multiselect("🏷️ תגיות", OBSERVATION_TAGS, key=f"t_{it}")
            uploaded_files = st.file_uploader("קבצים", accept_multiple_files=True, key=f"f_{it}")

            if st.button("💾 שמור תצפית"):
                if not challenge.strip(): st.error("חובה להזין קושי.")
                else:
                    links = []
                    if uploaded_files and svc:
                        for f in uploaded_files: links.append(upload_file_to_drive(f, svc))
                    entry = {
                        "date": date.today().isoformat(), "student_name": student_name,
                        "num_drawings": num_drawings, "work_duration": work_duration,
                        "challenge": challenge, "done": done, "timestamp": datetime.now().strftime("%H:%M:%S"),
                        "file_links": ", ".join(links), "tags": ", ".join(tags)
                    }
                    with open(DATA_FILE, "a", encoding="utf-8") as f: f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                    if svc: update_master_excel([entry], svc)
                    st.success("נשמר!")
                    st.session_state.form_iteration += 1
                    st.rerun()

    with col_chat:
        st.subheader(f"🤖 עוזר מחקר אקדמי: {student_name}")
        chat_cont = st.container(height=550)
        with chat_cont:
            for q, a in st.session_state.chat_history:
                st.markdown(f"**🧐 חוקר:** {q}"); st.info(f"**🤖 AI:** {a}")
        u_input = st.chat_input("שאל את עוזר המחקר...")
        if u_input:
            client = genai.Client(api_key=st.secrets["GOOGLE_API_KEY"])
            # הגדרת דמות החוקר והפורמט המבוקש
            prompt = f"""
            אתה עוזר מחקר אקדמי בכיר המלווה חוקר בכתיבת תזה על חינוך הנדסי וראייה מרחבית. 
            פנה תמיד למשתמש כאל 'החוקר' וענה בצורה מקצועית ואקדמית.
            
            נושא השיחה: הסטודנט {student_name}.
            נתוני התצפיות שנאספו עליו עד כה: {drive_history}.
            
            הנחיות לכתיבה:
            1. השתמש בציטוטים בתוך הטקסט בפורמט APA (למשל: Smith, 2017).
            2. התמקד במקורות מכתבי עת אקדמיים (Journals) וספרים מקצועיים משנת 2014 ומעלה.
            3. הימנע מקישורים לאתרים כלליים כמו Quora, Reddit או ויקיפדיה.
            4. בסוף התשובה, ספק רשימה ביבליוגרפית מלאה בפורמט APA 7th Edition.
            5. נתח את הקשיים של הסטודנט מול התאוריות המקובלות (כמו המודל של Sorby או Cognitive Load Theory).
            
            שאלה מהחוקר: {u_input}
            """
            res = client.models.generate_content(
                model="gemini-2.0-flash", 
                contents=prompt,
                config={'tools': [{'google_search': {}}]} 
            )
            st.session_state.chat_history.append((u_input, res.text)); st.rerun()

with tab2:
    if st.button("🔄 סנכרון לדרייב"):
        if os.path.exists(DATA_FILE) and svc:
            all_d = [json.loads(l) for l in open(DATA_FILE, "r", encoding="utf-8")]
            update_master_excel(all_d, svc); st.success("סונכרן!")

with tab3:
    st.header("🤖 ניתוח מגמות אקדמי")
    if st.button("✨ בצע ניתוח עומק לתזה"):
        if svc:
            with st.spinner("מנתח נתונים ומחפש ספרות רלוונטית..."):
                query = f"name = '{MASTER_FILENAME}' and trashed = false"
                res = svc.files().list(q=query, supportsAllDrives=True).execute().get('files', [])
                if res:
                    file_id = res[0]['id']; request = svc.files().get_media(fileId=file_id)
                    fh = io.BytesIO(); downloader = MediaIoBaseDownload(fh, request)
                    done = False
                    while not done: _, done = downloader.next_chunk()
                    fh.seek(0); df = pd.read_excel(fh)
                    
                    data_summary = ""
                    for _, row in df.iterrows():
                        data_summary += f"תלמיד: {row['student_name']} | קושי: {row['challenge']} | פעולות: {row.get('done')}\n"
                    
                    client = genai.Client(api_key=st.secrets["GOOGLE_API_KEY"])
                    prompt = f"""
                    בצע ניתוח מגמות אקדמי עבור החוקר. 
                    הנתונים: {data_summary}
                    
                    דגשים לניתוח:
                    1. השתמש במינוח אקדמי מקצועי (Spatial Visualization, Mental Rotation, Orthographic Projection).
                    2. שלב ציטוטים של חוקרים מובילים (כגון Sorby, Maier, Gorska) בתוך הניתוח.
                    3. ספק רשימה ביבליוגרפית בפורמט APA 7th Edition בסוף.
                    """
                    response = client.models.generate_content(
                        model="gemini-2.0-flash", 
                        contents=prompt,
                        config={'tools': [{'google_search': {}}]}
                    )
                    st.markdown(response.text)
