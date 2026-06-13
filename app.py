import streamlit as st
import pandas as pd
import json
import base64
import os
import io
import time
import requests
from datetime import date, datetime
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload
from streamlit_mic_recorder import mic_recorder

# --- חיבור למנוע הסטטיסטי (ai_engine.py) ---
try:
    from ai_engine import render_ai_agent_tab
except ImportError:
    def render_ai_agent_tab(df):
        st.warning("⚠️ קובץ ai_engine.py לא נמצא. הטאב הזה מושבת.")

# ==========================================
# --- 0. הגדרות מערכת ועיצוב ---
# ==========================================
DATA_FILE = "reflections.jsonl"
MASTER_FILENAME = "All_Observations_Master.xlsx"

# תיקיית האם (לתמונות ותצפיות רגילות)
GDRIVE_FOLDER_ID = st.secrets.get("GDRIVE_FOLDER_ID")

# התיקייה החדשה שלך להקלטות וניתוחי ראיונות
INTERVIEW_FOLDER_ID = "1NQz2UZ6BfAURfN4a8h4_qSkyY-_gxhxP"

CLASS_ROSTER = ["נתנאל", "רועי", "אסף", "עילאי", "טדי", "מירון", "אופק", "דניאל.ר", "אלי", "טיגרן", "פולינה.ק", "תלמיד אחר..."]
TAGS_OPTIONS = ["התעלמות מקווים נסתרים", "בלבול בין היטלים", "קושי ברוטציה מנטלית", "טעות בפרופורציות", "קושי במעבר בין היטלים", "שימוש בכלי מדידה", "סיבוב פיזי של המודל", "תיקון עצמי", "עבודה עצמאית שוטפת"]
st.set_page_config(page_title="מערכת תצפית מחקרית - 54.0", layout="wide")

st.markdown("""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Heebo:wght=300;400;700&display=swap');
        
        /* הגדרות כלליות */
        html, body, .stApp { 
            direction: rtl; 
            text-align: right; 
            font-family: 'Heebo', sans-serif !important; 
        }

        /* מניעת היפוך של סליידרים */
        [data-testid="stSlider"] { direction: ltr !important; }

        /* תיקון להתראות ופסים ירוקים */
        [data-testid="stNotification"], .stAlert {
            direction: rtl;
            width: 100% !important;
            margin: 10px 0 !important;
        }
        
        /* --- פתרון הסיידבר החותך בטלפון --- */
        @media (max-width: 600px) {
            /* הסתרת הסיידבר לחלוטין במובייל */
            section[data-testid="stSidebar"] {
                display: none !important;
            }
            /* ביטול השוליים המיותרים שהסיידבר משאיר */
            .main .block-container {
                padding-right: 1rem !important;
                padding-left: 1rem !important;
                width: 100% !important;
            }
        }

        /* עיצוב כפתורים ותיבות משוב */
        .stButton > button { width: 100%; font-weight: bold; border-radius: 12px; height: 3em; }
        .stButton button[kind="primary"] { background-color: #28a745; color: white; }
        .feedback-box { background-color: #f8f9fa; padding: 20px; border-radius: 15px; border: 1px solid #dee2e6; margin: 15px 0; color: #333; }
    </style>
""", unsafe_allow_html=True)

# ==========================================
# --- 1. פונקציות לוגיקה (נתונים ו-AI) ---
# ==========================================

def normalize_name(name):
    if not isinstance(name, str): return ""
    import re
    # 1. הסרת רווחים לפני הכל (הטיפ של קופיילוט)
    name = name.replace(" ", "")
    # 2. השארת רק אותיות ומספרים (ניקוי נקודות, מקפים וכו')
    clean = re.sub(r'[^א-תa-zA-Z0-9]', '', name)
    return clean.strip()

@st.cache_resource
def get_drive_service():
    try:
        b64 = st.secrets.get("GDRIVE_SERVICE_ACCOUNT_B64")
        js = base64.b64decode("".join(b64.split())).decode("utf-8")
        creds = Credentials.from_service_account_info(json.loads(js), scopes=["https://www.googleapis.com/auth/drive"])
        return build("drive", "v3", credentials=creds)
    except: return None

