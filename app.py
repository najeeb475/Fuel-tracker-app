import streamlit as st
import pandas as pd
from datetime import timedelta, date
import io
import plotly.express as px
import firebase_admin
from firebase_admin import credentials, firestore
from streamlit_cookies_controller import CookieController

# --- HELPER FUNCTION TO CLEAN NUMBERS ---
def clean_numeric(val):
    """Converts messy Excel text (like '1,000' or '500 L') to a clean float."""
    if pd.isnull(val): return 0.0
    val_str = str(val).replace(',', '').replace(' ', '').replace('L', '').replace('l', '').replace('ltr', '')
    try: 
        return float(val_str)
    except: 
        return 0.0

# --- 1. SECURITY & LOGIN ---
controller = CookieController()
if 'logged_in' not in st.session_state:
    if controller.get('logged_in') == 'true':
        st.session_state.logged_in = True
        st.session_state.role = controller.get('role')

if 'logged_in' not in st.session_state or not st.session_state.logged_in:
    st.title("🔒 Access Portal")
    tab1, tab2 = st.tabs([" Team Access", "🔑 Admin Login"])
    with tab1:
        if st.button("Enter as Team"):
            st.session_state.logged_in = True; st.session_state.role = 'Team'
            controller.set('logged_in', 'true'); controller.set('role', 'Team')
            st.rerun()
    with tab2:
        password = st.text_input("Enter Admin Password", type="password")
        if st.button("Login as Admin"):
            if password == "admin123": 
                st.session_state.logged_in = True; st.session_state.role = 'Admin'
                controller.set('logged_in', 'true'); controller.set('role', 'Admin')
                st.rerun()
            else: st.error("Incorrect password.")
    st.stop()

# --- 2. PAGE CONFIG ---
st.set_page_config(page_title="Supply & CPD Tracker", layout="wide")
st.title("📊 Supply & CPD Tracker App")
if st.session_state.role == 'Admin': st.sidebar.success("🔑 Logged in as Admin")
else: st.sidebar.info("👥 Logged in as Team Member")
if st.sidebar.button("Logout"):
    st.session_state.logged_in = False; st.session_state.role = None
    controller.remove('logged_in'); controller.remove('role')
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

# --- 4. LOAD DATA ---
df = pd.DataFrame()
if db:
    try:
        docs = db.collection('supplies').stream()
        data = [doc.to_dict() for doc in docs]
        if data:
            df = pd.DataFrame(data)
            
            if 'Supply Date' in df.columns:
                df['Supply Date'] = pd.to_datetime(df['Supply Date'], errors='coerce')
            elif 'Date' in df.columns: 
                df = df.rename(columns={'Date': 'Supply Date'})
                df['Supply Date'] = pd.to_datetime(df['Supply Date'], errors='coerce')
            
            num_cols = ['Qty before supply Tank 1', 'QTY supplied Tank 1', 'Qty before supply Tank 2', 'QTY supplied Tank 2', 'Approved CPD']
            for col in num_cols:
                if col in df.columns:
                    df[col] = df[col].apply(clean_numeric)

            if 'Site ID' in df.columns and 'Supply Date' in df.columns:
                df = df.drop_duplicates(subset=['Site ID', 'Supply Date'], keep='last')
                
            if not df.empty:
                if 'Zones' in df.columns: df['Zones'] = df['Zones'].astype(str).str.strip().str.upper()
                st.sidebar.info(f"📊 Loaded {len(df)} unique records from database.")
    except Exception as e:
        st.warning(f"Database load issue: {e}")

# --- 5. DATA INPUT ---
st.sidebar.header("📥 Data Input")
input_method = st.sidebar.radio("How would you like to input data?", ("Manual Entry", "Upload Excel File"), horizontal=True)

