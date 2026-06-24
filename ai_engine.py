"""
Triangulation Lab — מעבדת ממצאים מוצלבת
גרסה 2.5 | תיקונים: מניעת סלט משתני קושי, פתרון הזרקה כפולה בצאט (Token Bloat), ותיקון גרף קו מגמה לתאריכים חופפים
"""

import streamlit as st
import pandas as pd
import numpy as np
import re
import json
import os
from scipy import stats
import plotly.graph_objects as go
import plotly.express as px
from difflib import get_close_matches

# ─────────────────────────────────────────────
# הגדרות המחקר
# ─────────────────────────────────────────────
METRICS_DICTIONARY = {
    "score_proj":     {"app_name": "📐 המרת ייצוגים",   "color": "#4C72B0"},
    "score_spatial":  {"app_name": "🧠 תפיסה מרחבית",   "color": "#DD8452"},
    "score_conv":     {"app_name": "📏 פרופורציות",       "color": "#55A868"},
    "score_efficacy": {"app_name": "⚡ מסוגלות עצמית",   "color": "#C44E52"},
    "score_model":    {"app_name": "🧊 שימוש במודל 3D",  "color": "#8172B2"},
    "score_views":    {"app_name": "🔄 מעבר בין היטלים", "color": "#937860"},
}
SCORE_COLS  = list(METRICS_DICTIONARY.keys())
CAT_COLS    = ["cat_convert_rep", "cat_dims_props", "cat_proj_trans", "cat_3d_support"]
CAT_NAMES   = {
    "cat_convert_rep":  "המרת ייצוגים",
    "cat_dims_props":   "פרופורציות/ממדים",
    "cat_proj_trans":   "היטלים/העתקות",
    "cat_3d_support":   "תמיכה תלת-ממדית",
}

# ─────────────────────────────────────────────
# ניקוי שמות
# ─────────────────────────────────────────────
def clean_name(val: str) -> str:
    if pd.isna(val):
        return ""
    val = str(val).strip().lower()
    val = re.sub(r"[^\w]", "", val)
    return val

def fuzzy_match(key: str, pool: list[str], cutoff: float = 0.82) -> str | None:
    if key in pool:
        return key
    matches = get_close_matches(key, pool, n=1, cutoff=cutoff)
    return matches[0] if matches else None

# ─────────────────────────────────────────────
# טעינת קבצים
# ─────────────────────────────────────────────
def load_master(file) -> pd.DataFrame:
    df = pd.read_excel(file) if file.name.endswith(".xlsx") else pd.read_csv(file)
    df["name_key"] = df["student_name"].apply(clean_name)
    df["date"]     = pd.to_datetime(df.get("date", pd.NaT), errors="coerce")
    return df

def load_prepost(file) -> pd.DataFrame | None:
    raw = pd.read_excel(file, header=None) if file.name.endswith(".xlsx") else pd.read_csv(file, header=None)
    header_row = 0
    for idx, row in raw.iterrows():
        vals = " ".join([str(v) for v in row if str(v) not in ("nan", "")]).lower()
        if "name" in vals or "שם" in vals:
            header_row = idx
            break
    df = pd.read_excel(file, header=header_row) if file.name.endswith(".xlsx") else pd.read_csv(file, header=header_row)
    name_col = next((c for c in df.columns if "name" in str(c).lower() or "שם" in str(c)), df.columns[0])
    df = df.rename(columns={name_col: "name"})
    df = df[df["name"].notna() & (df["name"].astype(str).str.strip() != "")].reset_index(drop=True)
    df["name_key"] = df["name"].apply(clean_name)
    return df

def get_pre_post_cols(df: pd.DataFrame):
    pre_cols  = [c for c in df.columns if re.search(r"pre",  str(c), re.I) and re.search(r"q\d+", str(c), re.I)]
    post_cols = [c for c in df.columns if re.search(r"post", str(c), re.I) and re.search(r"q\d+", str(c), re.I)]
    pre_cols  = sorted(pre_cols,  key=lambda c: int(re.search(r"\d+", c).group()))
    post_cols = sorted(post_cols, key=lambda c: int(re.search(r"\d+", c).group()))
    return pre_cols, post_cols

