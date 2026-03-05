import streamlit as st

st.write("שלום! אם אתם רואים את זה, המערכת עובדת.")

if st.button("לחץ לבדיקה"):
    st.balloons()
    st.success("הצלחנו!")

# בדיקת סודות (אל תחשוף את המפתח האמיתי, רק תבדוק אם הוא קיים)
if "GOOGLE_API_KEY" in st.secrets:
    st.write("✅ מפתח ה-API נמצא ב-Secrets")
else:
    st.error("❌ מפתח ה-API חסר ב-Secrets!")
