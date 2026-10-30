import streamlit as st
import pandas as pd
from datetime import timedelta, date, datetime
import io
import plotly.express as px
import firebase_admin
from firebase_admin import credentials, firestore
from streamlit_cookies_controller import CookieController

# --- HELPER FUNCTION TO CLEAN NUMBERS ---
def clean_numeric(val):
    if pd.isnull(val): return 0.0
    val_str = str(val).replace(',', '').replace(' ', '').replace('L', '').replace('l', '').replace('ltr', '')
    try: return float(val_str)
    except: return 0.0

# --- 1. SECURITY & LOGIN ---
controller = CookieController()
cookie_expiry = datetime.now() + timedelta(days=30)

if controller.get('logged_in') == 'true':
    st.session_state.logged_in = True
    st.session_state.role = controller.get('role') or 'Team'

if 'logged_in' not in st.session_state or not st.session_state.logged_in:
    st.title("🔒 Access Portal")
    tab1, tab2 = st.tabs(["👥 Team Access", "🔑 Admin Login"])
    with tab1:
        st.write("Load data, add waybills, and view basic supply metrics. (No password required)")
        if st.button("Enter as Team"):
            st.session_state.logged_in = True
            st.session_state.role = 'Team'
            controller.set('logged_in', 'true', expires=cookie_expiry)
            controller.set('role', 'Team', expires=cookie_expiry)
            st.rerun()
    with tab2:
        st.write("Full access to analytics, editing, and database management.")
        password = st.text_input("Enter Admin Password", type="password")
        if st.button("Login as Admin"):
            if password == "admin123": 
                st.session_state.logged_in = True
                st.session_state.role = 'Admin'
                controller.set('logged_in', 'true', expires=cookie_expiry)
                controller.set('role', 'Admin', expires=cookie_expiry)
                st.rerun()
            else: st.error("Incorrect password.")
    st.stop()

# --- 2. PAGE CONFIG ---
st.set_page_config(page_title="Supply & CPD Tracker", layout="wide")
st.title(" Supply & CPD Tracker App")

if st.session_state.role == 'Admin': 
    st.sidebar.success("🔑 Logged in as Admin")
else: 
    st.sidebar.info("👥 Logged in as Team Member")

if st.sidebar.button("Logout"):
    st.session_state.logged_in = False
    st.session_state.role = None
    controller.remove('logged_in')
    controller.remove('role')
    st.rerun()

# --- 3. FIREBASE CONNECTION ---
@st.cache_resource
def init_firebase():
    try:
        config = dict(st.secrets["firebase_config"])
        cred = credentials.Certificate(config)
        if not firebase_admin._apps:
            firebase_admin.initialize_app(cred, {'databaseURL': st.secrets["firebase_db_url"]})
        return firestore.client()
    except Exception as e:
        st.error(f"Database connection failed: {e}")
        return None

db = init_firebase()

# --- 4. LOAD DATA (SUPPLIES & WAYBILLS) ---
df_raw = pd.DataFrame()
df_math = pd.DataFrame()
df_waybills = pd.DataFrame()

if db:
    try:
        # Load Supplies
        docs = db.collection('supplies').stream()
        data = []
        for doc in docs:
            d = doc.to_dict()
            d['doc_id'] = doc.id 
            data.append(d)
            
        if data:
            df_raw = pd.DataFrame(data)
            if 'Site ID' in df_raw.columns: df_raw['Site ID'] = df_raw['Site ID'].astype(str).str.strip()
            if 'Supply Date' in df_raw.columns:
                df_raw['Supply Date'] = pd.to_datetime(df_raw['Supply Date'], errors='coerce')
            elif 'Date' in df_raw.columns: 
                df_raw = df_raw.rename(columns={'Date': 'Supply Date'})
                df_raw['Supply Date'] = pd.to_datetime(df_raw['Supply Date'], errors='coerce')
            
            num_cols = ['Qty before supply Tank 1', 'QTY supplied Tank 1', 'Qty before supply Tank 2', 'QTY supplied Tank 2', 'Approved CPD']
            for col in num_cols:
                if col in df_raw.columns: df_raw[col] = df_raw[col].apply(clean_numeric).fillna(0.0)
            if not df_raw.empty and 'Zones' in df_raw.columns: df_raw['Zones'] = df_raw['Zones'].astype(str).str.strip().str.upper()
                
            if 'Site ID' in df_raw.columns and 'Supply Date' in df_raw.columns:
                agg_dict = {
                    'QTY supplied Tank 1': 'sum', 'QTY supplied Tank 2': 'sum',
                    'Qty before supply Tank 1': 'sum', 'Qty before supply Tank 2': 'sum',
                    'Approved CPD': 'mean', 'Region': 'first', 'Cluster': 'first', 
                    'Zones': 'first', 'Bobtail number': 'last', 'Type of supply': 'last'
                }
                agg_dict = {k: v for k, v in agg_dict.items() if k in df_raw.columns}
                df_math = df_raw.groupby(['Site ID', 'Supply Date']).agg(agg_dict).reset_index()

        # Load Waybills
        wb_docs = db.collection('waybills').stream()
        wb_data = [doc.to_dict() for doc in wb_docs]
        if wb_data:
            df_waybills = pd.DataFrame(wb_data)
            
            # Handle both old 'Waybill Date' and new 'Trip Start Date'
            if 'Trip Start Date' in df_waybills.columns:
                df_waybills['Trip Start Date'] = pd.to_datetime(df_waybills['Trip Start Date'], errors='coerce')
            elif 'Waybill Date' in df_waybills.columns:
                df_waybills['Trip Start Date'] = pd.to_datetime(df_waybills['Waybill Date'], errors='coerce')
                
            if 'Trip End Date' in df_waybills.columns:
                df_waybills['Trip End Date'] = pd.to_datetime(df_waybills['Trip End Date'], errors='coerce')

            num_wb_cols = ['Initial QTY (L)', 'Loaded QTY (L)', 'Loaded QTY (Kg)', 'Supplied QTY (L)', 'Remaining QTY (L)', 'Mapped Sites', 'Supplied Sites']
            for col in num_wb_cols:
                if col in df_waybills.columns: 
                    df_waybills[col] = pd.to_numeric(df_waybills[col], errors='coerce').fillna(0.0)
            
            # Calculate Variances for display
            if 'Mapped Sites' in df_waybills.columns and 'Supplied Sites' in df_waybills.columns:
                df_waybills['Site Variance'] = df_waybills['Mapped Sites'] - df_waybills['Supplied Sites']
                
            df_waybills = df_waybills.sort_values('Trip Start Date', ascending=False)
                
        st.sidebar.info(f"📊 Loaded {len(df_raw)} supply records & {len(df_waybills)} waybills.")
    except Exception as e:
        st.warning(f"Database load issue: {e}")