def student_observations(df_master: pd.DataFrame, name_key: str) -> pd.DataFrame:
    sub = df_master[df_master["name_key"] == name_key].copy()
    available = [c for c in SCORE_COLS if c in sub.columns]
    sub = sub[sub[available].notna().any(axis=1)]
    return sub.sort_values("date")

def build_triangulation_table(df_master: pd.DataFrame, df_pp: pd.DataFrame | None) -> pd.DataFrame:
    rows = []
    pp_keys = list(df_pp["name_key"].unique()) if df_pp is not None else []

    for key in sorted(df_master["name_key"].unique()):
        if not key or key == "":
            continue
        obs = student_observations(df_master, key)
        if obs.empty:
            continue

        available = [c for c in SCORE_COLS if c in obs.columns]
        mean_scores = obs[available].apply(pd.to_numeric, errors="coerce").mean(axis=1)

        valid_scores = mean_scores.dropna()
        delta_obs = (valid_scores.iloc[-1] - valid_scores.iloc[0]) if len(valid_scores) > 1 else np.nan

        mean_pre = mean_post = delta_quest = np.nan
        if df_pp is not None:
            matched_key = fuzzy_match(key, pp_keys)
            if matched_key:
                pp_row = df_pp[df_pp["name_key"] == matched_key]
                pre_cols, post_cols = get_pre_post_cols(df_pp)
                if pre_cols:
                    mean_pre  = pp_row[pre_cols].apply(pd.to_numeric, errors="coerce").mean(axis=1).mean()
                if post_cols:
                    mean_post = pp_row[post_cols].apply(pd.to_numeric, errors="coerce").mean(axis=1).mean()
                if not (np.isnan(mean_pre) or np.isnan(mean_post)):
                    delta_quest = mean_post - mean_pre

        wm = obs["work_method"].dropna().mode()
        rows.append({
            "שם":             obs["student_name"].iloc[0],
            "n_תצפיות":       len(obs),
            "ממוצע_תצפיות":   round(float(mean_scores.mean()), 2) if not np.isnan(mean_scores.mean()) else None,
            "Δ_תצפיות":       round(float(delta_obs), 2) if not np.isnan(delta_obs) else None,
            "pre_שאלון":      round(float(mean_pre), 2) if not np.isnan(mean_pre) else None,
            "post_שאלון":     round(float(mean_post), 2) if not np.isnan(mean_post) else None,
            "Δ_שאלון":        round(float(delta_quest), 2) if not np.isnan(delta_quest) else None,
            "שיטת_עבודה":     wm.iloc[0] if not wm.empty else "—",
        })
    return pd.DataFrame(rows)

# ─────────────────────────────────────────────
# גרפים עם תמיכה בתאריכים חופפים
# ─────────────────────────────────────────────
RTL_LAYOUT = dict(
    font_family="Heebo, Arial, sans-serif",
    plot_bgcolor="#F8F9FA",
    paper_bgcolor="white",
    margin=dict(t=50, b=40, l=60, r=60),
)

def chart_student_timeline(obs: pd.DataFrame, student_name: str) -> go.Figure:
    available = [c for c in SCORE_COLS if c in obs.columns]
    obs = obs.dropna(subset=available, how="all").copy()
    
    # שיפור 3: פתרון לתאריכים חופפים באותו יום - הוספת מונה פנימי (#1, #2) לציר ה-X
    obs["date_str"] = obs["date"].dt.strftime("%d/%m/%y").fillna("ללא תאריך")
    obs["cum_count"] = obs.groupby("date_str").cumcount() + 1
    obs["x_label"] = obs["date_str"] + " (#" + obs["cum_count"].astype(str) + ")"

    fig = go.Figure()
    for col in available:
        vals = pd.to_numeric(obs[col], errors="coerce")
        if vals.notna().sum() < 1:
            continue
        meta = METRICS_DICTIONARY[col]
        fig.add_trace(go.Scatter(
            x=obs["x_label"],
            y=vals,
            mode="lines+markers",
            name=meta["app_name"],
            line=dict(color=meta["color"], width=2),
            marker=dict(size=8),
            connectgaps=True,
        ))

    fig.update_layout(
        title=f"ציר זמן ציונים — {student_name}",
        xaxis_title="תאריך ומספר תצפית",
        yaxis_title="ציון (1–5)",
        yaxis=dict(range=[0.5, 5.5], dtick=1),
        legend=dict(orientation="h", y=-0.25),
        **RTL_LAYOUT,
    )
    return fig

