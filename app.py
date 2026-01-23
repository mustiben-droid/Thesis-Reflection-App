import json
import base64
import os
import io
import logging
import pandas as pd
import streamlit as st
import google.generativeai as genai
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload
from datetime import date, datetime

# --- 0. הגדרות ועיצוב ---
logging.basicConfig(level=logging.INFO)
DATA_FILE = "reflections.jsonl"
MASTER_FILENAME = "All_Observations_Master.xlsx"
GDRIVE_FOLDER_ID = st.secrets.get("GDRIVE_FOLDER_ID")
CLASS_ROSTER = ["נתנאל", "רועי", "אסף", "עילאי", "טדי", "גאל", "אופק", "דניאל.ר", "אלי", "טיגרן", "פולינה.ק", "תלמיד אחר..."]
TAGS_OPTIONS = ["התעלמות מקווים נסתרים", "בלבול בין היטלים", "קושי ברוטציה מנטלית", "טעות בפרופורציות", "קושי במעבר בין היטלים", "שימוש בכלי מדידה", "סיבוב פיזי של המודל", "תיקון עצמי", "עבודה עצמאית שוטפת"]

st.set_page_config(page_title="מערכת תצפית - 43.0", layout="wide")

st.markdown("""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Heebo:wght@300;400;700&display=swap');
        html, body, .stApp { direction: rtl; text-align: right; font-family: 'Heebo', sans-serif !important; }
        [data-testid="stSlider"] { direction: ltr !important; }
        .stButton > button { width: 100%; font-weight: bold; border-radius: 12px; background-color: #28a745; color: white; height: 3em; }
        .feedback-box { background-color: #fff3cd; padding: 15px; border-radius: 10px; border: 1px solid #ffeeba; margin-top: 10px; }
    </style>
""", unsafe_allow_html=True)

# --- 1. מודול טעינה חכם (מבוסס Copilot) ---
def normalize_name(name):
    if not isinstance(name, str): return ""
    return name.replace(" ", "").replace(".", "").replace("־", "").replace("-", "").strip()

@st.cache_resource
def get_drive_service():
    try:
        b64 = st.secrets.get("GDRIVE_SERVICE_ACCOUNT_B64")
        if not b64: return None
        json_str = base64.b64decode(b64).decode("utf-8")
        creds = Credentials.from_service_account_info(json.loads(json_str), scopes=["https://www.googleapis.com/auth/drive"])
        return build("drive", "v3", credentials=creds)
    except: return None

def load_full_dataset(svc):
    df_drive = pd.DataFrame()
    if svc:
        try:
            query = f"name = '{MASTER_FILENAME}' and trashed = false"
            res = svc.files().list(q=query, spaces='drive', supportsAllDrives=True, includeItemsFromAllDrives=True).execute().get('files', [])
            if res:
                request = svc.files().get_media(fileId=res[0]['id'])
                fh = io.BytesIO()
                downloader = MediaIoBaseDownload(fh, request)
                done = False
                while not done: _, done = downloader.next_chunk()
                fh.seek(0)
                df_drive = pd.read_excel(fh)
                # וידוא עמודת שם
                possible = [c for c in df_drive.columns if "student" in c.lower()]
                if possible: df_drive.rename(columns={possible[0]: "student_name"}, inplace=True)
        except Exception as e: logging.error(f"Drive error: {e}")

    df_local = pd.DataFrame()
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                df_local = pd.DataFrame([json.loads(l) for l in f if l.strip()])
        except: pass

    df = pd.concat([df_drive, df_local], ignore_index=True)
    if not df.empty and 'student_name' in df.columns:
        df = df.dropna(subset=['student_name'])
        df['name_clean'] = df['student_name'].apply(normalize_name)
    return df

