import json, base64, os, io, time, pandas as pd, streamlit as st
import google.generativeai as genai
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload
from datetime import date, datetime

# --- 0. הגדרות ועיצוב ---
DATA_FILE = "reflections.jsonl"
MASTER_FILENAME = "All_Observations_Master.xlsx"
CLASS_ROSTER = ["נתנאל", "רועי", "אסף", "עילאי", "טדי", "גאל", "אופק", "דניאל.ר", "אלי", "טיגרן", "פולינה.ק", "תלמיד אחר..."]
TAGS_OPTIONS = ["התעלמות מקווים נסתרים", "בלבול בין היטלים", "קושי ברוטציה מנטלית", "טעות בפרופורציות", "קושי במעבר בין היטלים", "שימוש בכלי מדידה", "סיבוב פיזי של המודל", "תיקון עצמי", "עבודה עצמאית שוטפת"]
GDRIVE_FOLDER_ID = st.secrets.get("GDRIVE_FOLDER_ID")

st.set_page_config(page_title="מערכת תצפית מחקרית", layout="wide")

st.markdown("""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Heebo:wght@300;400;700&display=swap');
        html, body, .stApp { direction: rtl; text-align: right; font-family: 'Heebo', sans-serif !important; }
        [data-testid="stSlider"] { direction: ltr !important; }
        .stButton > button { width: 100%; font-weight: bold; border-radius: 12px; background-color: #28a745; color: white; height: 3em; }
    </style>
""", unsafe_allow_html=True)

# --- 1. מודול טעינה ומיפוי נתונים ---
def normalize_name(name):
    if not isinstance(name, str): return ""
    return name.replace(" ", "").replace(".", "").replace("־", "").replace("-", "").strip()

def map_research_cols(df):
    if df is None or df.empty: return pd.DataFrame()
    df.columns = [str(c).strip() for c in df.columns]
    mapping = {
        'cat_convert_rep': ['cat_convert_rep', 'score_conv'],
        'cat_proportions': ['cat_proportions', 'score_prop'],
        'cat_model_usage': ['cat_model_usage', 'score_model'],
        'cat_self_efficacy': ['cat_self_efficacy', 'score_efficacy'],
        'cat_model_difficulty': ['cat_model_difficulty', 'difficulty_model']
    }
    for target, sources in mapping.items():
        for s in sources:
            if s in df.columns:
                if target not in df.columns: df[target] = df[s]
                else: df[target] = df[target].fillna(df[s])
    if 'student_name' not in df.columns:
        p = [c for c in df.columns if "student" in c.lower() or "name" in c.lower()]
        if p: df.rename(columns={p[0]: 'student_name'}, inplace=True)
    return df

@st.cache_resource
def get_drive_service():
    try:
        b64 = st.secrets.get("GDRIVE_SERVICE_ACCOUNT_B64")
        js = base64.b64decode(b64).decode("utf-8")
        creds = Credentials.from_service_account_info(json.loads(js), scopes=["https://www.googleapis.com/auth/drive"])
        return build("drive", "v3", credentials=creds)
    except: return None

def load_full_dataset(svc):
    all_dfs = []
    if svc:
        try:
            res = svc.files().list(q=f"name = '{MASTER_FILENAME}'", supportsAllDrives=True, includeItemsFromAllDrives=True).execute().get('files', [])
            if res:
                fh = io.BytesIO()
                downloader = MediaIoBaseDownload(fh, svc.files().get_media(fileId=res[0]['id']))
                done = False
                while not done: _, done = downloader.next_chunk()
                fh.seek(0)
                all_dfs.append(map_research_cols(pd.read_excel(fh)))
        except: pass
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                all_dfs.append(map_research_cols(pd.DataFrame([json.loads(l) for l in f if l.strip()])))
        except: pass
    if not all_dfs: return pd.DataFrame()
    df = pd.concat(all_dfs, ignore_index=True, sort=False)
    if 'student_name' in df.columns:
        df['name_clean'] = df['student_name'].apply(normalize_name)
    return df