def chart_radar(obs: pd.DataFrame, student_name: str) -> go.Figure:
    available = [c for c in SCORE_COLS if c in obs.columns]
    means = obs[available].apply(pd.to_numeric, errors="coerce").mean()
    labels = [METRICS_DICTIONARY[c]["app_name"] for c in available]
    values = [round(float(means[c]), 2) for c in available]

    fig = go.Figure(go.Scatterpolar(
        r=values + [values[0]],
        theta=labels + [labels[0]],
        fill="toself",
        fillcolor="rgba(76,114,176,0.2)",
        line=dict(color="#4C72B0", width=2),
        marker=dict(size=7),
    ))
    fig.update_layout(
        title=f"פרופיל מיומנויות — {student_name}",
        polar=dict(radialaxis=dict(visible=True, range=[0, 5])),
        **RTL_LAYOUT,
    )
    return fig

def chart_pre_post_bar(tri_df: pd.DataFrame) -> go.Figure:
    df = tri_df.dropna(subset=["pre_שאלון", "post_שאלון"]).copy()
    fig = go.Figure()
    fig.add_trace(go.Bar(name="Pre", x=df["שם"], y=df["pre_שאלון"], marker_color="#8172B2", opacity=0.85))
    fig.add_trace(go.Bar(name="Post", x=df["שם"], y=df["post_שאלון"], marker_color="#4C72B0", opacity=0.85))
    fig.update_layout(
        title="השוואת שאלון Pre vs Post לכל תלמיד",
        barmode="group", xaxis_title="תלמיד", yaxis_title="ממוצע ציון שאלון (1–5)",
        yaxis=dict(range=[0, 5.5]), legend=dict(orientation="h", y=1.1), **RTL_LAYOUT,
    )
    return fig

def chart_delta_scatter(tri_df: pd.DataFrame) -> go.Figure:
    df = tri_df.dropna(subset=["Δ_תצפיות", "Δ_שאלון"]).copy()
    if df.empty: return None
    color_map = {"🧊 בעזרת גוף מודפס": "#4C72B0", "🎨 ללא גוף (דמיון)": "#DD8452"}
    fig = go.Figure()
    for wm, grp in df.groupby("שיטת_עבודה"):
        fig.add_trace(go.Scatter(
            x=grp["Δ_תצפיות"], y=grp["Δ_שאלון"], mode="markers+text", name=str(wm), text=grp["שם"],
            textposition="top center", marker=dict(size=14, color=color_map.get(wm, "#888"), opacity=0.85, line=dict(width=1, color="white")),
        ))
    fig.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.5)
    fig.add_vline(x=0, line_dash="dash", line_color="gray", opacity=0.5)
    fig.update_layout(
        title="Δ תצפיות מול Δ שאלון (לפי שיטת עבודה)",
        xaxis_title="שינוי ציון תצפיות (ראשון → אחרון)", yaxis_title="שינוי ציון שאלון (Pre → Post)", **RTL_LAYOUT,
    )
    return fig

