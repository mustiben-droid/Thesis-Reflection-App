import streamlit as st
import pandas as pd
import numpy as np
import re
import json

try:
    import plotly.express as px
    import google.generativeai as genai
    from scipy import stats
    import statsmodels.api as sm
    from statsmodels.formula.api import ols
except ImportError as e:
    st.error(f"Error: Missing library for statistical engine: {e}")

api_key = st.secrets.get("GOOGLE_API_KEY", "")
genai.configure(api_key=api_key)

MODEL_NAME = "gemini-2.0-flash"  # מודל יציב ונתמך


def run_smart_comparison(df, group_col, val_col):
    """
    בוחר אוטומטית בין T-test למבחן Mann-Whitney
    בהתאם לגודל המדגם והנחות היסוד.
    """
    groups = df[group_col].dropna().unique()
    if len(groups) != 2:
        return {"error": f"השוואה דורשת בדיוק 2 קבוצות בעמודה '{group_col}'. נמצאו: {list(groups)}"}

    g1 = df[df[group_col] == groups[0]][val_col].dropna()
    g2 = df[df[group_col] == groups[1]][val_col].dropna()

    if len(g1) < 2 or len(g2) < 2:
        return {"error": f"אין מספיק תצפיות לביצוע מבחן (נמצאו {len(g1)} ו-{len(g2)} תצפיות). נדרשות לפחות 2 לכל קבוצה."}

    use_non_parametric = len(g1) < 20 or len(g2) < 20

    res = {
        "group1": {"name": str(groups[0]), "M": round(g1.mean(), 2), "SD": round(g1.std(), 2), "N": len(g1), "Md": round(g1.median(), 2)},
        "group2": {"name": str(groups[1]), "M":
