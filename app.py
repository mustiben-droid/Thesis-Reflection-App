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

# --- הגדרות קבועות ---
DATA_FILE = "reflections.jsonl"
GDRIVE_FOLDER_ID = st.secrets.get("GDRIVE_FOLDER_ID")

# רשימת התלמידים הקבועה
CLASS_ROSTER = [
    "נתנאל",
    "רועי",
    "אסף",
    "עילאי",
    "תלמיד אחר..." 
]

# רשימת התגיות
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

# -----------------------------
# עיצוב (CSS)
# -----------------------------
def setup_design():
    st.set_page_config(page_title="יומן תצפית", page_icon="🎓", layout="centered")
    
    st.markdown("""
        <style>
            /* 1. איפוס כללי */
            .stApp, [data-testid="stAppViewContainer"] { background-color: #ffffff !important; }
            
            /* תיקון קריטי למובייל: מבטיח שהתוכן לא יחתך בצדדים */
            .block-container { 
                padding-top: 1rem !important; 
                padding-bottom: 5rem !important; 
                padding-left: 1rem !important;
                padding-right: 1rem !important;
                max-width: 100% !important; 
            }
            
            /* 2. כותרות וטקסטים */
            h1, h2, h3, h4, h5, h6 { color: #4361ee !important; font-family: sans-serif; text-align: center !important; }
            p, label, span, div, small { color: #000000 !important; }
            
            /* 3. כפתורים */
            button[kind="secondary"], button[kind="primary"], [data-testid="stBaseButton-secondary"], [data-testid="stBaseButton-primary"] {
                background-color: #f0f2f6 !important;
                border: 1px solid #b0b0b0 !important;
                color: #000000 !important;
            }
            button * {
                color: #000000 !important;
                -webkit-text-fill-color: #000000 !important;
                font-weight: bold !important;
            }

            /* 4. שדות קלט */
            .stTextInput input, .stSelectbox div[data-baseweb="select"] > div, .stTextArea textarea {
                background-color: #ffffff !important;
                color: #000000 !important;
                -webkit-text-fill-color: #000000 !important;
                border: 1px solid #cccccc !important;
                direction: rtl;
            }
            .stSelectbox div[data-baseweb="select"] span { color: #000000 !important; }

            /* 5. סליידרים */
            [data-testid="stSlider"] { direction: ltr !important; padding-bottom: 5px; }
            div[data-testid="stThumbValue"] {
                color: #ffffff !important;       
                background-color: #4361ee !important; 
                font-size: 18px !important;      
                font-weight: bold !important;
                padding: 4px 8px !important;    
                border-radius: 6px !important;   
                -webkit-text-fill-color: #ffffff !important;
            }

            /* 6. תגיות */
            .stMultiSelect > div > div {
                background-color: #f0f2f6 !important;
                border: 1px solid #d1d5db !important;
                color: black !important;
                direction: rtl !important;
            }
            span[data-baseweb="tag"] {
                background-color: #fff9c4 !important;
                border: 1px solid #fbc02d !important;
            }
            span[data-baseweb="tag"] span {
                color: #000000 !important;
                -webkit-text-fill-color: #000000 !important;
            }
            span[data-baseweb="tag"] svg { fill: #000000 !important; }
            ul[data-baseweb="menu"], li[role="option"] {
                background-color: #ffffff !important;
                color: #000000 !important;
                direction: rtl !important;
            }

            /* 7. כפתור שמירה */
            [data-testid="stFormSubmitButton"] > button { 
                background-color: #4361ee !important; 
                color: white !important; 
                -webkit-text-fill-color: white !important;
                border: none; width: 100%; padding: 15px; font-size: 20px; font-weight: bold; border-radius: 12px; margin-top: 20px; 
            }
            [data-testid="stFormSubmitButton"] > button * { color: white !important; }

            /* 8. העלמת התפריט העליון של Streamlit כדי לחסוך מקום */
            #MainMenu {visibility: hidden;}
            header {visibility: hidden;}

            html, body { direction: rtl; }
        </style>
    """, unsafe_allow_html=True)

# -----------------------------
# לוגיקה
# -----------------------------
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
        st.error(f"Drive connect failed: {e}"); return None

