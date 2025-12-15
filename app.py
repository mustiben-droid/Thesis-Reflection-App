import json
import os
from datetime import date, datetime, timedelta

import streamlit as st
from google import genai              # הוסף את השורה הזו
from google.genai.errors import APIError  # הוסף את השורה הזו
DATA_FILE = "reflections.jsonl"

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
            d = date.fromisoformat(e["date"])
            if week_ago <= d <= today:
                out.append(e)
    return out
def generate_summary(entries: list) -> str:
    """מחבר את כל הרשומות מהשבוע ושולח אותן ל-Gemini לסיכום."""
    full_text = "אלה הן רשומות רפלקציה שבועיות שבוצעו במהלך כתיבת עבודת תזה. הרפלקציות נאספו בפורמט JSONL. סיכום שבועי:"
    
    if not entries:
        return "לא נמצאו רשומות רפלקציה בשבוע האחרון לסיכום."

    for entry in entries:
        full_text += f"\n---\nרפלקציה מ: {entry.get('date')}\n"
        full_text += f"תכנון: {entry.get('planned')}\n"
        full_text += f"בוצע: {entry.get('done')}\n"
        full_text += f"קושי: {entry.get('challenge')}\n"
        full_text += f"תובנה: {entry.get('insight')}\n"
        full_text += f"צעד הבא: {entry.get('next_step')}\n"

    try:
        # קורא את המפתח ממשתנה הסביבה ($env:GOOGLE_API_KEY)
        client = genai.Client()

        # הגדרת הפרומפט
        prompt = (
            "על סמך רשומות הרפלקציה הבאות, בצע ניתוח וסכם את השבוע. "
            "הסיכום צריך להיות בשלושה חלקים, מופרדים: "
            "1. **מגמות ודפוסים:** מהם הדפוסים העיקריים שעולים מהרשומות (מבחינת תכנון מול ביצוע, וקשיים חוזרים)? "
            "2. **הישגים מרכזיים:** מהם הביצועים והתובנות החשובות ביותר? "
            "3. **המלצות לצעדים הבאים:** הצע צעדים ממוקדים לשבוע הבא. "
            f"הרשומות: \n{full_text}"
        )
        
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
        )
        return response.text

    except APIError as e:
        return f"שגיאת API: ודא שמפתח ה-API שלך ('GOOGLE_API_KEY') מוגדר כהלכה ושיש לך קרדיט. שגיאה: {e}"
    except Exception as e:
        return f"שגיאה בלתי צפויה בעת יצירת הסיכום: {e}"


st.title("יומן רפלקציה לתזה")

with st.form("reflection_form"):
    st.subheader("פרטי רפלקציה")
    
    # 1. פרמטר חדש: שם תלמיד
    # ---
    student_name = st.text_input("שם תלמיד", help="הזן את שם התלמיד שעבורו נרשמת הרפלקציה.")
    
    # פרמטר קיים: מזהה שיעור
    # ---
    lesson_id = st.text_input("מזהה שיעור")

    st.subheader("רפלקציה מילולית")
    planned = st.text_area("מה תכננתי?")
    done = st.text_area("מה בוצע בפועל?")
    challenge = st.text_area("קושי מרכזי")
    insight = st.text_area("תובנה להמשך")
    next_step = st.text_area("צעד הבא")
    
    st.subheader("קטגוריות תפיסה מרחבית בשרטוט הנדסי (דירוג)")
    st.markdown("אנא דרג את רמת הקושי או ההתמודדות של התלמיד בכל קטגוריה (1=קל/מצוין, 5=קשה/נדרש שיפור).")

    # 2. פרמטרים חדשים: קטגוריות תפיסה מרחבית
    # נשתמש ב-st.select_slider לדירוג נוח בין 1 ל-5
    # ---
    categories = [1, 2, 3, 4, 5]
    
    cat_convert = st.select_slider(
        "א. המרת ייצוגים (איזומטריה להיטלים)", 
        options=categories, 
        value=3,
        help="מעבר בין מבט תלת-ממדי למבטי דו-ממד."
    )
    
    cat_dims = st.select_slider(
        "ב. מידות ופרופורציות", 
        options=categories, 
        value=3,
        help="התייחסות למידות, שמירת פרופורציות או שימוש בכלי מדידה."
    )
    
    cat_proj = st.select_slider(
        "ג. מעבר בין היטלים", 
        options=categories, 
        value=3,
        help="השלכה נכונה בין היטל על להיטל צד או מבט נוסף."
    )
    
    cat_3d_support = st.select_slider(
        "ד. שימוש בגוף מודפס כתומך חשיבה", 
        options=categories, 
        value=3,
        help="היכולת להשתמש במודל פיזי כדי לשפר את החשיבה המרחבית."
    )
    
    submitted = st.form_submit_button("שמור")

    # --- התחלה של החלק התחתון המאוחד (הדבק כאן) ---

# ודא שהקוד הזה מגיע מיד אחרי submitted = st.form_submit_button("שמור")
if submitted:
    # 1. שמירת הרפלקציה המלאה (רק פעם אחת)
    res = save_reflection({
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
    })
    # 2. הצגת הודעת הצלחה (משתמשת ב-res)
    st.success(f"נשמר ✅ ({res['date']})")

st.divider()

# 3. טעינת נתונים והצגה (הטבלה המסודרת)
st.subheader("רפלקציות מהשבוע האחרון")
entries = load_last_week()
st.write(f"נמצאו: {len(entries)}")

for e in reversed(entries[-10:]):
    # הצגת כותרת הרפלקציה
    st.markdown(f"**{e.get('date')} — {e.get('student_name', 'אין שם')}** (שיעור: {e.get('lesson_id','')})")
    
    # יצירת טבלה מסודרת לכל הרפלקציה
    st.table({
        "תלמיד": e.get('student_name', ''),
        "תכנון": e.get('planned', ''),
        "בוצע": e.get('done', ''),
        "קושי": e.get('challenge', ''),
        "תובנה": e.get('insight', ''),
        "צעד הבא": e.get('next_step', ''),
        "דירוג המרת ייצוגים": e.get('cat_convert_rep', '---'),
        "דירוג מידות ופרופורציות": e.get('cat_dims_props', '---'),
        "דירוג מעבר בין היטלים": e.get('cat_proj_trans', '---'),
        "דירוג גוף מודפס": e.get('cat_3d_support', '---'),
    })
    st.divider() 

# 4. כפתור הסיכום של Gemini (חייב להיות בסוף!)
if st.button("✨ סכם שבוע אחרון עם Gemini"):
    if not entries:
        st.info("אין מספיק נתונים (רשומות) מהשבוע האחרון ליצירת סיכום.")
    else:
        with st.spinner("יוצר סיכום על ידי Gemini (זה עשוי לקחת כמה שניות)..."):
            # ודא שהפונקציה generate_summary(entries) קיימת בפונקציות העליונות
            summary_text = generate_summary(entries) 
        
        st.subheader("סיכום שבועי מונע-AI")
        st.markdown(summary_text)