# --- 5. DATA INPUT (Role-Based) ---
st.sidebar.header("📥 Data Input")

if st.session_state.role == 'Admin':
    input_options = ("Manual Entry", "Edit Single Record", "Bulk Edit (Spreadsheet)", "Upload Excel File")
else:
    input_options = ("Manual Entry", "Upload Excel File")

input_method = st.sidebar.radio("How would you like to input data?", input_options, horizontal=True)

if input_method == "Manual Entry":
    st.sidebar.subheader("Enter Supply Details")
    with st.sidebar.form("manual_entry_form"):
        if not df_raw.empty and 'Site ID' in df_raw.columns:
            existing_sites = sorted(df_raw['Site ID'].dropna().unique().tolist())
            site_choice = st.selectbox("Select Site", ["➕ New Site"] + existing_sites)
            if site_choice == "➕ New Site":
                site_id = st.text_input("New Site ID"); region = st.text_input("Region"); cluster = st.text_input("Cluster")
                zone = st.selectbox("Zones", ["A1", "A2", "A3"])
            else:
                site_id = site_choice
                site_df = df_raw[df_raw['Site ID'] == str(site_id)]
                if not site_df.empty:
                    last_record = site_df.sort_values('Supply Date').iloc[-1]
                    region = last_record.get('Region', ''); cluster = last_record.get('Cluster', ''); zone = last_record.get('Zones', 'A1')
                    st.success(f"Updating existing site: {site_id}")
                else: region = ''; cluster = ''; zone = 'A1'
        else:
            site_id = st.text_input("Site ID"); region = st.text_input("Region"); cluster = st.text_input("Cluster"); zone = st.selectbox("Zones", ["A1", "A2", "A3"])

        col1, col2 = st.columns(2)
        with col1:
            qty_before_t1 = st.number_input("Qty before supply Tank 1", min_value=0.0, format="%.2f")
            qty_supplied_t1 = st.number_input("QTY supplied Tank 1", min_value=0.0, format="%.2f")
            qty_before_t2 = st.number_input("Qty before supply Tank 2", min_value=0.0, format="%.2f")
            qty_supplied_t2 = st.number_input("QTY supplied Tank 2", min_value=0.0, format="%.2f")
        with col2:
            if st.session_state.role == 'Admin':
                approved_cpd = st.number_input("Approved CPD", min_value=0.0, format="%.2f")
            else:
                approved_cpd = 0.0 
            supply_date = st.date_input("Supply Date")
            bobtail = st.text_input("Bobtail number")
            supply_type = st.text_input("Type of supply", value="Oct 1st supply")
            
        submitted = st.form_submit_button("💾 Save to Database")
        if submitted:
            if not site_id: st.error("Please enter a Site ID.")
            elif not db: st.error("Database not connected.")
            else:
                record = {'Site ID': str(site_id), 'Region': str(region), 'Cluster': str(cluster), 'Zones': str(zone).strip().upper(),
                          'Qty before supply Tank 1': float(qty_before_t1), 'QTY supplied Tank 1': float(qty_supplied_t1),
                          'Qty before supply Tank 2': float(qty_before_t2), 'QTY supplied Tank 2': float(qty_supplied_t2),
                          'Approved CPD': float(approved_cpd), 'Supply Date': supply_date.strftime("%Y-%m-%d"),
                          'Bobtail number': str(bobtail), 'Type of supply': str(supply_type).strip()}
                db.collection('supplies').add(record)
                st.success("✅ Saved successfully!"); st.rerun()

