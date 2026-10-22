import streamlit as st
import pandas as pd
from datetime import timedelta, date
import io
import plotly.express as px
import firebase_admin
from firebase_admin import credentials, firestore
from streamlit_cookies_controller import CookieController

# --- 1. SECURITY & LOGIN (WITH COOKIES) ---
controller = CookieController()

# Check if user is already logged in via cookies
if 'logged_in' not in st.session_state:
    if controller.get('logged_in') == 'true':
        st.session_state.logged_in = True
        st.session_state.role = controller.get('role')

if 'logged_in' not in st.session_state or not st.session_state.logged_in:
    st.title("🔒 Access Portal")
    st.write("Please select your access level to continue.")
    
    tab1, tab2 = st.tabs(["👥 Team Access (Data Entry & View)", "🔑 Admin Login"])

    with tab1:
        st.subheader("Team Members")
        st.write("Upload data, enter manual records, view the dashboard, and download reports. (No password required)")
        if st.button("Enter as Team"):
            st.session_state.logged_in = True
            st.session_state.role = 'Team'
            controller.set('logged_in', 'true')
            controller.set('role', 'Team')
            st.rerun()

    with tab2:
        st.subheader("Administrator")
        st.write("Full access including data entry, reports, and exclusive administrative controls.")
        password = st.text_input("Enter Admin Password", type="password")
        if st.button("Login as Admin"):
            if password == "admin123": 
                st.session_state.logged_in = True
                st.session_state.role = 'Admin'
                controller.set('logged_in', 'true')
                controller.set('role', 'Admin')
                st.rerun()
            else:
                st.error("Incorrect password. Please try again.")
    st.stop()

# --- 2. PAGE CONFIG & SIDEBAR ---
st.set_page_config(page_title="Supply & CPD Tracker", layout="wide")
st.title("📊 Supply & CPD Tracker App")

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

# --- 3. CONNECT TO FIREBASE DATABASE ---
@st.cache_resource
def init_firebase():
    try:
        config = dict(st.secrets["firebase_config"])
        cred = credentials.Certificate(config)
        if not firebase_admin._apps:
            firebase_admin.initialize_app(cred, {'databaseURL': st.secrets["firebase_db_url"]})
        return firestore.client()
    except Exception as e:
        st.error(f"Database connection failed. Check your Secrets. Error: {e}")
        return None

db = init_firebase()

# --- 4. LOAD DATA FROM FIREBASE ---
df = pd.DataFrame()
if db:
    try:
        docs = db.collection('supplies').stream()
        data = [doc.to_dict() for doc in docs]
        if data:
            df = pd.DataFrame(data)
            if 'Supply Date' in df.columns:
                df['Supply Date'] = pd.to_datetime(df['Supply Date'], errors='coerce')
            
            # 🛠️ FIX 1: AUTOMATIC DATA CLEANING (Removes spaces, standardizes capitalization)
            if not df.empty:
                if 'Zones' in df.columns:
                    df['Zones'] = df['Zones'].astype(str).str.strip().str.upper()
                if 'Type of supply' in df.columns:
                    df['Type of supply'] = df['Type of supply'].astype(str).str.strip().str.lower()
                    
    except Exception as e:
        st.warning("Database is empty. You can start adding data!")

# --- 5. DATA INGESTION (MANUAL & EXCEL) ---
st.sidebar.header("📥 Data Input")
input_method = st.sidebar.radio(
    "How would you like to input data?", 
    ("Manual Entry", "Upload Excel File"), 
    horizontal=True
)

