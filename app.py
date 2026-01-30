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

# ==========================================
# --- 0. הגדרות מערכת ועיצוב ---
# ==========================================
DATA_FILE = "reflections.jsonl"
MASTER_FILENAME = "All_Observations_Master.xlsx"

# תיקיית האם (לתמונות ותצפיות רגילות)
GDRIVE_FOLDER_ID = st.secrets.get("GDRIVE_FOLDER_ID")

# התיקייה החדשה שלך להקלטות וניתוחי ראיונות
INTERVIEW_FOLDER_ID = "1NQz2UZ6BfAURfN4a8h4_qSkyY-_gxhxP"

CLASS_ROSTER = ["נתנאל", "רועי", "אסף", "עילאי", "טדי", "גאל", "אופק", "דניאל.ר", "אלי", "טיגרן", "פולינה.ק", "תלמיד אחר..."]
TAGS_OPTIONS = ["התעלמות מקווים נסתרים", "בלבול בין היטלים", "קושי ברוטציה מנטלית", "טעות בפרופורציות", "קושי במעבר בין היטלים", "שימוש בכלי מדידה", "סיבוב פיזי של המודל", "תיקון עצמי", "עבודה עצמאית שוטפת"]
st.set_page_config(page_title="מערכת תצפית מחקרית - 54.0", layout="wide")

