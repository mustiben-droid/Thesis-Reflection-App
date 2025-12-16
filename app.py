import json # חובה לייבא json!
import os
import io
from datetime import date, datetime, timedelta

import streamlit as st
from google import genai
from google.genai.errors import APIError

# --- Google Drive Imports ---
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
# --- סוף Google Drive Imports ---

# --- הגדרות קבועות (מעודכן) ---
DATA_FILE = "reflections.jsonl"
# קורא את הסודות שהגדרת ב-Streamlit Cloud
GDRIVE_FOLDER_ID = st.secrets.get("GDRIVE_FOLDER_ID")
# קורא את השם החדש ששמרת כטקסט גולמי
GDRIVE_SERVICE_ACCOUNT_JSON = st.secrets.get("GDRIVE_SERVICE_ACCOUNT_JSON") 
# -----------------------------

def set_rtl():
    st.markdown("""
        <style>
            /* כללי RTL כלליים לדף ולשדות טקסט */
            html, body, [data-testid="stAppViewContainer"] {
                direction: rtl; 
            }
            input, textarea, [data-testid="stTextarea"] {
                direction: rtl !important;
                text-align: right;
            }
            
            /* התיקון ל-Sliders */
            [data-testid="stSlider"] {
                direction: rtl; 
            }
            [data-testid="stSlider"] * {
                direction: rtl !important;
                text-align: right !important;
            }
            
            /* שומר על כיוון LTR לכפתורים וכותרות Streamlit */
            [data-testid="stHeader"], [data-testid="baseButton"] {
                direction: ltr; 
            }
        </style>
        """, unsafe_allow_html=True)