if input_method == "Manual Entry":
    st.sidebar.subheader("Enter Supply Details")
    with st.sidebar.form("manual_entry_form"):
        col1, col2 = st.columns(2)
        with col1:
            site_id = st.text_input("Site ID")
            region = st.text_input("Region")
            cluster = st.text_input("Cluster")
            zone = st.selectbox("Zones", ["A1", "A2", "A3"])
            qty_before_t1 = st.number_input("Qty before supply Tank 1", min_value=0.0, format="%.2f")
            qty_supplied_t1 = st.number_input("QTY supplied Tank 1", min_value=0.0, format="%.2f")
            qty_before_t2 = st.number_input("Qty before supply Tank 2", min_value=0.0, format="%.2f")
            qty_supplied_t2 = st.number_input("QTY supplied Tank 2", min_value=0.0, format="%.2f")
        with col2:
            approved_cpd = st.number_input("Approved CPD", min_value=0.0, format="%.2f")
            supply_date = st.date_input("Supply Date")
            bobtail = st.text_input("Bobtail number")
            supply_type = st.selectbox("Type of supply", ["1st supply", "2nd supply", "3rd supply"])
            
        submitted = st.form_submit_button("💾 Save to Database")
        if submitted:
            if not site_id: 
                st.error("Please enter at least a Site ID.")
            elif not db: 
                st.error("Database not connected.")
            else:
                record = {
                    'Site ID': str(site_id), 
                    'Region': str(region), 
                    'Cluster': str(cluster),
                    'Zones': str(zone).strip().upper(),
                    'Qty before supply Tank 1': float(qty_before_t1), 
                    'QTY supplied Tank 1': float(qty_supplied_t1),
                    'Qty before supply Tank 2': float(qty_before_t2), 
                    'QTY supplied Tank 2': float(qty_supplied_t2),
                    'Approved CPD': float(approved_cpd), 
                    'Supply Date': supply_date.strftime("%Y-%m-%d"), 
                    'Bobtail number': str(bobtail),
                    'Type of supply': str(supply_type).strip().lower()
                }
                db.collection('supplies').add(record)
                st.success("✅ Saved to Firebase successfully!")
                st.rerun()

elif input_method == "Upload Excel File":
    st.sidebar.subheader("Upload Excel to Database")
    uploaded_file = st.sidebar.file_uploader("Upload your Excel or CSV file", type=["xlsx", "csv"])
    
    if uploaded_file is not None and db:
        if uploaded_file.name.endswith('.csv'): 
            temp_df = pd.read_csv(uploaded_file)
        else: 
            temp_df = pd.read_excel(uploaded_file)
        
        temp_df.columns = [str(c).strip() for c in temp_df.columns]
        
        def find_col(keywords, exclude=None):
            if exclude is None: exclude = []
            for col in temp_df.columns:
                c = str(col).lower()
                if all(k in c for k in keywords) and not any(k in c for k in exclude): 
                    return col
            return None

        rename_map = {}
        if find_col(['before', 'tank', '1']): rename_map[find_col(['before', 'tank', '1'])] = 'Qty before supply Tank 1'
        if find_col(['suppl', 'tank', '1'], exclude=['before']): rename_map[find_col(['suppl', 'tank', '1'], exclude=['before'])] = 'QTY supplied Tank 1'
        if find_col(['before', 'tank', '2']): rename_map[find_col(['before', 'tank', '2'])] = 'Qty before supply Tank 2'
        if find_col(['suppl', 'tank', '2'], exclude=['before']): rename_map[find_col(['suppl', 'tank', '2'], exclude=['before'])] = 'QTY supplied Tank 2'
        if find_col(['approved', 'cpd']): rename_map[find_col(['approved', 'cpd'])] = 'Approved CPD'
        if find_col(['supply', 'date']): rename_map[find_col(['supply', 'date'])] = 'Supply Date'
        if find_col(['site']): rename_map[find_col(['site'])] = 'Site ID'
        if find_col(['region']): rename_map[find_col(['region'])] = 'Region'
        if find_col(['cluster']): rename_map[find_col(['cluster'])] = 'Cluster'
        if find_col(['bobtail']): rename_map[find_col(['bobtail'])] = 'Bobtail number'
        if find_col(['zone']): rename_map[find_col(['zone'])] = 'Zones'
        if find_col(['type', 'supply']): rename_map[find_col(['type', 'supply'])] = 'Type of supply'

        temp_df.rename(columns=rename_map, inplace=True)
        
        required_cols = ['Site ID', 'Region', 'Cluster', 'Qty before supply Tank 1', 'QTY supplied Tank 1', 'Qty before supply Tank 2', 'QTY supplied Tank 2', 'Approved CPD', 'Supply Date', 'Bobtail number']
        for col in required_cols:
            if col not in temp_df.columns: 
                temp_df[col] = 0.0 if 'Qty' in col or 'CPD' in col else ''
        
        if 'Zones' not in temp_df.columns:
            temp_df['Zones'] = 'A1'
        if 'Type of supply' not in temp_df.columns:
            temp_df['Type of supply'] = '1st supply'

        count = 0
        for index, row in temp_df.iterrows():
            date_val = row['Supply Date']
            if hasattr(date_val, 'strftime'): 
                date_val = date_val.strftime("%Y-%m-%d")
            else: 
                date_val = str(date_val)
            
            # 🛠️ FIX 2: CLEAN DATA DURING UPLOAD TO PREVENT MISMATCHES
            zone_val = str(row.get('Zones', 'A1')).strip().upper()
            supply_type_val = str(row.get('Type of supply', '1st supply')).strip().lower()
            
            record = {
                'Site ID': str(row['Site ID']), 
                'Region': str(row['Region']), 
                'Cluster': str(row['Cluster']),
                'Zones': zone_val,
                'Qty before supply Tank 1': float(row['Qty before supply Tank 1']), 
                'QTY supplied Tank 1': float(row['QTY supplied Tank 1']),
                'Qty before supply Tank 2': float(row['Qty before supply Tank 2']), 
                'QTY supplied Tank 2': float(row['QTY supplied Tank 2']),
                'Approved CPD': float(row['Approved CPD']), 
                'Supply Date': date_val, 
                'Bobtail number': str(row['Bobtail number']),
                'Type of supply': supply_type_val
            }
            db.collection('supplies').add(record)
            count += 1
        
        st.sidebar.success(f"✅ Uploaded {count} rows to Firebase!")
        st.rerun()

