# --- עדכון פונקציית הצ'אט בקוד (חלק מגרסה 11.5) ---

        if u_input:
            client = genai.Client(api_key=st.secrets["GOOGLE_API_KEY"])
            # הנחיה קשיחה למניעת המצאת מקורות
            prompt = f"""
            אתה עוזר מחקר אקדמי. חל עליך איסור מוחלט להמציא מאמרים או שמות של חוקרים (כמו Alias, Black, White).
            
            משימה:
            1. השתמש בכלי ה-Google Search המחובר אליך כדי למצוא מאמרים אמיתיים בלבד (2014-2026).
            2. אם מצאת מאמר, חובה לספק את שם המאמר המדויק ואת ה-Link/DOI שלו.
            3. אם אינך מוצא מאמר ספציפי שמתאים ב-100%, כתוב: 'לא נמצא מקור אקדמי ספציפי התואם את המקרה, אך לפי התצפיות...'
            4. נתח את הסטודנט {student_name} על בסיס ההיסטוריה: {drive_history}.
            
            שאלה: {u_input}
            """
            res = client.models.generate_content(
                model="gemini-2.0-flash", 
                contents=prompt,
                config={'tools': [{'google_search': {}}]} # הפעלת אימות בזמן אמת
            )
            st.session_state.chat_history.append((u_input, res.text)); st.rerun()