# -----------------------------
# Utilities
# -----------------------------
def get_google_api_key() -> str:
    return st.secrets.get("GOOGLE_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""

def save_reflection(entry: dict) -> dict:
    """שומר רשומה ללוג המקומי (JSONL)."""
    with open(DATA_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return {"status": "saved", "date": entry["date"]}

def load_last_week():
    # ... (הפונקציה נשארת ללא שינוי) ...
    if not os.path.exists(DATA_FILE):
        return []
    
    today = date.today()
    week_ago = today - timedelta(days=6)

    out = []
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            e = json.loads(line)
            
            if e.get("type") == "weekly_summary":
                continue 
            
            try:
                d = date.fromisoformat(e.get("date", today.isoformat()))
            except Exception:
                continue

            if week_ago <= d <= today:
                out.append(e)

    return out

def load_all_summaries():
    """טוען ושולף את כל הסיכומים השבועיים שנשמרו."""
    if not os.path.exists(DATA_FILE):
        return []

    summaries = []
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            e = json.loads(line)
            if e.get("type") == "weekly_summary":
                summaries.append(e)

    return summaries

# -----------------------------
# Google Drive Functions (מעודכן)
# -----------------------------

def get_drive_service():
    """מייצר חיבור מאומת לשירות Google Drive API."""
    # משתמש בשם החדש
    if not (GDRIVE_FOLDER_ID and GDRIVE_SERVICE_ACCOUNT_JSON):
        return None
    try:
        SCOPES = ['https://www.googleapis.com/auth/drive.file']
        
        # שלב קריטי: המרה מטקסט גולמי למילון JSON
        service_account_info = json.loads(GDRIVE_SERVICE_ACCOUNT_JSON)
        
        credentials = Credentials.from_service_account_info(
            service_account_info, # משתמשים במילון ה-JSON שהומר
            scopes=SCOPES
        )
        service = build('drive', 'v3', credentials=credentials)
        return service
    except Exception as e:
        # אם יש שגיאת פורמט ב-JSON, היא תיתפס כאן, ונוכל לראות אותה
        st.error(f"שגיאת אימות ל-Google Drive: ודא שהסודות וההרשאות תקינים. פרטי שגיאה: {e}")
        return None

def upload_summary_to_drive(summary_text: str, drive_service):
    # ... (הפונקציה נשארת ללא שינוי) ...
    today_str = date.today().isoformat()
    file_name = f"סיכום שבועי לתזה - {today_str}.md"
    
    query = f"name='{file_name}' and '{GDRIVE_FOLDER_ID}' in parents and trashed=false"
    response = drive_service.files().list(
        q=query,
        spaces='drive',
        fields='files(id)'
    ).execute()
    
    files = response.get('files', [])
    file_id = files[0]['id'] if files else None

    media = MediaIoBaseUpload(
        io.BytesIO(summary_text.encode('utf-8')),
        mimetype='text/markdown',
        resumable=True
    )

    if file_id:
        drive_service.files().update(
            fileId=file_id,
            media_body=media
        ).execute()
        return f"עודכן קובץ: {file_name}"
    else:
        file_metadata = {
            'name': file_name,
            'parents': [GDRIVE_FOLDER_ID],
            'mimeType': 'text/markdown'
        }
        drive_service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id, name'
        ).execute()
        return f"נוצר קובץ חדש: {file_name}"

def upload_reflection_to_drive(entry: dict, drive_service):
    # ... (הפונקציה נשארת ללא שינוי) ...
    student_name = entry.get("student_name", "ללא-שם").replace(" ", "_")
    date_str = entry.get("date", date.today().isoformat())
    file_name = f"רפלקציה-{student_name}-{date_str}-{entry.get('timestamp')}.json"
    
    # 1. הכנת תוכן הקובץ (JSON)
    reflection_json = json.dumps(entry, ensure_ascii=False, indent=4).encode('utf-8')
    media = MediaIoBaseUpload(
        io.BytesIO(reflection_json),
        mimetype='application/json',
        resumable=True
    )

    # 2. יצירת קובץ חדש
    file_metadata = {
        'name': file_name,
        'parents': [GDRIVE_FOLDER_ID],
        'mimeType': 'application/json'
    }
    drive_service.files().create(
        body=file_metadata,
        media_body=media,
        fields='id, name'
    ).execute()
    return f"רפלקציה נשמרה כ-JSON: {file_name}"
    
# -----------------------------
# Gemini Summary Function
# -----------------------------
def generate_summary(entries: list) -> str:
    # ... (הפונקציה נשארת ללא שינוי) ...
    if not entries:
        return "לא נמצאו רשומות רפלקציה בשבוע האחרון לסיכום."

    # Build prompt body... 
    header = (
        "אלה הן רשומות רפלקציה שבועיות שבוצעו במהלך כתיבת עבודת תזה. "
        "הרפלקציות נאספו בפורמט JSONL.\n"
    )
    full_text = header
    for entry in entries:
        full_text += f"\n---\nרפלקציה מ: {entry.get('date')}\n"
        full_text += f"תלמיד: {entry.get('student_name')}\n"
        full_text += f"מזהה שיעור: {entry.get('lesson_id')}\n"
        full_text += f"תכנון: {entry.get('planned')}\n"
        full_text += f"בוצע: {entry.get('done')}\n"
        full_text += f"קושי: {entry.get('challenge')}\n"
        full_text += f"תובנה: {entry.get('insight')}\n"
        full_text += f"צעד הבא: {entry.get('next_step')}\n"
        full_text += (
            f"דירוגים (1=קל/מצוין, 5=קשה): "
            f"המרת ייצוגים={entry.get('cat_convert_rep')}, "
            f"מידות/פרופורציות={entry.get('cat_dims_props')}, "
            f"מעבר בין היטלים={entry.get('cat_proj_trans')}, "
            f"גוף מודפס={entry.get('cat_3d_support')}\n"
        )

    prompt = (
        "על סמך רשומות הרפלקציה הבאות, בצע ניתוח וסכם את השבוע.\n"
        "הסיכום צריך להיות בשלושה חלקים, מופרדים בבירור:\n"
        "1) **מגמות ודפוסים** – דפוסים מרכזיים (תכנון מול ביצוע, קשיים חוזרים)\n"
        "2) **הישגים מרכזיים** – ביצועים ותובנות חשובות\n"
        "3) **המלצות לצעדים הבאים** – צעדים ממוקדים לשבוע הבא\n\n"
        f"הרשומות:\n{full_text}"
    )

    api_key = get_google_api_key()
    if not api_key:
        return ("שגיאת API: לא נמצא GOOGLE_API_KEY. הגדר ב-Streamlit Secrets.")

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        return response.text or "לא התקבל טקסט מהמודל."

    except APIError as e:
        msg = str(e)
        if ("expired" in msg.lower()) or ("api_key_invalid" in msg.lower()) or ("api key" in msg.lower()):
            return ("שגיאת API: מפתח ה-API לא תקין או פג תוקף. עדכן ב-Streamlit Secrets.")
        return f"שגיאת API: {msg}"

    except Exception as e:
        return f"שגיאה בלתי צפויה בעת יצירת הסיכום: {e}"

# -----------------------------
# Streamlit UI
# -----------------------------

set_rtl()
st.title("יומן תצפית")


with st.form("reflection_form"):
    st.subheader("פרטי רפלקציה")
    student_name = st.text_input("שם תלמיד", help="הזן את שם התלמיד שעבורו נרשמה הרפלקציה.")
    lesson_id = st.text_input("מזהה שיעור")

    st.subheader("רפלקציה מילולית")
    planned = st.text_area("מה תכננתי?")
    done = st.text_area("מה בוצע בפועל?")
    challenge = st.text_area("קושי מרכזי")
    insight = st.text_area("תובנה להמשך")
    next_step = st.text_area("צעד הבא")

    st.subheader("קטגוריות תפיסה מרחבית בשרטוט הנדסי (דירוג)")
    st.markdown("אנא דרג את רמת הקושי או ההתמודדות של התלמיד בכל קטגוריה (1=קל/מצוין, 5=קשה/נדרש שיפור).")

    categories = [1, 2, 3, 4, 5]

    cat_convert = st.select_slider("א. המרת ייצוגים (איזומטריה להיטלים)", options=categories, value=3, help="מעבר בין מבט תלת-ממדי למבטי דו-ממד.")
    cat_dims = st.select_slider("ב. מידות ופרופורציות", options=categories, value=3, help="התייחסות למידות, שמירת פרופורציות או שימוש בכלי מדידה.")
    cat_proj = st.select_slider("ג. מעבר בין היטלים", options=categories, value=3, help="השלכה נכונה בין היטל על להיטל צד או מבט נוסף.")
    cat_3d_support = st.select_slider("ד. שימוש בגוף מודפס כתומך חשיבה", options=categories, value=3, help="היכולת להשתמש במודל פיזי כדי לשפר את החשיבה המרחבית.")

    submitted = st.form_submit_button("שמור")


if submitted:
    # 1. בניית הרשומה המלאה (כולל תאריך וזמן)
    reflection_entry = {
        "type": "reflection",
        "student_name": student_name,
        "lesson_id": lesson_id,
        "planned": planned,
        "done": done,
        "challenge": challenge,
        "insight": insight,
        "next_step": next_step,
        "cat_convert_rep": cat_convert,
        "cat_dims_props": cat_dims,
        "cat_proj_trans": cat_proj,
        "cat_3d_support": cat_3d_support,
        "date": date.today().isoformat(),
        "timestamp": datetime.now().isoformat(timespec="seconds")
    }
    
    # 2. שמירה ללוג המקומי (חובה לטובת הסיכום השבועי)
    save_reflection(reflection_entry)
    
    # 3. שמירה ל-Google Drive
    with st.spinner("שומר רפלקציה ב-Google Drive..."):
        drive_service = get_drive_service()
        if drive_service:
            try:
                drive_status = upload_reflection_to_drive(reflection_entry, drive_service)
                st.success(f"נשמר בהצלחה ✅ (לוג מקומי ו-Drive): {drive_status}")
            except Exception as e:
                # שינוי קטן בהודעה כדי לעזור לאתר שגיאות קריטיות כמו הרשאות כתיבה
                st.error(f"שגיאה בשמירה ל-Google Drive: ודא שניתנה הרשאת 'Editor' לחשבון השירות. פרטי שגיאה: {e}")
        else:
            st.warning("נשמר בלוג המקומי בלבד. לא ניתן להתחבר ל-Google Drive. ")


st.divider()

# --- הצגת כפתור הסיכום ---
entries = load_last_week() 

if st.button("✨ סכם שבוע אחרון עם Gemini"):
    if not entries:
        st.info("אין מספיק נתונים (רשומות) מהשבוע האחרון ליצירת סיכום.")
    else:
        with st.spinner("יוצר סיכום ושומר..."):
            
            # יצירת הסיכום
            summary_text = generate_summary(entries)

            # שמירה מקומית
            summary_entry = {
                "type": "weekly_summary", 
                "content": summary_text,
                "source_entries_count": len(entries),
                "date": date.today().isoformat()
            }
            save_reflection(summary_entry)
            st.success("הסיכום השבועי נשמר אוטומטית לקובץ המקומי! ✅")
            
            # שמירה ל-Google Drive
            drive_service = get_drive_service()
            if drive_service:
                try:
                    drive_status = upload_summary_to_drive(summary_text, drive_service)
                    st.success(f"נשמר בהצלחה ל-Google Drive: {drive_status}")
                except Exception as e:
                    st.error(f"שגיאה בשמירה ל-Google Drive: ודא שניתנה הרשאת 'Editor' לחשבון השירות. פרטי שגיאה: {e}")
            else:
                 st.warning("לא ניתן להתחבר ל-Google Drive. ודא שהסודות והרשאות השיתוף תקינים.")
            
        st.subheader("סיכום שבועי מונע-AI")
        st.markdown(summary_text)

st.divider()

# --- הצגת סיכומים קודמים ---
st.subheader("סיכומים שבועיים קודמים")
summaries = load_all_summaries()

if summaries:
    st.info(f"נמצאו {len(summaries)} סיכומים שבועיים שמורים. ")
    
    for s in reversed(summaries): 
        date_str = s.get('date', 'תאריך לא ידוע')
        count = s.get('source_entries_count', 0)
        
        with st.expander(f"סיכום מ-{date_str} (מבוסס על {count} רשומות)"):
            st.markdown(s.get('content', 'אין תוכן'))
            
else:
    st.info("עדיין לא נוצר סיכום שבועי אוטומטי.")