# --- 2. ניהול מצב (Session State) ---
if "it" not in st.session_state: st.session_state.it = 0
if "chat_history" not in st.session_state: st.session_state.chat_history = []
if "student_context" not in st.session_state: st.session_state.student_context = ""
if "last_selected_student" not in st.session_state: st.session_state.last_selected_student = ""

svc = get_drive_service()
full_df = load_full_dataset(svc)

tab1, tab2, tab3 = st.tabs(["📝 הזנה וצ'אט", "🔄 סנכרון", "📊 ניתוח מחקרי"])

# --- Tab 1: הזנה וצ'אט ---
with tab1:
    col_in, col_chat = st.columns([1.2, 1])
    with col_in:
        it = st.session_state.it
        name = st.selectbox("👤 בחר סטודנט", CLASS_ROSTER, key=f"sel_{it}")
        
        if name != st.session_state.last_selected_student:
            target = normalize_name(name)
            match = full_df[full_df['name_clean'] == target] if not full_df.empty else pd.DataFrame()
            st.session_state.student_context = match.tail(15).to_string() if not match.empty else ""
            st.session_state.last_selected_student = name
            st.session_state.chat_history = []
            st.rerun()

        if st.session_state.student_context:
            st.success(f"✅ נמצאה היסטוריה עבור {name}. היועץ מעודכן.")

        c1, c2 = st.columns(2)
        with c1:
            meth = st.radio("🛠️ תרגול:", ["🧊 גוף מודפס", "🎨 דמיון"], key=f"wm_{it}")
            diff_ex = st.select_slider("📉 קושי:", ["קל", "בינוני", "קשה"], key=f"ed_{it}")
            img_files = st.file_uploader("📸 העלאת תמונות", accept_multiple_files=True, type=['png', 'jpg', 'jpeg'], key=f"img_{it}")
        with c2:
            s1 = st.slider("המרת ייצוגים", 1, 5, 3, key=f"s1_{it}")
            s2 = st.slider("פרופורציות", 1, 5, 3, key=f"s2_{it}")
            s3 = st.slider("שימוש במודל", 1, 5, 3, key=f"s3_{it}")
            s4 = st.slider("מסוגלות עצמית", 1, 5, 3, key=f"s4_{it}")
            s5 = st.slider("רמת קושי המודל", 1, 5, 3, key=f"s5_{it}")

        tags = st.multiselect("🏷️ תגיות אבחון", TAGS_OPTIONS, key=f"t_{it}")
        ch = st.text_area("🗣️ תיאור התצפית (Challenge)", key=f"ch_{it}")
        interp = st.text_area("🧠 פרשנות מחקרית (Interpretation)", key=f"int_{it}")

        if st.button("💾 שמור תצפית"):
            if ch:
                links = []
                if img_files and svc:
                    for f in img_files:
                        media = MediaIoBaseUpload(io.BytesIO(f.getvalue()), mimetype=f.type)
                        res = svc.files().create(body={'name': f.name, 'parents': [GDRIVE_FOLDER_ID] if GDRIVE_FOLDER_ID else []}, media_body=media, fields='webViewLink', supportsAllDrives=True).execute()
                        links.append(res.get('webViewLink'))
                entry = {"date": str(date.today()), "student_name": name, "work_method": meth, "exercise_difficulty": diff_ex, "cat_convert_rep": s1, "cat_proportions": s2, "cat_model_usage": s3, "cat_self_efficacy": s4, "cat_model_difficulty": s5, "challenge": ch, "interpretation": interp, "tags": tags, "file_links": links, "timestamp": datetime.now().isoformat()}
                with open(DATA_FILE, "a", encoding="utf-8") as f: f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                st.session_state.it += 1; st.rerun()

    with col_chat:
        st.subheader(f"🤖 יועץ מחקר: {name}")
        chat_cont = st.container(height=450)
        for q, a in st.session_state.chat_history:
            chat_cont.chat_message("user").write(q); chat_cont.chat_message("assistant").write(a)
        if p := st.chat_input("שאל את היועץ..."):
            genai.configure(api_key=st.secrets["GOOGLE_API_KEY"], transport='rest')
            model = genai.GenerativeModel('gemini-1.5-flash')
            prompt = f"אתה עוזר מחקר אקדמי. נתח את הסטודנט {name}. היסטוריה: {st.session_state.student_context}. שאלה: {p}"
            resp = model.generate_content(prompt).text
            st.session_state.chat_history.append((p, resp)); st.rerun()

