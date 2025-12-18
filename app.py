import json
import base64
import os
import io
from datetime import date, datetime, timedelta
import pandas as pd
import streamlit as st
from google import genai

# --- Google Drive Imports ---
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# --- 1. הגדרות קבועות ---
DATA_FILE = "reflections.jsonl"
GDRIVE_FOLDER_ID = st.secrets.get("GDRIVE_FOLDER_ID")

CLASS_ROSTER = [
    "נתנאל",
    "רועי",
    "אסף",
    "עילאי",
    "תלמיד אחר..." 
]

OBSERVATION_TAGS = [
    "התעלמות מקווים נסתרים",
    "בלבול בין היטלים (צד/פנים/על)",
    "קושי ברוטציה מנטלית",
    "טעות בפרופורציות/מידות",
    "קושי במעבר בין היטלים",
    "שימוש בכלי מדידה",
    "סיבוב פיזי של המודל",
    "שימוש בתנועות ידיים (Embodiment)",
    "ספירת משבצות",
    "תיקון עצמי",
    "בקשת אישור תכופה",
    "ויתור/תסכול",
    "עבודה עצמאית שוטפת",
    "הבנה אינטואיטיבית מהירה"
]

# --- 2. עיצוב (CSS) ---
def setup_design():
    st.set_page_config(page_title="יומן תצפית", page_icon="🎓", layout="centered")
    
    st.markdown("""
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Heebo:wght@300;400;700&display=swap');

            /* הגדרות בסיס */
            :root {
                --background-color: #ffffff;
                --text-color: #000000;
            }

            html, body, .stApp {
                background-color: #ffffff !important;
                color: #000000 !important;
                font-family: 'Heebo', sans-serif !important;
                direction: rtl;
                text-align: right;
            }

            .block-container { 
                padding-top: 1rem !important; 
                padding-bottom: 5rem !important; 
                max-width: 100% !important; 
            }

            /* --- כותרות וטקסטים --- */
            h1, h2, h3, h4, h5, h6 { 
                color: #2c3e50 !important; 
                font-family: 'Heebo', sans-serif !important;
                text-align: right !important;
                direction: rtl !important;
                width: 100%;
            }
            h1 { text-align: center !important; } 

            p, label, span, div, small { 
                color: #000000 !important; 
                text-align: right;
                direction: rtl;
            }

            /* --- שדות קלט --- */
            .stTextInput input, .stTextArea textarea, .stSelectbox > div > div {
                background-color: #ffffff !important;
                color: #000000 !important;
                border: 1px solid #ced4da !important;
                border-radius: 8px;
                direction: rtl;
                text-align: right;
            }

            /* --- תפריטים נפתחים --- */
            div[data-baseweb="popover"], ul[data-baseweb="menu"] {
                background-color: #ffffff !important;
                border: 1px solid #cccccc !important;
                text-align: right !important;
            }
            li[role="option"] {
                background-color: #ffffff !important;
                color: black !important;
                text-align: right !important;
                direction: rtl !important;
                justify-content: flex-end !important;
            }
            div[data-baseweb="select"] span {
                color: #000000 !important;
                -webkit-text-fill-color: #000000 !important;
                text-align: right !important;
            }

            /* --- כפתורים --- */
            .stButton > button, .stDownloadButton > button {
                background-color: #f0f2f6 !important;
                color: #000000 !important;
                border: 1px solid #b0b0b0 !important;
                border-radius: 8px;
                width: 100%;
                font-weight: bold;
                -webkit-text-fill-color: #000000 !important;
            }
            [data-testid="stFormSubmitButton"] > button {
                background: linear-gradient(90deg, #4361ee 0%, #3a0ca3 100%) !important;
                color: white !important;
                -webkit-text-fill-color: white !important;
                border: none;
                box-shadow: 0 4px 6px rgba(0,0,0,0.1);
            }

            /* --- כרטיס ובועות צ'אט --- */
            [data-testid="stForm"] {
                background-color: #ffffff;
                padding: 15px;
                border-radius: 15px;
                box-shadow: 0 4px 15px rgba(0,0,0,0.05);
                border: 1px solid #e0e0e0;
            }
            .stChatMessage {
                background-color: #f9f9f9 !important;
                border: 1px solid #ddd;
                color: black !important;
                direction: rtl;
                text-align: right;
            }
            [data-testid="stChatMessageContent"] p { color: black !important; text-align: right !important; }
            .stChatMessage .stAvatar { display: none; }

            /* === תיקון סליידרים (כיוון + תצוגת מספר) === */
            
            /* 1. כיוון הסליידר משמאל לימין (כדי ש-1 יהיה משמאל) */
            [data-testid="stSlider"] {
                direction: ltr !important;
                text-align: left !important;
                padding-top: 15px !important;
            }

            /* 2. הכותרת מעל הסליידר - חזרה לימין */
            [data-testid="stSlider"] label p {
                direction: rtl !important;
                text-align: right !important;
                width: 100%;
                display: block;
            }

            /* 3. הבועה שמראה את המספר (התיקון החדש!) */
            div[data-testid="stThumbValue"] {
                background-color: #4361ee !important; /* רקע כחול בולט */
                color: #ffffff !important;           /* טקסט לבן */
                font-weight: bold !important;
                font-size: 16px !important;
                border-radius: 6px !important;
                padding: 2px 8px !important;
                opacity: 1 !important; /* תמיד גלוי בגרירה */
                z-index: 999 !important;
                direction: ltr !important;
            }
        </style>
    """, unsafe_allow_html=True)