if input_method == "Manual Entry":
    st.sidebar.subheader("Enter Supply Details")
    with st.sidebar.form("manual_entry_form"):
        
        # ️ NEW FEATURE: Select existing site to make manual entry faster for the team
        if not df.empty and 'Site ID' in df.columns:
            existing_sites = sorted([str(s) for s in df['Site ID'].dropna().unique().tolist()])
            site_choice = st.selectbox("Select Site", ["➕ New Site"] + existing_sites)
            
            if site_choice == "➕ New Site":
                site_id = st.text_input("New Site ID")
                region = st.text_input("Region")
                cluster = st.text_input("Cluster")
                zone = st.selectbox("Zones", ["A1", "A2", "A3"])
            else:
                site_id = site_choice
                last_record = df[df['Site ID'] == site_id].sort_values('Supply Date').iloc[-1]
                region = last_record.get('Region', '')
                cluster = last_record.get('Cluster', '')
                zone = last_record.get('Zones', 'A1')
                st.success(f"Updating existing site: {site_id}")
        else:
            site_id = st.text_input("Site ID")
            region = st.text_input("Region")
            cluster = st.text_input("Cluster")
            zone = st.selectbox("Zones", ["A1", "A2", "A3"])

        col1, col2 = st.columns(2)
        with col1:
            qty_before_t1 = st.number_input("Qty before supply Tank 1", min_value=0.0, format="%.2f")
            qty_supplied_t1 = st.number_input("QTY supplied Tank 1", min_value=0.0, format="%.2f")
            qty_before_t2 = st.number_input("Qty before supply Tank 2", min_value=0.0, format="%.2f")
            qty_supplied_t2 = st.number_input("QTY supplied Tank 2", min_value=0.0, format="%.2f")
        with col2:
            approved_cpd = st.number_input("Approved CPD", min_value=0.0, format="%.2f")
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

elif input_method == "Upload Excel File":
    st.sidebar.subheader("Upload Excel to Database")
    uploaded_file = st.sidebar.file_uploader("Choose your Excel or CSV file", type=["xlsx", "csv"])
    
    if uploaded_file is not None:
        st.session_state['file_to_upload'] = uploaded_file
        st.sidebar.success(f"✅ File '{uploaded_file.name}' is ready.")
    
    if 'file_to_upload' in st.session_state:
        if st.sidebar.button(" CLICK HERE TO UPLOAD DATA TO DASHBOARD", type="primary"):
            file_to_process = st.session_state['file_to_upload']
            if not db:
                st.sidebar.error("❌ Database not connected.")
            else:
                try:
                    if file_to_process.name.endswith('.csv'): temp_df = pd.read_csv(file_to_process)
                    else: temp_df = pd.read_excel(file_to_process) 
                    
                    if temp_df.empty:
                        st.sidebar.error("❌ The file appears to be empty.")
                        st.stop()
                    
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

                    count = 0
                    progress_bar = st.sidebar.progress(0.0)
                    total_rows = len(temp_df)
                    
                    for index, row in temp_df.iterrows():
                        date_val = row['Supply Date']
                        if hasattr(date_val, 'strftime'): date_val = date_val.strftime("%Y-%m-%d")
                        else: date_val = str(date_val)
                        
                        zone_val = str(row.get('Zones', 'A1')).strip().upper()
                        supply_type_val = str(row.get('Type of supply', '1st supply')).strip()
                        
                        q_b_t1 = clean_numeric(row['Qty before supply Tank 1'])
                        q_s_t1 = clean_numeric(row['QTY supplied Tank 1'])
                        q_b_t2 = clean_numeric(row['Qty before supply Tank 2'])
                        q_s_t2 = clean_numeric(row['QTY supplied Tank 2'])
                        cpd = clean_numeric(row['Approved CPD'])

                        record = {'Site ID': str(row['Site ID']), 'Region': str(row['Region']), 'Cluster': str(row['Cluster']), 'Zones': zone_val,
                                  'Qty before supply Tank 1': q_b_t1, 'QTY supplied Tank 1': q_s_t1,
                                  'Qty before supply Tank 2': q_b_t2, 'QTY supplied Tank 2': q_s_t2,
                                  'Approved CPD': cpd, 'Supply Date': date_val, 'Bobtail number': str(row['Bobtail number']), 'Type of supply': supply_type_val}
                        db.collection('supplies').add(record)
                        count += 1
                        progress_val = min(count / total_rows, 1.0)
                        progress_bar.progress(progress_val)
                    
                    st.sidebar.success(f"✅ Successfully uploaded {count} rows!")
                    del st.session_state['file_to_upload']
                    st.rerun()
                except Exception as e:
                    st.sidebar.error(f"❌ Upload failed: {str(e)}")

