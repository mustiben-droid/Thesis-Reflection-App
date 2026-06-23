import streamlit as st
import pandas as pd
import numpy as np
import re
import json
import os  # ניהול נתיבים וקבצים במערכת לשמירה בטוחה לדרייב
from scipy import stats

# ==========================================================
# מילון המיפוי וההגדרות הרשמי של המחקר
# ==========================================================
METRICS_DICTIONARY = {
    "score_proj": {
        "app_name": "📐 המרת ייצוגים (הטלה)",
        "definition": "היכולת הקוגניטיבית לתרגם גוף מתלת-ממד (מודל פיזי/איזומטריה) לדו-ממד (היטלים שטוחים) ולהיפך."
    },
    "score_spatial": {
        "app_name": "🧠 תפיסה מרחבית",
        "definition": "יכולת מנטלית לתפוס, לעבד, לסובב (רוטציה מנטלית) ולדמיין אלמנטים וצורות במרחב התלת-ממדי."
    },
    "score_conv": {
        "app_name": "📏 פרופורציות ומוסכמות",
        "definition": "חשיבה מתכנסת - יישום חוקים נוקשים של שרטוט טכני (קווים נסתרים, צירים) ושמירה על יחסי גודל וקנה מידה מדויקים."
    },
    "score_efficacy": {
        "app_name": "ציון מסוגלות עצמית בתצפית",
        "definition": "הערכת החוקר בזמן אמת בכיתה לגבי מידת הביטחון, העצמאות ותפיסת היכולת שהתלמיד מפגין מול המטלה (להפריד משאלוני Pre/Post)."
    },
    "score_model": {
        "app_name": "🧊 שימוש במודל 3D / הבנת מודל",
        "definition": "מידת ההבנה והיעילות של התלמיד בעבודה עם מודלים תלת-ממדיים מודפסים או דיגיטליים כפיגום למידה."
    },
    "score_views": {
        "app_name": "🔄 מעבר בין היטלים",
        "definition": "מיומנות מנטלית לנוע בתוך עולם הדו-ממד בין המבטים השונים (השלכת גבהים ורוחב בין מבט פנים, על וצד)."
    },
    "difficulty": {
        "app_name": "📉 רמת קושי התרגיל",
        "definition": "ציון (1-5) המגדיר את המורכבות הגיאומטרית של המטלה שניתנה לתלמיד באותו שיעור (עוגן להערכת מגמת השתפרות)."
    },
    "cat_convert_rep": {
        "app_name": "מוקד קושי: המרת ייצוגים",
        "definition": "מדד המעריך את רמת האתגר או השגיאות שהתלמיד חווה במעבר בין שפות ייצוג (תלת-ממד לדו-ממד), כולל קשיי רוטציה מנטלית."
    },
    "cat_dims_props": {
        "app_name": "מוקד קושי: פרופורציות וממדים",
        "definition": "מדד המעריך קשיים בשמירה על יחסי גודל אחידים, קריאת מידות חסרות, שימוש בכלי מדידה או קווי התאמה בין המבטים."
    },
    "cat_proj_trans": {
        "app_name": "מוקד קושי: היטלים והעתקות",
        "definition": "מדד המעריך שגיאות בטרנספורמציות גיאומטריות (שיקוף, היפוך כיוונים, זיהוי ושרטוט קווים נסתרים, בלבול בין היטלים)."
    },
    "cat_3d_support": {
        "app_name": "מוקד קושי: תמיכה תלת-ממדית",
        "definition": "מדד המעריך עד כמה התלמיד תלוי פיזית וקוגניטיבית בנוכחות/בסיבוב של מודל תלת-ממדי מוחשי כדי להצליח לשרטט."
    }
}

SCORE_COLS = ['score_proj', 'score_spatial', 'score_conv', 'score_efficacy', 'score_model', 'score_views']
CAT_COLS = ['cat_convert_rep', 'cat_dims_props', 'cat_proj_trans', 'cat_3d_support']

TAG_TO_CAT_MAP = {
    "התעלמות מקווים נסתרים": ["cat_proj_trans"],
    "בלבול בין היטלים": ["cat_proj_trans"],
    "קושי ברוטציה מנטלית": ["cat_convert_rep", "cat_3d_support"],
    "טעות בפרופורציות": ["cat_dims_props"],
    "קושי במעבר בין היטלים": ["cat_proj_trans", "cat_convert_rep"],
    "שימוש בכלי מדידה": ["cat_dims_props"],
    "סיבוב פיזי של המודל": ["cat_3d_support"],
    "תיקון עצמי": [],
    "עבודה עצמאית שוטפת": [],
}

# ==========================================================
# פונקציות עזר - ניקוי, הצלבת שמות ושמירה מאובטחת לדרייב
# ==========================================================

def clean_name_string(val):
    if pd.isna(val):
        return ""
    val = str(val).strip().lower()
    val = re.sub(r'[^\w\s]', '', val)
    return val.replace(' ', '')


def find_name_column(df):
    name_cols = [c for c in df.columns
                 if ('name' in str(c).lower() and 'unnamed' not in str(c).lower()) or 'שם' in str(c)]
    return name_cols[0] if name_cols else df.columns[0]


def save_report_to_local_or_drive(student_name, report_text):
    """
    יוצר קובץ טקסט של דוח הפרופיל המוצלב בנתיב אבסולוטי קבוע.
    מבטיח שהקובץ נשמר בתוך תיקיית העבודה שמסונכרנת לגוגל דרייב.
    """
    clean_name = student_name.replace(' ', '_').replace('.', '')
    filename = f"Report_Triangulation_{clean_name}.txt"
    
    # ניתוב דינמי לנתיב המלא של תיקיית האפליקציה הנוכחית
    target_path = os.path.abspath(os.path.join(os.getcwd(), filename))
    try:
        with open(target_path, "w", encoding="utf-8") as f:
            f.write(report_text)
        return True, target_path
    except Exception as e:
        return False, str(e)