def get_ai_response(prompt_type, context_data):
    api_key = st.secrets.get("GOOGLE_API_KEY")
    if not api_key: 
        return "שגיאה: מפתח ה-AI לא מוגדר ב-Secrets."
    
    try:
        # הגדרת הקישור ל-API בשיטת REST (מונע שגיאות גרסה בשרת)
        genai.configure(api_key=api_key, transport='rest')
        
        # שימוש במודל החדש והמומלץ ביותר (כפי ש-Copilot הציע)
        # בחרתי ב-1.5-flash כי הוא הכי יציב בחיבורים האלו
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        history_str = str(context_data.get('history', ""))
        clean_history = history_str[:5000]
        
        if prompt_type == "chat":
            full_prompt = (
                f"אתה עוזר מחקר אקדמי. נתח את התצפיות של הסטודנט {context_data['name']}:\n"
                f"{clean_history}\n\n"
                f"השאלה: {context_data['question']}\n"
                f"ענה בעברית מקצועית."
            )
        else: # feedback
            full_prompt = f"תן משוב פדגוגי קצר (3 שורות) על התצפית: {context_data['challenge']}"
            
        # יצירת התוכן
        response = model.generate_content(full_prompt)
        
        if response and response.text:
            return response.text
        else:
            return "ה-AI החזיר תשובה ריקה, נסה שוב."
            
    except Exception as e:
        # אם gemini-1.5-flash עדיין נותן 404, סימן שהחשבון שלך עבר ל-2.0
        try:
            model_2 = genai.GenerativeModel('gemini-2.0-flash-exp')
            return model_2.generate_content(full_prompt).text
        except:
            return f"שגיאה טכנית בחיבור למודלים החדשים: {str(e)[:100]}"
        
# --- 2. ניהול מצב ---
if "it" not in st.session_state: st.session_state.it = 0
if "chat_history" not in st.session_state: st.session_state.chat_history = []
if "student_context" not in st.session_state: st.session_state.student_context = ""
if "last_selected_student" not in st.session_state: st.session_state.last_selected_student = ""
if "show_success_bar" not in st.session_state: st.session_state.show_success_bar = False
if "last_feedback" not in st.session_state: st.session_state.last_feedback = ""

svc = get_drive_service()
st.title("🎓 מנחה מחקר חכם - גרסה 43.0")
tab1, tab2, tab3 = st.tabs(["📝 הזנה ומשוב", "🔄 סנכרון", "📊 ניתוח"])

with tab1:
    col_in, col_chat = st.columns([1.2, 1])
    with col_in:
        it = st.session_state.it
        student_name = st.selectbox("👤 בחר סטודנט", CLASS_ROSTER, key=f"sel_{it}")
        
        if student_name != st.session_state.last_selected_student:
            with st.spinner(f"טוען היסטוריה עבור {student_name}..."):
                full_df = load_full_dataset(svc)
                target = normalize_name(student_name)
                match = full_df[full_df['name_clean'] == target] if not full_df.empty else pd.DataFrame()
                
                if not match.empty:
                    st.session_state.student_context = match.tail(15).to_string()
                    st.session_state.show_success_bar = True
                else:
                    st.session_state.student_context = ""
                    st.session_state.show_success_bar = False
            st.session_state.last_selected_student = student_name
            st.session_state.chat_history = []
            st.rerun()

        if st.session_state.show_success_bar:
            st.success(f"✅ נמצאה היסטוריה עבור {student_name}. הסוכן מעודכן.")
        else:
            st.info(f"ℹ️ {student_name}: אין תצפיות קודמות במערכת.")

        st.markdown("---")
        # טופס
        c1, c2 = st.columns(2)
        with c1:
            work_method = st.radio("🛠️ סוג תרגול:", ["🧊 בעזרת גוף מודפס", "🎨 ללא גוף (דמיון)"], key=f"wm_{it}", horizontal=True)
            ex_diff = st.select_slider("📉 רמת קושי:", options=["קל", "בינוני", "קשה"], key=f"ed_{it}")
        with c2:
            drw_cnt = st.number_input("כמות שרטוטים", min_value=0, key=f"dc_{it}")
            dur_min = st.number_input("זמן עבודה (דק')", min_value=0, key=f"dm_{it}")

        st.markdown("### 📊 מדדים כמותיים (1-5)")
        m1, m2 = st.columns(2)
        with m1:
            s1 = st.slider("המרת ייצוגים", 1, 5, 3, key=f"s1_{it}")
            s2 = st.slider("מעבר בין היטלים", 1, 5, 3, key=f"s2_{it}")
        with m2:
            s3 = st.slider("שימוש במודל", 1, 5, 3, key=f"s3_{it}")
            s4 = st.slider("מסוגלות עצמית", 1, 5, 3, key=f"s4_{it}")

        tags = st.multiselect("🏷️ תגיות אבחון", TAGS_OPTIONS, key=f"t_{it}")
        challenge = st.text_area("🗣️ תיאור התצפית", key=f"ch_{it}")
        interpretation = st.text_area("🧠 פרשנות מחקרית", key=f"int_{it}")
        up_files = st.file_uploader("📷 צרף תמונות", accept_multiple_files=True, type=['png','jpg','jpeg'], key=f"up_{it}")

        if st.session_state.last_feedback:
            st.markdown(f'<div class="feedback-box"><b>💡 משוב:</b><br>{st.session_state.last_feedback}</div>', unsafe_allow_html=True)

        if st.button("💾 שמור תצפית"):
            if not challenge: st.error("חובה להזין תיאור.")
            else:
                with st.spinner("מעלה ושומר..."):
                    links = []
                    if up_files and svc:
                        for f in up_files:
                            file_meta = {'name': f.name, 'parents': [GDRIVE_FOLDER_ID] if GDRIVE_FOLDER_ID else []}
                            media = MediaIoBaseUpload(io.BytesIO(f.getvalue()), mimetype=f.type)
                            res = svc.files().create(body=file_meta, media_body=media, fields='webViewLink', supportsAllDrives=True).execute()
                            links.append(res.get('webViewLink'))
                    
                    entry = {
                        "date": date.today().isoformat(), "student_name": student_name, "work_method": work_method,
                        "exercise_difficulty": ex_diff, "drawings_count": int(drw_cnt), "duration_min": int(dur_min),
                        "cat_convert_rep": int(s1), "cat_proj_trans": int(s2), "cat_3d_support": int(s3), 
                        "cat_self_efficacy": int(s4), "tags": tags, "challenge": challenge, 
                        "interpretation": interpretation, "file_links": links, "timestamp": datetime.now().isoformat()
                    }
                    with open(DATA_FILE, "a", encoding="utf-8") as f:
                        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                    st.session_state.last_feedback = get_ai_response("feedback", {"challenge": challenge})
                    st.session_state.it += 1
                    st.rerun()

    with col_chat:
        st.subheader(f"🤖 יועץ: {student_name}")
        chat_cont = st.container(height=450)
        for q, a in st.session_state.chat_history:
            with chat_cont:
                st.chat_message("user").write(q); st.chat_message("assistant").write(a)
        u_q = st.chat_input("שאל את הסוכן...")
        if u_q:
            resp = get_ai_response("chat", {"name": student_name, "history": st.session_state.student_context, "question": u_q})
            st.session_state.chat_history.append((u_q, resp)); st.rerun()