@st.cache_data(ttl=300)
def load_full_dataset(_svc):
    df_drive = pd.DataFrame()
    file_id = st.secrets.get("MASTER_FILE_ID")
    
    # 1. ניסיון משיכת נתונים מהדרייב
    if _svc and file_id:
        try:
            req = _svc.files().get_media(fileId=file_id)
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, req)
            done = False
            while not done:
                _, done = downloader.next_chunk()
            fh.seek(0)
            df_drive = pd.read_excel(fh)
            
            if 'student_name' not in df_drive.columns:
                cols = [c for c in df_drive.columns if any(x in str(c).lower() for x in ["student", "name", "שם", "תלמיד"])]
                if cols:
                    df_drive.rename(columns={cols[0]: "student_name"}, inplace=True)
        except Exception as e:
            # במקום pass - עכשיו אנחנו מדווחים על הבעיה
            st.error(f"❌ שגיאה בטעינת קובץ המאסטר מהדרייב: {e}")

    # 2. ניסיון משיכת נתונים מהמכשיר המקומי
    df_local = pd.DataFrame()
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                df_local = pd.DataFrame([json.loads(l) for l in f if l.strip()])
        except Exception as e:
            # מדווחים אם הקובץ המקומי פגום
            st.error(f"❌ שגיאה בקריאת הנתונים המקומיים (reflections.jsonl): {e}")

    # 3. איחוד וניקוי כפילויות
    df = pd.concat([df_drive, df_local], ignore_index=True)
    
    if not df.empty:
        # טיפול בזמנים לטובת זיהוי כפילויות מדויק
        if 'timestamp' in df.columns:
            df['timestamp'] = pd.to_datetime(df['timestamp'], errors='coerce')
        
        # ניקוי כפילויות (השיפור של Copilot)
        df = df.drop_duplicates(subset=['student_name', 'timestamp'], keep='last')
        
        # סידור שמות
        if 'student_name' in df.columns:
            df['student_name'] = df['student_name'].astype(str).str.strip()
            df['name_clean'] = df['student_name'].apply(normalize_name)
    
    return df
    
def call_gemini(prompt, audio_bytes=None):
    try:
        api_key = st.secrets.get("GOOGLE_API_KEY")
        if not api_key: return "שגיאה: חסר API Key"

        # השורה המעודכנת והיציבה שמחליפה את gemini-flash-latest
        model_id = "gemini-1.5-flash" 
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent?key={api_key}"
        
        headers = {'Content-Type': 'application/json'}
        
        if audio_bytes:
            # זיהוי אוטומטי של סוג האודיו (WebM לעומת WAV)
            mime_type = "audio/webm" if audio_bytes.startswith(b'\x1a\x45\xdf\xa3') else "audio/wav"
            audio_base64 = base64.b64encode(audio_bytes).decode('utf-8')
            
            payload = {
                "contents": [{
                    "parts": [
                        {"text": prompt},
                        {"inlineData": {"mimeType": mime_type, "data": audio_base64}}
                    ]
                }]
            }
        else:
            payload = {"contents": [{"parts": [{"text": prompt}]}]}

        response = requests.post(url, headers=headers, json=payload, timeout=90)
        res_json = response.json()

        if response.status_code != 200:
            return f"שגיאת API ({response.status_code}): {res_json.get('error', {}).get('message', 'Unknown error')}"

        # חילוץ בטוח של התשובה (מניעת IndexError)
        candidates = res_json.get('candidates', [])
        if not candidates:
            return "ג'ימיני לא החזיר תשובה. ייתכן שהתוכן נחסם עקב מגבלות בטיחות או רעש באודיו."
        
        return candidates[0].get('content', {}).get('parts', [{}])[0].get('text', 'לא התקבל טקסט מהמודל.')

    except Exception as e:
        return f"שגיאה טכנית: {str(e)}"
        
def get_ai_model():
    """אתחול והגדרת מודל ה-Gemini מתוך ה-Secrets עבור הטאב הסטטיסטי"""
    api_key = st.secrets.get("GOOGLE_API_KEY", "")
    if not api_key:
        st.error("⚠️ חסר מפתח API (GOOGLE_API_KEY) ב-Secrets.")
        return None
    import google.generativeai as genai
    genai.configure(api_key=api_key)
    return genai.GenerativeModel('gemini-1.5-flash')        