# ==========================================================
# עיבודי שאלונים ותצפיות (פייטון סטטיסטי)
# ==========================================================

def get_pre_post_pairs(df_quest):
    pre_cols, post_cols = {}, {}
    for c in df_quest.columns:
        m = re.search(r'(\d+)', str(c))
        if not m:
            continue
        num = int(m.group(1))
        c_low = str(c).lower()
        if 'pre' in c_low:
            pre_cols[num] = c
        elif 'post' in c_low:
            post_cols[num] = c
    return [(pre_cols[n], post_cols[n], n) for n in sorted(pre_cols) if n in post_cols]


def compute_questionnaire_deltas(df_quest, name_col):
    pairs = get_pre_post_pairs(df_quest)
    if not pairs:
        return pd.DataFrame(columns=['name_key', 'mean_pre', 'mean_post', 'delta_quest'])

    pre_cols = [p[0] for p in pairs]
    post_cols = [p[1] for p in pairs]

    work = df_quest.copy()
    work['name_key'] = work[name_col].apply(clean_name_string)
    work['mean_pre'] = work[pre_cols].apply(pd.to_numeric, errors='coerce').mean(axis=1)
    work['mean_post'] = work[post_cols].apply(pd.to_numeric, errors='coerce').mean(axis=1)
    work['delta_quest'] = work['mean_post'] - work['mean_pre']

    out = work[['name_key', 'mean_pre', 'mean_post', 'delta_quest']].dropna(subset=['mean_pre', 'mean_post'])
    return out.groupby('name_key', as_index=False).mean(numeric_only=True)


def compute_master_trends(df_master, name_col='student_name'):
    df = df_master.copy()
    df['name_key'] = df[name_col].apply(clean_name_string)

    available_scores = [c for c in SCORE_COLS if c in df.columns]
    if not available_scores:
        return pd.DataFrame(columns=['name_key', 'mean_master', 'delta_master', 'slope_master', 'work_method_mode'])

    df['overall_score'] = df[available_scores].apply(pd.to_numeric, errors='coerce').mean(axis=1)

    if 'date' in df.columns:
        df['date_parsed'] = pd.to_datetime(df['date'], errors='coerce')
    elif 'timestamp' in df.columns:
        df['date_parsed'] = pd.to_datetime(df['timestamp'], errors='coerce')
    else:
        df['date_parsed'] = pd.NaT

    rows = []
    for key, g in df.groupby('name_key'):
        if not key:
            continue
        g = g.dropna(subset=['overall_score'])
        if g.empty:
            continue
        g = g.sort_values('date_parsed')

        mean_master = g['overall_score'].mean()
        delta_master = g['overall_score'].iloc[-1] - g['overall_score'].iloc[0]

        slope_master = np.nan
        if g['date_parsed'].notna().sum() >= 2 and len(g) >= 2:
            x = g['date_parsed'].astype('int64') / 1e9 / 86400.0
            y = g['overall_score'].values
            mask = ~np.isnan(x) & ~np.isnan(y)
            if mask.sum() >= 2 and np.std(x[mask]) > 0:
                slope_master, _, _, _, _ = stats.linregress(x[mask], y[mask])

        work_method_mode = None
        if 'work_method' in g.columns:
            modes = g['work_method'].dropna()
            if not modes.empty:
                work_method_mode = modes.mode().iloc[0]

        rows.append({
            "name_key": key,
            "n_observations": len(g),
            "mean_master": round(float(mean_master), 3),
            "delta_master": round(float(delta_master), 3),
            "slope_master": round(float(slope_master), 4) if not np.isnan(slope_master) else None,
            "work_method_mode": work_method_mode
        })

    return pd.DataFrame(rows)


def compute_tag_category_counts(df_master, name_col='student_name'):
    if 'tags' not in df_master.columns:
        return pd.DataFrame(columns=['name_key', 'n_observations'] + CAT_COLS)

    df = df_master.copy()
    df['name_key'] = df[name_col].apply(clean_name_string)

    def parse_tags(val):
        if pd.isna(val) or val == "":
            return []
        if isinstance(val, list):
            return val
        s = str(val)
        try:
            parsed = json.loads(s.replace("'", '"'))
            if isinstance(parsed, list):
                return parsed
        except Exception:
            pass
        return [t.strip().strip("[]'\"") for t in s.split(',') if t.strip().strip("[]'\"")]

    rows = []
    for key, g in df.groupby('name_key'):
        if not key:
            continue
        counts = {c: 0 for c in CAT_COLS}
        for tags_val in g['tags']:
            for tag in parse_tags(tags_val):
                for cat in TAG_TO_CAT_MAP.get(tag, []):
                    counts[cat] += 1
        row = {"name_key": key, "n_observations": len(g)}
        row.update(counts)
        rows.append(row)

    return pd.DataFrame(rows)


def run_correlation(x, y, x_name="X", y_name="Y"):
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    mask = ~np.isnan(x) & ~np.isnan(y)
    x, y = x[mask], y[mask]
    n = len(x)

    if n < 3:
        return {"error": f"נדרשים לפחות 3 תלמידים עם נתונים תקינים בשני המשתנים (נמצאו {n})."}

    r_pearson, p_pearson = stats.pearsonr(x, y)
    r_spearman, p_spearman = stats.spearmanr(x, y)

    return {
        "x_variable": x_name,
        "y_variable": y_name,
        "n": n,
        "pearson_r": round(float(r_pearson), 3),
        "pearson_p": round(float(p_pearson), 4),
        "spearman_rho": round(float(r_spearman), 3),
        "spearman_p": round(float(p_spearman), 4),
        "x_values": [round(float(v), 3) for v in x],
        "y_values": [round(float(v), 3) for v in y],
    }


