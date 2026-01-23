import json
import base64
import os
import io
import time
import pandas as pd
import streamlit as st
import google.generativeai as genai
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload
from datetime import date, datetime

# --- 0. הגדרות ועיצוב ---
DATA_FILE = "reflections.jsonl"
MASTER_FILENAME = "All_Observations_Master.xlsx"
GDRIVE_FOLDER_ID = st.secrets.get("GDRIVE_FOLDER_ID")
CLASS_ROSTER = ["נתנאל", "רועי", "אסף", "עילאי", "טדי", "גאל", "אופק", "דניאל.ר", "אלי", "טיגרן", "פולינה.ק", "תלמיד אחר..."]
TAGS_OPTIONS = ["התעלמות מקווים נסתרים", "בלבול בין היטלים", "קושי ברוטציה מנטלית", "טעות בפרופורציות", "קושי במעבר בין היטלים", "שימוש בכלי מדידה", "סיבוב פיזי של המודל", "תיקון עצמי", "עבודה עצמאית שוטפת"]

st.set_page_config(page_title="מערכת תצפית אקדמית - 53.0", layout="wide")

st.markdown("""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Heebo:wght@300;400;700&display=swap');
        html, body, .stApp { direction: rtl; text-align: right; font-family: 'Heebo', sans-serif !important; }
        [data-testid="stSlider"] { direction: ltr !important; }
        .stButton > button { width: 100%; font-weight: bold; border-radius: 12px; background-color: #28a745; color: white; height: 3em; }
        .feedback-box { background-color: #f8f9fa; padding: 15px; border-radius: 10px; border: 1px solid #dee2e6; margin-top: 10px; }
    </style>
""", unsafe_allow_html=True)

# --- 1. מודול נתונים (טעינה מהירה) ---
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
            res = svc.files().list(q=f"name = '{MASTER_FILENAME}' and trashed = false", supportsAllDrives=True, includeItemsFromAllDrives=True).execute().get('files', [])
            if res:
                fh = io.BytesIO()
                downloader = MediaIoBaseDownload(fh, svc.files().get_media(fileId=res[0]['id']))
                done = False
                while not done: _, done = downloader.next_chunk()
                fh.seek(0)
                df_drive = pd.read_excel(fh)
                mapping = {'score_conv': 'cat_convert_rep', 'score_proj': 'cat_proj_trans', 'score_model': 'cat_3d_support', 'score_efficacy': 'cat_self_efficacy'}
                df_drive = df_drive.rename(columns=mapping)
        except: pass
    
    df_local = pd.DataFrame()
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                df_local = pd.DataFrame([json.loads(l) for l in f if l.strip()])
        except: pass
    
    df = pd.concat([df_drive, df_local], ignore_index=True)
    if not df.empty and 'student_name' in df.columns:
        df['name_clean'] = df['student_name'].apply(lambda x: str(x).replace(" ", "").replace(".", "").strip())
    return df

def get_ai_response(prompt_type, context):
    api_key = st.secrets.get("GOOGLE_API_KEY")
    if not api_key: return "⚠️ מפתח API חסר"
    
    # אופטימיזציה: מנסים את המודל המהיר ביותר עם REST
    genai.configure(api_key=api_key, transport='rest')
    model = genai.GenerativeModel('gemini-1.5-flash')
    
    hist = str(context.get('history', ""))[:4000]
    if prompt_type == "chat":
        p = f"אתה עוזר מחקר. נתח את {context['name']} לפי התצפיות:\n{hist}\nשאלה: {context['question']}"
    else:
        p = f"סכם תובנות מחקריות (כמותי ואיכותני) מהיום הבא:\n{hist}"

    try:
        return model.generate_content(p).text
    except Exception as e:
        return f"שגיאת AI: {str(e)[:50]}"

# --- 2. ממשק המערכת ---
if "it" not in st.session_state: st.session_state.it = 0
if "chat_history" not in st.session_state: st.session_state.chat_history = []
if "ai_analysis_result" not in st.session_state: st.session_state.ai_analysis_result = ""

svc = get_drive_service()
full_df = load_full_dataset(svc)

tab1, tab2, tab3 = st.tabs(["📝 הזנה ומשוב", "🔄 סנכרון", "📊 ניתוח ותובנות"])

