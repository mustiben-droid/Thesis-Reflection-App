import json, base64, os, io, logging, pandas as pd, streamlit as st
from google import generativeai as genai
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload
from datetime import date, datetime

# ==========================================
# --- 0. הגדרות מערכת ועיצוב ---
# ==========================================
DATA_FILE = "reflections.jsonl"
MASTER_FILENAME = "All_Observations_Master.xlsx"
GDRIVE_FOLDER_ID = st.secrets.get("GDRIVE_FOLDER_ID")
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
    # משאיר רק אותיות ומספרים (מוחק נקודות, רווחים, מקפים וכו')
    return re.sub(r'[^א-תa-zA-Z0-9]', '', name).strip()

@st.cache_resource
def get_drive_service():
    try:
        b64 = st.secrets.get("GDRIVE_SERVICE_ACCOUNT_B64")
        js = base64.b64decode("".join(b64.split())).decode("utf-8")
        creds = Credentials.from_service_account_info(json.loads(js), scopes=["https://www.googleapis.com/auth/drive"])
        return build("drive", "v3", credentials=creds)
    except: return None

@st.cache_data(ttl=30)
def load_full_dataset(_svc):
    df_drive = pd.DataFrame()
    file_id = st.secrets.get("MASTER_FILE_ID")
    
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
        except Exception:
            pass

    df_local = pd.DataFrame()
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                df_local = pd.DataFrame([json.loads(l) for l in f if l.strip()])
        except Exception:
            pass

    # שים לב ליישור של השורה הזו - היא צריכה להיות בקו אחד עם ה-if-ים למעלה
    df = pd.concat([df_drive, df_local], ignore_index=True)
    
    if not df.empty and 'student_name' in df.columns:
        df['student_name'] = df['student_name'].astype(str).str.strip()
        df['name_clean'] = df['student_name'].apply(normalize_name)
    
    return df
    
def call_gemini(prompt):
    try:
        api_key = st.secrets.get("GOOGLE_API_KEY")
        if not api_key: 
            return "שגיאה: חסר API Key ב-Secrets"
            
        # אתחול נקי ללא transport='rest'
        genai.configure(api_key=api_key)
        
        # שימוש בתחביר החדש והמחמיר ביותר
        model = genai.GenerativeModel(model_name="gemini-2.0-flash")
        
        # שליחת הבקשה
        response = model.generate_content(prompt)
        
        if response.text:
            return response.text
        else:
            return "התקבלה תשובה ריקה מהמודל."
            
    except Exception as e:
        # אם יש שגיאה, ננסה "נסיגת בטיחות" ל-1.5 פלאש בתחביר החדש
        try:
            model = genai.GenerativeModel(model_name="gemini-1.5-flash")
            response = model.generate_content(prompt)
            return response.text
        except Exception as e2:
            return f"שגיאה סופית בחיבור ל-AI: {str(e2)}"