# --- Tab 2: סנכרון נתונים (תיקון חיבור לדרייב) ---
with tab2:
    st.header("🔄 סנכרון מאגר הנתונים")
    st.write("פעולה זו מאחדת את התצפיות החדשות עם קובץ האקסל המרכזי ב-Google Drive.")

    # שימוש בחיבור הקיים שכבר הוגדר בתחילת הקוד
    # ודאי שבתחילת הקובץ מופיע: svc = get_drive_service()
    
    if st.button("🚀 סנכרן נתונים עכשיו"):
        if svc is None:
            st.error("❌ לא נמצא חיבור תקין ל-Google Drive. בדקי את ה-Secrets ב-Streamlit.")
            st.info("ודאי שקיים Secret בשם GDRIVE_SERVICE_ACCOUNT_B64 או GOOGLE_SERVICE_ACCOUNT.")
            st.stop()

        if not os.path.exists(DATA_FILE):
            st.warning("אין נתונים חדשים לסנכרון (הקובץ המקומי ריק).")
        else:
            with st.spinner("מבצע איחוד נתונים והעלאה לדרייב..."):
                try:
                    # 1. קריאת הנתונים המקומיים החדשים
                    with open(DATA_FILE, "r", encoding="utf-8") as f:
                        new_entries = [json.loads(line) for line in f if line.strip()]
                    
                    new_df = pd.DataFrame(new_entries)

                    # 2. איחוד עם הדאטה הקיים (full_df נטען בראש הקובץ)
                    if not full_df.empty:
                        updated_df = pd.concat([full_df, new_df], ignore_index=True)
                    else:
                        updated_df = new_df
                    
                    # הסרת כפילויות לפי שם סטודנט וחותמת זמן
                    updated_df = updated_df.drop_duplicates(subset=['student_name', 'timestamp'], keep='last')

                    # 3. יצירת קובץ אקסל בזיכרון
                    buf = io.BytesIO()
                    with pd.ExcelWriter(buf, engine='openpyxl') as w:
                        updated_df.to_excel(w, index=False)
                    buf.seek(0)

                    # 4. עדכון/יצירה ב-Google Drive
                    # חיפוש הקובץ הקיים
                    res = svc.files().list(
                        q=f"name = '{MASTER_FILENAME}'",
                        supportsAllDrives=True,
                        includeItemsFromAllDrives=True
                    ).execute().get('files', [])

                    media = MediaIoBaseUpload(
                        buf, 
                        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        resumable=True
                    )

                    if res:
                        # עדכון קובץ קיים
                        svc.files().update(
                            fileId=res[0]['id'],
                            media_body=media,
                            supportsAllDrives=True
                        ).execute()
                    else:
                        # יצירת קובץ חדש
                        file_metadata = {
                            'name': MASTER_FILENAME,
                            'parents': [GDRIVE_FOLDER_ID] if GDRIVE_FOLDER_ID else []
                        }
                        svc.files().create(
                            body=file_metadata,
                            media_body=media,
                            supportsAllDrives=True
                        ).execute()

                    # 5. ניקוי וסיום
                    os.remove(DATA_FILE)
                    st.success("✅ הסנכרון הושלם בהצלחה! הקובץ בדרייב מעודכן.")
                    time.sleep(1)
                    st.rerun()
                    
                except Exception as e:
                    st.error(f"❌ תקלה במהלך הסנכרון: {e}")

# --- Tab 3: ניתוח מחקרי איכותני שבועי (גרסה סופית ומתוקנת) ---

if full_df.empty:
    st.info("אין נתונים לניתוח. וודא שביצעת סנכרון בטאב 2.")