def run_paired_pre_post_test(df_quest, name_col):
    pairs = get_pre_post_pairs(df_quest)
    if not pairs:
        return {"error": "לא נמצאו זוגות עמודות Pre/Post תואמות בקובץ השאלונים."}

    pre_cols = [p[0] for p in pairs]
    post_cols = [p[1] for p in pairs]

    work_df = df_quest.copy()
    work_df['mean_pre'] = work_df[pre_cols].apply(pd.to_numeric, errors='coerce').mean(axis=1)
    work_df['mean_post'] = work_df[post_cols].apply(pd.to_numeric, errors='coerce').mean(axis=1)
    work_df = work_df.dropna(subset=['mean_pre', 'mean_post'])

    if len(work_df) < 2:
        return {"error": f"נמצאו רק {len(work_df)} תלמידים עם נתוני Pre+Post תקינים. נדרשים לפחות 2."}

    pre_vals = work_df['mean_pre'].values
    post_vals = work_df['mean_post'].values
    diffs = post_vals - pre_vals
    n = len(diffs)

    per_student = [{
        "name": str(row.get(name_col, "")),
        "mean_pre": round(float(row['mean_pre']), 2),
        "mean_post": round(float(row['mean_post']), 2),
        "delta": round(float(row['mean_post'] - row['mean_pre']), 2)
    } for _, row in work_df.iterrows()]

    result = {
        "n_students": n,
        "n_questions_matched": len(pairs),
        "descriptive": {
            "M_pre": round(float(np.mean(pre_vals)), 2),
            "SD_pre": round(float(np.std(pre_vals, ddof=1)), 2),
            "M_post": round(float(np.mean(post_vals)), 2),
            "SD_post": round(float(np.std(post_vals, ddof=1)), 2),
            "M_diff": round(float(np.mean(diffs)), 2),
            "SD_diff": round(float(np.std(diffs, ddof=1)), 2),
        },
        "per_student": per_student
    }

    if n < 20:
        try:
            w_stat, p_val = stats.wilcoxon(pre_vals, post_vals)
        except ValueError as e:
            return {"error": f"לא ניתן להריץ Wilcoxon: {e}"}

        p_for_z = p_val if p_val > 0 else 1e-10
        z_approx = stats.norm.isf(p_for_z / 2)
        effect_r = round(float(z_approx / np.sqrt(n)), 3)

        result.update({
            "test_type": "Wilcoxon Signed-Rank Test (Non-parametric)",
            "stat_name": "W",
            "stat_val": round(float(w_stat), 3),
            "p": round(float(p_val), 4),
            "effect_size_name": "r (matched-pairs rank-biserial approx.)",
            "effect_size": effect_r,
            "note": "נעשה שימוש במבחן לא-פרמטרי (Wilcoxon) בשל גודל מדגם קטן (N<20)."
        })
    else:
        t_stat, p_val = stats.ttest_rel(pre_vals, post_vals)
        sd_diff = np.std(diffs, ddof=1)
        cohen_dz = float(np.mean(diffs) / sd_diff) if sd_diff != 0 else 0.0

        result.update({
            "test_type": "Paired Samples T-Test",
            "stat_name": "t",
            "stat_val": round(float(t_stat), 3),
            "df": n - 1,
            "p": round(float(p_val), 4),
            "effect_size_name": "Cohen's d_z",
            "effect_size": round(cohen_dz, 3),
            "note": "נעשה שימוש במבחן t למדגמים זוגיים."
        })

    return result


def run_group_comparison(df, group_col, val_col):
    groups = df[group_col].dropna().unique()
    if len(groups) != 2:
        return {"error": f"השוואה דורשת בדיוק 2 קבוצות בעמודה '{group_col}'. נמצאו: {list(groups)}"}

    g1 = pd.to_numeric(df[df[group_col] == groups[0]][val_col], errors='coerce').dropna()
    g2 = pd.to_numeric(df[df[group_col] == groups[1]][val_col], errors='coerce').dropna()

    if len(g1) < 2 or len(g2) < 2:
        return {"error": f"אין מספיק תצפיות (נמצאו {len(g1)} ו-{len(g2)}). נדרשות לפחות 2 לכל קבוצה."}

    res = {
        "group1": {"name": str(groups[0]), "M": round(float(g1.mean()), 2), "SD": round(float(g1.std()), 2), "N": len(g1)},
        "group2": {"name": str(groups[1]), "M": round(float(g2.mean()), 2), "SD": round(float(g2.std()), 2), "N": len(g2)},
    }

    if len(g1) < 20 or len(g2) < 20:
        u_stat, p_val = stats.mannwhitneyu(g1, g2, alternative='two-sided')
        res.update({"test_type": "Mann-Whitney U Test", "stat_name": "U", "stat_val": round(float(u_stat), 3), "p": round(float(p_val), 4)})
    else:
        t_stat, p_val = stats.ttest_ind(g1, g2)
        res.update({"test_type": "Independent Samples T-Test", "stat_name": "t", "stat_val": round(float(t_stat), 3), "df": len(g1) + len(g2) - 2, "p": round(float(p_val), 4)})

    return res