elif input_method == "Edit Single Record":
    st.sidebar.subheader("✏️ Edit / Update Single Record")
    if not df_raw.empty and 'Site ID' in df_raw.columns:
        edit_site = st.sidebar.selectbox("1. Select Site ID", sorted(df_raw['Site ID'].unique().tolist()))
        site_dates = df_raw[df_raw['Site ID'] == edit_site]['Supply Date'].sort_values(ascending=False)
        date_options = [d.strftime('%Y-%m-%d') for d in site_dates]
        edit_date_str = st.sidebar.selectbox("2. Select Date to Edit", date_options)
        row_data_df = df_raw[(df_raw['Site ID'] == str(edit_site)) & (df_raw['Supply Date'].astype(str) == edit_date_str)]
        if not row_data_df.empty:
            row_data = row_data_df.iloc[0]; doc_id = row_data['doc_id']
            st.sidebar.info(f"Editing record ID: {doc_id[:8]}...")
            with st.sidebar.form("edit_form"):
                st.markdown("**Update Values:**")
                new_cpd = st.number_input("Approved CPD", value=float(row_data.get('Approved CPD', 0.0)), format="%.2f")
                new_q_b_t1 = st.number_input("Qty before supply Tank 1", value=float(row_data.get('Qty before supply Tank 1', 0.0)), format="%.2f")
                new_q_s_t1 = st.number_input("QTY supplied Tank 1", value=float(row_data.get('QTY supplied Tank 1', 0.0)), format="%.2f")
                new_q_b_t2 = st.number_input("Qty before supply Tank 2", value=float(row_data.get('Qty before supply Tank 2', 0.0)), format="%.2f")
                new_q_s_t2 = st.number_input("QTY supplied Tank 2", value=float(row_data.get('QTY supplied Tank 2', 0.0)), format="%.2f")
                new_bobtail = st.text_input("Bobtail number", value=str(row_data.get('Bobtail number', '')))
                new_type = st.text_input("Type of supply", value=str(row_data.get('Type of supply', '')))
                col_btn1, col_btn2 = st.columns(2)
                with col_btn1: save_changes = st.form_submit_button("✅ Save", type="primary")
                with col_btn2: delete_record = st.form_submit_button("️ Delete", type="secondary")
            if save_changes:
                update_data = {'Approved CPD': float(new_cpd), 'Qty before supply Tank 1': float(new_q_b_t1), 'QTY supplied Tank 1': float(new_q_s_t1),
                               'Qty before supply Tank 2': float(new_q_b_t2), 'QTY supplied Tank 2': float(new_q_s_t2),
                               'Bobtail number': str(new_bobtail), 'Type of supply': str(new_type)}
                db.collection('supplies').document(doc_id).update(update_data)
                st.sidebar.success("✅ Record updated!"); st.rerun()
            if delete_record:
                db.collection('supplies').document(doc_id).delete()
                st.sidebar.success("🗑️ Record deleted!"); st.rerun()
        else: st.sidebar.warning("Could not find this specific record.")
    else: st.sidebar.warning("No data available to edit.")

elif input_method == "Bulk Edit (Spreadsheet)":
    st.sidebar.subheader("✏️ Bulk Update Records")
    st.sidebar.write("Select a date to edit all sites for that month in a spreadsheet view.")
    if not df_raw.empty and 'Supply Date' in df_raw.columns:
        unique_dates = sorted(df_raw['Supply Date'].dt.date.unique(), reverse=True)
        selected_bulk_date = st.sidebar.date_input("Select Date to Edit", value=unique_dates[0] if unique_dates else date.today())
        bulk_df = df_raw[df_raw['Supply Date'].dt.date == selected_bulk_date].copy()
        if not bulk_df.empty:
            st.sidebar.success(f"Found {len(bulk_df)} records for {selected_bulk_date}")
            editable_cols = ['Approved CPD', 'Qty before supply Tank 1', 'QTY supplied Tank 1', 'Qty before supply Tank 2', 'QTY supplied Tank 2', 'Bobtail number', 'Type of supply']
            cols_to_show = ['Site ID', 'Region', 'Zones'] + [c for c in editable_cols if c in bulk_df.columns]
            st.subheader(f"Edit Records for {selected_bulk_date}")
            st.write("Click on any cell below to change the value. When finished, click 'Save All Changes'.")
            edited_df = st.data_editor(bulk_df[cols_to_show], num_rows="fixed", use_container_width=True, key="bulk_editor")
            if st.button("💾 Save All Changes to Database", type="primary"):
                count = 0
                for idx in edited_df.index:
                    doc_id = bulk_df.loc[idx, 'doc_id']
                    update_data = {}
                    for col in editable_cols:
                        if col in edited_df.columns:
                            val = edited_df.loc[idx, col]
                            if col in ['Approved CPD', 'Qty before supply Tank 1', 'QTY supplied Tank 1', 'Qty before supply Tank 2', 'QTY supplied Tank 2']:
                                update_data[col] = float(val) if pd.notnull(val) else 0.0
                            else: update_data[col] = str(val)
                    db.collection('supplies').document(doc_id).update(update_data)
                    count += 1
                st.success(f"✅ Successfully updated {count} records in the database!"); st.rerun()
        else: st.warning("No records found for this date.")
    else: st.warning("Database is empty.")