# --- 6. ADMIN CONTROLS ---
if st.session_state.role == 'Admin':
    st.sidebar.markdown("---")
    st.sidebar.subheader("🔑 Admin Controls")
    if st.sidebar.button("🗑️ Clear Database (Danger)"): 
        if st.sidebar.checkbox("Are you sure? This deletes everything permanently."):
            docs = db.collection('supplies').stream()
            for doc in docs:
                doc.reference.delete()
            st.success("Firebase Database cleared!")
            st.rerun()

# --- 7. THE ACTION ENGINE ---
if not df.empty:
    st.divider()
    
    if 'Supply Date' in df.columns and 'Site ID' in df.columns:
        df = df.sort_values(by=['Site ID', 'Supply Date'])
        
        for col in ['Qty before supply Tank 1', 'QTY supplied Tank 1', 'Qty before supply Tank 2', 'QTY supplied Tank 2', 'Approved CPD']:
            if col in df.columns: 
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0)

        df['Total QTY Before Supply'] = df['Qty before supply Tank 1'] + df['Qty before supply Tank 2']
        df['Total QTY Supplied'] = df['QTY supplied Tank 1'] + df['QTY supplied Tank 2']

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
            else: 
                return None
        df['Estimated Next Supply Date'] = df.apply(calc_next_date, axis=1)

        def calc_variance(row):
            if row['Estimated CPD'] == 0 or pd.isnull(row['Estimated CPD']): 
                return 0
            return row['Approved CPD'] - row['Estimated CPD']
        df['CPD Variance'] = df.apply(calc_variance, axis=1)
        
        def get_status(row):
            if row['Estimated CPD'] == 0 or pd.isnull(row['Estimated CPD']): 
                return "⚪ N/A"
            app = row['Approved CPD']
            var = row['CPD Variance']
            if app == 0: 
                return "⚪ N/A"
            pct = abs(var) / app
            if pct <= 0.05: 
                return "🟢 On Target"
            elif pct <= 0.15: 
                return "🟡 Slight Variance"
            else: 
                return "🔴 High Variance"
        df['Variance Status'] = df.apply(get_status, axis=1)

        today = pd.Timestamp.today().date()
        def get_supply_alert(next_date):
            if pd.isnull(next_date): 
                return ""
            days_diff = (next_date - today).days
            if days_diff < 0: 
                return "🚨 OVERDUE"
            elif days_diff == 0: 
                return "🔴 CRITICAL: Supply Today"
            elif days_diff <= 2: 
                return f"🟡 WARNING: Supply in {days_diff} days"
            else: 
                return ""
        df['Supply Alert'] = df['Estimated Next Supply Date'].apply(get_supply_alert)

    # --- 8. SIDEBAR FILTERS ---
    st.sidebar.header("🔍 Filters")
    min_date = df['Supply Date'].min().date()
    max_date = df['Supply Date'].max().date()
    
    start_date = st.sidebar.date_input("Start Date", value=min_date, min_value=min_date, max_value=max_date)
    end_date = st.sidebar.date_input("End Date", value=max_date, min_value=min_date, max_value=max_date)
    
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

    if filtered_df.empty:
        st.warning("No data found for the selected filters.")
    else:
        # --- 9. SUMMARY DASHBOARD ---
        st.subheader("📊 Summary Dashboard")
        
        total_sites = filtered_df['Site ID'].nunique()
        total_supplied = filtered_df['Total QTY Supplied'].sum()
        high_variance_count = (filtered_df['Variance Status'] == '🔴 High Variance').sum()
        sites_supplied_in_range = filtered_df['Site ID'].nunique()
        urgent_supplies = filtered_df['Supply Alert'].apply(lambda x: 1 if 'CRITICAL' in str(x) or 'WARNING' in str(x) or 'OVERDUE' in str(x) else 0).sum()

        col1, col2, col3, col4, col5 = st.columns(5)
        col1.metric("Total Sites Tracked", total_sites)
        col2.metric("Sites Supplied in Range", sites_supplied_in_range)
        col3.metric("Total Fuel Supplied", f"{total_supplied:,.0f} L")
        col4.metric("High Variance Sites", high_variance_count, delta="-" if high_variance_count > 0 else "0")
        col5.metric("Urgent Supplies", urgent_supplies, delta="Action" if urgent_supplies > 0 else "Good")

        st.markdown("---")

        # 🛠️ FIX 3: COUNT UNIQUE SITES INSTEAD OF ROWS FOR ZONES
        st.subheader("📍 Sites by Zone")
        if 'Zones' in filtered_df.columns:
            zone_col1, zone_col2, zone_col3 = st.columns(3)
            with zone_col1:
                zone_a1 = filtered_df[filtered_df['Zones'] == 'A1']['Site ID'].nunique()
                st.metric(label="Zone A1", value=zone_a1)
            with zone_col2:
                zone_a2 = filtered_df[filtered_df['Zones'] == 'A2']['Site ID'].nunique()
                st.metric(label="Zone A2", value=zone_a2)
            with zone_col3:
                zone_a3 = filtered_df[filtered_df['Zones'] == 'A3']['Site ID'].nunique()
                st.metric(label="Zone A3", value=zone_a3)
        
        st.markdown("---")

        # 🛠️ FIX 4: COUNT UNIQUE SITES INSTEAD OF ROWS FOR SUPPLY TYPE
        st.subheader("🚛 Sites by Supply Type")
        if 'Type of supply' in filtered_df.columns:
            supply_col1, supply_col2, supply_col3 = st.columns(3)
            with supply_col1:
                supply_1st = filtered_df[filtered_df['Type of supply'] == '1st supply']['Site ID'].nunique()
                st.metric(label="1st Supply", value=supply_1st)
            with supply_col2:
                supply_2nd = filtered_df[filtered_df['Type of supply'] == '2nd supply']['Site ID'].nunique()
                st.metric(label="2nd Supply", value=supply_2nd)
            with supply_col3:
                supply_3rd = filtered_df[filtered_df['Type of supply'] == '3rd supply']['Site ID'].nunique()
                st.metric(label="3rd Supply", value=supply_3rd)
        
        st.markdown("---")

        # --- 10. CHARTS ---
        chart_col1, chart_col2 = st.columns(2)
        with chart_col1:
            st.subheader("Total QTY Supplied by Region")
            if 'Region' in filtered_df.columns: 
                st.bar_chart(filtered_df.groupby('Region')['Total QTY Supplied'].sum(), width="stretch")
                
        with chart_col2:
            st.subheader("Variance Status Distribution")
            status_counts = filtered_df['Variance Status'].value_counts().reset_index()
            status_counts.columns = ['Status', 'Count']
            color_map = {'🟢 On Target': '#28a745', '🟡 Slight Variance': '#ffc107', '🔴 High Variance': '#dc3545', '⚪ N/A': '#6c757d'}
            fig = px.bar(status_counts, x='Status', y='Count', color='Status', color_discrete_map=color_map, text='Count')
            fig.update_layout(showlegend=False, yaxis_title='Number of Records', xaxis_title='')
            fig.update_traces(textposition='outside')
            st.plotly_chart(fig, use_container_width=True)

        st.markdown("---")

        # --- 11. HISTORICAL TREND CHART ---
        st.subheader("📈 Historical CPD Trend")
        trend_sites = filtered_df['Site ID'].unique()
        if len(trend_sites) > 0:
            default_trend_site = selected_site if selected_site != 'All' else trend_sites[0]
            trend_site_select = st.selectbox("View Trend for Site:", trend_sites, index=list(trend_sites).index(default_trend_site) if default_trend_site in trend_sites else 0)
            site_trend_data = filtered_df[filtered_df['Site ID'] == trend_site_select].sort_values('Supply Date')
            
            if not site_trend_data.empty and site_trend_data['Estimated CPD'].sum() > 0:
                chart_data_melted = site_trend_data[['Supply Date', 'Estimated CPD', 'Approved CPD']].melt(id_vars='Supply Date', value_vars=['Estimated CPD', 'Approved CPD'], var_name='CPD Type', value_name='Value')
                fig_line = px.line(chart_data_melted, x='Supply Date', y='Value', color='CPD Type', markers=True, color_discrete_map={'Estimated CPD': '#007bff', 'Approved CPD': '#dc3545'}, title=f'CPD Trend for {trend_site_select}')
                st.plotly_chart(fig_line, use_container_width=True)

        st.markdown("---")

        # --- 12. DETAILED TABLE & EXCEL EXPORT ---
        st.subheader("📋 Detailed Data & Analysis")
        def highlight_var(val):
            if val > 0: return 'background-color: #d4edda'
            elif val < 0: return 'background-color: #f8d7da'
            return ''
            
        def highlight_alert(val):
            if 'CRITICAL' in str(val) or 'OVERDUE' in str(val): return 'background-color: #ffcccc; font-weight: bold;'
            elif 'WARNING' in str(val): return 'background-color: #fff2cc; font-weight: bold;'
            return ''

        display_cols = ['Site ID', 'Region', 'Cluster', 'Zones', 'Type of supply', 'Total QTY Supplied', 'Total QTY Before Supply', 'Approved CPD', 'Estimated CPD', 'CPD Variance', 'Variance Status', 'Supply Date', 'Estimated Next Supply Date', 'Supply Alert', 'Bobtail number']
        final_cols = [c for c in display_cols if c in filtered_df.columns]
        display_df = filtered_df[final_cols]

        styled_df = display_df.style.map(highlight_var, subset=['CPD Variance'])
        if 'Supply Alert' in styled_df.columns: 
            styled_df = styled_df.map(highlight_alert, subset=['Supply Alert'])
        
        def format_num(x): return f"{x:.0f}" if not pd.isnull(x) else ''
        def format_date(x): return x.strftime('%Y-%m-%d') if not pd.isnull(x) and hasattr(x, 'strftime') else str(x)

        format_dict = {col: format_num for col in ['Total QTY Supplied', 'Total QTY Before Supply', 'Approved CPD', 'Estimated CPD', 'CPD Variance'] if col in display_df.columns}
        if 'Estimated Next Supply Date' in display_df.columns: format_dict['Estimated Next Supply Date'] = format_date
        if 'Supply Date' in display_df.columns: format_dict['Supply Date'] = format_date

        st.dataframe(styled_df.format(format_dict), width="stretch", hide_index=True)

        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer: 
            display_df.to_excel(writer, index=False, sheet_name='Supply Data')
            
        st.download_button(
            label="📥 Download Filtered Data as Excel", 
            data=output.getvalue(), 
            file_name=f"supply_data_{start_date}_to_{end_date}.xlsx", 
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

else:
    st.info("👆 Database is empty. Use the sidebar to add your first manual entry or upload an Excel file to populate the database!")
