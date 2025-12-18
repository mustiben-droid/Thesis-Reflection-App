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

# --- 1. הגדרות קבועות ומשתנים ---
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

# --- 2. פונקציית העיצוב (CSS) ---
def setup_design():
    st.set_page_config(page_title="יומן תצפית", page_icon="🎓", layout="centered")
    
    st.markdown("""
        <style>
            /* ייבוא פונט היבו (Heebo) */
            @import url('https://fonts.googleapis.com/css2?family=Heebo:wght@300;400;700&display=swap');

            /* החלת הפונט */
            html, body, [class*="css"]  {
                font-family: 'Heebo', sans-serif;
                direction: rtl;
            }

            /* רקע כללי */
            .stApp { background-color: #f8f9fa; }
            
            /* התאמה למובייל - מניעת חיתוך בצדדים */
            .block-container { 
                padding-top: 1rem !important; 
                padding-bottom: 5rem !important; 
                padding-left: 0.5rem !important;
                padding-right: 0.5rem !important;
                max-width: 100% !important; 
            }

            /* כותרות */
            h1, h2, h3 { color: #2c3e50 !important; font-weight: 700; text-align: center; }
            h4, h5 { color: #34495e !important; font-weight: 600; text-align: right; }
            p, label, span, div, small { color: #000000 !important; }

            /* --- עיצוב כרטיס לטופס --- */
            [data-testid="stForm"] {
                background-color: #ffffff;
                padding: 15px;
                border-radius: 15px;
                box-shadow: 0 4px 15px rgba(0,0,0,0.05);
                border: 1px solid #e0e0e0;
            }

            /* שדות קלט */
            .stTextInput input, .stSelectbox div[data-baseweb="select"] > div, .stTextArea textarea {
                background-color: #ffffff !important;
                color: #000000 !important;
                border: 1px solid #ced4da !important;
                direction: rtl;
                border-radius: 8px;
            }

            /* כפתורים */
            .stButton > button {
                border-radius: 10px;
                font-weight: bold;
                width: 100%;
                border: 1px solid #b0b0b0;
            }
            
            /* כפתור שמירה ראשי - כחול ויפה */
            [data-testid="stFormSubmitButton"] > button {
                background: linear-gradient(90deg, #4361ee 0%, #3a0ca3 100%);
                color: white !important;
                border: none;
                padding: 10px;
                font-size: 18px;
                margin-top: 10px;
                box-shadow: 0 4px 6px rgba(0,0,0,0.1);
            }
            [data-testid="stFormSubmitButton"] > button * { color: white !important; -webkit-text-fill-color: white !important; }

            /* סליידרים */
            [data-testid="stSlider"] { direction: ltr !important; padding-bottom: 10px; }
            
            /* בועות צ'אט */
            .stChatMessage {
                background-color: #ffffff;
                border-radius: 15px;
                box-shadow: 0 2px 5px rgba(0,0,0,0.05);
                border: none;
                margin-bottom: 10px;
                direction: rtl;
            }
            [data-testid="stChatMessageContent"] { text-align: right; }
            .stChatMessage .stAvatar { display: none; } /* הסתרת אווטאר לחסכון במקום */

            /* הסתרת תפריט עליון של סטרימליט */
            #MainMenu {visibility: hidden;}
            header {visibility: hidden;}
        </style>
    """, unsafe_allow_html=True)

# --- 3. פונקציות עזר (Auth, Drive, Files) ---