elif input_method == "Upload Excel File":
    st.sidebar.subheader("Upload Excel to Database")
    uploaded_file = st.sidebar.file_uploader("Choose your Excel or CSV file", type=["xlsx", "csv"])
    if uploaded_file is not None:
        st.session_state['file_to_upload'] = uploaded_file
        st.sidebar.success(f"✅ File '{uploaded_file.name}' is ready.")
    if 'file_to_upload' in st.session_state:
        if st.sidebar.button("🚀 CLICK HERE TO UPLOAD DATA TO DASHBOARD", type="primary"):
            file_to_process = st.session_state['file_to_upload']
            if not db: st.sidebar.error("❌ Database not connected.")
            else:
                try:
                    if file_to_process.name.endswith('.csv'): temp_df = pd.read_csv(file_to_process)
                    else: temp_df = pd.read_excel(file_to_process) 
                    if temp_df.empty: st.sidebar.error("❌ The file appears to be empty."); st.stop()
                    temp_df.columns = [str(c).strip() for c in temp_df.columns]
                    def find_col(keywords, exclude=None):
                        if exclude is None: exclude = []
                        for col in temp_df.columns:
                            c = str(col).lower()
                            if all(k in c for k in keywords) and not any(k in c for k in exclude): return col
                        return None
                    rename_map = {}
                    if find_col(['before', 'tank', '1']): rename_map[find_col(['before', 'tank', '1'])] = 'Qty before supply Tank 1'
                    if find_col(['suppl', 'tank', '1'], exclude=['before']): rename_map[find_col(['suppl', 'tank', '1'], exclude=['before'])] = 'QTY supplied Tank 1'
                    if find_col(['before', 'tank', '2']): rename_map[find_col(['before', 'tank', '2'])] = 'Qty before supply Tank 2'
                    if find_col(['suppl', 'tank', '2'], exclude=['before']): rename_map[find_col(['suppl', 'tank', '2'], exclude=['before'])] = 'QTY supplied Tank 2'
                    if find_col(['approved', 'cpd']): rename_map[find_col(['approved', 'cpd'])] = 'Approved CPD'
                    date_col = find_col(['supply', 'date']) or find_col(['date'])
                    if date_col: rename_map[date_col] = 'Supply Date'
                    if find_col(['site']): rename_map[find_col(['site'])] = 'Site ID'
                    if find_col(['region']): rename_map[find_col(['region'])] = 'Region'
                    if find_col(['cluster']): rename_map[find_col(['cluster'])] = 'Cluster'
                    if find_col(['bobtail']): rename_map[find_col(['bobtail'])] = 'Bobtail number'
                    if find_col(['zone']): rename_map[find_col(['zone'])] = 'Zones'
                    if find_col(['type', 'supply']): rename_map[find_col(['type', 'supply'])] = 'Type of supply'
                    temp_df.rename(columns=rename_map, inplace=True)
                    required_cols = ['Site ID', 'Region', 'Cluster', 'Qty before supply Tank 1', 'QTY supplied Tank 1', 'Qty before supply Tank 2', 'QTY supplied Tank 2', 'Approved CPD', 'Supply Date', 'Bobtail number']
                    for col in required_cols:
                        if col not in temp_df.columns: temp_df[col] = 0.0 if 'Qty' in col or 'CPD' in col else ''
                    if 'Zones' not in temp_df.columns: temp_df['Zones'] = 'A1'
                    if 'Type of supply' not in temp_df.columns: temp_df['Type of supply'] = '1st supply'
                    count = 0; progress_bar = st.sidebar.progress(0.0); total_rows = len(temp_df)
                    for index, row in temp_df.iterrows():
                        date_val = row['Supply Date']
                        if hasattr(date_val, 'strftime'): date_val = date_val.strftime("%Y-%m-%d")
                        else: date_val = str(date_val)
                        zone_val = str(row.get('Zones', 'A1')).strip().upper()
                        supply_type_val = str(row.get('Type of supply', '1st supply')).strip()
                        q_b_t1 = clean_numeric(row['Qty before supply Tank 1']); q_s_t1 = clean_numeric(row['QTY supplied Tank 1'])
                        q_b_t2 = clean_numeric(row['Qty before supply Tank 2']); q_s_t2 = clean_numeric(row['QTY supplied Tank 2'])
                        cpd = clean_numeric(row['Approved CPD'])
                        record = {'Site ID': str(row['Site ID']), 'Region': str(row['Region']), 'Cluster': str(row['Cluster']), 'Zones': zone_val,
                                  'Qty before supply Tank 1': q_b_t1, 'QTY supplied Tank 1': q_s_t1,
                                  'Qty before supply Tank 2': q_b_t2, 'QTY supplied Tank 2': q_s_t2,
                                  'Approved CPD': cpd, 'Supply Date': date_val, 'Bobtail number': str(row['Bobtail number']), 'Type of supply': supply_type_val}
                        db.collection('supplies').add(record)
                        count += 1; progress_val = min(count / total_rows, 1.0); progress_bar.progress(progress_val)
                    st.sidebar.success(f"✅ Successfully uploaded {count} rows!"); del st.session_state['file_to_upload']; st.rerun()
                except Exception as e: st.sidebar.error(f"❌ Upload failed: {str(e)}")