def save_reflection(entry: dict) -> dict:
    with open(DATA_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return {"status": "saved", "date": entry["date"]}

def load_data_as_dataframe():
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
    if not os.path.exists(DATA_FILE): return []
    today = date.today()
    week_ago = today - timedelta(days=6)
    out = []
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip(): continue
            e = json.loads(line)
            if e.get("type") == "weekly_summary": continue
            try:
                d = date.fromisoformat(e.get("date", today.isoformat()))
            except: continue
            if week_ago <= d <= today: out.append(e)
    return out

# --- דרייב ---
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
            st.toast("לא נמצאו קבצים לשחזור בדרייב.")
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
        st.error(f"שגיאה בשחזור: {e}")
        return False

# --- סיכום מחקרי ---
def generate_summary(entries: list) -> str:
    if not entries: return "לא נמצאו נתונים לניתוח מהשבוע האחרון."
    
    readable_entries = []
    for e in entries:
        readable_entries.append(f"""
        תלמיד: {e.get('student_name')}
        תאריך: {e.get('date')}
        שיעור: {e.get('lesson_id')} (קושי: {e.get('task_difficulty')})
        תגיות: {', '.join(e.get('tags', []))}
        תיאור פעולות: {e.get('done')}
        ציטוטים/אתגרים: {e.get('challenge')}
        פרשנות המורה: {e.get('interpretation')}
        ציונים (1-5): המרה={e.get('cat_convert_rep')}, מידות={e.get('cat_dims_props')}, היטלים={e.get('cat_proj_trans')}, שימוש בגוף={e.get('cat_3d_support')}
        """)
    
    full_text = "\n".join(readable_entries)
    
    prompt = f"""
    אתה עוזר מחקר אקדמי. כתוב דוח סיכום שבועי בעברית.
    הנחיות:
    1. השתמש במונחים מקצועיים.
    2. חלק ל: "מגמות בכיתה", "ניתוח פרטני", "המלצות".
    3. תן משקל משמעותי ל"פרשנות המורה" בניתוח שלך.
    
    הנתונים:
    {full_text}
    """
    
    api_key = get_google_api_key()
    if not api_key: return "חסר מפתח API"
    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(model="gemini-2.0-flash", contents=prompt, config={"temperature": 0.3})
        return response.text
    except Exception as e: return f"Error: {e}"

def render_slider_metric(label, key):
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
# ממשק ראשי
# -----------------------------

setup_design()

# ביטלתי את סרגל הצד (Sidebar) כדי למנוע בעיות במובייל.
# כותרת ראשית
st.title("🎓 יומן תצפית")
st.markdown("### מעקב אחר מיומנויות תפיסה מרחבית")

tab1, tab2, tab3 = st.tabs(["📝 רפלקציה", "📊 התקדמות וייצוא", "🧠 עוזר מחקרי"])

# --- לשונית 1: הזנת נתונים ---
with tab1:
    with st.form("reflection_form"):
        st.markdown("#### 1. פרטי התצפית") 
        col_student, col_lesson = st.columns(2)
        with col_student:
            selected_student = st.selectbox("👤 שם תלמיד", CLASS_ROSTER)
            student_name = st.text_input("✍️ הזן שם תלמיד:") if selected_student == "תלמיד אחר..." else selected_student
        
        with col_lesson:
            lesson_id = st.text_input("📚 שיעור מס'", placeholder="לדוגמה: היטלים 1")
            task_difficulty = st.selectbox("⚖️ רמת קושי המטלה", ["בסיסי", "בינוני", "מתקדם"])

        st.markdown("#### 2. אופן העבודה")
        work_method = st.radio("🛠️ כיצד התבצע השרטוט?", ["🎨 ללא גוף (דמיון)", "🧊 בעזרת גוף מודפס"], horizontal=True)

        st.markdown("#### 3. תיאור תצפית ופרשנות")
        selected_tags = st.multiselect("🏷️ תגיות מהירות (ניתן לבחור כמה):", OBSERVATION_TAGS)
        
        col_text1, col_text2 = st.columns(2)
        with col_text1:
            planned = st.text_area("📋 תיאור המטלה", height=100, placeholder="מה נדרש לעשות?")
            challenge = st.text_area("🗣️ ציטוטים / תגובות", height=100, placeholder="ציטוטים, שפת גוף...")
        with col_text2:
            done = st.text_area("👀 פעולות שנצפו", height=100, placeholder="מה הוא עשה בפועל?")
            interpretation = st.text_area("💡 פרשנות אישית (למה זה קרה?)", height=100, placeholder="התובנות שלך...")

        st.markdown("#### 📷 תיעוד ויזואלי")
        upload_label = "צרף צילום שרטוט/גוף (מהמצלמה או מהגלריה)"
        uploaded_image = st.file_uploader(upload_label, type=['jpg', 'jpeg', 'png'])

        st.markdown("#### 4. מדדי הערכה")
        c1, c2 = st.columns(2)
        with c1:
            cat_convert = render_slider_metric("🔄 המרת ייצוגים", "m1")
            cat_dims = render_slider_metric("📏 מידות ופרופורציות", "m2")
        with c2:
            cat_proj = render_slider_metric("📐 קושי במעבר בין היטלים", "m3")
            cat_3d_support = render_slider_metric("🧊 שימוש בגוף מודפס", "m4")
        
        cat_self_efficacy = render_slider_metric("💪 מסוגלות עצמית", "m5")

        submitted = st.form_submit_button("💾 שמור תצפית")

        if submitted:
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
            
            svc = get_drive_service()
            if svc:
                try:
                    json_bytes = io.BytesIO(json.dumps(entry, ensure_ascii=False, indent=4).encode('utf-8'))
                    upload_file_to_drive(json_bytes, f"ref-{student_name}-{entry['date']}.json", 'application/json', svc)
                    if uploaded_image:
                        image_bytes = io.BytesIO(uploaded_image.getvalue())
                        upload_file_to_drive(image_bytes, f"img-{student_name}-{entry['date']}.jpg", 'image/jpeg', svc)
                        st.success("📸 התמונה והנתונים נשמרו בדרייב!")
                    else:
                        st.success("✅ הנתונים נשמרו בהצלחה!")
                except Exception as e:
                    st.error(f"שגיאה בגיבוי לענן: {e}")
            else:
                st.warning("נשמר מקומית בלבד.")

# --- לשונית 2: לוח בקרה ---
with tab2:
    st.markdown("### 🕵️ מעקב התפתחות וייצוא נתונים")
    
    # מיקום חדש לכפתור הסנכרון - בתוך הלשונית עצמה
    st.info("אם נכנסת ממכשיר חדש, לחץ כאן כדי למשוך נתונים ישנים:")
    if st.button("🔄 סנכרן נתונים מהדרייב", key="sync_btn"):
         with st.spinner("מושך נתונים..."):
            if restore_from_drive(): st.rerun()
            else: st.info("הכל מסונכרן.")

    st.divider()
    
    df = load_data_as_dataframe()
    export_df = df.copy()
    if "tags" in export_df.columns:
        export_df["tags"] = export_df["tags"].apply(lambda x: ", ".join(x) if isinstance(x, list) else x)

    st.markdown("#### 📥 ייצוא נתונים למחקר")
    col_ex1, col_ex2 = st.columns(2)
    with col_ex1:
        csv = export_df.to_csv(index=False).encode('utf-8')
        st.download_button("📄 הורד כ-CSV", data=csv, file_name="thesis_data.csv", mime="text/csv")
    
    with col_ex2:
        try:
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                export_df.to_excel(writer, index=False, sheet_name='Data')
            st.download_button("📊 הורד כ-Excel", data=output.getvalue(), file_name="thesis_data.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        except:
            st.error("נדרשת ספריית openpyxl לאקסל")

    st.divider()
    
    if not df.empty:
        metric_cols = ['cat_convert_rep', 'cat_dims_props', 'cat_proj_trans', 'cat_3d_support', 'cat_self_efficacy']
        heb_names = {'cat_convert_rep': 'המרת ייצוגים', 'cat_dims_props': 'מידות', 'cat_proj_trans': 'היטלים', 'cat_3d_support': 'שימוש בגוף', 'cat_self_efficacy': 'מסוגלות עצמית'}
        
        all_students = df['student_name'].unique() if 'student_name' in df.columns else []
        if len(all_students) > 0:
            selected_student_graph = st.selectbox("🎓 בחר תלמיד:", all_students)
            student_df = df[df['student_name'] == selected_student_graph].sort_values("date")
            if not student_df.empty:
                chart_data = student_df.set_index("date")[metric_cols].rename(columns=heb_names)
                st.line_chart(chart_data)
                cols_to_show = ['date', 'task_difficulty', 'tags', 'interpretation', 'has_image']
                existing_cols = [c for c in cols_to_show if c in student_df.columns]
                st.dataframe(student_df[existing_cols].tail(5), hide_index=True)
    else:
        st.info("💡 אין נתונים. לחץ על 'סנכרן נתונים מהדרייב' למעלה.")

# --- לשונית 3: AI ---
with tab3:
    st.markdown("### 🤖 עוזר מחקרי")
    st.info("העוזר ינתח את הנתונים מהשבוע האחרון, יכתוב דוח מסודר וישמור אותו בדרייב.")
    
    if st.button("✨ צור סיכום שבועי ושמור"):
        entries = load_last_week()
        if not entries:
            st.warning("לא נמצאו תצפיות מהשבוע האחרון.")
        else:
            with st.spinner("מנתח נתונים..."):
                summary_text = generate_summary(entries)
                st.markdown("---")
                st.markdown(summary_text)
                
                svc = get_drive_service()
                if svc:
                    try:
                        file_bytes = io.BytesIO(summary_text.encode('utf-8'))
                        filename = f"Weekly-Summary-{date.today()}.txt"
                        upload_file_to_drive(file_bytes, filename, 'text/plain', svc)
                        st.success(f"✅ הדוח נשמר: {filename}")
                    except: pass