def chart_category_heatmap(df_master: pd.DataFrame) -> go.Figure:
    available_cats = [c for c in CAT_COLS if c in df_master.columns]
    if not available_cats: return None
    rows = []
    for key in sorted(df_master["name_key"].unique()):
        if not key: continue
        obs = student_observations(df_master, key)
        name = obs["student_name"].iloc[0]
        means = obs[available_cats].apply(pd.to_numeric, errors="coerce").mean()
        row = {"שם": name}
        row.update({CAT_NAMES.get(c, c): round(float(means[c]), 2) if not np.isnan(means[c]) else None for c in available_cats})
        rows.append(row)
    df_heat = pd.DataFrame(rows).set_index("שם").apply(pd.to_numeric, errors="coerce")
    fig = go.Figure(go.Heatmap(
        z=df_heat.values, x=list(df_heat.columns), y=list(df_heat.index),
        colorscale=[[0, "#2ecc71"], [0.5, "#f39c12"], [1, "#e74c3c"]], zmin=1, zmax=5,
        text=df_heat.round(1).values.astype(str), texttemplate="%{text}",
        hovertemplate="תלמיד: %{y}<br>קטגוריה: %{x}<br>ציון: %{z:.2f}<extra></extra>",
        colorbar=dict(title="רמת קושי<br>(1=נמוך, 5=גבוה)"),
    ))
    fig.update_layout(title="מפת חום — מוקדי קושי לפי תלמיד", xaxis_title="קטגוריית קושי", yaxis_title="תלמיד", **RTL_LAYOUT)
    return fig

def chart_group_score_box(df_master: pd.DataFrame) -> go.Figure:
    available = [c for c in SCORE_COLS if c in df_master.columns]
    fig = go.Figure()
    for col in available:
        vals = pd.to_numeric(df_master[col], errors="coerce").dropna()
        meta = METRICS_DICTIONARY[col]
        fig.add_trace(go.Box(y=vals, name=meta["app_name"], marker_color=meta["color"], boxmean=True))
    fig.update_layout(title="フィזור ציונים לקבוצה (כל תצפיות)", yaxis_title="ציון (1–5)", yaxis=dict(range=[0.5, 5.5]), showlegend=False, **RTL_LAYOUT)
    return fig

def chart_work_method_comparison(df_master: pd.DataFrame) -> go.Figure:
    if "work_method" not in df_master.columns: return None
    available = [c for c in SCORE_COLS if c in df_master.columns]
    df = df_master[df_master["work_method"].notna()].copy()
    if df.empty: return None
    fig = go.Figure()
    colors = {"🧊 בעזרת גוף מודפס": "#4C72B0", "🎨 ללא גוף (דמיון)": "#DD8452"}
    for wm, grp in df.groupby("work_method"):
        means = grp[available].apply(pd.to_numeric, errors="coerce").mean()
        fig.add_trace(go.Bar(
            name=str(wm), x=[METRICS_DICTIONARY[c]["app_name"] for c in available],
            y=[round(float(means[c]), 2) for c in available], marker_color=colors.get(wm, "#888"), opacity=0.85,
        ))
    fig.update_layout(title="ממוצע ציונים לפי שיטת עבודה", barmode="group", xaxis_title="מדד", yaxis_title="ממוצע (1–5)", yaxis=dict(range=[0, 5.5]), legend=dict(orientation="h", y=1.1), **RTL_LAYOUT)
    return fig

# ─────────────────────────────────────────────
# פונקציית שמירת היסטוריית הניתוחים לדרייב
# ─────────────────────────────────────────────
def save_chain(name: str, messages: list) -> tuple[bool, str]:
    clean = re.sub(r"[^\w]", "_", name)
    path = os.path.abspath(f"Report_Triangulation_{clean}.txt")
    try:
        content = "\n\n" + "=" * 50 + "\n\n"
        content = content.join([f"[{m['role'].upper()}]:\n{m['content']}" for m in messages])
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return True, path
    except Exception as e:
        return False, str(e)