# --- 3. פונקציות עזר ---

def get_google_api_key() -> str:
    return st.secrets.get("GOOGLE_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""

def get_drive_service():
    if not GDRIVE_FOLDER_ID or not st.secrets.get("GDRIVE_SERVICE_ACCOUNT_B64"): return None
    try:
        SCOPES = ["https://www.googleapis.com/auth/drive.file"]
        service_account_json_str = base64.b64decode(st.secrets["GDRIVE_SERVICE_ACCOUNT_B64"]).decode("utf-8")
        creds = Credentials.from_service_account_info(json.loads(service_account_json_str), scopes=SCOPES)
        return build("drive", "v3", credentials=creds)
    except Exception as e:
        st.error(f"שגיאת דרייב: {e}")
        return None

def save_reflection(entry: dict) -> dict:
    with open(DATA_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return {"status": "saved", "date": entry["date"]}

def load_data_as_dataframe():
    columns = ["student_name", "lesson_id", "task_difficulty", "work_method", "tags", "planned", "done", "interpretation", "challenge", "cat_convert_rep", "cat_dims_props", "cat_proj_trans", "cat_3d_support", "cat_self_efficacy", "date", "timestamp", "has_image"]
    if not os.path.exists(DATA_FILE): return pd.DataFrame(columns=columns)
    data = []
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip(): continue
            try:
                entry = json.loads(line)
                if entry.get("type") == "reflection": data.append(entry)
            except: continue
    df = pd.DataFrame(data)
    if df.empty: return pd.DataFrame(columns=columns)
    if "date" in df.columns: df["date"] = pd.to_datetime(df["date"])
    return df

def load_last_week():
    if not os.path.exists(DATA_FILE): return []
    today = date.today()
    week_ago = today - timedelta(days=6)
    out = []
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip(): continue
            try:
                e = json.loads(line)
                if e.get("type") == "weekly_summary": continue
                d = date.fromisoformat(e.get("date", today.isoformat()))
                if week_ago <= d <= today: out.append(e)
            except: continue
    return out

# --- 4. פונקציות דרייב ---

def upload_file_to_drive(file_obj, filename, mime_type, drive_service):
    media = MediaIoBaseUpload(file_obj, mimetype=mime_type)
    file_metadata = {'name': filename, 'parents': [GDRIVE_FOLDER_ID], 'mimeType': mime_type}
    drive_service.files().create(body=file_metadata, media_body=media, supportsAllDrives=True).execute()

def restore_from_drive():
    svc = get_drive_service()
    if not svc: return False
    try:
        query = f"'{GDRIVE_FOLDER_ID}' in parents and mimeType='application/json' and trashed=false"
        results = svc.files().list(q=query, orderBy="createdTime desc").execute()
        files = results.get('files', [])
        if not files:
            st.toast("לא נמצאו קבצים.")
            return False
        existing_data = set()
        if os.path.exists(DATA_FILE):
             with open(DATA_FILE, "r", encoding="utf-8") as f:
                 for line in f: existing_data.add(line.strip())
        restored_count = 0
        for file in files:
            file_content = svc.files().get_media(fileId=file['id']).execute().decode('utf-8')
            try:
                json_obj = json.loads(file_content)
                json_line = json.dumps(json_obj, ensure_ascii=False)
                if json_line not in existing_data:
                    with open(DATA_FILE, "a", encoding="utf-8") as f:
                        f.write(json_line + "\n")
                    existing_data.add(json_line)
                    restored_count += 1
            except: pass
        if restored_count > 0:
            st.toast(f"שוחזרו {restored_count} תצפיות!")
            return True
        else:
            st.toast("הנתונים מעודכנים.")
            return False
    except Exception as e:
        st.error(f"שגיאה: {e}")
        return False

# --- 5. פונקציות AI ---

def generate_summary(entries: list) -> str:
    if not entries: return "אין נתונים."
    readable = []
    for e in entries:
        readable.append(f"תלמיד: {e.get('student_name')} | תיאור: {e.get('done')} | פרשנות: {e.get('interpretation')} | ציונים: היטלים={e.get('cat_proj_trans')}")
    full_text = "\n".join(readable)
    prompt = f"""
    אתה עוזר מחקר אקדמי. כתוב דוח סיכום שבועי בעברית לתזה.
    נושאים: מגמות כלליות, ניתוח פרטני, המלצות. דגש על פרשנות המורה ושימוש במודלים.
    נתונים: {full_text}
    """
    api_key = get_google_api_key()
    if not api_key: return "חסר מפתח API."
    try:
        client = genai.Client(api_key=api_key)
        return client.models.generate_content(model="gemini-2.0-flash", contents=prompt).text
    except Exception as e: return f"שגיאה: {e}"

def get_all_data_as_text():
    df = load_data_as_dataframe()
    if df.empty: return "אין נתונים."
    text_data = ""
    for _, row in df.iterrows():
        text_data += f"[תצפית] {row['date']} | {row['student_name']} | קושי: {row.get('task_difficulty')} | שיטה: {row.get('work_method')} | תיאור: {row.get('done')} | פרשנות: {row.get('interpretation')} | ציונים: {row.get('cat_proj_trans')}\n"
    return text_data

def chat_with_data(user_query, context_data):
    api_key = get_google_api_key()
    if not api_key: return "חסר מפתח."
    prompt = f"""
    אתה עוזר מחקר אקדמי. ענה על סמך הנתונים בלבד.
    נתונים: {context_data}
    שאלה: {user_query}
    ענה בעברית מקצועית.
    """
    try:
        client = genai.Client(api_key=api_key)
        return client.models.generate_content(model="gemini-2.0-flash", contents=prompt).text
    except: return "שגיאה."

def render_slider_metric(label, key):
    # הכותרת נשארת מימין
    st.markdown(f"**{label}**")
    
    # הסליידר עצמו
    val = st.slider(label, 1, 5, 3, key=key, label_visibility="collapsed")
    
    # טקסט עזר למטה - מיושר בצורה שמתאימה לסליידר (1 משמאל, 5 מימין)
    st.markdown(
        """<div style="display: flex; justify-content: space-between; direction: ltr; font-size: 12px; color: #555; margin-top: -10px;">
        <span>1 (קושי רב)</span>
        <span>5 (שליטה מלאה)</span>
        </div>""", unsafe_allow_html=True
    )
    return val

# -----------------------------
# 6. ממשק ראשי
# -----------------------------
setup_design()

st.title("🎓 יומן תצפית")
st.markdown("### מעקב אחר מיומנויות תפיסה מרחבית")

tab1, tab2, tab3 = st.tabs(["📝 רפלקציה", "📊 התקדמות", "🤖 עוזר מחקרי"])

# --- טאב 1: הזנה ---
with tab1:
    with st.form("reflection_form"):
        st.markdown("#### 1. פרטי התצפית") 
        col1, col2 = st.columns(2)
        with col1:
            selected_student = st.selectbox("👤 שם תלמיד", CLASS_ROSTER)
            student_name = st.text_input("✍️ הזן שם:") if selected_student == "תלמיד אחר..." else selected_student
        with col2:
            lesson_id = st.text_input("📚 שיעור", placeholder="לדוגמה: היטלים 1")
            task_difficulty = st.selectbox("⚖️ קושי", ["בסיסי", "בינוני", "מתקדם"])

        st.markdown("#### 2. אופן העבודה")
        work_method = st.radio("🛠️", ["🎨 ללא גוף (דמיון)", "🧊 בעזרת גוף מודפס"], horizontal=True, label_visibility="collapsed")

        st.markdown("#### 3. תיאור ופרשנות")
        selected_tags = st.multiselect("🏷️ תגיות:", OBSERVATION_TAGS)
        
        c1, c2 = st.columns(2)
        with c1:
            planned = st.text_area("📋 המטלה", height=100)
            challenge = st.text_area("🗣️ ציטוטים", height=100)
        with c2:
            done = st.text_area("👀 פעולות", height=100)
            interpretation = st.text_area("💡 פרשנות אישית", height=100)

        st.markdown("#### 📷 תיעוד")
        uploaded_image = st.file_uploader("העלאת תמונה", type=['jpg', 'jpeg', 'png'])

        st.markdown("#### 4. מדדים")
        mc1, mc2 = st.columns(2)
        with mc1:
            cat_convert = render_slider_metric("🔄 המרת ייצוגים", "m1")
            cat_dims = render_slider_metric("📏 מידות", "m2")
        with mc2:
            cat_proj = render_slider_metric("📐 מעבר היטלים", "m3")
            cat_3d_support = render_slider_metric("🧊 שימוש בגוף", "m4")
        cat_self_efficacy = render_slider_metric("💪 מסוגלות עצמית", "m5")

        if st.form_submit_button("💾 שמור תצפית"):
            entry = {
                "type": "reflection", "student_name": student_name, "lesson_id": lesson_id,
                "task_difficulty": task_difficulty, "work_method": work_method, "tags": selected_tags, 
                "planned": planned, "done": done, "challenge": challenge, "interpretation": interpretation, 
                "cat_convert_rep": cat_convert, "cat_dims_props": cat_dims, "cat_proj_trans": cat_proj, 
                "cat_3d_support": cat_3d_support, "cat_self_efficacy": cat_self_efficacy,
                "date": date.today().isoformat(), "timestamp": datetime.now().isoformat(),
                "has_image": uploaded_image is not None
            }
            save_reflection(entry)
            svc = get_drive_service()
            if svc:
                try:
                    json_bytes = io.BytesIO(json.dumps(entry, ensure_ascii=False, indent=4).encode('utf-8'))
                    upload_file_to_drive(json_bytes, f"ref-{student_name}-{entry['date']}.json", 'application/json', svc)
                    if uploaded_image:
                        image_bytes = io.BytesIO(uploaded_image.getvalue())
                        upload_file_to_drive(image_bytes, f"img-{student_name}-{entry['date']}.jpg", 'image/jpeg', svc)
                except: pass
            
            st.balloons()
            st.success("נשמר בהצלחה!")

# --- טאב 2: דאשבורד ---
with tab2:
    st.markdown("### 📊 לוח בקרה")
    if st.button("🔄 סנכרן מהדרייב"):
         with st.spinner("מסנכרן..."):
            if restore_from_drive(): st.rerun()
            else: st.info("הנתונים מעודכנים.")
    
    st.divider()
    
    df = load_data_as_dataframe()
    export_df = df.copy()
    if "tags" in export_df.columns: export_df["tags"] = export_df["tags"].apply(lambda x: ", ".join(x) if isinstance(x, list) else x)
    
    st.markdown("#### 📥 ייצוא נתונים")
    d1, d2 = st.columns(2)
    with d1:
        st.download_button("📄 הורד CSV", export_df.to_csv(index=False).encode('utf-8'), "data.csv", "text/csv")
    with d2:
        try:
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer: export_df.to_excel(writer, index=False)
            st.download_button("📊 הורד Excel", output.getvalue(), "data.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        except: st.error("חסרה ספריית openpyxl")

    st.divider()

    if not df.empty:
        k1, k2, k3 = st.columns(3)
        k1.metric("סה'כ תצפיות", len(df))
        k2.metric("תלמידים", df['student_name'].nunique())
        try: k3.metric("ממוצע היטלים", f"{df['cat_proj_trans'].mean():.1f}")
        except: pass
        
        st.markdown("#### 📈 גרף התקדמות")
        student = st.selectbox("בחר תלמיד לגרף:", df['student_name'].unique())
        st_df = df[df['student_name'] == student].sort_values("date")
        st.line_chart(st_df.set_index("date")[['cat_proj_trans', 'cat_3d_support', 'cat_self_efficacy']])
    else:
        st.info("אין נתונים להצגה בגרפים.")

# --- טאב 3: AI ---
with tab3:
    st.markdown("### 🤖 עוזר מחקרי")
    
    st.markdown("#### 📄 דוח שבועי")
    if st.button("✨ צור סיכום שבועי ושמור"):
        entries = load_last_week()
        if not entries: st.warning("אין נתונים מהשבוע האחרון.")
        else:
            with st.spinner("מכין דוח..."):
                res = generate_summary(entries)
                st.markdown(res)
                svc = get_drive_service()
                if svc:
                    try:
                        upload_file_to_drive(io.BytesIO(res.encode('utf-8')), f"Summary-{date.today()}.txt", 'text/plain', svc)
                        st.success("נשמר בדרייב!")
                    except: pass

    st.divider()
    st.markdown("#### 💬 צ'אט עם הנתונים")
    
    if "messages" not in st.session_state: st.session_state.messages = []
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]): st.markdown(msg["content"])
        
    if prompt := st.chat_input("שאל משהו על הנתונים..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"): st.markdown(prompt)
        with st.chat_message("assistant"):
            with st.spinner("חושב..."):
                ans = chat_with_data(prompt, get_all_data_as_text())
                st.markdown(ans)
        st.session_state.messages.append({"role": "assistant", "content": ans})

# --- סוף הקוד ---