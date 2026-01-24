import json
import base64
import os
import io
import time
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
CLASS_ROSTER = ["נתנאל", "רועי", "אסף", "עילאי", "טדי", "גאל", "אופק", "דניאל.ר", "אלי", "טיגרן", "פולינה.ק", "תלמיד אחר..."]
TAGS_OPTIONS = ["התעלמות מקווים נסתרים", "בלבול בין היטלים", "קושי ברוטציה מנטלית", "טעות בפרופורציות", "קושי במעבר בין היטלים", "שימוש בכלי מדידה", "סיבוב פיזי של המודל", "תיקון עצמי", "עבודה עצמאית שוטפת"]

st.set_page_config(page_title="מערכת תצפית - 44.0", layout="wide")

st.markdown("""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Heebo:wght@300;400;700&display=swap');
        html, body, .stApp { direction: rtl; text-align: right; font-family: 'Heebo', sans-serif !important; }
        [data-testid="stSlider"] { direction: ltr !important; }
        .stButton > button { width: 100%; font-weight: bold; border-radius: 12px; background-color: #28a745; color: white; height: 3em; }
        .feedback-box { background-color: #fff3cd; padding: 15px; border-radius: 10px; border: 1px solid #ffeeba; margin-top: 10px; }
    </style>
""", unsafe_allow_html=True)

# --- 1. פונקציות עזר ---
def normalize_name(name):
    if not isinstance(name, str): return ""
    return name.replace(" ", "").replace(".", "").replace("־", "").replace("-", "").strip()

@st.cache_resource
def get_drive_service():
    try:
        b64 = st.secrets.get("GDRIVE_SERVICE_ACCOUNT_B64")
        if not b64: 
            return None
        json_str = base64.b64decode(b64).decode("utf-8")
        creds = Credentials.from_service_account_info(
            json.loads(json_str), 
            scopes=["https://www.googleapis.com/auth/drive"]
        )
        return build("drive", "v3", credentials=creds)
    except Exception as e:
        logging.error(f"Drive initialization error: {e}")
        return None

@st.cache_data(ttl=300)  # Cache ל-5 דקות
def load_full_dataset(_svc):
    """טעינת נתונים מ-Drive ומקומי עם cache"""
    df_drive = pd.DataFrame()
    if _svc:
        try:
            query = f"name = '{MASTER_FILENAME}' and trashed = false"
            res = _svc.files().list(
                q=query, 
                spaces='drive', 
                supportsAllDrives=True, 
                includeItemsFromAllDrives=True
            ).execute().get('files', [])
            
            if res:
                fh = io.BytesIO()
                downloader = MediaIoBaseDownload(fh, _svc.files().get_media(fileId=res[0]['id']))
                done = False
                while not done: 
                    _, done = downloader.next_chunk()
                fh.seek(0)
                df_drive = pd.read_excel(fh)
                
                # וידוא עמודת שם
                possible = [c for c in df_drive.columns if "student" in c.lower()]
                if possible: 
                    df_drive.rename(columns={possible[0]: "student_name"}, inplace=True)
        except Exception as e: 
            logging.error(f"Drive error: {e}")

    df_local = pd.DataFrame()
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                lines = [json.loads(l) for l in f if l.strip()]
                if lines:
                    df_local = pd.DataFrame(lines)
        except Exception as e:
            logging.error(f"Local file error: {e}")

    # איחוד נתונים
    df = pd.concat([df_drive, df_local], ignore_index=True)
    
    if not df.empty and 'student_name' in df.columns:
        df = df.dropna(subset=['student_name'])
        df['name_clean'] = df['student_name'].apply(normalize_name)
    
    return df

def get_ai_response(prompt_type, context_data):
    """קבלת תשובה מ-AI עם fallback למודלים שונים"""
    api_key = st.secrets.get("GOOGLE_API_KEY")
    if not api_key: 
        return "⚠️ מפתח ה-API לא מוגדר ב-Secrets"
    
    try:
        genai.configure(api_key=api_key, transport='rest')
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        history_str = str(context_data.get('history', ""))
        clean_history = history_str[:5000]
        
        if prompt_type == "chat":
            full_prompt = (
                f"אתה עוזר מחקר אקדמי. נתח את התצפיות של הסטודנט {context_data.get('name', 'לא ידוע')}:\n"
                f"{clean_history}\n\n"
                f"השאלה: {context_data.get('question', '')}\n"
                f"ענה בעברית מקצועית."
            )
        else:  # feedback
            full_prompt = f"תן משוב פדגוגי קצר (3 שורות) על התצפית: {context_data.get('challenge', '')}"
        
        response = model.generate_content(full_prompt)
        
        if response and response.text:
            return response.text
        else:
            return "ה-AI החזיר תשובה ריקה"
            
    except Exception as e:
        # Fallback ל-2.0
        try:
            model_2 = genai.GenerativeModel('gemini-2.0-flash-exp')
            return model_2.generate_content(full_prompt).text
        except:
            return f"שגיאת AI: {str(e)[:100]}"

