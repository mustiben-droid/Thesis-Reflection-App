import json
import os
from datetime import date, datetime, timedelta

import streamlit as st
from google import genai
from google.genai.errors import APIError


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
            
            /* התיקון האולטימטיבי ל-Sliders */
            [data-testid="stSlider"] {
                direction: rtl; 
            }
            /* כופה RTL על *כל* האלמנטים הפנימיים בתוך ה-Slider */
            [data-testid="stSlider"] * {
                direction: rtl !important;
                text-align: right !important;
            }
            /* --- סוף התיקון ל-Sliders --- */
            
            /* שומר על כיוון LTR לכפתורים וכותרות Streamlit */
            [data-testid="stHeader"], [data-testid="baseButton"] {
                direction: ltr; 
            }
        </style>
        """, unsafe_allow_html=True)

DATA_FILE = "reflections.jsonl"
# -----------------------------
# Utilities
# -----------------------------
def get_google_api_key() -> str:
    """
    Streamlit Cloud: st.secrets["GOOGLE_API_KEY"]
    Local dev: env var GOOGLE_API_KEY
    """
    return st.secrets.get("GOOGLE_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""


def save_reflection(entry: dict) -> dict:
    entry = dict(entry)
    entry.setdefault("date", date.today().isoformat())
    entry.setdefault("timestamp", datetime.now().isoformat(timespec="seconds"))
    with open(DATA_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return {"status": "saved", "date": entry["date"]}


def load_last_week():
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
            try:
                d = date.fromisoformat(e.get("date", today.isoformat()))
            except Exception:
                continue

            if week_ago <= d <= today:
                out.append(e)

    return out


def generate_summary(entries: list) -> str:
    """מחבר את כל הרשומות מהשבוע ושולח אותן ל-Gemini לסיכום."""
    if not entries:
        return "לא נמצאו רשומות רפלקציה בשבוע האחרון לסיכום."

    # Build prompt body
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
        return (
            "שגיאת API: לא נמצא GOOGLE_API_KEY.\n\n"
            "פתרון:\n"
            "ב-Streamlit Cloud: Settings → Secrets והוסף:\n"
            'GOOGLE_API_KEY = "YOUR_KEY"\n'
            "או מקומית: הגדר משתנה סביבה GOOGLE_API_KEY."
        )

    try:
        # Pass key explicitly (more reliable than implicit env discovery)
        client = genai.Client(api_key=api_key)

        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        return response.text or "לא התקבל טקסט מהמודל."

    except APIError as e:
        msg = str(e)

        # Friendlier message for common key problems
        if ("expired" in msg.lower()) or ("api_key_invalid" in msg.lower()) or ("api key" in msg.lower()):
            return (
                "שגיאת API: מפתח ה-API לא תקין או פג תוקף.\n\n"
                "פתרון מהיר:\n"
                "1) צור מפתח חדש ב-AI Studio\n"
                "2) עדכן אותו ב-Streamlit Secrets תחת GOOGLE_API_KEY\n"
                "3) בצע Restart לאפליקציה\n\n"
                f"פרטי שגיאה: {msg}"
            )

        return f"שגיאת API: {msg}"

    except Exception as e:
        return f"שגיאה בלתי צפויה בעת יצירת הסיכום: {e}"

set_rtl()
st.title("יומן רפלקציה לתזה")

with st.form("reflection_form"):
    st.subheader("פרטי רפלקציה")

    student_name = st.text_input("שם תלמיד", help="הזן את שם התלמיד שעבורו נרשמת הרפלקציה.")
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

    cat_convert = st.select_slider(
        "א. המרת ייצוגים (איזומטריה להיטלים)",
        options=categories,
        value=3,
        help="מעבר בין מבט תלת-ממדי למבטי דו-ממד.",
    )

    cat_dims = st.select_slider(
        "ב. מידות ופרופורציות",
        options=categories,
        value=3,
        help="התייחסות למידות, שמירת פרופורציות או שימוש בכלי מדידה.",
    )

    cat_proj = st.select_slider(
        "ג. מעבר בין היטלים",
        options=categories,
        value=3,
        help="השלכה נכונה בין היטל על להיטל צד או מבט נוסף.",
    )

    cat_3d_support = st.select_slider(
        "ד. שימוש בגוף מודפס כתומך חשיבה",
        options=categories,
        value=3,
        help="היכולת להשתמש במודל פיזי כדי לשפר את החשיבה המרחבית.",
    )

    submitted = st.form_submit_button("שמור")


if submitted:
    res = save_reflection(
        {
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
        }
    )
    st.success(f"נשמר ✅ ({res['date']})")

st.divider()

st.subheader("רפלקציות מהשבוע האחרון")
entries = load_last_week()
st.write(f"נמצאו: {len(entries)}")

for e in reversed(entries[-10:]):
    st.markdown(f"**{e.get('date')} — {e.get('student_name', 'אין שם')}** (שיעור: {e.get('lesson_id','')})")

    st.table(
        {
            "תלמיד": e.get("student_name", ""),
            "תכנון": e.get("planned", ""),
            "בוצע": e.get("done", ""),
            "קושי": e.get("challenge", ""),
            "תובנה": e.get("insight", ""),
            "צעד הבא": e.get("next_step", ""),
            "דירוג המרת ייצוגים": e.get("cat_convert_rep", "---"),
            "דירוג מידות ופרופורציות": e.get("cat_dims_props", "---"),
            "דירוג מעבר בין היטלים": e.get("cat_proj_trans", "---"),
            "דירוג גוף מודפס": e.get("cat_3d_support", "---"),
        }
    )
    st.divider()

if st.button("✨ סכם שבוע אחרון עם Gemini"):
    if not entries:
        st.info("אין מספיק נתונים (רשומות) מהשבוע האחרון ליצירת סיכום.")
    else:
        with st.spinner("יוצר סיכום על ידי Gemini (זה עשוי לקחת כמה שניות)..."):
            summary_text = generate_summary(entries)

        st.subheader("סיכום שבועי מונע-AI")
        st.markdown(summary_text)
