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

# --- 0. הגדרות ---
logging.basicConfig(level=logging.INFO)
DATA_FILE = "reflections.jsonl"
MASTER_FILENAME = "All_Observations_Master.xlsx"
CLASS_ROSTER = ["נתנאל", "רועי", "אסף", "עילאי", "טדי", "גאל", "אופק", "דניאל.ר", "אלי", "טיגרן", "פולינה.ק", "תלמיד אחר..."]
TAGS_OPTIONS = ["התעלמות מקווים נסתרים", "בלבול בין היטלים", "קושי ברוטציה מנטלית", "טעות בפרופורציות", "קושי במעבר בין היטלים", "שימוש בכלי מדידה", "סיבוב פיזי של המודל", "תיקון עצמי", "עבודה עצמאית שוטפת"]

st.set_page_config(page_title="מערכת תצפית - 45.0", layout="wide")

st.markdown("""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Heebo:wght@300;400;700&display=swap');
        html, body, .stApp { direction: rtl; text-align: right; font-family: 'Heebo', sans-serif !important; }
        [data-testid="stSlider"] { direction: ltr !important; }
        .stButton > button { width: 100%; font-weight: bold; border-radius: 12px; height: 3em; }
        .feedback-box { 
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px; 
            border-radius: 15px; 
            margin: 15px 0;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }
        .feedback-box h4 { margin-top: 0; color: #fff; }
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
        if not b64: return None
        json_str = base64.b64decode(b64).decode("utf-8")
        creds = Credentials.from_service_account_info(
            json.loads(json_str), 
            scopes=["https://www.googleapis.com/auth/drive"]
        )
        return build("drive", "v3", credentials=creds)
    except Exception as e:
        logging.error(f"Drive error: {e}")
        return None

@st.cache_data(ttl=300)
def load_full_dataset(_svc):
    df_drive = pd.DataFrame()
    if _svc:
        try:
            query = f"name = '{MASTER_FILENAME}' and trashed = false"
            res = _svc.files().list(
                q=query, 
                supportsAllDrives=True
            ).execute().get('files', [])
            
            if res:
                fh = io.BytesIO()
                downloader = MediaIoBaseDownload(fh, _svc.files().get_media(fileId=res[0]['id']))
                done = False
                while not done: _, done = downloader.next_chunk()
                fh.seek(0)
                df_drive = pd.read_excel(fh)
                possible = [c for c in df_drive.columns if "student" in c.lower()]
                if possible: df_drive.rename(columns={possible[0]: "student_name"}, inplace=True)
        except Exception as e: 
            logging.error(f"Drive load error: {e}")

    df_local = pd.DataFrame()
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                lines = [json.loads(l) for l in f if l.strip()]
                if lines: df_local = pd.DataFrame(lines)
        except: pass

    df = pd.concat([df_drive, df_local], ignore_index=True)
    if not df.empty and 'student_name' in df.columns:
        df = df.dropna(subset=['student_name'])
        df['name_clean'] = df['student_name'].apply(normalize_name)
    return df

def get_ai_response(prompt_type, context_data):
    """
    פונקציה מתקדמת לקבלת תשובות AI
    
    Args:
        prompt_type: 'chat', 'reflection', או 'analysis'
        context_data: dict עם המידע הרלוונטי
    """
    api_key = st.secrets.get("GOOGLE_API_KEY")
    if not api_key: 
        return "⚠️ מפתח API לא מוגדר"
    
    try:
        genai.configure(api_key=api_key, transport='rest')
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        # בחירת פרומפט לפי סוג
        if prompt_type == "chat":
            full_prompt = (
                f"אתה עוזר מחקר אקדמי. נתח את התצפיות של {context_data.get('name', 'הסטודנט')}:\n"
                f"{str(context_data.get('history', ''))[:5000]}\n\n"
                f"שאלה: {context_data.get('question', '')}\n"
                f"ענה בעברית מקצועית."
            )
        
        elif prompt_type == "reflection":
            # פרומפט מתקדם למנחה מחקר
            observation = context_data.get('challenge', '')
            tags = context_data.get('tags', [])
            student_name = context_data.get('student_name', '')
            
            full_prompt = f"""
אתה פרופ' דן רוזנברג, מנחה תזה בכיר בחינוך טכנולוגי ושרטוט הנדסי.
התמחותך: מחקר איכותני, תצפיות שיטתיות, וניתוח קוגניטיבי של תהליכי למידה.

הסטודנטית כתבה את התצפית הבאה על {student_name}:
"{observation}"

תגיות שסומנו: {', '.join(tags) if tags else 'לא צוינו'}

בצע ניתוח מחקרי מקצועי:

**1. הערכת איכות התצפית (ציון 1-5):**
- אובייקטיביות (עובדות vs. פרשנות)
- עשירות תיאורית (פרטים קונקרטיים)
- רלוונטיות מחקרית
- רמת השפה האקדמית

**2. נקודות חוזק:**
(מה עובד היטב בתצפית הזו?)

**3. נקודות לשיפור:**
(מה חסר? איפה יש פרשנות יתר? מה לא מספיק ספציפי?)

**4. נוסח משופר (2-3 שורות):**
כתוב נוסח מקצועי ואובייקטיבי המתאים לפרק ממצאים בעבודת מחקר.
השתמש במונחים: "התלמיד ביצע...", "נצפה...", "התבטא..." (ולא "נראה כאילו", "נחשב")

**5. המלצה מתודולוגית:**
איזה מידע נוסף כדאי לאסוף בתצפית הבאה?

ענה בעברית אקדמית, תמציתית וישירה.
"""
        
        elif prompt_type == "analysis":
            # ניתוח מגמות רוחב
            full_prompt = f"""
אתה מנחה מחקר מנוסה. נתח את המגמות בנתונים:
{str(context_data.get('history', ''))[:4000]}

שאלת מחקר: {context_data.get('question', 'זהה דפוסים')}

ספק:
1. ממצאים מרכזיים (3-4 נקודות)
2. דפוסים חוזרים
3. המלצות להמשך מחקר
"""
        
        else:
            full_prompt = "שאלה לא מזוהה"
        
        # שליחת הבקשה
        response = model.generate_content(full_prompt)
        
        if response and response.text:
            return response.text
        else:
            return "לא התקבלה תשובה מהמודל"
            
    except Exception as e:
        # Fallback למודל 2.0
        try:
            model_2 = genai.GenerativeModel('gemini-2.0-flash-exp')
            return model_2.generate_content(full_prompt).text
        except:
            return f"שגיאת AI: {str(e)[:100]}"

# --- 2. אתחול State ---
if "it" not in st.session_state: st.session_state.it = 0
if "chat_history" not in st.session_state: st.session_state.chat_history = []
if "student_context" not in st.session_state: st.session_state.student_context = ""
if "last_selected_student" not in st.session_state: st.session_state.last_selected_student = ""
if "last_feedback" not in st.session_state: st.session_state.last_feedback = ""
if "show_success_bar" not in st.session_state: st.session_state.show_success_bar = False

# --- 3. טעינת נתונים ---
svc = get_drive_service()
full_df = load_full_dataset(svc)

# --- 4. ממשק ---
st.title("🎓 מנחה מחקר חכם - גרסה 45.0")
tab1, tab2, tab3 = st.tabs(["📝 הזנה ומשוב", "🔄 סנכרון", "📊 ניתוח"])

with tab1:
    col_in, col_chat = st.columns([1.2, 1])
    
    with col_in:
        it = st.session_state.it
        student_name = st.selectbox("👤 בחר סטודנט", CLASS_ROSTER, key=f"sel_{it}")
        
        # טעינת הקשר עם אינדיקציה ויזואלית
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
            st.session_state.last_feedback = ""
            st.rerun()

        # הצגת סטטוס טעינה
        if st.session_state.show_success_bar:
            st.success(f"✅ נמצאה היסטוריה עבור {student_name}. הסוכן מעודכן.")
        else:
            st.info(f"ℹ️ {student_name}: אין תצפיות קודמות במערכת.")

        st.markdown("---")
        
        # טופס מלא עם כל הפיצ'רים המקוריים
        c1, c2 = st.columns(2)
        with c1:
            work_method = st.radio(
                "🛠️ סוג תרגול:", 
                ["🧊 בעזרת גוף מודפס", "🎨 ללא גוף (דמיון)"], 
                key=f"wm_{it}", 
                horizontal=True
            )
            ex_diff = st.select_slider(
                "📉 רמת קושי:", 
                options=["קל", "בינוני", "קשה"], 
                key=f"ed_{it}"
            )
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
        
        challenge = st.text_area(
            "🗣️ תצפית שדה (תאר מה ראית - פעולות, התנהגות, שרטוטים):", 
            height=150,
            key=f"ch_{it}",
            placeholder="דוגמה: התלמיד ביצע 3 ניסיונות לשרטט את ההיטל העליון. בניסיון הראשון התעלם מקו נסתר, לאחר מכן תיקן בעצמו תוך שימוש במסרגה..."
        )
        
        interpretation = st.text_area(
            "🧠 פרשנות מחקרית (אופציונלי):", 
            height=80,
            key=f"int_{it}",
            placeholder="הסבר מה התצפית מלמדת על תהליך החשיבה של התלמיד..."
        )

        # העלאת תמונות (חזרה!)
        up_files = st.file_uploader(
            "📷 צרף תמונות של שרטוטים/עבודות", 
            accept_multiple_files=True, 
            type=['png', 'jpg', 'jpeg'], 
            key=f"up_{it}",
            help="תמונות יועלו ל-Google Drive ויקושרו לתצפית"
        )

        # תיבת המשוב של המנחה
        if st.session_state.last_feedback:
            st.markdown(
                f'<div class="feedback-box">'
                f'<h4>💡 משוב מהמנחה האקדמי</h4>'
                f'{st.session_state.last_feedback}'
                f'</div>', 
                unsafe_allow_html=True
            )

        # כפתורים
        col_btns = st.columns(2)
        with col_btns[0]:
            if st.button("🔍 בקש משוב מהמנחה", use_container_width=True):
                if not challenge:
                    st.warning("⚠️ כתוב תחילה תצפית בתיבת הטקסט")
                else:
                    with st.spinner("המנחה האקדמי קורא ומנתח..."):
                        feedback = get_ai_response("reflection", {
                            "challenge": challenge,
                            "tags": tags,
                            "student_name": student_name
                        })
                        st.session_state.last_feedback = feedback
                        st.rerun()
        
        with col_btns[1]:
            if st.button("💾 שמור תצפית", type="primary", use_container_width=True):
                if not challenge:
                    st.error("⚠️ חובה להזין תיאור תצפית")
                else:
                    with st.spinner("מעלה תמונות ושומר..."):
                        # העלאת תמונות ל-Drive
                        links = []
                        GDRIVE_FOLDER_ID = st.secrets.get("GDRIVE_FOLDER_ID")
                        
                        if up_files and svc:
                            for f in up_files:
                                try:
                                    file_meta = {'name': f.name}
                                    if GDRIVE_FOLDER_ID:
                                        file_meta['parents'] = [GDRIVE_FOLDER_ID]
                                    
                                    media = MediaIoBaseUpload(
                                        io.BytesIO(f.getvalue()), 
                                        mimetype=f.type
                                    )
                                    res = svc.files().create(
                                        body=file_meta, 
                                        media_body=media, 
                                        fields='webViewLink', 
                                        supportsAllDrives=True
                                    ).execute()
                                    links.append(res.get('webViewLink'))
                                except Exception as e:
                                    st.warning(f"לא הצלחתי להעלות {f.name}: {e}")
                        
                        # שמירת התצפית המלאה
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
                        
                        st.session_state.last_feedback = ""
                        st.session_state.it += 1
                        st.success("✅ תצפית נשמרה בהצלחה!")
                        time.sleep(0.8)
                        st.rerun()

    with col_chat:
        st.subheader(f"🤖 יועץ: {student_name}")
        chat_cont = st.container(height=450)
        
        for q, a in st.session_state.chat_history:
            with chat_cont:
                st.chat_message("user").write(q)
                st.chat_message("assistant").write(a)
        
        u_q = st.chat_input("שאל על הסטודנט...")
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
        st.warning("⚠️ שירות Drive לא זמין")
    elif not os.path.exists(DATA_FILE):
        st.info("אין נתונים מקומיים לסנכרון")
    elif st.button("🚀 סנכרן הכל לדרייב"):
        try:
            with st.spinner("מסנכרן..."):
                with open(DATA_FILE, "r", encoding="utf-8") as f:
                    locals_ = [json.loads(line) for line in f if line.strip()]
                
                df_merged = pd.concat(
                    [full_df, pd.DataFrame(locals_)],
                    ignore_index=True
                ).drop_duplicates(subset=['student_name', 'timestamp'], keep='last')
                
                buf = io.BytesIO()
                with pd.ExcelWriter(buf, engine='openpyxl') as w:
                    df_merged.to_excel(w, index=False)
                buf.seek(0)
                
                query = f"name = '{MASTER_FILENAME}' and trashed = false"
                res = svc.files().list(q=query, supportsAllDrives=True).execute().get('files', [])
                
                media = MediaIoBaseUpload(buf, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                
                if res:
                    svc.files().update(fileId=res[0]['id'], media_body=media, supportsAllDrives=True).execute()
                else:
                    GDRIVE_FOLDER_ID = st.secrets.get("GDRIVE_FOLDER_ID")
                    body = {'name': MASTER_FILENAME}
                    if GDRIVE_FOLDER_ID:
                        body['parents'] = [GDRIVE_FOLDER_ID]
                    svc.files().create(body=body, media_body=media, supportsAllDrives=True).execute()
                
                os.remove(DATA_FILE)
                st.success(f"✅ סונכרנו {len(locals_)} רשומות!")
                st.cache_data.clear()
                time.sleep(1)
                st.rerun()
        except Exception as e:
            st.error(f"❌ שגיאה: {str(e)}")

with tab3:
    st.header("📊 ניתוח מחקרי")
    
    if full_df.empty:
        st.info("אין נתונים לניתוח. בצע סנכרון בטאב 2.")
    else:
        # בחירה בין ניתוח אישי לשבועי
        analysis_mode = st.radio(
            "בחר סוג ניתוח:",
            ["👤 ניתוח אישי", "📅 ניתוח שבועי"],
            horizontal=True
        )
        
        if analysis_mode == "👤 ניתוח אישי":
            # ניתוח אישי - כמו שהיה
            if 'student_name' in full_df.columns:
                all_students = sorted(full_df['student_name'].unique().tolist())
                selected_s = st.selectbox("👤 בחר סטודנט:", ["כולם"] + all_students)
                
                view_df = full_df if selected_s == "כולם" else full_df[full_df['student_name'] == selected_s]
                
                cols_to_show = ['date', 'student_name', 'work_method', 'challenge', 'interpretation', 'tags', 'cat_convert_rep', 'cat_proj_trans', 'cat_self_efficacy']
                actual_cols = [c for c in cols_to_show if c in view_df.columns]
                
                if actual_cols:
                    if 'date' in actual_cols:
                        st.dataframe(view_df[actual_cols].sort_values(by='date', ascending=False), use_container_width=True)
                    else:
                        st.dataframe(view_df[actual_cols], use_container_width=True)
                
                # ניתוח AI אישי
                st.markdown("---")
                if st.button("✨ הפק ניתוח מגמות אקדמי"):
                    with st.spinner("המנחה מנתח את כל התצפיות..."):
                        analysis = get_ai_response("analysis", {
                            "history": view_df.tail(15).to_string(),
                            "question": "זהה דפוסים חוזרים, התקדמות, ונקודות למעקב"
                        })
                        st.markdown(f'<div class="feedback-box"><h4>📊 ניתוח מחקרי</h4>{analysis}</div>', unsafe_allow_html=True)
        
        else:
            # ניתוח שבועי - הקוד המקורי שלך
            st.subheader("🧠 ניתוח תמות שבועי")
            
            # יצירת עמודת שבוע
            df_an = full_df.copy()
            if 'date' in df_an.columns:
                df_an['date'] = pd.to_datetime(df_an['date'], errors='coerce')
                df_an['week'] = df_an['date'].dt.strftime('%Y - שבוע %U')
                
                weeks = sorted(df_an['week'].dropna().unique(), reverse=True)
                if weeks:
                    sel_week = st.selectbox("בחר שבוע לניתוח:", weeks)
                    w_df = df_an[df_an['week'] == sel_week]
                    
                    # תצוגת הנתונים
                    st.write(f"**{len(w_df)} תצפיות בשבוע {sel_week}**")
                    st.dataframe(w_df[['student_name', 'challenge', 'tags', 'interpretation']].fillna(''), use_container_width=True)
                    
                    # כפתור ניתוח + שמירה
                    if st.button("✨ הפק ניתוח תמות ושמור לדרייב"):
                        with st.spinner("ג'ימיני מנתח תמות חוזרות..."):
                            # הכנת הטקסט לניתוח
                            txt = ""
                            for _, r in w_df.iterrows():
                                txt += f"סטודנט: {r.get('student_name','')} | תצפית: {r.get('challenge','')} | תובנה: {r.get('interpretation','')}\n---\n"
                            
                            try:
                                # קריאה ל-AI
                                genai.configure(api_key=st.secrets["GOOGLE_API_KEY"], transport='rest')
                                model = genai.GenerativeModel('gemini-1.5-flash')
                                
                                prompt = f"""
אתה מנחה מחקר איכותני. נתח את התצפיות מ{sel_week}:

{txt}

בצע ניתוח תמות (Thematic Analysis):
1. זהה 3-5 תמות מרכזיות החוזרות בתצפיות
2. לכל תמה - ספק דוגמאות מהשטח
3. הצע המלצות פדגוגיות
4. זהה סטודנטים הזקוקים למעקב מיוחד

ענה בעברית אקדמית בפורמט מובנה.
"""
                                
                                response = model.generate_content(prompt).text
                                
                                # הצגת התוצאה
                                st.markdown(f'<div class="feedback-box"><h4>📊 ניתוח תמות - {sel_week}</h4>{response}</div>', unsafe_allow_html=True)
                                
                                # שמירה לדרייב
                                if svc:
                                    f_name = f"ניתוח_תמות_{sel_week.replace(' ', '_')}.txt"
                                    media = MediaIoBaseUpload(
                                        io.BytesIO(response.encode('utf-8')), 
                                        mimetype='text/plain'
                                    )
                                    
                                    GDRIVE_FOLDER_ID = st.secrets.get("GDRIVE_FOLDER_ID")
                                    body = {'name': f_name}
                                    if GDRIVE_FOLDER_ID:
                                        body['parents'] = [GDRIVE_FOLDER_ID]
                                    
                                    svc.files().create(
                                        body=body, 
                                        media_body=media, 
                                        supportsAllDrives=True
                                    ).execute()
                                    
                                    st.success(f"✅ הניתוח נשמר בדרייב בשם: {f_name}")
                                else:
                                    st.warning("לא ניתן לשמור - שירות Drive לא זמין")
                                    
                            except Exception as e:
                                st.error(f"❌ שגיאה בניתוח: {str(e)[:200]}")
                else:
                    st.warning("אין נתוני תאריכים תקינים")
            else:
                st.error("חסרה עמודת 'date' בנתונים")

# --- Sidebar ---
st.sidebar.write("**מצב חיבור:**")
st.sidebar.write("🔗 Drive:", "✅ מחובר" if svc else "❌ לא מחובר")
if not full_df.empty:
    st.sidebar.metric("תצפיות במערכת", len(full_df))
    if 'student_name' in full_df.columns:
        st.sidebar.metric("סטודנטים", full_df['student_name'].nunique())