# --- 2. אתחול State ---
if "it" not in st.session_state: 
    st.session_state.it = 0
if "chat_history" not in st.session_state: 
    st.session_state.chat_history = []
if "student_context" not in st.session_state: 
    st.session_state.student_context = ""
if "last_selected_student" not in st.session_state: 
    st.session_state.last_selected_student = ""
if "show_success_bar" not in st.session_state: 
    st.session_state.show_success_bar = False
if "last_feedback" not in st.session_state: 
    st.session_state.last_feedback = ""

# --- 3. טעינת נתונים גלובלית ---
svc = get_drive_service()
full_df = load_full_dataset(svc)

# --- 4. ממשק ---
st.title("🎓 מנחה מחקר חכם - גרסה 44.0")
tab1, tab2, tab3 = st.tabs(["📝 הזנה ומשוב", "🔄 סנכרון", "📊 ניתוח"])

with tab1:
    col_in, col_chat = st.columns([1.2, 1])
    
    with col_in:
        it = st.session_state.it
        student_name = st.selectbox("👤 בחר סטודנט", CLASS_ROSTER, key=f"sel_{it}")
        
        # טעינת הקשר אישי
        if student_name != st.session_state.last_selected_student:
            with st.spinner(f"טוען היסטוריה עבור {student_name}..."):
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
        
        # טופס הזנה
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

        # הצגת משוב קודם
        if st.session_state.last_feedback:
            st.markdown(f'<div class="feedback-box"><b>💡 משוב AI:</b><br>{st.session_state.last_feedback}</div>', unsafe_allow_html=True)

        # כפתור שמירה
        if st.button("💾 שמור תצפית"):
            if not challenge:
                st.error("⚠️ חובה להזין תיאור")
            else:
                with st.spinner("מעלה ושומר..."):
                    links = []
                    GDRIVE_FOLDER_ID = st.secrets.get("GDRIVE_FOLDER_ID")
                    
                    if up_files and svc:
                        for f in up_files:
                            file_meta = {'name': f.name}
                            if GDRIVE_FOLDER_ID:
                                file_meta['parents'] = [GDRIVE_FOLDER_ID]
                            
                            media = MediaIoBaseUpload(io.BytesIO(f.getvalue()), mimetype=f.type)
                            res = svc.files().create(
                                body=file_meta, 
                                media_body=media, 
                                fields='webViewLink', 
                                supportsAllDrives=True
                            ).execute()
                            links.append(res.get('webViewLink'))
                    
                    entry = {
                        "date": date.today().isoformat(),
                        "student_name": student_name,
                        "work_method": work_method,
                        "exercise_difficulty": ex_diff,
                        "drawings_count": int(drw_cnt),
                        "duration_min": int(dur_min),
                        "cat_convert_rep": int(s1),
                        "cat_proj_trans": int(s2),
                        "cat_3d_support": int(s3),
                        "cat_self_efficacy": int(s4),
                        "tags": tags,
                        "challenge": challenge,
                        "interpretation": interpretation,
                        "file_links": links,
                        "timestamp": datetime.now().isoformat()
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
                st.chat_message("user").write(q)
                st.chat_message("assistant").write(a)
        
        u_q = st.chat_input("שאל את הסוכן...")
        if u_q:
            resp = get_ai_response("chat", {
                "name": student_name,
                "history": st.session_state.student_context,
                "question": u_q
            })
            st.session_state.chat_history.append((u_q, resp))
            st.rerun()

with tab2:
    st.header("🔄 סנכרון לדרייב")
    
    if not svc:
        st.warning("⚠️ שירות Drive לא זמין - בדוק הגדרות Secrets")
    elif not os.path.exists(DATA_FILE):
        st.info("אין נתונים מקומיים לסנכרון")
    elif st.button("🚀 סנכרן הכל לדרייב"):
        try:
            with st.spinner("מסנכרן נתונים..."):
                # קריאת נתונים מקומיים
                with open(DATA_FILE, "r", encoding="utf-8") as f:
                    locals_ = [json.loads(line) for line in f if line.strip()]
                
                # איחוד עם נתונים קיימים
                df_merged = pd.concat(
                    [full_df, pd.DataFrame(locals_)],
                    ignore_index=True
                ).drop_duplicates(
                    subset=['student_name', 'timestamp'],
                    keep='last'
                )
                
                # יצירת Excel
                buf = io.BytesIO()
                with pd.ExcelWriter(buf, engine='openpyxl') as w:
                    df_merged.to_excel(w, index=False)
                buf.seek(0)
                
                # חיפוש קובץ קיים
                query = f"name = '{MASTER_FILENAME}' and trashed = false"
                res = svc.files().list(q=query, supportsAllDrives=True).execute().get('files', [])
                
                media = MediaIoBaseUpload(
                    buf,
                    mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
                
                # עדכון או יצירה
                if res:
                    svc.files().update(
                        fileId=res[0]['id'],
                        media_body=media,
                        supportsAllDrives=True
                    ).execute()
                else:
                    GDRIVE_FOLDER_ID = st.secrets.get("GDRIVE_FOLDER_ID")
                    body = {'name': MASTER_FILENAME}
                    if GDRIVE_FOLDER_ID:
                        body['parents'] = [GDRIVE_FOLDER_ID]
                    
                    svc.files().create(
                        body=body,
                        media_body=media,
                        supportsAllDrives=True
                    ).execute()
                
                # מחיקת קובץ מקומי
                os.remove(DATA_FILE)
                st.success(f"✅ סונכרנו {len(locals_)} רשומות!")
                time.sleep(1)
                st.cache_data.clear()  # ניקוי cache
                st.rerun()
                
        except Exception as e:
            st.error(f"❌ שגיאה בסנכרון: {str(e)}")
            logging.error(f"Sync error: {e}")

with tab3:
    st.header("📊 ניתוח נתונים ומגמות")
    
    if full_df.empty:
        st.info("ℹ️ אין עדיין נתונים במערכת. בצע סנכרון בטאב 2 כדי להתחיל בניתוח.")
    else:
        # פילטרים
        col_f1, col_f2 = st.columns([1, 1])
        with col_f1:
            if 'student_name' in full_df.columns:
                all_students = sorted(full_df['student_name'].unique().tolist())
                selected_s = st.selectbox("👤 בחר סטודנט לניתוח:", ["כולם"] + all_students, key="ana_s_tab3")
            else:
                st.error("חסרה עמודת student_name")
                selected_s = "כולם"
        
        # סינון נתונים
        view_df = full_df if selected_s == "כולם" else full_df[full_df['student_name'] == selected_s]
        
        # תצוגת טבלה
        st.subheader(f"📋 תצפיות עבור: {selected_s}")
        
        cols_to_show = ['date', 'student_name', 'challenge', 'interpretation', 'tags', 'cat_convert_rep', 'cat_proj_trans', 'cat_self_efficacy']
        actual_cols = [c for c in cols_to_show if c in view_df.columns]
        
        if actual_cols:
            if 'date' in actual_cols:
                st.dataframe(
                    view_df[actual_cols].sort_values(by='date', ascending=False),
                    use_container_width=True
                )
            else:
                st.dataframe(view_df[actual_cols], use_container_width=True)
        else:
            st.warning("אין עמודות מתאימות להצגה")

        # ניתוח AI
        st.markdown("---")
        st.subheader("🧠 תובנות סוכן ה-AI")
        
        if st.button("✨ הפק ניתוח מגמות למידה"):
            with st.spinner(f"הסוכן מנתח את ההיסטוריה של {selected_s}..."):
                recent_context = view_df.tail(10).to_string()
                
                analysis_prompt = {
                    "name": selected_s,
                    "history": recent_context,
                    "question": """
                    נתח את נתוני התצפיות:
                    1. זהה דפוסי קושי חוזרים לפי התגיות והתיאור
                    2. התייחס למדדים הכמותיים (1-5)
                    3. הצע המלצה פדגוגית להמשך
                    """
                }
                
                analysis_res = get_ai_response("chat", analysis_prompt)
                st.markdown(f'<div class="feedback-box">{analysis_res}</div>', unsafe_allow_html=True)