# ─────────────────────────────────────────────
# סוכן Gemini - הגדרת זהות נקייה מהמלצות
# ─────────────────────────────────────────────
SYSTEM_RULES = """
אתה פרופסור ומתודולוג מחקר בכיר המלווה כתיבת פרק ממצאים (Results) בלבד לתזת מאסטר במחקר פעולה.
תפקידך לחלץ תמות, קטגוריות וקשרים כמותיים ואיכותניים מתוך הדאטה שמועבר אליך.

חוק קשיח ואבסולוטי: אסור לך בשום אופן לכתוב המלצות פדגוגיות, עצות למורה, או הצעות לעתיד (כמו 'מומלץ להשתמש ב-AR' או 'כדאי לתת לו משוב'). התמקד אך ורק במה שהנתונים מראים בפועל ברמת הממצא הטהור.

הנחיה קריטית למניעת סלט:
- משתני cat_* (מוקדי קושי) הם ספירת שגיאות! ציון נמוך (כמו 1) הוא חוזק ומצוין (אפס שגיאות). אל תציג ציון נמוך ב-cat_* כחולשה.
- ציר הזמן מסודר כרונולוגית: דצמבר 2025 הוא תחילת הסמסטר (Baseline), פברואר ומאי 2026 הם ההמשך.
נהל שיחה משורשרת. כתוב בעברית אקדמית רהוטה לפי כללי APA 7th Edition.
"""

def init_gemini(api_key: str):
    import google.generativeai as genai
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-2.5-flash", system_instruction=SYSTEM_RULES)
    return model.start_chat(history=[])