else:
    st.header("🧠 ניתוח מחקר איכותני - רוחב כיתתי")

    # 1. הכנת הדאטה ומיפוי עמודות
    df_an = full_df.copy()
    actual_columns = df_an.columns.tolist()

    target_cols = {
        'date': 'date' if 'date' in actual_columns else None,
        'student_name': 'student_name' if 'student_name' in actual_columns else None,
        'challenge': 'challenge' if 'challenge' in actual_columns else None,
        'interpretation': 'insight' if 'insight' in actual_columns else None
    }

    if not target_cols['interpretation']:
        st.error("❌ לא נמצאה עמודת Insight באקסל. הניתוח לא יכול להמשיך.")
    else:
        # בניית דאטה-פריים מעובד
        final_df = pd.DataFrame()
        for key, original_name in target_cols.items():
            if original_name:
                final_df[key] = df_an[original_name]

        final_df['date'] = pd.to_datetime(final_df['date'], errors='coerce')
        final_df = final_df.dropna(subset=['date'])
        final_df['week'] = final_df['date'].dt.strftime('%Y - שבוע %U')

        # 2. בחירת שבוע לניתוח
        weeks = sorted(final_df['week'].unique(), reverse=True)
        sel_week = st.selectbox("בחר שבוע לניתוח תמות:", weeks)

        w_df = final_df[final_df['week'] == sel_week]

        if w_df.empty:
            st.warning("לא נמצאו תצפיות בשבוע שנבחר.")
        else:
            st.subheader(f"📋 תצפיות שנאספו בשבוע זה ({len(w_df)} שורות)")
            st.dataframe(w_df[['student_name', 'challenge', 'interpretation']])

            # 3. כפתור ג'ימיני לניתוח ושמירה
            if st.button(f"✨ הפק ניתוח איכותני כולל לשבוע זה (שמור לדרייב)"):
                with st.spinner("ג'ימיני מנתח תמות מכלל התלמידים..."):

                    # ריכוז כל התצפיות לטקסט אחד
                    research_context = ""
                    for _, row in w_df.iterrows():
                        research_context += f"סטודנט: {row['student_name']}\n"
                        research_context += f"תצפית (Challenge): {row['challenge']}\n"
                        research_context += f"פרשנות (Insight): {row['interpretation']}\n"
                        research_context += "--- \n"

                    # פרומפט מחקרי
                    prompt = f"""
אתה חוקר אקדמי בכיר. בצע ניתוח תמטי (Thematic Analysis) על נתוני שבוע {sel_week}.
זהה קשרים בין התצפיות לבין התובנות (Insights) שכתבה החוקרת.
חלץ תמות מרכזיות לגבי הקשיים הקוגניטיביים של הכיתה ונסח פסקה אקדמית לממצאים.

הנתונים לניתוח:
{research_context}
"""

                    try:
                        # הגדרה תקינה של Google AI SDK
                        from google import generativeai as genai
                        genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])

                        # מודל חדש ויציב – gemini‑2.0‑flash
                        model = genai.GenerativeModel(model_name="gemini-2.0-flash")

                        response = model.generate_content(prompt)
                        res = response.text

                        st.markdown("---")
                        st.markdown("### 📝 תוצאות הניתוח המחקרי:")
                        st.info(res)

                        # שמירה לדרייב
                        if svc:
                            f_name = f"ניתוח_איכותני_כיתתי_{sel_week.replace(' ', '_')}.txt"
                            meta = {
                                'name': f_name,
                                'parents': [GDRIVE_FOLDER_ID] if GDRIVE_FOLDER_ID else []
                            }
                            media = MediaIoBaseUpload(
                                io.BytesIO(res.encode('utf-8')),
                                mimetype='text/plain'
                            )
                            svc.files().create(
                                body=meta,
                                media_body=media,
                                supportsAllDrives=True
                            ).execute()

                            st.success(f"✅ הניתוח נשמר בדרייב בשם: {f_name}")

                    except Exception as e:
                        st.error(f"שגיאה בהפקת הניתוח: {str(e)}")

# --- סוף הקוד ---