st.markdown("""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Heebo:wght@300;400;700&display=swap');
        
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

        model_id = "gemini-flash-latest" 
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
        # כאן ממשיך שאר הקוד שלך (זמן עבודה, מספר שרטוטים וכו')

        # הוספת תיבות למספר שרטוטים וזמן - מעל ה-multiselect
        c_metrics1, c_metrics2 = st.columns(2)
        with c_metrics1:
            duration = st.number_input("⏱️ זמן עבודה (בדקות):", min_value=0, value=45, step=5, key=f"dur_{it}")
        with c_metrics2:
            drawings = st.number_input("📋 מספר שרטוטים שבוצעו:", min_value=0, value=1, step=1, key=f"drw_{it}")
        
        st.markdown("---")
        work_method = st.radio("🛠️ צורת עבודה:", ["🧊 בעזרת גוף מודפס", "🎨 ללא גוף (דמיון)"], key=f"wm_{it}", horizontal=True)

# --- 2. מדדים כמותיים (1-5) ---
        st.markdown("### 📊 מדדים כמותיים (1-5)")
        m1, m2 = st.columns(2)
        with m1:
            score_proj = st.slider("📐 המרת ייצוגים (הטלה)", 1, 5, 3, key=f"s1_{st.session_state.it}")
            score_views = st.slider("🔄 מעבר בין היטלים", 1, 5, 3, key=f"s2_{st.session_state.it}")
            score_model = st.slider("🧊 שימוש במודל 3D", 1, 5, 3, key=f"s3_{st.session_state.it}")
        with m2:
            score_spatial = st.slider("🧠 תפיסה מרחבית", 1, 5, 3, key=f"s4_{st.session_state.it}")
            score_conv = st.slider("📏 פרופורציות ומוסכמות", 1, 5, 3, key=f"s5_{st.session_state.it}")
            difficulty = st.slider("📉 רמת קושי התרגיל", 1, 5, 3, key=f"sd_{st.session_state.it}")

        st.markdown("---")
        
        # --- 3. תיבות טקסט ותמונות (החזרתי אותן!) ---
        tags = st.multiselect("🏷️ תגיות אבחון", TAGS_OPTIONS, key=f"t_{st.session_state.it}")
        
        # תיבות הטקסט שומרות על Key קבוע כדי שה-AI וה-Pop יעבדו
        st.text_area("🗣️ תצפית שדה (Challenge):", height=150, key="field_obs_input")
        st.text_area("🧠 תובנה/פרשנות (Insight):", height=100, key="insight_input")
        
        up_files = st.file_uploader("📷 צרף תמונות", accept_multiple_files=True, type=['png', 'jpg', 'jpeg'], key=f"up_{st.session_state.it}")
        
        # --- 4. כפתורי פעולה ---
        st.markdown("---")
        c_btns = st.columns(2)
        
        with c_btns[0]:
            if st.button("🔍 בקש רפלקציה (AI)", key=f"ai_btn_{st.session_state.it}"):
                raw_ins = st.session_state.get("insight_input", "")
                if raw_ins.strip():
                    with st.spinner("היועץ מנתח..."):
                        res = call_gemini(f"פנה אלי בלשון זכר. נתח תצפית על {student_name}: {raw_ins}")
                        st.session_state.last_feedback = res
                        st.rerun()
                else:
                    st.warning("תיבת התובנות ריקה.")

    with c_btns[1]:
            if st.button("💾 שמור תצפית", type="primary", key=f"save_btn_{st.session_state.it}"):
                final_ch = st.session_state.get("field_obs_input", "").strip()
                final_ins = st.session_state.get("insight_input", "").strip()
                
                # 1. יצירת ה-entry לבדיקה (חשוב שהשם והזמן יהיו כאן)
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
                    "timestamp": datetime.now().isoformat()
                }
                
                # 2. בדיקת תקינות - עוצר כאן אם שכחת שם תלמיד
                if validate_entry(entry):
                    # בדיקה שיש תוכן כלשהו לשמור
                    if final_ch or final_ins or up_files:
                        with st.spinner("שומר לאקסל ומעלה קבצים..."):
                            img_links = []
                            if up_files:
                                for f in up_files:
                                    link = drive_upload_file(svc, f, GDRIVE_FOLDER_ID)
                                    if link:
                                        img_links.append(link)
                            
                            # הוספת הקישורים ל-entry רק אחרי שהועלו
                            entry["images"] = ", ".join(img_links)
                            
                            # 3. כתיבה לקובץ המקומי (JSONL)
                            with open(DATA_FILE, "a", encoding="utf-8") as f:
                                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                            
                            # החלק האהוב עליך - הבלונים וההצלחה!
                            st.balloons()
                            st.success("✅ נשמר בהצלחה!")
                            
                            # 4. ניקוי ה-Session State כדי לעבור לתלמיד הבא
                            st.session_state.pop("field_obs_input", None)
                            st.session_state.pop("insight_input", None)
                            st.session_state.last_feedback = ""
                            for k in list(st.session_state.keys()):
                                if any(k.startswith(p) for p in ["field_obs_input_", "insight_input_", "t_", "up_"]):
                                    st.session_state.pop(k, None)
                            
                            st.session_state.it += 1
                            time.sleep(1.8)
                            st.rerun()
                    else:
                        st.warning("⚠️ לא ניתן לשמור תצפית ריקה. אנא מלא את ה-Challenge או את התובנות.")
                        
        # הצגת המשוב מתחת לכפתורים
    if st.session_state.last_feedback:
            st.markdown("---")
            st.markdown(f'<div class="feedback-box"><b>💡 משוב יועץ AI:</b><br>{st.session_state.last_feedback}</div>', unsafe_allow_html=True)           
            if st.button("🗑️ נקה משוב"):
                st.session_state.last_feedback = ""
                st.rerun()

    with col_chat:
        st.subheader(f"🤖 יועץ: {student_name}")
        chat_cont = st.container(height=450)
        for q, a in st.session_state.chat_history:
            with chat_cont:
                st.chat_message("user").write(q); st.chat_message("assistant").write(a)
        
        u_q = st.chat_input("שאל על הסטודנט...")
        if u_q:
            resp = call_gemini(f"היסטוריה: {st.session_state.student_context}. שאלה: {u_q}")
            st.session_state.chat_history.append((u_q, resp)); st.rerun()

def render_tab_sync(svc, full_df):
    st.header("🔄 סנכרון לדרייב")
    # שליפת ה-ID מה-Secrets שהגדרת
    file_id = st.secrets.get("MASTER_FILE_ID")
    
    if os.path.exists(DATA_FILE) and st.button("🚀 סנכרן לקובץ המרכזי"):
        if not file_id:
            st.error("⚠️ חסר MASTER_FILE_ID בתוך ה-Secrets של Streamlit!")
            return

        try:
            with st.spinner("מתחבר לקובץ המאסטר וממזג נתונים..."):
                # 1. קריאת התצפיות החדשות מהמכשיר
                with open(DATA_FILE, "r", encoding="utf-8") as f:
                    locals_ = [json.loads(l) for l in f if l.strip()]
                
                # 2. איחוד עם המאסטר הקיים ומניעת כפילויות
                df_new = pd.DataFrame(locals_)
                df_combined = pd.concat([full_df, df_new], ignore_index=True)
                df_combined = df_combined.drop_duplicates(subset=['student_name', 'timestamp'], keep='last')
                
                # 3. הכנת הקובץ למשלוח
                buf = io.BytesIO()
                with pd.ExcelWriter(buf, engine='openpyxl') as w:
                    df_combined.to_excel(w, index=False)
                buf.seek(0)
                
                # 4. עדכון הקובץ הספציפי בדרייב (לפי ה-ID)
                media = MediaIoBaseUpload(buf, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                svc.files().update(fileId=file_id, media_body=media, supportsAllDrives=True).execute()
                
                # 5. ניקוי וסיום
                os.remove(DATA_FILE)
                st.success("✅ הנתונים סונכרנו בהצלחה לקובץ המאסטר הראשי!")
                st.cache_data.clear()
                st.rerun()
        except Exception as e:
            st.error(f"❌ שגיאת סנכרון: {e}")

def render_tab_analysis(svc):
    st.header("📊 מרכז ניתוח ומגמות")
    df_v = load_full_dataset(svc)
    
    if df_v.empty:
        st.info("אין עדיין מספיק נתונים לניתוח. בצע סנכרון בטאב 2 או הזן תצפיות חדשות.")
        return

    # עיבוד תאריכים לשבועות
    df_v['date'] = pd.to_datetime(df_v['date'], errors='coerce')
    df_v['week'] = df_v['date'].dt.strftime('%Y - שבוע %U')
    
    # --- חלק א: מעקב התקדמות אישי ---
    st.subheader("📈 מעקב התקדמות אישי")
    all_students = sorted(df_v['student_name'].dropna().unique())
    sel_student = st.selectbox("בחר תלמיד למעקב ויזואלי:", all_students)
    
    student_data = df_v[df_v['student_name'] == sel_student].sort_values('date')
    
    if len(student_data) >= 1:
        # מיפוי המדדים לשמות החדשים והנכונים
        metrics = {
            'score_proj': 'המרת ייצוגים',
            'score_views': 'מעבר בין היטלים',
            'score_model': 'שימוש במודל 3D',
            'score_spatial': 'תפיסה מרחבית',
            'score_conv': 'פרופורציות'
        }
        
        # בדיקה אילו מדדים באמת קיימים בנתונים (השיפור של Perplexity)
        available_metrics = [c for c in metrics.keys() if c in student_data.columns]
        
        if available_metrics:
            plot_df = student_data[['date'] + available_metrics].copy()
            plot_df = plot_df.rename(columns=metrics).set_index('date')
            
            st.line_chart(plot_df)
            st.caption("מגמת שינוי במדדים הכמותיים (1-5)")
            
            # הצגת הערה אם חלק מהמדדים חסרים
            missing = [metrics[c] for c in metrics.keys() if c not in student_data.columns]
            if missing:
                st.info(f"💡 הערה: המדדים הבאים טרם תועדו עבור תלמיד זה: {', '.join(missing)}")
        else:
            st.warning("⚠️ לא נמצאו מדדים כמותיים להצגה עבור תלמיד זה.")
    else:
        st.warning("אין מספיק נתונים להצגת גרף עבור תלמיד זה.")

    st.markdown("---")

    # --- חלק ב: ניתוח כיתתי שבועי ---
    st.subheader("🧠 ניתוח תמות שבועי (AI)")
    weeks = sorted(df_v['week'].dropna().unique(), reverse=True)
    sel_w = st.selectbox("בחר שבוע לניתוח כיתתי:", weeks)
    w_df = df_v[df_v['week'] == sel_w]
    
    col_table, col_ai = st.columns([1, 1])
    
    with col_table:
        st.write(f"תצפיות בשבוע {sel_w}:")
        # וידוי שהעמודות קיימות לפני הצגת הטבלה
        cols_to_show = [c for c in ['student_name', 'challenge', 'tags'] if c in w_df.columns]
        st.dataframe(w_df[cols_to_show], use_container_width=True)
    
    with col_ai:
        if st.button("✨ הפק ניתוח שבועי ושמור לדרייב"):
            with st.spinner("ג'ימיני מנתח את התצפיות..."):
                txt = "".join([f"תלמיד: {r.get('student_name','')} | קושי: {r.get('challenge','')} | תובנה: {r.get('insight','')}\n" for _, r in w_df.iterrows()])
                response = call_gemini(f"בצע ניתוח תמות אקדמי על התצפיות הבאות עבור שבוע {sel_w}:\n\n{txt}")
                st.markdown(f'<div class="feedback-box"><b>📊 ממצאים לשבוע {sel_w}:</b><br>{response}</div>', unsafe_allow_html=True)
                
                try:
                    f_name = f"ניתוח_תמות_{sel_w.replace(' ', '_')}.txt"
                    drive_upload_bytes(svc, response, f_name, GDRIVE_FOLDER_ID, is_text=True)
                    st.success(f"הניתוח נשמר בדרייב.")
                except Exception as e:
                    st.error(f"הניתוח הופק אך נכשלה השמירה: {e}")

def render_tab_interview(svc, full_df):
    it = st.session_state.it
    st.subheader("🎙️ ראיון עומק וניתוח תמות למחקר")
    
    student_name = st.selectbox("בחר סטודנט לראיון:", CLASS_ROSTER, key=f"int_sel_{it}")
    
    # 1. הקלטת אודיו
    audio_data = mic_recorder(start_prompt="התחל הקלטה ⏺️", stop_prompt="עצור ונתח ⏹️", key=f"mic_int_{it}")
    
    if audio_data:
        audio_bytes = audio_data['bytes']
        st.session_state[f"audio_bytes_{it}"] = audio_bytes
        st.audio(audio_bytes, format="audio/wav")
        
        if st.button("✨ בצע תמלול וניתוח תמות עומק", key=f"btn_an_{it}"):
            with st.status("🤖 ג'ימיני מנתח...", expanded=True) as status:
                prompt = f"נתח ראיון של {student_name}. תמלל ונתח תפיסה מרחבית."
                analysis_res = call_gemini(prompt, audio_bytes)
                
                if "שגיאה" in analysis_res:
                    status.update(label="❌ נכשל", state="error")
                    st.error(analysis_res)
                else:
                    st.session_state[f"last_analysis_{it}"] = analysis_res
                    status.update(label="✅ הושלם!", state="complete")
                    st.rerun()

    # 2. הצגת תוצאות ושמירה
    analysis_key = f"last_analysis_{it}"
    if analysis_key in st.session_state and st.session_state[analysis_key]:
        st.markdown(f'<div class="feedback-box">{st.session_state[analysis_key]}</div>', unsafe_allow_html=True)
        
        if st.button("💾 שמור וסנכרן לתיקיית המחקר ולאקסל", type="primary", key=f"save_int_{it}"):
            saved_audio = st.session_state.get(f"audio_bytes_{it}")
            if not saved_audio:
                st.error("ההקלטה לא נמצאה בזיכרון.")
            else:
                prog_bar = st.progress(0)
                try:
                    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
                    # העלאה לדרייב
                    a_link = drive_upload_bytes(svc, saved_audio, f"Int_{student_name}_{ts}.wav", RESEARCH_FOLDER_ID)
                    prog_bar.progress(50)
                    t_link = drive_upload_bytes(svc, st.session_state[analysis_key], f"An_{student_name}_{ts}.txt", RESEARCH_FOLDER_ID, is_text=True)
                    
                    # רישום ב-JSONL המקומי
                    entry = {
                        "type": "interview", 
                        "date": date.today().isoformat(),
                        "student": student_name, 
                        "audio": a_link, 
                        "text": t_link,
                        "timestamp": datetime.now().isoformat()
                    }
                    with open(DATA_FILE, "a", encoding="utf-8") as f:
                        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                    
                    prog_bar.progress(100)
                    st.success("✅ נשמר בהצלחה!")
                    st.balloons()
                    time.sleep(2)
                    st.rerun()
                except Exception as e:
                    st.error(f"שגיאה בשמירה: {e}")

def drive_upload_file(svc, file_obj, folder_id):
    """מעלה קובץ (כמו תמונה) מה-Uploader - משמש לטאב 1"""
    try:
        from googleapiclient.http import MediaIoBaseUpload
        import io
        file_content = file_obj.read()
        file_obj.seek(0) 
        media = MediaIoBaseUpload(io.BytesIO(file_content), mimetype=file_obj.type, resumable=True)
        file_metadata = {'name': file_obj.name, 'parents': [folder_id]}
        
        result = svc.files().create(
            body=file_metadata, 
            media_body=media, 
            fields='id, webViewLink', 
            supportsAllDrives=True
        ).execute()
        
        return result.get('webViewLink', '')
    except Exception as e:
        # דיווח מפורט על התקלה
        st.error(f"❌ העלאת התמונה '{file_obj.name}' נכשלה.")
        st.exception(e) 
        return ""

def drive_upload_bytes(svc, content, filename, folder_id, is_text=False):
    """מעלה תוכן (אודיו או טקסט) מהזיכרון - משמש לטאב 4"""
    try:
        from googleapiclient.http import MediaIoBaseUpload
        import io
        mime = 'text/plain' if is_text else 'audio/wav'
        if is_text and isinstance(content, str):
            content = content.encode('utf-8')
        
        media = MediaIoBaseUpload(io.BytesIO(content), mimetype=mime, resumable=True)
        file_metadata = {'name': filename, 'parents': [folder_id] if folder_id else []}
        
        f = svc.files().create(
            body=file_metadata, 
            media_body=media, 
            fields='id, webViewLink', 
            supportsAllDrives=True
        ).execute()
        
        return f.get('webViewLink')
    except Exception as e:
        # התראה קריטית לראיונות
        type_str = "הניתוח" if is_text else "הקלטת האודיו"
        st.error(f"❌ תקלה קריטית: {type_str} לא נשמר בדרייב!")
        st.exception(e)
        return "שגיאת העלאה"
        
# ==========================================
# --- 3. גוף הקוד הראשי (Main) ---
# ==========================================

# אתחול שירותים ונתונים
svc = get_drive_service()
full_df = load_full_dataset(svc)

# אתחול ה-Session State (רק אם הם לא קיימים)
if "it" not in st.session_state: 
    st.session_state.it = 0
if "last_selected_student" not in st.session_state: 
    st.session_state.last_selected_student = ""
if "show_success_bar" not in st.session_state: 
    st.session_state.show_success_bar = False
if "last_feedback" not in st.session_state: 
    st.session_state.last_feedback = ""
if "chat_history" not in st.session_state: 
    st.session_state.chat_history = []

# יצירת הטאבים בממשק
tab1, tab2, tab3, tab4 = st.tabs(["📝 הזנה ומשוב", "🔄 סנכרון", "📊 ניתוח", "🎙️ ראיון עומק"])

with tab1: 
    render_tab_entry(svc, full_df)
with tab2: 
    render_tab_sync(svc, full_df)
with tab3: 
    render_tab_analysis(svc)
with tab4: 
    render_tab_interview(svc, full_df)

# סיידבר - כפתורי בקרה
st.sidebar.markdown("---")
if st.sidebar.button("🔄 רענן נתונים"):
    st.cache_data.clear()
    st.rerun()

st.sidebar.markdown("---")
st.sidebar.write(f"מצב חיבור דרייב: {'✅' if svc else '❌'}")
st.sidebar.caption(f"גרסת מערכת: 54.0 | {date.today()}")

# וודא שאין כלום מתחת לשורה הזו!