# --- 5.5 NEW: ADVANCED WAYBILL MANAGEMENT ---
st.sidebar.markdown("---")
st.sidebar.header("🚛 Waybill Management")
waybill_action = st.sidebar.radio("Select Waybill Action", ["➕ Add New Waybill", "📋 View Recent Waybills"])

if waybill_action == "➕ Add New Waybill":
    st.sidebar.subheader("Log Truck Waybill")
    with st.sidebar.form("waybill_form"):
        waybill_no = st.text_input("Waybill Number / ID")
        truck_no = st.text_input("Truck / Bobtail Number")
        driver_name = st.text_input("Driver Name (Optional)")
        
        col_d1, col_d2 = st.columns(2)
        with col_d1: trip_start_date = st.date_input("Trip Start Date", value=date.today())
        with col_d2: trip_end_date = st.date_input("Trip End Date", value=date.today())
        
        st.markdown("**Quantity Tracking:**")
        initial_qty_l = st.number_input("Initial QTY (Litres)", min_value=0.0, format="%.2f")
        loaded_qty_l = st.number_input("QTY After Loading (Litres)", min_value=0.0, format="%.2f")
        loaded_qty_kg = st.number_input("QTY After Loading (Kg)", min_value=0.0, format="%.2f")
        supplied_qty_l = st.number_input("Total QTY Supplied (Litres)", min_value=0.0, format="%.2f")
        remaining_qty_l = st.number_input("Remaining QTY in Truck (Litres)", min_value=0.0, format="%.2f")
        
        st.markdown("**Site Mapping:**")
        mapped_sites = st.number_input("Mapped Sites (Planned)", min_value=0, step=1)
        supplied_sites = st.number_input("Supplied Sites (Actual)", min_value=0, step=1)
        
        if st.form_submit_button("💾 Save Waybill", type="primary"):
            if not waybill_no or not truck_no:
                st.sidebar.error("Waybill Number and Truck Number are required.")
            else:
                wb_record = {
                    'Waybill Number': str(waybill_no).strip(),
                    'Truck Number': str(truck_no).strip(),
                    'Driver Name': str(driver_name).strip(),
                    'Trip Start Date': trip_start_date.strftime("%Y-%m-%d"),
                    'Trip End Date': trip_end_date.strftime("%Y-%m-%d"),
                    'Initial QTY (L)': float(initial_qty_l),
                    'Loaded QTY (L)': float(loaded_qty_l),
                    'Loaded QTY (Kg)': float(loaded_qty_kg),
                    'Supplied QTY (L)': float(supplied_qty_l),
                    'Remaining QTY (L)': float(remaining_qty_l),
                    'Mapped Sites': int(mapped_sites),
                    'Supplied Sites': int(supplied_sites),
                    'Added By': st.session_state.role
                }
                db.collection('waybills').add(wb_record)
                st.sidebar.success("✅ Waybill saved successfully!")
                st.rerun()

elif waybill_action == "📋 View Recent Waybills":
    st.sidebar.subheader("Recent Waybills")
    if not df_waybills.empty:
        wb_display_cols = ['Trip Start Date', 'Waybill Number', 'Truck Number', 'Loaded QTY (L)', 'Supplied Sites']
        final_wb_cols = [c for c in wb_display_cols if c in df_waybills.columns]
        st.sidebar.dataframe(df_waybills[final_wb_cols].head(10), hide_index=True, use_container_width=True)
    else:
        st.sidebar.info("No waybills logged yet.")

# --- 6. ADMIN CONTROLS ---
if st.session_state.role == 'Admin':
    st.sidebar.markdown("---")
    st.sidebar.subheader(" Admin Controls")
    if st.sidebar.button("️ Clear Database"): 
        if st.sidebar.checkbox("Are you sure? This deletes everything permanently."):
            docs = db.collection('supplies').stream()
            for doc in docs: doc.reference.delete()
            wb_docs = db.collection('waybills').stream()
            for doc in wb_docs: doc.reference.delete()
            st.success("All databases cleared!"); st.rerun()