# --- Tab 1: הזנה מלאה ---
with tab1:
    col_in, col_chat = st.columns([1.2, 1])
    with col_in:
        it = st.session_state.it
        student_name = st.selectbox("👤 בחר סטודנט", CLASS_ROSTER, key=f"sel_{it}")
        
        st.markdown("---")
        c1, c2 = st.columns(2)
        with c1:
            work_method = st.radio("🛠️ סוג תרגול:", ["🧊 בעזרת גוף מודפס", "🎨 ללא גוף (דמיון)"], key=f"wm_{it}")
            ex_diff = st.select_slider("📉 רמת קושי:", options=["קל", "בינוני", "קשה"], key=f"ed_{it}")
        with c2:
            drw_cnt = st.number_input("כמות שרטוטים", min_value=0, key=f"dc_{it}")
            dur_min = st.number_input("זמן עבודה (דק')", min_value=0, key=f"dm_{it}")

        st.markdown("### 📊 מדדים (1-5)")
        m1, m2 = st.columns(2)
        with m1:
            s1 = st.slider("המרת ייצוגים", 1, 5, 3, key=f"s1_{it}")
            s2 = st.slider("מעבר בין היטלים", 1, 5, 3, key=f"s2_{it}")
        with m2:
            s3 = st.slider("שימוש במודל", 1, 5, 3, key=f"s3_{it}")
            s4 = st.slider("מסוגלות עצמית", 1, 5, 3, key=f"s4_{it}")

        challenge = st.text_area("🗣️ תיאור התצפית (חובה)", key=f"ch_{it}")
        interpretation = st.text_area("🧠 פרשנות מחקרית", key=f"int_{it}")

        if st.button("💾 שמור תצפית"):
            if not challenge: st.error("אנא מלא תיאור תצפית.")
            else:
                entry = {
                    "date": date.today().isoformat(), "student_name": student_name, "work_method": work_method,
                    "exercise_difficulty": ex_diff, "drawings_count": int(drw_cnt), "duration_min": int(dur_min),
                    "cat_convert_rep": int(s1), "cat_proj_trans": int(s2), "cat_3d_support": int(s3), 
                    "cat_self_efficacy": int(s4), "challenge": challenge, "interpretation": interpretation, "timestamp": datetime.now().isoformat()
                }
                with open(DATA_FILE, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                st.success("נשמר בהצלחה!")
                time.sleep(1); st.session_state.it += 1; st.rerun()

    with col_chat:
        st.subheader(f"🤖 צ'אט: {student_name}")
        chat_cont = st.container(height=400)
        for q, a in st.session_state.chat_history:
            with chat_cont: st.chat_message("user").write(q); st.chat_message("assistant").write(a)
        u_q = st.chat_input("שאל על הסטודנט...")
        if u_q:
            match = full_df[full_df['name_clean'] == student_name.replace(" ","").replace(".","")] if not full_df.empty else pd.DataFrame()
            ans = get_ai_response("chat", {"name": student_name, "history": match.tail(10).to_string(), "question": u_q})
            st.session_state.chat_history.append((u_q, ans)); st.rerun()

# --- Tab 2: סנכרון (הצעת קלוד) ---
with tab2:
    st.header("🔄 סנכרון לדרייב")
    if st.button("🚀 סנכרן הכל עכשיו"):
        if not os.path.exists(DATA_FILE): st.warning("אין נתונים חדשים.")
        else:
            with st.spinner("ממזג נתונים..."):
                try:
                    with open(DATA_FILE, "r", encoding="utf-8") as f: locals_ = [json.loads(l) for l in f if l.strip()]
                    df_final = pd.concat([full_df, pd.DataFrame(locals_)], ignore_index=True).drop_duplicates(subset=['student_name', 'timestamp'], keep='last')
                    buf = io.BytesIO()
                    with pd.ExcelWriter(buf, engine='openpyxl') as w: df_final.to_excel(w, index=False)
                    buf.seek(0)
                    query = f"name = '{MASTER_FILENAME}' and trashed = false"
                    res = svc.files().list(q=query, supportsAllDrives=True).execute().get('files', [])
                    media = MediaIoBaseUpload(buf, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                    if res: svc.files().update(fileId=res[0]['id'], media_body=media, supportsAllDrives=True).execute()
                    else: svc.files().create(body={'name': MASTER_FILENAME, 'parents': [GDRIVE_FOLDER_ID] if GDRIVE_FOLDER_ID else []}, media_body=media, supportsAllDrives=True).execute()
                    os.remove(DATA_FILE); st.success("הסנכרון הושלם!")
                except Exception as e: st.error(f"שגיאה: {e}")

# --- Tab 3: ניתוח משופר ---
with tab3:
    st.header("📊 ניתוח תובנות מחקריות")
    if full_df.empty: st.info("אין נתונים להצגה.")
    else:
        mode = st.radio("סוג ניתוח:", ["🔍 סטודנט לאורך זמן", "📅 סיכום יומי משולב"], horizontal=True)
        
        if mode == "🔍 סטודנט לאורך זמן":
            sel = st.selectbox("בחר סטודנט", full_df['student_name'].unique())
            sd = full_df[full_df['student_name'] == sel].sort_values('timestamp')
            
            c1, c2, c3 = st.columns(3)
            c1.metric("ממוצע המרה", f"{sd['cat_convert_rep'].mean():.1f}")
            c2.metric("ממוצע היטלים", f"{sd['cat_proj_trans'].mean():.1f}")
            c3.metric("תצפיות", len(sd))
            
            st.line_chart(sd.set_index('date')[['cat_convert_rep', 'cat_proj_trans', 'cat_self_efficacy']])
            
            user_req = st.text_area("בקשה מיוחדת מה-AI:")
            if st.button("🚀 הפק ניתוח אישי"):
                with st.spinner("מנתח..."):
                    st.session_state.ai_analysis_result = get_ai_response("chat", {"name": sel, "history": sd.to_string(), "question": user_req if user_req else "סכם מגמות עיקריות"})
            
            if st.session_state.ai_analysis_result:
                st.info(st.session_state.ai_analysis_result)
                st.download_button("📥 הורד ניתוח (TXT)", st.session_state.ai_analysis_result, file_name=f"Analysis_{sel}.txt")

        else: # ניתוח יומי
            sel_date = st.selectbox("בחר תאריך", sorted(full_df['date'].unique(), reverse=True))
            day_data = full_df[full_df['date'] == sel_date]
            st.write(f"ממוצעים ליום זה:")
            st.dataframe(day_data[['cat_convert_rep', 'cat_proj_trans', 'cat_self_efficacy']].mean())
            
            if st.button("✨ הפק תובנות ליום זה"):
                with st.spinner("מנתח את כלל הכיתה..."):
                    res = get_ai_response("class", {"history": day_data.to_string()})
                    st.success(res)
                    st.download_button("📥 הורד דוח יומי", res, file_name=f"Daily_{sel_date}.txt")