# ─────────────────────────────────────────────
# UI ראשי
# ─────────────────────────────────────────────
def main():
    st.set_page_config(page_title="Triangulation Lab", page_icon="🔬", layout="wide")
    st.title("🔬 מעבדת טריאנגולציה — ניתוח מוצלב")

    # סנכרון Session State
    for key in ("df_master", "df_pp", "gemini_session", "agent_messages", "current_analyzed_student"):
        if key not in st.session_state:
            st.session_state[key] = None if key != "agent_messages" else []

    with st.sidebar:
        st.header("📁 טעינת קבצים")
        files = st.file_uploader("גרור קבצי xlsx (מאסטר + Pre/Post):", type=["xlsx", "csv"], accept_multiple_files=True)
        if files:
            for f in files:
                try:
                    sniff = pd.read_excel(f, header=None, nrows=5) if f.name.endswith(".xlsx") else pd.read_csv(f, header=None, nrows=5)
                    text  = " ".join(str(v) for v in sniff.values.flatten() if str(v) not in ("nan", "")).lower()
                    f.seek(0)
                    if "student_name" in text or "score_spatial" in text or "work_method" in text:
                        st.session_state.df_master = load_master(f)
                        st.success(f"✅ מאסטר: {f.name} ({len(st.session_state.df_master)} שורות)")
                    elif "preq" in text or "_post" in text or "q1_pre" in text:
                        st.session_state.df_pp = load_prepost(f)
                        st.success(f"✅ Pre/Post: {f.name} ({len(st.session_state.df_pp)} תלמידים)")
                except Exception as e:
                    st.error(f"שגיאה בטעינה: {e}")

    df_master = st.session_state.df_master
    df_pp     = st.session_state.df_pp

    if df_master is None:
        st.info("טען קובץ מאסטר תצפיות כדי להתחיל.")
        return

    tab_tri, tab_student, tab_group, tab_agent = st.tabs(["📊 טריאנגולציה", "👤 תלמיד בודד", "📈 קבוצה", "🤖 סוכן AI"])

    # טאב 1 — טריאנגולציה
    with tab_tri:
        st.subheader("טבלת טריאנגולציה — כלל התלמידים")
        tri_df = build_triangulation_table(df_master, df_pp)
        if not tri_df.empty:
            def color_delta(val):
                if pd.isna(val) or val == "—": return ""
                try:
                    v = float(val)
                    if v > 0.2:  return "background-color: #d4edda; color: #155724"
                    if v < -0.2: return "background-color: #f8d7da; color: #721c24"
                    return "background-color: #fff3cd; color: #856404"
                except: return ""
            st.dataframe(tri_df.style.applymap(color_delta, subset=["Δ_תצפיות", "Δ_שאלון"]), use_container_width=True, hide_index=True)
            st.divider()
            col1, col2 = st.columns(2)
            with col1: st.plotly_chart(chart_pre_post_bar(tri_df), use_container_width=True)
            with col2:
                fig_sc = chart_delta_scatter(tri_df)
                if fig_sc: st.plotly_chart(fig_sc, use_container_width=True)
        else: st.warning("לא נמצאו נתונים לטריאנגולציה.")

    # טאב 2 — תלמיד בודד
    with tab_student:
        students = sorted([k for k in df_master["student_name"].dropna().unique()])
        selected = st.selectbox("בחר תלמיד:", students)
        if selected:
            key = clean_name(selected)
            obs = student_observations(df_master, key)
            if obs.empty: st.warning("אין תצפיות עם ציונים עבור תלמיד זה.")
            else:
                col1, col2, col3, col4 = st.columns(4)
                available = [c for c in SCORE_COLS if c in obs.columns]
                means = obs[available].apply(pd.to_numeric, errors="coerce").mean()
                col1.metric("מספר תצפיות", len(obs))
                col2.metric("ממוצע כללי", f"{means.mean():.2f}")
                wm = obs["work_method"].dropna().mode()
                col3.metric("שיטה דומיננטית", wm.iloc[0] if not wm.empty else "—")
                if df_pp is not None:
                    mk = fuzzy_match(key, list(df_pp["name_key"].unique()))
                    if mk:
                        pp_row = df_pp[df_pp["name_key"] == mk]
                        pre_cols, post_cols = get_pre_post_pairs(df_pp)[0][:2] if get_pre_post_pairs(df_pp) else (None, None)
                        pre_cols, post_cols = get_pre_post_cols(df_pp)
                        if pre_cols and post_cols:
                            pre_m  = pp_row[pre_cols].apply(pd.to_numeric, errors="coerce").mean(axis=1).mean()
                            post_m = pp_row[post_cols].apply(pd.to_numeric, errors="coerce").mean(axis=1).mean()
                            col4.metric("Δ שאלון", f"{post_m - pre_m:+.2f}")

                st.columns(1)
                c1, c2 = st.columns([2, 1])
                with c1: st.plotly_chart(chart_student_timeline(obs, selected), use_container_width=True)
                with c2: st.plotly_chart(chart_radar(obs, selected), use_container_width=True)
                st.subheader("📋 תצפיות גולמיות")
                show_cols = [c for c in ["date", "difficulty", "work_method"] + available + ["interpretation", "tags"] if c in obs.columns]
                st.dataframe(obs[show_cols], use_container_width=True, hide_index=True)

    # טאב 3 — קבוצה
    with tab_group:
        st.subheader("ניתוח קבוצתי")
        c1, c2 = st.columns(2)
        with c1: st.plotly_chart(chart_group_score_box(df_master), use_container_width=True)
        with c2:
            fig_wm = chart_work_method_comparison(df_master)
            if fig_wm: st.plotly_chart(fig_wm, use_container_width=True)
        fig_heat = chart_category_heatmap(df_master)
        if fig_heat: st.plotly_chart(fig_heat, use_container_width=True)
        st.subheader("📐 סטטיסטיקה תיאורית")
        available = [c for c in SCORE_COLS if c in df_master.columns]
        desc = df_master[available].apply(pd.to_numeric, errors="coerce").describe().T
        desc.index = [METRICS_DICTIONARY[c]["app_name"] for c in desc.index]
        st.dataframe(desc.round(2), use_container_width=True)

    # טאב 4 — סוכן AI משורשר
    with tab_agent:
        st.subheader("🤖 סוכן ניתוח ממצאים (שיחה משורשרת)")
        st.caption("הסוכן זוכר את כל השיחה. שאל שאלות המשך בצורה רציפה (למשל: 'למה הציון שלו ירד אובייקטיבית?').")

        for msg in st.session_state.agent_messages:
            with st.chat_message(msg["role"]): st.markdown(msg["content"])

        prompt = st.chat_input("שאל על ממצאים, תמות, קטגוריות...")
        if prompt:
            st.session_state.agent_messages.append({"role": "user", "content": prompt})
            with st.chat_message("user"): st.markdown(prompt)

            with st.chat_message("assistant"):
                api_key = st.secrets.get("GOOGLE_API_KEY", "")
                if not api_key:
                    st.error("⚠️ חסר מפתח GOOGLE_API_KEY ב-Streamlit Secrets.")
                    st.stop()

                if st.session_state.gemini_session is None:
                    st.session_state.gemini_session = init_gemini(api_key)

                # בדיקה האם מדובר בתלמיד חדש או המשך שיחה
                payload_str = ""
                all_students = list(df_master["student_name"].dropna().unique())
                found_student = None
                
                for s in all_students:
                    if str(s).strip() in prompt:
                        found_student = s
                        break
                if found_student is None:
                    for w in prompt.split():
                        m = fuzzy_match(clean_name(w), [clean_name(s) for s in all_students], cutoff=0.80)
                        if m:
                            found_student = all_students[[clean_name(s) for s in all_students].index(m)]
                            break

                # שיפור 2: מניעת Token Bloat - הזרקת ה-JSON מתבצעת רק אם זה תלמיד חדש שלא נבדק בשיחה הנוכחית
                if found_student and found_student != st.session_state.current_analyzed_student:
                    st.session_state.current_analyzed_student = found_student
                    key = clean_name(found_student)
                    obs = student_observations(df_master, key)
                    available = [c for c in SCORE_COLS if c in obs.columns]
                    
                    timeline = []
                    for _, row in obs.iterrows():
                        # שיפור 1: העברת הנתונים הכמותיים כמדדי יעילות הפוכים (שגיאה נמוכה = יעילות גבוהה) כדי למנוע סלט לוגי ב-AI
                        inverted_cats = {}
                        for c in CAT_COLS:
                            if c in row and pd.notna(row[c]):
                                inverted_cats[f"{c}_efficiency_index"] = round(float(5.0 - pd.to_numeric(row[c])), 2)

                        timeline.append({
                            "date": str(row.get("date", ""))[:10],
                            "difficulty": row.get("difficulty"),
                            "performance_scores": {c: row.get(c) for c in available},
                            "error_category_counts_raw": {c: row.get(c) for c in CAT_COLS if c in row},
                            "cognitive_efficiency_indices_calculated": inverted_cats,
                            "work_method": row.get("work_method"),
                            "interpretation": str(row.get("interpretation", row.get("insight", "")))[:500],
                            "tags": str(row.get("tags", "")),
                        })
                    
                    pp_data = {}
                    if df_pp is not None:
                        mk = fuzzy_match(key, list(df_pp["name_key"].unique()))
                        if mk:
                            pp_row = df_pp[df_pp["name_key"] == mk]
                            pre_cols, post_cols = get_pre_post_cols(df_pp)
                            if pre_cols: pp_data["mean_pre"] = round(float(pp_row[pre_cols].apply(pd.to_numeric, errors="coerce").mean(axis=1).mean()), 2)
                            if post_cols: pp_data["mean_post"] = round(float(pp_row[post_cols].apply(pd.to_numeric, errors="coerce").mean(axis=1).mean()), 2)
                    
                    payload_str = f"\n[עוגן נתוני מחקר - סטודנט: {found_student}]: {json.dumps({'timeline': timeline, 'questionnaire': pp_data}, ensure_ascii=False)}"

                with st.spinner("הסוכן מנתח ומגבש תמות..."):
                    response = st.session_state.gemini_session.send_message(prompt + payload_str).text
                st.markdown(response)
                st.session_state.agent_messages.append({"role": "assistant", "content": response})

        # ממשק ארכוב בטוח ואחיד לדרייב
        if st.session_state.agent_messages:
            st.divider()
            col_name, col_btn = st.columns([3, 1])
            save_name = col_name.text_input("שם לקובץ הניתוח בארכיון:", value=f"Analysis_{st.session_state.current_analyzed_student or 'Output'}")
            if col_btn.button("💾 שמור שיחה לדרייב"):
                ok, path = save_chain(save_name, st.session_state.agent_messages)
                if ok: st.success(f"✅ כלל ממצאי השיחה המשורשרת אורכבו בהצלחה בנתיב המאסטר: `{path}`")
                else: st.error(f"⚠️ שגיאה בשמירה: {path}")

if __name__ == "__main__":
    main()