# --- 7. DASHBOARD LOGIC ---
if not df_math.empty:
    st.divider()
    
    if 'Supply Date' in df_math.columns and 'Site ID' in df_math.columns:
        df_math = df_math.sort_values(by=['Site ID', 'Supply Date'])
        df_math['Total QTY Supplied'] = df_math['QTY supplied Tank 1'] + df_math['QTY supplied Tank 2']
        df_math['Total QTY Before Supply'] = df_math['Qty before supply Tank 1'] + df_math['Qty before supply Tank 2']
        
        df_math['Prev_Total_Before'] = df_math.groupby('Site ID')['Total QTY Before Supply'].shift(1)
        df_math['Prev_Total_Supplied'] = df_math.groupby('Site ID')['Total QTY Supplied'].shift(1)
        df_math['Prev_Supply_Date'] = df_math.groupby('Site ID')['Supply Date'].shift(1)
        df_math['Days_Diff'] = (df_math['Supply Date'] - df_math['Prev_Supply_Date']).dt.days
        
        df_math['Total_Consumed'] = (df_math['Prev_Total_Before'] + df_math['Prev_Total_Supplied']) - df_math['Total QTY Before Supply']
        df_math['Estimated CPD'] = df_math['Total_Consumed'] / df_math['Days_Diff']
        df_math['Estimated CPD'] = df_math['Estimated CPD'].where(df_math['Days_Diff'] > 0, 0) 
        
        df_math['Total_QTY_After_Supply'] = df_math['Total QTY Before Supply'] + df_math['Total QTY Supplied']
        df_math['Days_Fuel_Last'] = df_math['Total_QTY_After_Supply'] / df_math['Estimated CPD']
        df_math['Days_Fuel_Last'] = df_math['Days_Fuel_Last'].where(df_math['Estimated CPD'] > 0, 0) 
        
        def calc_next_date(row):
            if row['Days_Fuel_Last'] > 0 and not pd.isnull(row['Supply Date']):
                next_date = row['Supply Date'] + timedelta(days=row['Days_Fuel_Last'])
                return next_date.date() if hasattr(next_date, 'date') else next_date
            else: return None
        df_math['Estimated Next Supply Date'] = df_math.apply(calc_next_date, axis=1)
        
        def calc_variance(row):
            if row['Estimated CPD'] == 0 or pd.isnull(row['Estimated CPD']): return 0
            return row['Approved CPD'] - row['Estimated CPD']
        df_math['CPD Variance'] = df_math.apply(calc_variance, axis=1)
        
        def get_status(row):
            if row['Estimated CPD'] == 0 or pd.isnull(row['Estimated CPD']): return "⚪ N/A"
            app = row['Approved CPD']; var = row['CPD Variance']
            if app == 0: return "⚪ N/A"
            pct = abs(var) / app
            if pct <= 0.05: return "🟢 On Target"
            elif pct <= 0.15: return "🟡 Slight Variance"
            else: return "🔴 High Variance"
        df_math['Variance Status'] = df_math.apply(get_status, axis=1)
        
        today = pd.Timestamp.today().date()
        def get_supply_alert(next_date):
            if pd.isnull(next_date): return ""
            days_diff = (next_date - today).days
            if days_diff < 0: return "🚨 OVERDUE"
            elif days_diff == 0: return "🔴 CRITICAL: Supply Today"
            elif days_diff <= 2: return f"🟡 WARNING: Supply in {days_diff} days"
            else: return ""
        df_math['Supply Alert'] = df_math['Estimated Next Supply Date'].apply(get_supply_alert)

    st.sidebar.header("🔍 Filters")
    valid_dates = df_math['Supply Date'].dropna()
    if not valid_dates.empty:
        min_date = valid_dates.min().date(); max_date = valid_dates.max().date()
        start_date = st.sidebar.date_input("Start Date", value=min_date, min_value=min_date, max_value=max_date)
        end_date = st.sidebar.date_input("End Date", value=max_date, min_value=min_date, max_value=max_date)
    else:
        start_date = st.sidebar.date_input("Start Date", value=date(2023, 1, 1))
        end_date = st.sidebar.date_input("End Date", value=date(2026, 12, 31))

    regions = ['All'] + list(df_math['Region'].dropna().unique()) if 'Region' in df_math.columns else ['All']
    selected_region = st.sidebar.selectbox("Region", regions)
    clusters = ['All'] + list(df_math['Cluster'].dropna().unique()) if 'Cluster' in df_math.columns else ['All']
    selected_cluster = st.sidebar.selectbox("Cluster", clusters)
    zones = ['All'] + list(df_math['Zones'].dropna().unique()) if 'Zones' in df_math.columns else ['All']
    selected_zone = st.sidebar.selectbox("Zones", zones)
    supply_types = ['All'] + list(df_math['Type of supply'].dropna().unique()) if 'Type of supply' in df_math.columns else ['All']
    selected_supply_type = st.sidebar.selectbox("Type of Supply", supply_types)
    sites = ['All'] + list(df_math['Site ID'].dropna().unique()) if 'Site ID' in df_math.columns else ['All']
    selected_site = st.sidebar.selectbox("Site ID", sites)

    mask_math = ((df_math['Supply Date'].dt.date >= start_date) & (df_math['Supply Date'].dt.date <= end_date))
    if selected_region != 'All': mask_math &= (df_math['Region'] == selected_region)
    if selected_cluster != 'All': mask_math &= (df_math['Cluster'] == selected_cluster)
    if selected_zone != 'All': mask_math &= (df_math['Zones'] == selected_zone)
    if selected_supply_type != 'All': mask_math &= (df_math['Type of supply'] == selected_supply_type)
    if selected_site != 'All': mask_math &= (df_math['Site ID'] == selected_site)
    filtered_math_df = df_math[mask_math].copy()

    mask_raw = ((df_raw['Supply Date'].dt.date >= start_date) & (df_raw['Supply Date'].dt.date <= end_date))
    if selected_region != 'All': mask_raw &= (df_raw['Region'] == selected_region)
    if selected_cluster != 'All': mask_raw &= (df_raw['Cluster'] == selected_cluster)
    if selected_zone != 'All': mask_raw &= (df_raw['Zones'] == selected_zone)
    if selected_supply_type != 'All': mask_raw &= (df_raw['Type of supply'] == selected_supply_type)
    if selected_site != 'All': mask_raw &= (df_raw['Site ID'] == selected_site)
    filtered_raw_df = df_raw[mask_raw].copy()

    if filtered_math_df.empty: st.warning("No data found for the selected filters.")
    else:
        st.subheader("📊 Summary Dashboard")
        total_sites = filtered_math_df['Site ID'].nunique()
        total_supplied = pd.to_numeric(filtered_raw_df['QTY supplied Tank 1'], errors='coerce').fillna(0.0).sum() + \
                         pd.to_numeric(filtered_raw_df['QTY supplied Tank 2'], errors='coerce').fillna(0.0).sum()
        
        high_variance_count = 0
        if 'Estimated CPD' in filtered_math_df.columns and 'Approved CPD' in filtered_math_df.columns:
            valid_var = filtered_math_df[(filtered_math_df['Estimated CPD'] > 0) & (filtered_math_df['Approved CPD'] > 0)]
            if not valid_var.empty:
                variance_pct = (valid_var['CPD Variance'].abs() / valid_var['Approved CPD'])
                high_variance_count = int((variance_pct > 0.15).sum())
        
        urgent_supplies = filtered_math_df['Supply Alert'].apply(lambda x: 1 if 'CRITICAL' in str(x) or 'WARNING' in str(x) or 'OVERDUE' in str(x) else 0).sum()
        
        # Waybill Metrics
        total_waybills = len(df_waybills)
        total_dispatched = df_waybills['Loaded QTY (L)'].sum() if 'Loaded QTY (L)' in df_waybills.columns else 0.0
        
        if st.session_state.role == 'Admin':
            col1, col2, col3, col4, col5, col6 = st.columns(6)
            col1.metric("Total Sites Tracked", total_sites)
            col2.metric("Sites Supplied", total_sites)
            col3.metric("Total Fuel Supplied", f"{total_supplied:,.2f} L")
            col4.metric("High Variance", high_variance_count)
            col5.metric("Urgent Supplies", int(urgent_supplies))
            col6.metric("Waybills Logged", total_waybills)
        else:
            col1, col2, col3, col4, col5 = st.columns(5)
            col1.metric("Total Sites Tracked", total_sites)
            col2.metric("Sites Supplied", total_sites)
            col3.metric("Total Fuel Supplied", f"{total_supplied:,.2f} L")
            col4.metric("Urgent Supplies", int(urgent_supplies))
            col5.metric("Waybills Logged", total_waybills)
        
        st.markdown("---")
        st.subheader(" Sites by Zone")
        if 'Zones' in filtered_math_df.columns:
            z1, z2, z3 = st.columns(3)
            with z1: st.metric("Zone A1", filtered_math_df[filtered_math_df['Zones'] == 'A1']['Site ID'].nunique())
            with z2: st.metric("Zone A2", filtered_math_df[filtered_math_df['Zones'] == 'A2']['Site ID'].nunique())
            with z3: st.metric("Zone A3", filtered_math_df[filtered_math_df['Zones'] == 'A3']['Site ID'].nunique())
        st.markdown("---")
        st.subheader("🚛 Sites by Supply Type")
        if 'Type of supply' in filtered_math_df.columns:
            supply_counts = filtered_math_df.groupby('Type of supply')['Site ID'].nunique().sort_values(ascending=False)
            if len(supply_counts) > 0:
                cols = st.columns(min(len(supply_counts), 4))
                for i, (stype, count) in enumerate(supply_counts.items()):
                    with cols[i % 4]: st.metric(str(stype).title(), count)
        st.markdown("---")
        
        if st.session_state.role == 'Admin':
            chart_col1, chart_col2 = st.columns(2)
            with chart_col1:
                st.subheader("Total QTY Supplied by Region")
                if 'Region' in filtered_math_df.columns: st.bar_chart(filtered_math_df.groupby('Region')['Total QTY Supplied'].sum(), width="stretch")
            with chart_col2:
                st.subheader("Variance Status Distribution")
                status_counts = filtered_math_df['Variance Status'].value_counts().reset_index()
                status_counts.columns = ['Status', 'Count']
                color_map = {'🟢 On Target': '#28a745', '🟡 Slight Variance': '#ffc107', '🔴 High Variance': '#dc3545', '⚪ N/A': '#6c757d'}
                fig = px.bar(status_counts, x='Status', y='Count', color='Status', color_discrete_map=color_map, text='Count')
                fig.update_layout(showlegend=False, yaxis_title='Count', xaxis_title='')
                st.plotly_chart(fig, use_container_width=True)
        else:
            st.subheader("Total QTY Supplied by Region")
            if 'Region' in filtered_math_df.columns: st.bar_chart(filtered_math_df.groupby('Region')['Total QTY Supplied'].sum(), width="stretch")

        st.markdown("---")
        
        if st.session_state.role == 'Admin':
            st.subheader("📜 Site History & CPD Trend")
            st.write("Select a site below to see its Estimated CPD history across all months.")
            if 'Site ID' in df_math.columns:
                history_site = st.selectbox("Select Site ID to view history:", sorted(df_math['Site ID'].unique().tolist()))
                site_hist_df = df_math[df_math['Site ID'] == history_site].sort_values('Supply Date')
                hist_cols = ['Supply Date', 'Type of supply', 'Total QTY Supplied', 'Estimated CPD', 'Approved CPD', 'CPD Variance', 'Variance Status']
                final_hist_cols = [c for c in hist_cols if c in site_hist_df.columns]
                st.dataframe(site_hist_df[final_hist_cols], hide_index=True, use_container_width=True)
                if not site_hist_df.empty and 'Estimated CPD' in site_hist_df.columns:
                    chart_data = site_hist_df[['Supply Date', 'Estimated CPD', 'Approved CPD']].melt(id_vars='Supply Date', value_vars=['Estimated CPD', 'Approved CPD'], var_name='CPD Type', value_name='Value')
                    fig_hist = px.line(chart_data, x='Supply Date', y='Value', color='CPD Type', markers=True, title=f'CPD History for {history_site}')
                    st.plotly_chart(fig_hist, use_container_width=True)
        else:
            st.subheader(" Site Supply History")
            st.write("Select a site below to see its supply history.")
            if 'Site ID' in df_math.columns:
                history_site = st.selectbox("Select Site ID to view history:", sorted(df_math['Site ID'].unique().tolist()))
                site_hist_df = df_math[df_math['Site ID'] == history_site].sort_values('Supply Date')
                hist_cols = ['Supply Date', 'Type of supply', 'Total QTY Supplied', 'Supply Alert', 'Bobtail number']
                final_hist_cols = [c for c in hist_cols if c in site_hist_df.columns]
                st.dataframe(site_hist_df[final_hist_cols], hide_index=True, use_container_width=True)

        st.markdown("---")
        st.subheader("📋 Current Status (Latest Record per Site)")
        df_latest = filtered_math_df.sort_values('Supply Date').drop_duplicates(subset=['Site ID'], keep='last')
        
        if st.session_state.role == 'Admin':
            display_cols = ['Site ID', 'Region', 'Cluster', 'Zones', 'Type of supply', 'Total QTY Supplied', 'Total QTY Before Supply', 'Approved CPD', 'Estimated CPD', 'CPD Variance', 'Variance Status', 'Supply Date', 'Estimated Next Supply Date', 'Supply Alert', 'Bobtail number']
        else:
            display_cols = ['Site ID', 'Region', 'Cluster', 'Zones', 'Type of supply', 'Total QTY Supplied', 'Total QTY Before Supply', 'Supply Date', 'Estimated Next Supply Date', 'Supply Alert', 'Bobtail number']
            
        final_cols = [c for c in display_cols if c in df_latest.columns]
        st.dataframe(df_latest[final_cols], width="stretch", hide_index=True)

        # --- NEW: ADVANCED WAYBILL TRACKER SECTION ---
        st.markdown("---")
        st.subheader("🚛 Waybill Tracker & Analysis")
        if not df_waybills.empty:
            # Filter waybills by Trip Start Date
            if 'Trip Start Date' in df_waybills.columns:
                valid_wb_dates = df_waybills['Trip Start Date'].dropna()
                if not valid_wb_dates.empty:
                    wb_min = valid_wb_dates.min().date()
                    wb_max = valid_wb_dates.max().date()
                    wb_filter_date = st.date_input("Filter Waybills by Trip Start Date", value=wb_max, min_value=wb_min, max_value=wb_max)
                    filtered_wb = df_waybills[df_waybills['Trip Start Date'].dt.date == wb_filter_date]
                else:
                    filtered_wb = df_waybills
            else:
                filtered_wb = df_waybills
            
            if filtered_wb.empty:
                st.info(f"No waybills logged for the selected date.")
            else:
                # Show detailed comparison table
                wb_cols_show = [
                    'Waybill Number', 'Truck Number', 'Driver Name', 
                    'Trip Start Date', 'Trip End Date',
                    'Loaded QTY (L)', 'Loaded QTY (Kg)', 'Supplied QTY (L)', 'Remaining QTY (L)',
                    'Mapped Sites', 'Supplied Sites', 'Site Variance'
                ]
                final_wb_show = [c for c in wb_cols_show if c in filtered_wb.columns]
                st.dataframe(filtered_wb[final_wb_show], use_container_width=True, hide_index=True)
                
                # Waybill Summary for the selected day
                w_col1, w_col2, w_col3, w_col4 = st.columns(4)
                w_col1.metric("Total Trucks Dispatched", len(filtered_wb))
                
                if 'Loaded QTY (L)' in filtered_wb.columns:
                    w_col2.metric("Total Fuel Dispatched (L)", f"{filtered_wb['Loaded QTY (L)'].sum():,.2f} L")
                if 'Loaded QTY (Kg)' in filtered_wb.columns:
                    w_col3.metric("Total Fuel Dispatched (Kg)", f"{filtered_wb['Loaded QTY (Kg)'].sum():,.2f} Kg")
                if 'Supplied Sites' in filtered_wb.columns and 'Mapped Sites' in filtered_wb.columns:
                    total_mapped = int(filtered_wb['Mapped Sites'].sum())
                    total_supplied_wb = int(filtered_wb['Supplied Sites'].sum())
                    w_col4.metric("Sites: Mapped vs Supplied", f"{total_supplied_wb} / {total_mapped}")
        else:
            st.info("No waybills have been logged yet. Use the sidebar to add the first one!")

else:
    st.info("👆 Database is empty. Use the sidebar to upload an Excel file or add manual entries!")