# ==========================================
# --- 2. פונקציות ממשק משתמש (Tabs) ---
# ==========================================

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

        st.markdown("### 📊 מדדים כמותיים (1-5)")
        m1, m2 = st.columns(2)
        with m1:
            s1 = st.slider("המרת ייצוגים", 1, 5, 3, key=f"s1_{it}")
            s2 = st.slider("מעבר בין היטלים", 1, 5, 3, key=f"s2_{it}")
        with m2:
            s3 = st.slider("שימוש במודל 3D", 1, 5, 3, key=f"s3_{it}")
            s_diff = st.slider("📉 רמת קושי התרגיל", 1, 5, 3, key=f"sd_{it}")
            s4 = st.slider("📏 פרופורציות ומימדים", 1, 5, 3, key=f"s4_{it}")

      # 1. תגיות אבחון
        tags = st.multiselect("🏷️ תגיות אבחון", TAGS_OPTIONS, key=f"t_{it}")
        
        # 2. תצפית שדה
        ch_text = st.text_area("🗣️ תצפית שדה (Challenge):", height=150, key="field_obs_input")
        
        # 3. תובנה/פרשנות - כאן שינינו ל-Key קבוע כדי שה-AI יזהה את הטקסט
        ins = st.text_area("🧠 תובנה/פרשנות (Insight):", height=100, key="insight_input")
        
        up_files = st.file_uploader("📷 צרף תמונות", accept_multiple_files=True, type=['png', 'jpg', 'jpeg'], key=f"up_{it}")

        # כפתורי פעולה
        c_btns = st.columns(2)
        with c_btns[0]:
            if st.button("🔍 בקש רפלקציה (AI)", key=f"ai_btn_{it}"):
                # שינינו את המקור ל-insight_input
                raw_insight = st.session_state.get("insight_input", "")
                
                if raw_insight.strip():
                    with st.spinner("היועץ מנתח את התובנות שלך..."):
                        # הנחיה ללשון זכר וניתוח התובנה
                        prompt = f"פנה אלי בלשון זכר. נתח את התובנה המחקרית שלי לגבי הסטודנט {student_name}: {raw_insight}"
                        res = call_gemini(prompt)
                        st.session_state.last_feedback = res
                        st.rerun()
                else:
                    st.warning("תיבת התובנות (Insight) ריקה. כתוב שם משהו כדי שאוכל לנתח.")

       with c_btns[1]:
            # שימוש ב-key ייחודי מונע כפילויות לחיצה
            save_key = f"save_btn_{st.session_state.it}"
            
            if st.button("💾 שמור תצפית", type="primary", key=save_key):
                # משיכה מהזיכרון של כל מה שכתבת
                final_ch = st.session_state.get("field_obs_input", "").strip()
                final_ins = st.session_state.get("insight_input", "").strip()
                
                if final_ch or final_ins:
                    with st.spinner("שומר נתונים..."):
                        # 1. הכנת הנתונים למילון השמירה
                        entry = {
                            "date": date.today().isoformat(),
                            "student_name": student_name,
                            "duration_min": duration,
                            "drawings_count": drawings,
                            "work_method": work_method,
                            "challenge": final_ch,
                            "insight": final_ins,
                            "tags": tags,
                            "timestamp": datetime.now().isoformat()
                        }
                        
                        # 2. שמירה פיזית לקובץ (שמסתנכרן לדרייב)
                        with open(DATA_FILE, "a", encoding="utf-8") as f:
                            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                        
                        # 3. חגיגת שמירה - הבלונים חוזרים!
                        st.balloons()
                        st.success(f"✅ התצפית על {student_name} נשמרה בהצלחה.")

                        # 4. ניקוי הזיכרון (השיטה הבטוחה למניעת קריסות)
                        st.session_state.pop("field_obs_input", None)
                        st.session_state.pop("insight_input", None)
                        st.session_state.last_feedback = ""
                        
                        # 5. קידום המונה - מייצר "טופס חדש" לסטודנט הבא
                        st.session_state.it += 1
                        
                        # 6. השהיה קצרה לראות את הבלונים
                        import time
                        time.sleep(1.8)
                        
                        # 7. רענון האפליקציה למצב נקי
                        st.rerun()
                else:
                    st.error("לא ניתן לשמור תצפית ריקה. אנא כתוב משהו בתיבות.")
        # הצגת המשוב - חייב להיות מיושר בדיוק כמו c_btns
        if st.session_state.last_feedback:
            st.markdown("---")
            st.markdown(f'<div class="feedback-box"><b>💡 משוב יועץ AI:</b><br>{st.session_state.last_feedback}</div>', unsafe_allow_html=True)
        # --- חשוב: הצגת המשוב על המסך ---
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
        st.info("אין עדיין מספיק נתונים לניתוח. בצעי סנכרון בטאב 2.")
        return

    # עיבוד תאריכים לשבועות
    df_v['date'] = pd.to_datetime(df_v['date'], errors='coerce')
    df_v['week'] = df_v['date'].dt.strftime('%Y - שבוע %U')
    
    # --- חלק א: מעקב התקדמות אישי (מעולה לתזה!) ---
    st.subheader("📈 מעקב התקדמות אישי")
    all_students = sorted(df_v['student_name'].dropna().unique())
    sel_student = st.selectbox("בחר תלמיד למעקב ויזואלי:", all_students)
    
    student_data = df_v[df_v['student_name'] == sel_student].sort_values('date')
    
    if len(student_data) >= 1:
        # הגדרת המדדים שאנחנו רוצים להציג בגרף
        metrics = {
            'cat_convert_rep': 'המרת ייצוגים',
            'cat_dims_props': 'פרופורציות',
            'cat_proj_trans': 'מעבר בין היטלים',
            'cat_3d_support': 'שימוש במודל 3D'
        }
        
        # הכנת הנתונים לגרף
        plot_df = student_data[['date'] + list(metrics.keys())].copy()
        plot_df = plot_df.rename(columns=metrics).set_index('date')
        
        # הצגת הגרף
        st.line_chart(plot_df)
        st.caption("מגמת שינוי במדדים הכמותיים לאורך זמן (1-5)")
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
        st.dataframe(w_df[['student_name', 'challenge', 'tags']], use_container_width=True)
    
    with col_ai:
        if st.button("✨ הפק ניתוח שבועי ושמור לדרייב"):
            with st.spinner("ג'ימיני מנתח את כל התצפיות של השבוע..."):
                # איסוף כל הטקסט של השבוע
                txt = "".join([f"תלמיד: {r['student_name']} | קושי: {r.get('challenge','')} | תובנה: {r.get('insight','')}\n" for _, r in w_df.iterrows()])
                
                response = call_gemini(f"בצע ניתוח תמות (Thematic Analysis) אקדמי על התצפיות הבאות עבור שבוע {sel_w}:\n\n{txt}")
                
                st.markdown(f'<div class="feedback-box"><b>📊 ממצאים לשבוע {sel_w}:</b><br>{response}</div>', unsafe_allow_html=True)
                
                # שמירה אוטומטית לדרייב
                try:
                    f_name = f"ניתוח_תמות_{sel_w.replace(' ', '_')}.txt"
                    media = MediaIoBaseUpload(io.BytesIO(response.encode('utf-8')), mimetype='text/plain')
                    svc.files().create(
                        body={'name': f_name, 'parents': [GDRIVE_FOLDER_ID] if GDRIVE_FOLDER_ID else []},
                        media_body=media,
                        supportsAllDrives=True
                    ).execute()
                    st.success(f"הניתוח נשמר בדרייב כקובץ: {f_name}")
                except Exception as e:
                    st.error(f"הניתוח הופק אך נכשלה השמירה לדרייב: {e}")

# ==========================================
# --- 3. גוף הקוד הראשי (Main) ---
# ==========================================

svc = get_drive_service()
full_df = load_full_dataset(svc)

if "it" not in st.session_state: st.session_state.it = 0
if "last_selected_student" not in st.session_state: st.session_state.last_selected_student = ""
if "show_success_bar" not in st.session_state: st.session_state.show_success_bar = False
if "last_feedback" not in st.session_state: st.session_state.last_feedback = ""
if "chat_history" not in st.session_state: st.session_state.chat_history = []

tab1, tab2, tab3 = st.tabs(["📝 הזנה ומשוב", "🔄 סנכרון", "📊 ניתוח"])

with tab1: render_tab_entry(svc, full_df)
with tab2: render_tab_sync(svc, full_df)
with tab3: render_tab_analysis(svc)

st.sidebar.button("🔄 רענן נתונים", on_click=lambda: st.cache_data.clear())
st.sidebar.write(f"מצב חיבור דרייב: {'✅' if svc else '❌'}")






















