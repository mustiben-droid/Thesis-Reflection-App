def load_full_dataset(svc):
    df_drive = pd.DataFrame()
    if svc:
        try:
            res = svc.files().list(q=f"name = '{MASTER_FILENAME}' and trashed = false", 
                                 supportsAllDrives=True, includeItemsFromAllDrives=True).execute().get('files', [])
            if res:
                fh = io.BytesIO()
                downloader = MediaIoBaseDownload(fh, svc.files().get_media(fileId=res[0]['id']))
                done = False
                while not done: _, done = downloader.next_chunk()
                fh.seek(0)
                df_drive = pd.read_excel(fh)
                
                # --- תיקון השגיאה: הסרת עמודות כפולות מהאקסל ---
                df_drive = df_drive.loc[:, ~df_drive.columns.duplicated()]
                
                mapping = {'score_conv': 'cat_convert_rep', 'score_proj': 'cat_proj_trans', 
                           'score_model': 'cat_3d_support', 'score_efficacy': 'cat_self_efficacy'}
                df_drive = df_drive.rename(columns=mapping)
        except Exception as e:
            logger.error(f"Drive load failed: {e}")

    df_local = pd.DataFrame()
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                df_local = pd.DataFrame([json.loads(l) for l in f if l.strip()])
            # --- תיקון השגיאה: הסרת עמודות כפולות מהקובץ המקומי ---
            df_local = df_local.loc[:, ~df_local.columns.duplicated()]
        except: pass

    # וידוא ששני ה-DataFrames לא ריקים לפני איחוד
    if df_drive.empty and df_local.empty:
        return pd.DataFrame()
        
    try:
        # איחוד זהיר
        df = pd.concat([df_drive, df_local], ignore_index=True)
        # ניקוי סופי של עמודות כפולות שנוצרו באיחוד
        df = df.loc[:, ~df.columns.duplicated()]
        
        if not df.empty and 'student_name' in df.columns:
            df = df.dropna(subset=['student_name'])
            df['name_clean'] = df['student_name'].apply(lambda x: str(x).replace(" ", "").replace(".", "").strip())
        return df
    except Exception as e:
        st.error(f"שגיאת איחוד נתונים: {e}")
        return df_drive if not df_drive.empty else df_local