# ==========================================
# --- 2. פונקציות ממשק משתמש (Tabs) ---
# ==========================================

def validate_entry(entry):
    errors = []
    if not entry.get('student_name') or entry.get('student_name') == "תלמיד אחר...":
        errors.append("חובה לבחור שם תלמיד")
    if entry.get('duration_min', 0) <= 0:
        errors.append("זמן עבודה חייב להיות גדול מ-0")
    
    if errors:
        for err in errors:
            st.warning(f"⚠️ {err}")
        return False
    return True

def render_tab_entry(svc, full_df):
    it = st.session_state.it
    
    # 1. בחירת סטודנט - מחוץ לעמודות (לכל רוחב המסך)
    student_name = st.selectbox("👤 בחר סטודנט", CLASS_ROSTER, key=f"sel_{it}")
    
    # 2. לוגיקה של הפס הירוק
    if student_name != st.session_state.last_selected_student:
        target = normalize_name(student_name)
        match = full_df[full_df['name_clean'] == target] if not full_df.empty else pd.DataFrame()
        st.session_state.show_success_bar = not match.empty
        st.session_state.student_context = match.tail(15).to_string() if not match.empty else ""
        st.session_state.last_selected_student = student_name
        st.session_state.chat_history = []
        st.rerun()

    # 3. הפס הירוק - עכשיו הוא לכל רוחב המסך ולא יחתוך את הטלפון
    if st.session_state.show_success_bar:
        st.success(f"✅ נמצאה היסטוריה עבור {student_name}.")
    else:
        st.info(f"ℹ️ {student_name}: אין תצפיות קודמות.")

    # 4. עכשיו פותחים את העמודות עבור שאר הטופס
    col_in, col_chat = st.columns([1.2, 1])
    
    with col_in:
        # מדדי זמן ומספר מטלות
        c_metrics1, c_metrics2 = st.columns(2)
        with c_metrics1:
            duration = st.number_input("⏱️ זמן עבודה (בדקות):", min_value=0, value=45, step=5, key=f"dur_{it}")
        with c_metrics2:
            drawings = st.number_input("📋 מספר שרטוטים שבוצעו:", min_value=0, value=1, step=1, key=f"drw_{it}")
        
        st.markdown("---")
        work_method = st.radio("🛠️ צורת עבודה:", ["🧊 בעזרת גוף מודפס", "🎨 ללא גוף (דמיון)"], key=f"wm_{it}", horizontal=True)

        # המדדים הכמותיים (1-5)
        st.markdown("### 📊 מדדים כמותיים (1-5)")
        m1, m2 = st.columns(2)
        with m1:
            score_proj = st.slider("📐 המרת ייצוגים (הטלה)", 1, 5, 3, key=f"s1_{it}")
            score_views = st.slider("🔄 מעבר בין היטלים", 1, 5, 3, key=f"s2_{it}")
            score_model = st.slider("🧊 שימוש במודל 3D", 1, 5, 3, key=f"s3_{it}")
        with m2:
            score_spatial = st.slider("🧠 תפיסה מרחבית", 1, 5, 3, key=f"s4_{it}")
            score_conv = st.slider("📏 פרופורציות ומוסכמות", 1, 5, 3, key=f"s5_{it}")
            difficulty = st.slider("📉 רמת קושי התרגיל", 1, 5, 3, key=f"sd_{it}")

        st.markdown("---")
        
        # תגיות אבחון ותיבות הטקסט הדינמיות (שמתנקות מעצמן)
        tags = st.multiselect("🏷️ תגיות אבחון", TAGS_OPTIONS, key=f"t_{it}")
        
        st.text_area("🗣️ תצפית שדה (Challenge):", height=150, key=f"field_obs_input_{it}")
        st.text_area("🧠 תובנה/פרשנות (Insight):", height=100, key=f"insight_input_{it}")
        
        up_files = st.file_uploader("📷 צרף תמונות", accept_multiple_files=True, type=['png', 'jpg', 'jpeg'], key=f"up_{it}")
        
        st.markdown("---")
        
        c_btns = st.columns(2)
        
        # --- כפתור 1: בקשת רפלקציה ממוקדת מה-AI ---
        with c_btns[0]:
            if st.button("🔍 בקש רפלקציה (AI)", key=f"ai_btn_{it}"):
                raw_ch = st.session_state.get(f"field_obs_input_{it}", "").strip()
                raw_ins = st.session_state.get(f"insight_input_{it}", "").strip()
                
                if raw_ins or raw_ch:
                    with st.spinner("היועץ מנתח את מקרה הבוחן..."):
                        # בניית פרומפט ממוקד שבוחן את תהליך ההוראה והלמידה הספציפי
                        prompt = f"""
                        נתח כמנתח מחקר פעולה אקדמי (Action Research) את התצפית הבאה על הסטודנט {student_name}:
                        - קושי שנצפה (Challenge): {raw_ch}
                        - תובנת המורה (Insight): {raw_ins}
                        - מדדים כמותיים שהוזנו: הטלה={score_proj}, מעבר היטלים={score_views}, תפיסה מרחבית={score_spatial}, פרופורציות={score_conv}.
                        - שיטת עבודה: {work_method} (ברמת קושי {difficulty}).
                        
                        תנחומות/דגשים לניתוח:
                        1. האם פרשנות המורה עקבית ומבוססת ביחס למדדים ולתצפית הגולמית?
                        2. מה זה מלמד על הפדגוגיה הנדסית הנדרשת לשלב זה (שימוש במודל מול דמיון)?
                        3. ספק תובנה קצרה לקידום דרך ההוראה של נושא השרטוט הטכני במקרה זה.
                        """
                        res = call_gemini(prompt)
                        st.session_state.last_feedback = res
                        st.rerun()
                else:
                    st.warning("אנא מלא את תיבת התצפית או התובנות לפני בקשת רפלקציה.")

        # --- כפתור 2: שמירת התצפית + הרפלקציה של ה-AI ---
        with c_btns[1]:
            if st.button("💾 שמור תצפית", type="primary", key=f"save_btn_{it}"):
                final_ch = st.session_state.get(f"field_obs_input_{it}", "").strip()
                final_ins = st.session_state.get(f"insight_input_{it}", "").strip()
                
                # בניית האובייקט שישמר - שים לב לתוספת של ai_reflection
                entry = {
                    "type": "reflection",
                    "date": date.today().isoformat(),
                    "student_name": student_name,
                    "difficulty": difficulty,
                    "duration_min": duration,
                    "drawings_count": drawings,
                    "work_method": work_method,
                    "score_proj": score_proj,
                    "score_spatial": score_spatial,
                    "score_conv": score_conv,
                    "score_model": score_model,
                    "score_views": score_views,
                    "challenge": final_ch,
                    "insight": final_ins,
                    "tags": str(tags),
                    "ai_reflection": st.session_state.get("last_feedback", ""), # שמירת הרפלקציה המדויקת של אותו הרגע
                    "timestamp": datetime.now().isoformat()
                }
                
                if validate_entry(entry):
                    if final_ch or final_ins or up_files:
                        with st.spinner("שומר לאקסל ומעלה קבצים..."):
                            img_links = []
                            if up_files:
                                for f in up_files:
                                    link = drive_upload_file(svc, f, GDRIVE_FOLDER_ID)
                                    if link:
                                        img_links.append(link)
                            
                            entry["images"] = ", ".join(img_links)
                            
                            # כתיבה לקובץ המקומי לקראת הסנכרון הבא
                            with open(DATA_FILE, "a", encoding="utf-8") as f:
                                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                            
                            st.balloons()
                            st.success("✅ התצפית והרפלקציה המחקרית נשמרו בהצלחה!")
                            
                            # איפוס מוחלט של המשוב והזכרונות הזמניים כדי שהתלמיד הבא ייפתח חלק לחלוטין
                            st.session_state.last_feedback = ""
                            st.session_state.it += 1
                            time.sleep(1.2)
                            st.rerun()
                    else:
                        st.warning("⚠️ לא ניתן לשמור תצפית ריקה.")  
                        
        # הצגת המשוב מתחת לכ