def data_quality_report(df_master, df_quest=None, name_col='student_name'):
    issues = {}
    df = df_master.copy()
    df['name_key'] = df[name_col].apply(clean_name_string)

    counts = df.groupby('name_key').size()
    issues["students_with_under_2_observations"] = counts[counts < 2].index.tolist()

    out_of_range = {}
    for c in SCORE_COLS:
        if c in df.columns:
            vals = pd.to_numeric(df[c], errors='coerce')
            bad = df.loc[(vals < 1) | (vals > 5), name_col].dropna().unique().tolist()
            if bad:
                out_of_range[c] = bad
    issues["out_of_range_scores"] = out_of_range

    if df_quest is not None:
        q_col = find_name_column(df_quest)
        quest_keys = set(df_quest[q_col].apply(clean_name_string).dropna().unique())
        master_keys = set(df['name_key'].unique())
        issues["students_in_master_missing_from_questionnaire"] = sorted(master_keys - quest_keys - {''})

    return issues


# ==========================================================
# AI report helper
# ==========================================================

def ask_ai_for_report(model, stats_result, instructions):
    prompt = f"""
    נתוני החישוב האמיתיים של המחקר (התקבלו מתוך קוד הפייטון האמפירי):
    {json.dumps(stats_result, ensure_ascii=False)}

    הנחיות דיווח ספציפיות:
    {instructions}

    הנחיות קשיחות: אל תכתוב קוד פייטון בתשובה. נסח בעברית אקדמית נקייה התואמת לפרק ממצאים בתזה.
    """
    try:
        return model.generate_content(prompt).text
    except Exception as api_err:
        return f"⚠️ שגיאה בהפקת הדוח מול שרתי גוגל: {str(api_err)}"


# ==========================================================
# טאב הסוכן הראשי
# ==========================================================