# --- 6. ADMIN CONTROLS ---
if st.session_state.role == 'Admin':
    st.sidebar.markdown("---")
    st.sidebar.subheader("🔑 Admin Controls")
    if st.sidebar.button("🗑️ Clear Database"): 
        if st.sidebar.checkbox("Are you sure?"):
            docs = db.collection('supplies').stream()
            for doc in docs: doc.reference.delete()
            st.success("Database cleared!"); st.rerun()

# --- 7. DASHBOARD LOGIC ---
if not df.empty:
    st.divider()
    if 'Supply Date' in df.columns and 'Site ID' in df.columns:
        df = df.sort_values(by=['Site ID', 'Supply Date'])
        
        df['Total QTY Supplied'] = df['QTY supplied Tank 1'] + df['QTY supplied Tank 2']
        df['Total QTY Before Supply'] = df['Qty before supply Tank 1'] + df['Qty before supply Tank 2']
        
        df['Prev_Total_Before'] = df.groupby('Site ID')['Total QTY Before Supply'].shift(1)
        df['Prev_Total_Supplied'] = df.groupby('Site ID')['Total QTY Supplied'].shift(1)
        df['Prev_Supply_Date'] = df.groupby('Site ID')['Supply Date'].shift(1)
        df['Days_Diff'] = (df['Supply Date'] - df['Prev_Supply_Date']).dt.days
        
        df['Total_Consumed'] = (df['Prev_Total_Before'] + df['Prev_Total_Supplied']) - df['Total QTY Before Supply']
        df['Estimated CPD'] = df['Total_Consumed'] / df['Days_Diff']
        df['Estimated CPD'] = df['Estimated CPD'].where(df['Days_Diff'] > 0, 0) 
        
        df['Total_QTY_After_Supply'] = df['Total QTY Before Supply'] + df['Total QTY Supplied']
        df['Days_Fuel_Last'] = df['Total_QTY_After_Supply'] / df['Estimated CPD']
        df['Days_Fuel_Last'] = df['Days_Fuel_Last'].where(df['Estimated CPD'] > 0, 0) 
        
        def calc_next_date(row):
            if row['Days_Fuel_Last'] > 0 and not pd.isnull(row['Supply Date']):
                next_date = row['Supply Date'] + timedelta(days=row['Days_Fuel_Last'])
                return next_date.date() if hasattr(next_date, 'date') else next_date
            else: return None
        df['Estimated Next Supply Date'] = df.apply(calc_next_date, axis=1)

        def calc_variance(row):
            if row['Estimated CPD'] == 0 or pd.isnull(row['Estimated CPD']): return 0
            return row['Approved CPD'] - row['Estimated CPD']
        df['CPD Variance'] = df.apply(calc_variance, axis=1)
        
        def get_status(row):
            if row['Estimated CPD'] == 0 or pd.isnull(row['Estimated CPD']): return "⚪ N/A"
            app = row['Approved CPD']; var = row['CPD Variance']
            if app == 0: return "⚪ N/A"
            pct = abs(var) / app
            if pct <= 0.05: return "🟢 On Target"
            elif pct <= 0.15: return "🟡 Slight Variance"
            else: return "🔴 High Variance"
        df['Variance Status'] = df.apply(get_status, axis=1)

        today = pd.Timestamp.today().date()
        def get_supply_alert(next_date):
            if pd.isnull(next_date): return ""
            days_diff = (next_date - today).days
            if days_diff < 0: return " OVERDUE"
            elif days_diff == 0: return "🔴 CRITICAL: Supply Today"
            elif days_diff <= 2: return f"🟡 WARNING: Supply in {days_diff} days"
            else: return ""
        df['Supply Alert'] = df['Estimated Next Supply Date'].apply(get_supply_alert)

    st.sidebar.header(" Filters")
    valid_dates = df['Supply Date'].dropna()
    if not valid_dates.empty:
        min_date = valid_dates.min().date(); max_date = valid_dates.max().date()
        start_date = st.sidebar.date_input("Start Date", value=min_date, min_value=min_date, max_value=max_date)
        end_date = st.sidebar.date_input("End Date", value=max_date, min_value=min_date, max_value=max_date)
    else:
        start_date = st.sidebar.date_input("Start Date", value=date(2023, 1, 1))
        end_date = st.sidebar.date_input("End Date", value=date(2026, 12, 31))

    regions = ['All'] + list(df['Region'].dropna().unique()) if 'Region' in df.columns else ['All']
    selected_region = st.sidebar.selectbox("Region", regions)
    clusters = ['All'] + list(df['Cluster'].dropna().unique()) if 'Cluster' in df.columns else ['All']
    selected_cluster = st.sidebar.selectbox("Cluster", clusters)
    zones = ['All'] + list(df['Zones'].dropna().unique()) if 'Zones' in df.columns else ['All']
    selected_zone = st.sidebar.selectbox("Zones", zones)
    supply_types = ['All'] + list(df['Type of supply'].dropna().unique()) if 'Type of supply' in df.columns else ['All']
    selected_supply_type = st.sidebar.selectbox("Type of Supply", supply_types)
    sites = ['All'] + list(df['Site ID'].dropna().unique()) if 'Site ID' in df.columns else ['All']
    selected_site = st.sidebar.selectbox("Site ID", sites)

    mask = ((df['Supply Date'].dt.date >= start_date) & (df['Supply Date'].dt.date <= end_date))
    if selected_region != 'All': mask &= (df['Region'] == selected_region)
    if selected_cluster != 'All': mask &= (df['Cluster'] == selected_cluster)
    if selected_zone != 'All': mask &= (df['Zones'] == selected_zone)
    if selected_supply_type != 'All': mask &= (df['Type of supply'] == selected_supply_type)
    if selected_site != 'All': mask &= (df['Site ID'] == selected_site)
    filtered_df = df[mask].copy()

    if filtered_df.empty: st.warning("No data found for the selected filters.")
    else:
        st.subheader(" Summary Dashboard")
        total_sites = filtered_df['Site ID'].nunique()
        total_supplied = filtered_df['Total QTY Supplied'].sum()
        high_variance_count = (filtered_df['Variance Status'] == '🔴 High Variance').sum()
        urgent_supplies = filtered_df['Supply Alert'].apply(lambda x: 1 if 'CRITICAL' in str(x) or 'WARNING' in str(x) or 'OVERDUE' in str(x) else 0).sum()

        col1, col2, col3, col4, col5 = st.columns(5)
        col1.metric("Total Sites Tracked", total_sites)
        col2.metric("Sites Supplied in Range", total_sites)
        col3.metric("Total Fuel Supplied", f"{total_supplied:,.0f} L")
        col4.metric("High Variance Sites", high_variance_count)
        col5.metric("Urgent Supplies", urgent_supplies)
        st.markdown("---")

        st.subheader("📍 Sites by Zone")
        if 'Zones' in filtered_df.columns:
            z1, z2, z3 = st.columns(3)
            with z1: st.metric("Zone A1", filtered_df[filtered_df['Zones'] == 'A1']['Site ID'].nunique())
            with z2: st.metric("Zone A2", filtered_df[filtered_df['Zones'] == 'A2']['Site ID'].nunique())
            with z3: st.metric("Zone A3", filtered_df[filtered_df['Zones'] == 'A3']['Site ID'].nunique())
        st.markdown("---")

        st.subheader("🚛 Sites by Supply Type")
        if 'Type of supply' in filtered_df.columns:
            supply_counts = filtered_df.groupby('Type of supply')['Site ID'].nunique().sort_values(ascending=False)
            if len(supply_counts) > 0:
                cols = st.columns(min(len(supply_counts), 4))
                for i, (stype, count) in enumerate(supply_counts.items()):
                    with cols[i % 4]: st.metric(str(stype).title(), count)
        st.markdown("---")

        chart_col1, chart_col2 = st.columns(2)
        with chart_col1:
            st.subheader("Total QTY Supplied by Region")
            if 'Region' in filtered_df.columns: st.bar_chart(filtered_df.groupby('Region')['Total QTY Supplied'].sum(), width="stretch")
        with chart_col2:
            st.subheader("Variance Status Distribution")
            status_counts = filtered_df['Variance Status'].value_counts().reset_index()
            status_counts.columns = ['Status', 'Count']
            color_map = {'🟢 On Target': '#28a745', '🟡 Slight Variance': '#ffc107', '🔴 High Variance': '#dc3545', ' N/A': '#6c757d'}
            fig = px.bar(status_counts, x='Status', y='Count', color='Status', color_discrete_map=color_map, text='Count')
            fig.update_layout(showlegend=False, yaxis_title='Count', xaxis_title='')
            st.plotly_chart(fig, use_container_width=True)

        st.markdown("---")

        # 🛠️ NEW FEATURE: SITE HISTORY & CPD TREND
        st.subheader("📜 Site History & CPD Trend")
        st.write("Select a site below to see its Estimated CPD history across all months.")
        if 'Site ID' in df.columns:
            history_site = st.selectbox("Select Site ID to view history:", sorted([str(s) for s in df['Site ID'].unique().tolist()]))
            site_hist_df = df[df['Site ID'] == history_site].sort_values('Supply Date')
            
            hist_cols = ['Supply Date', 'Type of supply', 'Total QTY Supplied', 'Estimated CPD', 'Approved CPD', 'CPD Variance', 'Variance Status']
            final_hist_cols = [c for c in hist_cols if c in site_hist_df.columns]
            st.dataframe(site_hist_df[final_hist_cols], hide_index=True, use_container_width=True)
            
            # Optional: Add a line chart for the selected site's CPD history
            if not site_hist_df.empty and 'Estimated CPD' in site_hist_df.columns:
                chart_data = site_hist_df[['Supply Date', 'Estimated CPD', 'Approved CPD']].melt(id_vars='Supply Date', value_vars=['Estimated CPD', 'Approved CPD'], var_name='CPD Type', value_name='Value')
                fig_hist = px.line(chart_data, x='Supply Date', y='Value', color='CPD Type', markers=True, title=f'CPD History for {history_site}')
                st.plotly_chart(fig_hist, use_container_width=True)

        st.markdown("---")

        # Main Dashboard Table (One Line per Site)
        st.subheader("📋 Current Status (Latest Record per Site)")
        df_latest = filtered_df.sort_values('Supply Date').drop_duplicates(subset=['Site ID'], keep='last')
        display_cols = ['Site ID', 'Region', 'Cluster', 'Zones', 'Type of supply', 'Total QTY Supplied', 'Total QTY Before Supply', 'Approved CPD', 'Estimated CPD', 'CPD Variance', 'Variance Status', 'Supply Date', 'Estimated Next Supply Date', 'Supply Alert', 'Bobtail number']
        final_cols = [c for c in display_cols if c in df_latest.columns]
        st.dataframe(df_latest[final_cols], width="stretch", hide_index=True)

else:
    st.info("👆 Database is empty. Use the sidebar to upload an Excel file or add manual entries!")          