def get_google_api_key() -> str:
    return st.secrets.get("GOOGLE_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""

def get_drive_service():
    """מתחבר לגוגל דרייב"""
    if not GDRIVE_FOLDER_ID or not st.secrets.get("GDRIVE_SERVICE_ACCOUNT_B64"): return None
    try:
        SCOPES = ["https://www.googleapis.com/auth/drive.file"]
        service_account_json_str = base64.b64decode(st.secrets["GDRIVE_SERVICE_ACCOUNT_B64"]).decode("utf-8")
        creds = Credentials.from_service_account_info(json.loads(service_account_json_str), scopes=SCOPES)
        return build("drive", "v3", credentials=creds)
    except Exception as e:
        st.error(f"שגיאת התחברות לדרייב: {e}")
        return None

def save_reflection(entry: dict) -> dict:
    """שומר שורה בקובץ המקומי"""
    with open(DATA_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return {"status": "saved", "date": entry["date"]}

def load_data_as_dataframe():
    """טוען את כל הנתונים לטבלה"""
    columns = ["student_name", "lesson_id", "task_difficulty", "work_method", "tags", "planned", "done", "interpretation", "challenge", "cat_convert_rep", "cat_dims_props", "cat_proj_trans", "cat_3d_support", "cat_self_efficacy", "date", "timestamp", "has_image"]
    
    if not os.path.exists(DATA_FILE): 
        return pd.DataFrame(columns=columns)
        
    data = []
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip(): continue
            try:
                entry = json.loads(line)
                if entry.get("type") == "reflection": data.append(entry)
            except: continue
    
    df = pd.DataFrame(data)
    if df.empty:
        return pd.DataFrame(columns=columns)
        
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"])
    return df

def load_last_week():
    """טוען נתונים רק מהשבוע האחרון"""
    if not os.path.exists(DATA_FILE): return []
    today = date.today()
    week_ago = today - timedelta(days=6)
    out = []
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip(): continue
            try:
                e = json.loads(line)
                if e.get("type") == "weekly_summary": continue # מתעלם מסיכומים ישנים
                d = date.fromisoformat(e.get("date", today.isoformat()))
                if week_ago <= d <= today: out.append(e)
            except: continue
    return out

# --- 4. פונקציות דרייב (העלאה ושחזור) ---

def upload_file_to_drive(file_obj, filename, mime_type, drive_service):
    """מעלה קובץ לתיקייה בדרייב"""
    media = MediaIoBaseUpload(file_obj, mimetype=mime_type)
    file_metadata = {'name': filename, 'parents': [GDRIVE_FOLDER_ID], 'mimeType': mime_type}
    drive_service.files().create(body=file_metadata, media_body=media, supportsAllDrives=True).execute()

def restore_from_drive():
    """מושך את כל קבצי ה-JSON מהדרייב ומשחזר אותם לאפליקציה"""
    svc = get_drive_service()
    if not svc: return False
    try:
        # מחפש קבצי JSON בתיקייה
        query = f"'{GDRIVE_FOLDER_ID}' in parents and mimeType='application/json' and trashed=false"
        results = svc.files().list(q=query, orderBy="createdTime desc").execute()
        files = results.get('files', [])
        
        if not files:
            st.toast("לא נמצאו קבצים לשחזור בדרייב.")
            return False

        # קורא מה כבר קיים אצלנו כדי לא לשכפל
        existing_data = set()
        if os.path.exists(DATA_FILE):
             with open(DATA_FILE, "r", encoding="utf-8") as f:
                 for line in f: existing_data.add(line.strip())

        restored_count = 0
        for file in files:
            # מוריד את תוכן הקובץ
            file_content = svc.files().get_media(fileId=file['id']).execute().decode('utf-8')
            try:
                # מוודא שזה JSON תקין
                json_obj = json.loads(file_content)
                json_line = json.dumps(json_obj, ensure_ascii=False)
                
                # אם זה חדש - שומר
                if json_line not in existing_data:
                    with open(DATA_FILE, "a", encoding="utf-8") as f:
                        f.write(json_line + "\n")
                    existing_data.add(json_line)
                    restored_count += 1
            except: pass
            
        if restored_count > 0:
            st.toast(f"שוחזרו בהצלחה {restored_count} תצפיות!")
            return True
        else:
            st.toast("הנתונים שלך כבר מעודכנים.")
            return False

    except Exception as e:
        st.error(f"שגיאה בשחזור: {e}")
        return False

# --- 5. פונקציות AI (ג'מיני) ---

def generate_summary(entries: list) -> str:
    """מייצר סיכום שבועי רשמי"""
    if not entries: return "לא נמצאו נתונים מהשבוע האחרון."
    
    # המרת הנתונים לטקסט קריא
    readable_entries = []
    for e in entries:
        readable_entries.append(f"""
        תלמיד: {e.get('student_name')} | תאריך: {e.get('date')} | קושי: {e.get('task_difficulty')}
        תגיות: {e.get('tags')}
        תיאור: {e.get('done')} | פרשנות: {e.get('interpretation')}
        ציונים: המרה={e.get('cat_convert_rep')}, היטלים={e.get('cat_proj_trans')}, גוף={e.get('cat_3d_support')}
        """)
    full_text = "\n".join(readable_entries)
    
    prompt = f"""
    אתה עוזר מחקר אקדמי. כתוב דוח סיכום שבועי בעברית עבור תזה בנושא ראייה מרחבית.
    הנחיות:
    1. השתמש במונחים מקצועיים (רוטציה מנטלית, היטלים, ייצוגים, Embodiment).
    2. מבנה הדוח: "מגמות כלליות", "ניתוח פרטני (תלמידים בולטים)", "המלצות להמשך".
    3. תן דגש לפרשנות המורה ולשימוש במודלים פיזיים.
    
    הנתונים הגולמיים:
    {full_text}
    """
    
    api_key = get_google_api_key()
    if not api_key: return "חסר מפתח API."
    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(model="gemini-2.0-flash", contents=prompt)
        return response.text
    except Exception as e: return f"שגיאה: {e}"

def get_all_data_as_text():
    """מכין את כל הנתונים לצ'אט"""
    df = load_data_as_dataframe()
    if df.empty: return "אין נתונים במערכת."
    
    text_data = ""
    for index, row in df.iterrows():
        text_data += f"""
        [רשומה] תאריך: {row['date']}, תלמיד: {row['student_name']}
        שיעור: {row['lesson_id']} (קושי: {row.get('task_difficulty')}), שיטה: {row.get('work_method')}
        תגיות: {row.get('tags')}, תיאור: {row.get('done')}, פרשנות: {row.get('interpretation')}
        אתגרים: {row.get('challenge')}, ציונים: המרה={row.get('cat_convert_rep')}, מידות={row.get('cat_dims_props')}, היטלים={row.get('cat_proj_trans')}, גוף={row.get('cat_3d_support')}
        -------------------
        """
    return text_data

def chat_with_data(user_query, context_data):
    """צ'אט חופשי עם הנתונים"""
    api_key = get_google_api_key()
    if not api_key: return "חסר מפתח API."
    
    prompt = f"""
    אתה עוזר מחקר אקדמי ("Research Buddy"). יש לך גישה ליומן התצפיות המלא של המורה.
    
    כל הנתונים שנאספו:
    {context_data}
    
    השאלה של המורה: "{user_query}"
    
    הנחיות:
    1. ענה אך ורק על סמך הנתונים. אם אין מידע, תגיד שאין.
    2. חפש דפוסים, קשרים ומגמות (למשל: השפעת מודל על הצלחה).
    3. כתוב בעברית מקצועית וברורה.
    """
    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(model="gemini-2.0-flash", contents=prompt)
        return response.text
    except Exception as e: return f"שגיאה: {e}"

def render_slider_metric(label, key):
    """יוצר סליידר עם הסבר מילולי"""
    st.markdown(f"**{label}**")
    val = st.slider(label, 1, 5, 3, key=key, label_visibility="collapsed")
    st.markdown(
        """<div style="display: flex; justify-content: space-between; direction: ltr; font-size: 12px; color: #555;">
        <span>1 (קושי רב)</span>
        <span>5 (שליטה מלאה)</span>
        </div>""", unsafe_allow_html=True
    )
    return val

# -----------------------------
# 6. הממשק הראשי (Main UI)
# -----------------------------

setup_design()

st.title("🎓 יומן תצפית")
st.markdown("### מעקב אחר מיומנויות תפיסה מרחבית")

# הגדרת הלשוניות
tab1, tab2, tab3 = st.tabs(["📝 רפלקציה", "📊 התקדמות", "🤖 עוזר מחקרי"])

# --- לשונית 1: טופס הזנה ---
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
            planned = st.text_area("📋 המטלה", height=100, placeholder="מה נדרש לעשות?")
            challenge = st.text_area("🗣️ ציטוטים", height=100, placeholder="ציטוטים, שפת גוף...")
        with c2:
            done = st.text_area("👀 פעולות", height=100, placeholder="מה התלמיד עשה?")
            interpretation = st.text_area("💡 פרשנות אישית", height=100, placeholder="למה זה קרה לדעתך?")

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

        # כפתור שמירה
        if st.form_submit_button("💾 שמור תצפית"):
            entry = {
                "type": "reflection", "student_name": student_name, "lesson_id": lesson_id,
                "task_difficulty": task_difficulty, 
                "work_method": work_method, "tags": selected_tags, 
                "planned": planned, "done": done, 
                "challenge": challenge, 
                "interpretation": interpretation, 
                "cat_convert_rep": cat_convert, 
                "cat_dims_props": cat_dims, "cat_proj_trans": cat_proj, 
                "cat_3d_support": cat_3d_support, "cat_self_efficacy": cat_self_efficacy,
                "date": date.today().isoformat(), "timestamp": datetime.now().isoformat(),
                "has_image": uploaded_image is not None
            }
            save_reflection(entry)
            
            # העלאה לדרייב
            svc = get_drive_service()
            if svc:
                try:
                    json_bytes = io.BytesIO(json.dumps(entry, ensure_ascii=False, indent=4).encode('utf-8'))
                    upload_file_to_drive(json_bytes, f"ref-{student_name}-{entry['date']}.json", 'application/json', svc)
                    if uploaded_image:
                        image_bytes = io.BytesIO(uploaded_image.getvalue())
                        upload_file_to_drive(image_bytes, f"img-{student_name}-{entry['date']}.jpg", 'image/jpeg', svc)
                except: pass
            
            st.balloons() # חגיגה!
            st.success("התצפית נשמרה בהצלחה!")

# --- לשונית 2: דאשבורד ---
with tab2:
    st.markdown("### 📊 לוח בקרה")
    
    # כפתור סנכרון
    if st.button("🔄 סנכרן נתונים מהדרייב"):
         with st.spinner("מושך נתונים..."):
            if restore_from_drive(): st.rerun()
            else: st.info("הנתונים מעודכנים.")
    
    st.divider()

    df = load_data_as_dataframe()
    if not df.empty:
        # מדדים עליונים (KPIs)
        k1, k2, k3 = st.columns(3)
        k1.metric("סה'כ תצפיות", len(df))
        k2.metric("תלמידים", df['student_name'].nunique())
        try:
            k3.metric("ממוצע היטלים", f"{df['cat_proj_trans'].mean():.1f}")
        except: pass
        
        st.divider()
        
        # כפתורי ייצוא
        export_df = df.copy()
        if "tags" in export_df.columns: export_df["tags"] = export_df["tags"].apply(lambda x: ", ".join(x) if isinstance(x, list) else x)
        
        d1, d2 = st.columns(2)
        d1.download_button("📄 הורד CSV", export_df.to_csv(index=False).encode('utf-8'), "thesis_data.csv", "text/csv")
        try:
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer: export_df.to_excel(writer, index=False)
            d2.download_button("📊 הורד Excel", output.getvalue(), "thesis_data.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        except: pass
        
        st.divider()
        
        # גרף התקדמות
        st.markdown("#### 📈 גרף התקדמות אישי")
        if len(df) > 0:
            all_students = df['student_name'].unique()
            student = st.selectbox("בחר תלמיד להצגה:", all_students)
            st_df = df[df['student_name'] == student].sort_values("date")
            
            if not st_df.empty:
                chart_data = st_df.set_index("date")[['cat_proj_trans', 'cat_3d_support', 'cat_self_efficacy']]
                st.line_chart(chart_data)
                
                # טבלה קטנה למטה
                st.dataframe(st_df[['date', 'lesson_id', 'task_difficulty', 'interpretation']].tail(5), hide_index=True)
    else:
        st.info("אין נתונים להצגה. בצע סנכרון או הוסף תצפית חדשה.")

# --- לשונית 3: AI ועוזר מחקרי ---
with tab3:
    st.markdown("### 🤖 עוזר מחקרי")
    
    # חלק א': יצירת דוח מסודר
    st.markdown("#### 📄 דוח שבועי (לשמירה)")
    if st.button("✨ צור סיכום שבועי ושמור"):
        entries = load_last_week()
        if not entries:
            st.warning("אין נתונים מהשבוע האחרון.")
        else:
            with st.spinner("מייצר דוח, שומר בדרייב..."):
                res = generate_summary(entries)
                st.markdown(res)
                
                svc = get_drive_service()
                if svc:
                     try:
                        upload_file_to_drive(io.BytesIO(res.encode('utf-8')), f"Summary-{date.today()}.txt", 'text/plain', svc)
                        st.success("הדוח נשמר בדרייב בהצלחה!")
                     except: pass
    
    st.divider()

    # חלק ב': צ'אט חופשי
    st.markdown("#### 💬 צ'אט עם הנתונים")
    
    if "messages" not in st.session_state: st.session_state.messages = []
    
    # הצגת הודעות קודמות
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            
    # תיבת קלט
    if prompt := st.chat_input("שאל שאלה (למשל: מי התקשה השבוע ברוטציה?)..."):
        # הצגת שאלת המשתמש
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)
            
        # קבלת תשובה מה-AI
        with st.chat_message("assistant"):
            with st.spinner("מנתח נתונים..."):
                context = get_all_data_as_text()
                ans = chat_with_data(prompt, context)
                st.markdown(ans)
        
        # שמירת התשובה
        st.session_state.messages.append({"role": "assistant", "content": ans})

# --- סוף הקוד ---