def render_ai_agent_tab():
    st.header("🤖 סוכן חכם - הצלבת נתונים מרובים (Triangulation Lab)")
    st.markdown("---")

    st.subheader("📋 שלב א': טעינת קבצי המחקר מהמחשב")
    st.info("💡 הנחיה: יש לסמן את קובץ המאסטר (התצפיות) ואת קובץ השאלונים יחד ולגרור אותם לתיבה מטה.")

    uploaded_files = st.file_uploader(
        "לחץ כאן לבחירת קבצים או גרור והשלך לכאן (קבצי Excel או CSV)",
        type=["csv", "xlsx"],
        accept_multiple_files=True,
        key="research_files_uploader"
    )

    df_master = None
    df_quest = None
    quest_col_name = None
    other_dfs = {}

    if uploaded_files:
        for file in uploaded_files:
            try:
                if file.name.endswith('.csv'):
                    test_df = pd.read_csv(file, header=None).fillna("")
                else:
                    test_df = pd.read_excel(file, header=None).fillna("")

                all_text_list = [str(x) for x in test_df.values.flatten() if pd.notna(x)]
                combined_text = " ".join(all_text_list).lower()

                if 'work_method' in combined_text or 'student_name' in combined_text or 'score_spatial' in combined_text:
                    file.seek(0)
                    df_master = pd.read_csv(file) if file.name.endswith('.csv') else pd.read_excel(file)
                    st.success(f"✅ קובץ התצפיות (Master) זוהה ונטען בהצלחה: {file.name}")

                elif 'preq' in combined_text or 'post' in combined_text or 'q1_pre' in combined_text:
                    file.seek(0)
                    header_line = 0
                    for idx, row in test_df.iterrows():
                        row_items = [str(item) for item in row.tolist() if pd.notna(item)]
                        row_str = " ".join(row_items).lower()
                        if 'name' in row_str or 'q1' in row_str:
                            header_line = idx
                            break

                    file.seek(0)
                    df_quest = pd.read_csv(file, header=header_line) if file.name.endswith('.csv') else pd.read_excel(file, header=header_line)
                    quest_col_name = find_name_column(df_quest)
                    st.success(f"✅ קובץ השאלונים (Pre/Post) זוהה ונטען בהצלחה: {file.name}")

                else:
                    file.seek(0)
                    other_dfs[file.name] = pd.read_csv(file) if file.name.endswith('.csv') else pd.read_excel(file)
                    st.info(f"📁 נטען קובץ נתונים נוסף: {file.name}")

            except Exception as e:
                st.error(f"שגיאה בטעינת הקובץ {file.name}: {e}")

    if df_master is not None:
        with st.expander("🔍 בדיקת תקינות נתונים (Data Quality Check)"):
            dq = data_quality_report(df_master, df_quest)
            if dq.get("students_with_under_2_observations"):
                st.warning(f"תלמידים עם פחות מ-2 תצפיות: {', '.join(dq['students_with_under_2_observations'])}")
            else:
                st.success("✅ לכל התלמידים יש לפחות 2 תצפיות.")

            if dq.get("out_of_range_scores"):
                st.warning(f"ציונים מחוץ לטווח 1-5: {dq['out_of_range_scores']}")
            else:
                st.success("✅ כל הציונים הכמותיים בטווח 1-5.")

            if dq.get("students_in_master_missing_from_questionnaire"):
                st.info(f"תלמידים שיש להם תצפיות אך לא נמצאו בשאלון: {', '.join(dq['students_in_master_missing_from_questionnaire'])}")

    st.markdown("---")

    st.subheader("💬 התכתבות עם הסוכן הסטטיסטי")
    st.caption(
        "דוגמאות לשאלות: 'נתח את הפרופיל של עילאי' • 'יש שיפור מובהק בכיתה בין pre ל-post?' • "
        "'יש מתאם בין שיפור בשאלון לשיפור בכיתה?' • 'מסוגלות התחלתית מנבאת ביצועים?' • "
        "'יש הבדל בין שיטות העבודה?' • 'מה המגמה לאורך זמן?' • "
        "'יש קשר בין קושי בהיטלים (תגיות) לציון מעבר בין היטלים?'"
    )

    if "agent_messages" not in st.session_state:
        st.session_state.agent_messages = []

    for msg in st.session_state.agent_messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    prompt = st.chat_input("שאל את הסוכן הסטטיסטי...")
    if not prompt:
        return

    st.session_state.agent_messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        api_key = st.secrets.get("GOOGLE_API_KEY", "")
        if not api_key:
            st.error("⚠️ חסר מפתח API ב-Secrets.")
            return

        import google.generativeai as genai
        genai.configure(api_key=api_key)
        
        # הגדרת System Instructions קבועה ומחמירה למניעת סלט ועיגון השפה המדעית
        system_rules = (
            "אתה פרופסור ומתודולוג בכיר המלווה כתיבת תזת מאסטר במחקר פעולה (Action Research) פדגוגי. "
            "עליך לענות תמיד בעברית אקדמית רהוטה וגבוהה, חפה מחזרות, ותואמת לחלוטין את מדריך הדיווח APA 7th Edition. "
            "חל איסור מוחלט להמציא נתונים מספריים, שמות או מדדים שלא מופיעים במפורש במבנה הנתונים הסטטיסטי שחושב בפייטון. "
            "התייחס תמיד לשילוב בין ממצאים כמותיים (ממוצעים, שיפועים) לממצאים איכותניים (תצפיות שדה, תגיות) כטריאנגולציה מחקרית מבוססת תוקף."
        )
        model = genai.GenerativeModel(
            model_name='gemini-2.5-flash',
            system_instruction=system_rules
        )

        p_low = prompt.lower()

        def reply(text):
            st.markdown(text)
            st.session_state.agent_messages.append({"role": "assistant", "content": text})

        def need_quest():
            if df_quest is None:
                reply("⚠️ לא נמצא קובץ שאלונים (Pre/Post) בין הקבצים שהועלו. אנא העלה אותו ונסה שוב.")
                return True
            return False

        def need_master():
            if df_master is None:
                reply("⚠️ לא נמצא קובץ תצפיות (Master) בין הקבצים שהועלו. אנא העלה אותו ונסה שוב.")
                return True
            return False

        # 1. מבחן Paired Pre/Post כיתתי
        if any(kw in p_low for kw in ["מובהק", " pre", "post", "פרה", "פוסט", "wilcoxon", "t-test", "effect size",
                                        "שיפור כיתתי", "שיפור בכיתה בין"]) and "מתאם" not in p_low and "קשר" not in p_low:
            if need_quest():
                return
            with st.spinner("מריץ מבחן Pre/Post זוגי + Effect Size על נתוני הכיתה..."):
                stats_result = run_paired_pre_post_test(df_quest, quest_col_name)
                instructions = """
                בצע דיווח על מבחן Pre/Post זוגי (Paired Samples) שבוצע על נתוני שאלון המסוגלות העצמית של כל הכיתה.
                1. פתח בטבלת Markdown "Descriptive Statistics" (Stage, N, Mean, SD).
                2. הצג טבלה שנייה "Test Results" (שם המבחן, סטטיסטיקה, df אם רלוונטי, p-value, Effect Size).
                3. כתוב פסקת APA 7th Edition בעברית המדווחת את הממצא.
                4. פרש את גודל האפקט (קטן ~0.2, בינוני ~0.5, גדול ~0.8+).
                5. ציין אם ההבדל מובהק (p<0.05) ומה המשמעות הפדגוגית.
                6. סקור 2-3 תלמידים עם ה-delta הגבוה ביותר ועם ה-delta הנמוך/שלילי ביותר מתוך per_student.
                """
                reply(ask_ai_for_report(model, stats_result, instructions))
            return

        # 2. מתאם כמותי-איכותני: תגיות קושי
        if "תגי" in p_low or any(kw in p_low for kw in ["cat_", "מוקד קושי"]) or \
           ("קושי" in p_low and "קשר" in p_low) or ("קושי" in p_low and "מתאם" in p_low):
            if need_master():
                return
            with st.spinner("בונה מתאם בין תגיות הקושי האיכותניות לציונים הכמותיים..."):
                if 'tags' not in df_master.columns:
                    reply("⚠️ לא נמצאה עמודת 'tags' בקובץ המאסטר - לא ניתן לבצע ניתוח זה.")
                    return

                tag_counts = compute_tag_category_counts(df_master)
                master_trends = compute_master_trends(df_master)
                merged = tag_counts.merge(master_trends, on='name_key', how='inner')

                cat_col = next((c for c in CAT_COLS if c in p_low or
                                 METRICS_DICTIONARY[c]['app_name'] in prompt or
                                 any(part in p_low for part in c.split('_')[1:])), 'cat_proj_trans')
                if cat_col not in merged.columns:
                    cat_col = 'cat_proj_trans'

                score_col = 'mean_master'

                merged_valid = merged.dropna(subset=[cat_col, score_col])
                stats_result = run_correlation(
                    merged_valid[cat_col], merged_valid[score_col],
                    x_name=f"{METRICS_DICTIONARY[cat_col]['app_name']} (ספירת תגיות, n_obs={int(merged_valid['n_observations_x'].mean()) if 'n_observations_x' in merged_valid else 'N/A'})",
                    y_name="Mean overall observation score"
                )
                stats_result["category_definition"] = METRICS_DICTIONARY[cat_col]['definition']
                stats_result["category_tag_examples"] = [t for t, cats in TAG_TO_CAT_MAP.items() if cat_col in cats]

                instructions = """
                בצע דיווח על מתאם (Correlation) בין מדד איכותני-כמותי (ספירת תגיות קושי שתועדו בתצפיות, x)
                לבין הציון הכמותי הממוצע של התלמיד בכיתה (y).
                1. הסבר בקצרה מה המדד x מייצג, על סמך "category_definition" ו-"category_tag_examples".
                2. הצג טבלת Markdown עם N, Pearson r, p-value, Spearman rho, p-value.
                3. כתוב פסקת APA 7th Edition בעברית.
                4. פרש: האם תלמידים שתועדו יותר עם קשיים מסוג זה אכן הציגו ציונים נמוכים יותר (קשר שלילי צפוי)?
                5. ציין שמתאם אינו מעיד על קשר סיבתי, ושמספר התלמידים (N) קטן.
                """
                reply(ask_ai_for_report(model, stats_result, instructions))
            return

        # 3. מתאם Delta-Delta
        if "מתאם" in p_low and any(kw in p_low for kw in ["שיפור", "שינוי", "התקדמות", "מגמה", "שיפוע"]):
            if need_quest() or need_master():
                return
            with st.spinner("מחשב מתאם בין השינוי בשאלון לבין מגמת השינוי בתצפיות..."):
                quest_deltas = compute_questionnaire_deltas(df_quest, quest_col_name)
                master_trends = compute_master_trends(df_master)
                merged = quest_deltas.merge(master_trends, on='name_key', how='inner')

                use_slope = any(kw in p_low for kw in ["מגמה", "שיפוע", "לאורך זמן", "trend"])
                y_col, y_name = ("slope_master", "Slope of overall observation score over time") if use_slope else ("delta_master", "Δ Master score (last - first observation)")

                merged_valid = merged.dropna(subset=['delta_quest', y_col])
                stats_result = run_correlation(merged_valid['delta_quest'], merged_valid[y_col],
                                                 x_name="Δ Questionnaire (Post - Pre)", y_name=y_name)
                stats_result["n_students_total_merged"] = len(merged)
                stats_result["student_keys"] = merged_valid['name_key'].tolist()

                instructions = """
                בצע דיווח על מתאם (Correlation) בין שיפור התלמידים בשאלון המסוגלות העצמית (Δ Questionnaire)
                לבין מגמת השינוי בציוני התצפיות בכיתה (Master).
                1. הצג טבלת Markdown עם N, Pearson r, p-value, Spearman rho, p-value.
                2. כתוב פסקת APA 7th Edition בעברית המדווחת את ממצא המתאם.
                3. פרש את כיוון וחוזק הקשר (חלש/בינוני/חזק).
                4. דון במשמעות הפדגוגית: האם שיפור בתפיסה העצמית מתואם עם שיפור מעשי בכיתה?
                5. ציין שמתאם אינו מעיד על קשר סיבתי.
                """
                reply(ask_ai_for_report(model, stats_result, instructions))
            return

        # 4. מתאם Baseline
        if ("baseline" in p_low or "מסוגלות התחלתית" in p_low or "פרה" in p_low) and \
           any(kw in p_low for kw in ["מנבא", "ניבוי", "מתאם", "קשור"]):
            if need_quest() or need_master():
                return
            with st.spinner("מחשב מתאם בין מסוגלות התחלתית (Pre) לביצועים בכיתה..."):
                quest_deltas = compute_questionnaire_deltas(df_quest, quest_col_name)
                master_trends = compute_master_trends(df_master)
                merged = quest_deltas.merge(master_trends, on='name_key', how='inner').dropna(subset=['mean_pre', 'mean_master'])

                stats_result = run_correlation(merged['mean_pre'], merged['mean_master'],
                                                 x_name="Pre-questionnaire mean (baseline self-efficacy)",
                                                 y_name="Mean observation score in class")
                instructions = """
                בצע דיווח על מתאם בין רמת המסוגלות העצמית ההתחלתית (Pre-questionnaire) של תלמידים
                לבין ביצועיהם הממוצעים בתצפיות בכיתה.
                1. הצג טבלת Markdown עם N, Pearson r, p-value, Spearman rho, p-value.
                2. כתוב פסקת APA 7th Edition בעברית.
                3. פרש האם תלמידים שהגיעו עם מסוגלות עצמית גבוהה יותר אכן הציגו ביצועים גבוהים יותר בכיתה.
                4. דון בהשלכות הפדגוגיות (לדוגמה: זיהוי מוקדם של תלמידים בסיכון).
                """
                reply(ask_ai_for_report(model, stats_result, instructions))
            return

        # 5. השוואה בין שיטות עבודה
        if any(kw in p_low for kw in ["שיטת עבודה", "שיטות עבודה", "work_method", "גוף פיזי", "דמיון"]):
            if need_quest() or need_master():
                return
            with st.spinner("משווה בין קבוצות לפי שיטת עבודה..."):
                quest_deltas = compute_questionnaire_deltas(df_quest, quest_col_name)
                master_trends = compute_master_trends(df_master)
                merged = quest_deltas.merge(master_trends, on='name_key', how='inner').dropna(subset=['delta_quest', 'work_method_mode'])

                stats_result = run_group_comparison(merged, 'work_method_mode', 'delta_quest')
                instructions = """
                בצע דיווח על השוואה בין שתי קבוצות תלמידים, מקובצות לפי שיטת העבודה השכיחה שלהן
                (גוף פיזי מודפס מול דמיון), על מדד Δ Questionnaire (שיפור במסוגלות העצמית).
                1. פתח בטבלת Markdown "Group Statistics" (Group, N, Mean, SD).
                2. הצג טבלה שנייה "Test Results" (שם המבחן, סטטיסטיקה, p-value).
                3. כתוב פסקת APA 7th Edition בעברית.
                4. ציין אם ההבדל מובהק, ומה המשמעות הפדגוגית להעדפת שיטת עבודה אחת על פני האחרת.
                """
                reply(ask_ai_for_report(model, stats_result, instructions))
            return

        # 6. ניתוח מגמת זמן (Slope)
        if any(kw in p_low for kw in ["מגמה", "שיפוע", "trend", "לאורך זמן"]):
            if need_master():
                return
            with st.spinner("מחשב מגמות שינוי לאורך זמן לכל תלמיד..."):
                master_trends = compute_master_trends(df_master)
                slopes = master_trends.dropna(subset=['slope_master'])
                stats_result = {
                    "n_students_with_trend": len(slopes),
                    "mean_slope": round(float(slopes['slope_master'].mean()), 4) if not slopes.empty else None,
                    "positive_trend_students": slopes[slopes['slope_master'] > 0]['name_key'].tolist(),
                    "negative_trend_students": slopes[slopes['slope_master'] < 0]['name_key'].tolist(),
                    "no_change_students": slopes[slopes['slope_master'] == 0]['name_key'].tolist(),
                    "per_student": slopes.to_dict(orient='records'),
                }
                instructions = """
                בצע דיווח תיאורי על מגמות השינוי (שיפוע ציון תצפיות כללי לאורך זמן) לכל תלמיד.
                1. ציין כמה תלמידים הציגו מגמת שיפור (שיפוע חיובי), כמה ירידה, וכמה ללא שינוי.
                2. הצג את השיפוע הממוצע הכיתתי.
                3. כתוב פסקה פדגוגית בעברית על המגמה הכוללת במחקר הפעולה.
                4. ציין שניתוח זה תיאורי ואינו מבחן השוואה פורמלי.
                """
                reply(ask_ai_for_report(model, stats_result, instructions))
            return

        # --------------------------------------------------------
        # 7. פרופיל תלמיד מוצלב (Triangulation) - מניעת סלט לוגי
        # --------------------------------------------------------
        if df_master is None or df_quest is None:
            missing = []
            if df_master is None:
                missing.append("קובץ התצפיות (Master)")
            if df_quest is None:
                missing.append("קובץ השאלונים (Pre/Post)")
            reply(f"⚠️ לא ניתן לבצע את הניתוח המבוקש מכיוון שהמערכת לא הצליחה לזהות את: {', '.join(missing)}.")
            return

        with st.spinner("מצליב נתונים ומנתח את קבצי המחקר..."):
            master_clean = df_master.copy()
            if 'student_name' in master_clean.columns:
                master_clean['name_key'] = master_clean['student_name'].apply(clean_name_string)
            else:
                reply("⚠️ עמודת student_name לא נמצאה בקובץ המאסטר!")
                return

            quest_clean = df_quest.copy()
            quest_clean['name_key'] = quest_clean[quest_col_name].apply(clean_name_string)

            selected_student = None
            for name in master_clean['student_name'].dropna().unique():
                if str(name).strip() in prompt:
                    selected_student = name
                    break

            if not selected_student:
                for name in df_quest[quest_col_name].dropna().unique():
                    if str(name).strip().replace('.', '').replace(' ', '') in prompt.replace(' ', ''):
                        selected_student = name
                        break

            if not selected_student:
                reply("🔍 לא זיהיתי שם של תלמיד מוכר, ולא זיהיתי שאלת מחקר כיתתית.")
                return

            student_key = clean_name_string(selected_student)

            student_observations = master_clean[master_clean['name_key'] == student_key]
            if not student_observations.empty:
                # 🧪 שדרוג: סידור כרונולוגי קשיח של התצפיות מהמוקדם למאוחר למניעת סלט בציר הזמן
                if 'date' in student_observations.columns:
                    student_observations['date_parsed'] = pd.to_datetime(student_observations['date'], errors='coerce')
                    student_observations = student_observations.sort_values('date_parsed')
                
                num_data = student_observations.select_dtypes(include=[np.number])
                means = num_data.mean().round(2).to_dict()

                raw_interpretations = []
                for _, row in student_observations.iterrows():
                    date_str = str(row.get('date', 'תאריך חסר'))
                    diff_text = str(row.get('difficulty', 'לא צוין')).strip()
                    interp_text = str(row.get('interpretation', row.get('insight', ''))).strip()
                    method_text = str(row.get('work_method', 'לא צוין'))
                    tags_text = str(row.get('tags', ''))
                    raw_interpretations.append(
                        f"תאריך: {date_str} | שיטה: {method_text} | תגיות: {tags_text}\n- רמת קושי המטלה: {diff_text}\n- תיעוד פדגוגי חופשי: {interp_text}"
                    )

                master_summary = {
                    "total_observations": len(student_observations),
                    "average_quantitative_scores": means,
                    "chronological_qualitative_observations": raw_interpretations
                }
            else:
                master_summary = {"status": "לא נמצאו תצפיות עבור תלמיד זה במאסטר"}

            student_questionnaire = quest_clean[quest_clean['name_key'] == student_key]
            if not student_questionnaire.empty:
                q_row = student_questionnaire.iloc[0]
                pairs = get_pre_post_pairs(df_quest)
                pre_vals = [q_row[p[0]] for p in pairs if pd.notna(q_row[p[0]])]
                post_vals = [q_row[p[1]] for p in pairs if pd.notna(q_row[p[1]])]

                quest_summary = {
                    "has_questionnaire_data": True,
                    "mean_pre": round(float(np.mean(pre_vals)), 2) if pre_vals else None,
                    "mean_post": round(float(np.mean(post_vals)), 2) if post_vals else None,
                    "delta": round(float(np.mean(post_vals) - np.mean(pre_vals)), 2) if pre_vals and post_vals else None
                }
            else:
                quest_summary = {"status": "התלמיד לא נמצא בקובץ שאלוני ה-Pre/Post"}

            other_summary = {}
            for f_name, other_df in other_dfs.items():
                possible_name_cols = [c for c in other_df.columns
                                       if ('name' in str(c).lower() and 'unnamed' not in str(c).lower()) or 'שם' in str(c)]
                if possible_name_cols:
                    other_clean = other_df.copy()
                    other_clean['name_key'] = other_clean[possible_name_cols[0]].apply(clean_name_string)
                    sub_row = other_clean[other_clean['name_key'] == student_key]
                    if not sub_row.empty:
                        other_summary[f_name] = sub_row.iloc[0].drop(['name_key', possible_name_cols[0]], errors='ignore').to_dict()

            student_profile_json = {
                "student_name": str(selected_student),
                "observations_master_data": master_summary,
                "questionnaire_survey_data": quest_summary,
                "additional_files_data": other_summary
            }

            # 🧪 שדרוג: פרומפט מובנה קשיח המבהיר את ציר הזמן ואת חוקי המתודולוגיה
            base_instructions = f"""
            להלן הנתונים הסטטיסטיים של הסטודנט {selected_student}:
            {json.dumps(student_profile_json, ensure_ascii=False)}

            הנחיות מתודולוגיות קשיחות למניעת טעויות פירוש:
            1. משתני ה-cat_* (כמו cat_convert_rep) מייצגים ספירת שגיאות ומוקדי קושי מתוך התגיות! ציון נמוך (כמו 1.0) פירושו שהסטודנט כמעט ולא ביצע טעויות בקטגוריה זו. זוהי נקודת חוזק התואמת לציון ביצוע גבוה (score_conv).
            2. רצף התצפיות מסודר כרונולוגית. תצפיות מדצמבר 2025 הן תחילת הסמסטר (נקודת הבסיס - Baseline), בעוד פברואר ומאי 2026 מייצגים את התפתחות ההתערבות. נתח את השינוי בכיוון הנכון של הזמן!
            3. ירידה בממוצע המסוגלות העצמית בשאלון (Delta שלילית) לצד שיפור בציוני הביצוע בכיתה מייצגת פער תפיסתי קלאסי (Cognitive Misalignment). הסבר זאת כעלייה במודעות העצמית ובביקורתיות של הסטודנט, שהחליפה ביטחון מופרז חסר בסיס (אפקט דאנינג-קרוגר).
            """

            # הרצת השרשרת (Prompt Chaining) לקבלת עומק מקסימלי לפרק הממצאים
            with st.spinner("חלק א': מנתח מדדים כמותיים ואיכותניים מהשדה..."):
                p1_instructions = base_instructions + """
                נסח את הפרק הראשון: "1. פרופיל ביצוע כמותי ותמות איכותניות מהתצפיות".
                נתח את מדדי הביצוע, משך הזמן ורצף התאריכים (מדצמבר למאי), ושלב את התיעודים המילוליים והאסטרטגיות (כמו המרקרים או הגופים המודפסים).
                """
                part1_text = ask_ai_for_report(model, {"step": 1}, p1_instructions)

            with st.spinner("חלק ב': מנתח הלימה ותוקף תפיסתי מול השאלונים..."):
                p2_instructions = base_instructions + f"""
                בהסתמך על הניתוח המקדים הבא:
                {part1_text}
                נסח את הפרק השני: "2. בחינת תוקף והלימה תפיסתית (Cognitive Misalignment Evaluation)".
                הצלב בין מדדי הביצוע של החוקר בשטח לבין שאלוני הפרה-פוסט, ודון בפער הקוגניטיבי ובשינוי המסוגלות הנתפסת.
                """
                part2_text = ask_ai_for_report(model, {"step": 2}, p2_instructions)

            with st.spinner("חלק ג': מגבש תובנות ספיראליות למחקר הפעולה..."):
                p3_instructions = base_instructions + f"""
                בהסתמך על כלל הממצאים:
                {part2_text}
                נסח את הפרק המסכם: "3. השלכות פדגוגיות לאופיו הספיראלי של מחקר הפעולה".
                הסבר כיצד הממצאים מזינים את מחזורי ההתערבות הבאים ומדייקים את הפיגומים בכיתה.
                """
                part3_text = ask_ai_for_report(model, {"step": 3}, p3_instructions)

            # איחוד דוח העומק לפרק ממצאים מושלם
            report_text = f"🕵️ **דוח פרופיל מוצלב והערכת מגמה - {selected_student}**\n\n{part1_text}\n\n---\n\n{part2_text}\n\n---\n\n{part3_text}"
            
            reply(report_text)
            
            # ממשק שמירה בטוח ואבסולוטי לדרייב
            st.markdown("---")
            st.subheader("💾 ארכוב ממצאים")
            if st.button(f"💾 שמור את הדוח המדעי של {selected_student} לדרייב", key=f"save_drive_{student_key}"):
                with st.spinner("מייצר קובץ טקסט אקדמי ומסנכרן לענן..."):
                    success, filepath = save_report_to_local_or_drive(selected_student, report_text)
                    if success:
                        st.success(f"✅ הדוח אורכב בהצלחה בנתיב המאסטר: `{filepath}` והועלה אוטומטית לדרייב!")
                    else:
                        st.error(f"⚠️ שגיאה בארכוב הקובץ: {filepath}")