with tab2:
    if os.path.exists(DATA_FILE) and st.button("🚀 סנכרן הכל לדרייב"):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            all_entries = [json.loads(line) for line in f if line.strip()]
        # לוגיקת סנכרון (update_master_in_drive)
        st.success("הנתונים מוכנים לסנכרון.")
# --- Tab 3: ניתוח מחקרי ---
with tab3:
    if full_df.empty:
        st.info("אין נתונים לניתוח. בצעי סנכרון בטאב 2.")
    else:
        st.header("🧠 ניתוח תמות AI")
        df_an = full_df.copy()
        df_an['date'] = pd.to_datetime(df_an['date'], errors='coerce')
        df_an['week'] = df_an['date'].dt.strftime('%Y - שבוע %U')
        
        weeks = sorted(df_an['week'].unique(), reverse=True)
        sel_week = st.selectbox("בחר שבוע:", weeks)
        w_df = df_an[df_an['week'] == sel_week]
        
        st.dataframe(w_df)

        if st.button("✨ הפק ניתוח ושמור לדרייב"):
            with st.spinner("ג'ימיני מנתח..."):
                txt = ""
                for _, r in w_df.iterrows():
                    txt += f"סטודנט: {r.get('student_name','')} | תצפית: {r.get('challenge','')} | תובנה: {r.get('insight','')}\n---\n"

                try:
                    genai.configure(api_key=st.secrets["GOOGLE_API_KEY"], transport='rest')
                    model = genai.GenerativeModel('gemini-1.5-flash')
                    response = model.generate_content(f"נתח תמות אקדמיות בעברית לשבוע {sel_week}: {txt}").text
                    
                    st.info(response)
                    
                    if svc:
                        f_name = f"ניתוח_{sel_week}.txt"
                        media = MediaIoBaseUpload(io.BytesIO(response.encode('utf-8')), mimetype='text/plain')
                        svc.files().create(body={'name': f_name, 'parents': [GDRIVE_FOLDER_ID] if GDRIVE_FOLDER_ID else []}, media_body=media, supportsAllDrives=True).execute()
                        st.success(f"נשמר בדרייב בשם {f_name}")
                except Exception as e:
                    st.error(f"שגיאה בניתוח: {e}")

# --- Sidebar ---
st.sidebar.write("מצב חיבור:", "✅ מחובר" if svc else "❌ לא מחובר")






