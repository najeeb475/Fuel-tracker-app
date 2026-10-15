import streamlit as st
import pandas as pd
from datetime import timedelta, date
import io
import plotly.express as px

# --- 1. SECURITY & LOGIN ---
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.role = None

if not st.session_state.logged_in:
    st.title("🔒 Access Portal")
    st.write("Please select your access level to continue.")
    
    tab1, tab2 = st.tabs([" Team Access (Data Entry & View)", " Admin Login"])

    with tab1:
        st.subheader("Team Members")
        st.write("Upload data, enter manual records, view the dashboard, and download reports. (No password required)")
        if st.button("Enter as Team"):
            st.session_state.logged_in = True
            st.session_state.role = 'Team'
            st.rerun()

    with tab2:
        st.subheader("Administrator")
        st.write("Full access including data entry, reports, and exclusive administrative controls.")
        password = st.text_input("Enter Admin Password", type="password")
        if st.button("Login as Admin"):
            if password == "admin123": 
                st.session_state.logged_in = True
                st.session_state.role = 'Admin'
                st.rerun()
            else:
                st.error("Incorrect password. Please try again.")
    st.stop()

# --- 2. PAGE CONFIG & SIDEBAR ---
st.set_page_config(page_title="Supply & CPD Tracker", layout="wide")
st.title("📊 Supply & CPD Tracker App")

# Show who is logged in and Logout button
if st.session_state.role == 'Admin':
    st.sidebar.success("🔑 Logged in as Admin")
else:
    st.sidebar.info("👥 Logged in as Team Member")

if st.sidebar.button("Logout"):
    st.session_state.logged_in = False
    st.session_state.role = None
    st.rerun()

# --- 3. SESSION STATE ---
if 'manual_data' not in st.session_state:
    st.session_state.manual_data = []

df = pd.DataFrame()

# --- 4. DATA INGESTION (BOTH ADMIN AND TEAM) ---
st.sidebar.header("📥 Data Input")
input_method = st.sidebar.radio(
    "How would you like to input data?", 
    ("Upload Excel File", "Manual Entry"), 
    horizontal=True
)

if input_method == "Upload Excel File":
    uploaded_file = st.sidebar.file_uploader("Upload your Excel or CSV file", type=["xlsx", "csv"])
    
    if uploaded_file is not None:
        if uploaded_file.name.endswith('.csv'):
            df = pd.read_csv(uploaded_file)
        else:
            df = pd.read_excel(uploaded_file)
        
        df.columns = [str(c).strip() for c in df.columns]
        df = df.loc[:, ~df.columns.duplicated()]

        def find_col(keywords, exclude=None):
            if exclude is None: exclude = []
            for col in df.columns:
                c = str(col).lower()
                if all(k in c for k in keywords) and not any(k in c for k in exclude):
                    return col
            return None

        c_t1_b = find_col(['before', 'tank', '1'])
        c_t1_s = find_col(['suppl', 'tank', '1'], exclude=['before']) 
        c_t2_b = find_col(['before', 'tank', '2'])
        c_t2_s = find_col(['suppl', 'tank', '2'], exclude=['before'])
        c_cpd  = find_col(['approved', 'cpd'])
        c_date = find_col(['supply', 'date'])
        c_site = find_col(['site']) 
        c_region = find_col(['region'])
        c_cluster = find_col(['cluster'])
        c_bobtail = find_col(['bobtail'])

        rename_map = {}
        if c_t1_b: rename_map[c_t1_b] = 'Qty before supply Tank 1'
        if c_t1_s: rename_map[c_t1_s] = 'QTY supplied Tank 1'
        if c_t2_b: rename_map[c_t2_b] = 'Qty before supply Tank 2'
        if c_t2_s: rename_map[c_t2_s] = 'QTY supplied Tank 2'
        if c_cpd:  rename_map[c_cpd] = 'Approved CPD'
        if c_date: rename_map[c_date] = 'Supply Date'
        if c_site: rename_map[c_site] = 'Site ID'
        if c_region: rename_map[c_region] = 'Region'
        if c_cluster: rename_map[c_cluster] = 'Cluster'
        if c_bobtail: rename_map[c_bobtail] = 'Bobtail number'

        df.rename(columns=rename_map, inplace=True)
        df = df.loc[:, ~df.columns.duplicated()]

        tank_cols = ['Qty before supply Tank 1', 'QTY supplied Tank 1', 'Qty before supply Tank 2', 'QTY supplied Tank 2']
        for col in tank_cols:
            if col in df.columns: df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0)
            else: df[col] = 0.0

        if 'Approved CPD' in df.columns: df['Approved CPD'] = pd.to_numeric(df['Approved CPD'], errors='coerce').fillna(0.0)
        if 'Supply Date' in df.columns: df['Supply Date'] = pd.to_datetime(df['Supply Date'], errors='coerce')

elif input_method == "Manual Entry":
    st.sidebar.subheader("Enter Supply Details")
    with st.sidebar.form("manual_entry_form"):
        col1, col2 = st.columns(2)
        with col1:
            site_id = st.text_input("Site ID"); region = st.text_input("Region"); cluster = st.text_input("Cluster")
            qty_before_t1 = st.number_input("Qty before supply Tank 1", min_value=0.0, format="%.2f")
            qty_supplied_t1 = st.number_input("QTY supplied Tank 1", min_value=0.0, format="%.2f")
            qty_before_t2 = st.number_input("Qty before supply Tank 2", min_value=0.0, format="%.2f")
            qty_supplied_t2 = st.number_input("QTY supplied Tank 2", min_value=0.0, format="%.2f")
        with col2:
            approved_cpd = st.number_input("Approved CPD", min_value=0.0, format="%.2f")
            supply_date = st.date_input("Supply Date"); bobtail = st.text_input("Bobtail number")
            
        submitted = st.form_submit_button("➕ Add Record to List")
        if submitted:
            if not site_id: st.error("Please enter at least a Site ID.")
            else:
                new_record = {'Site ID': site_id, 'Region': region, 'Cluster': cluster,
                    'Qty before supply Tank 1': qty_before_t1, 'QTY supplied Tank 1': qty_supplied_t1,
                    'Qty before supply Tank 2': qty_before_t2, 'QTY supplied Tank 2': qty_supplied_t2,
                    'Approved CPD': approved_cpd, 'Supply Date': pd.to_datetime(supply_date), 'Bobtail number': bobtail}
                st.session_state.manual_data.append(new_record); st.success("Record added!")

    if st.session_state.manual_data:
        st.sidebar.write("**Current Manual Entries:**")
        temp_df = pd.DataFrame(st.session_state.manual_data)
        st.sidebar.dataframe(temp_df, use_container_width=True)
        df = temp_df

# --- 5. ADMIN CONTROLS (EXCLUSIVE TO ADMIN) ---
if st.session_state.role == 'Admin':
    st.sidebar.markdown("---")
    st.sidebar.subheader(" Admin Controls")
    st.sidebar.write("Exclusive controls for the administrator.")
    if st.sidebar.button("🗑️ Clear All Manual Entries"): 
        st.session_state.manual_data = []
        st.success("Manual entries cleared!")
        st.rerun()

# --- 6. THE ACTION ENGINE ---
if not df.empty:
    st.divider()
    
    if 'Supply Date' in df.columns and 'Site ID' in df.columns:
        df = df.sort_values(by=['Site ID', 'Supply Date'])
        
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
            if days_diff < 0: return "🚨 OVERDUE"
            elif days_diff == 0: return "🔴 CRITICAL: Supply Today"
            elif days_diff <= 2: return f"🟡 WARNING: Supply in {days_diff} days"
            else: return ""
        df['Supply Alert'] = df['Estimated Next Supply Date'].apply(get_supply_alert)

    # --- 7. SIDEBAR FILTERS ---
    st.sidebar.header("🔍 Filters")
    
    min_date = df['Supply Date'].min().date()
    max_date = df['Supply Date'].max().date()
    
    start_date = st.sidebar.date_input("Start Date", value=min_date, min_value=min_date, max_value=max_date)
    end_date = st.sidebar.date_input("End Date", value=max_date, min_value=min_date, max_value=max_date)
    
    regions = ['All'] + list(df['Region'].dropna().unique()) if 'Region' in df.columns else ['All']
    selected_region = st.sidebar.selectbox("Region", regions)
    
    clusters = ['All'] + list(df['Cluster'].dropna().unique()) if 'Cluster' in df.columns else ['All']
    selected_cluster = st.sidebar.selectbox("Cluster", clusters)
    
    sites = ['All'] + list(df['Site ID'].dropna().unique()) if 'Site ID' in df.columns else ['All']
    selected_site = st.sidebar.selectbox("Site ID", sites)

    mask = (
        (df['Supply Date'].dt.date >= start_date) & 
        (df['Supply Date'].dt.date <= end_date)
    )
    if selected_region != 'All': mask &= (df['Region'] == selected_region)
    if selected_cluster != 'All': mask &= (df['Cluster'] == selected_cluster)
    if selected_site != 'All': mask &= (df['Site ID'] == selected_site)
    
    filtered_df = df[mask].copy()

    if filtered_df.empty:
        st.warning("No data found for the selected filters.")
    else:
        # --- 8. SUMMARY DASHBOARD ---
        st.subheader("📊 Summary Dashboard")
        
        total_sites = filtered_df['Site ID'].nunique()
        total_supplied = filtered_df['Total QTY Supplied'].sum()
        high_variance_count = (filtered_df['Variance Status'] == '🔴 High Variance').sum()
        
        urgent_supplies = filtered_df['Supply Alert'].apply(
            lambda x: 1 if 'CRITICAL' in str(x) or 'WARNING' in str(x) or 'OVERDUE' in str(x) else 0
        ).sum()

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total Sites Tracked", total_sites)
        col2.metric("Total Fuel Supplied", f"{total_supplied:,.0f} L")
        col3.metric("High Variance Sites", high_variance_count, delta="-" if high_variance_count > 0 else "0")
        col4.metric("Urgent Supplies Needed", urgent_supplies, delta="Action Required" if urgent_supplies > 0 else "All Good")

        st.markdown("---")

        # --- 9. CHARTS ---
        chart_col1, chart_col2 = st.columns(2)
        
        with chart_col1:
            st.subheader("Total QTY Supplied by Region")
            if 'Region' in filtered_df.columns:
                st.bar_chart(filtered_df.groupby('Region')['Total QTY Supplied'].sum())

        with chart_col2:
            st.subheader("Variance Status Distribution")
            status_counts = filtered_df['Variance Status'].value_counts().reset_index()
            status_counts.columns = ['Status', 'Count']
            
            # --- COLORFUL VARIANCE GRAPH (PLOTLY) ---
            color_map = {
                '🟢 On Target': '#28a745',       # Green
                '🟡 Slight Variance': '#ffc107', # Yellow
                '🔴 High Variance': '#dc3545',   # Red
                '⚪ N/A': '#6c757d'              # Grey
            }
            
            fig = px.bar(status_counts, x='Status', y='Count', color='Status',
                         color_discrete_map=color_map, text='Count',
                         title='Variance Status Distribution')
            fig.update_layout(showlegend=False, yaxis_title='Number of Records', xaxis_title='')
            fig.update_traces(textposition='outside')
            st.plotly_chart(fig, use_container_width=True)

        st.markdown("---")

        # --- 10. HISTORICAL TREND CHART ---
        st.subheader("📈 Historical CPD Trend")
        
        trend_sites = filtered_df['Site ID'].unique()
        if len(trend_sites) > 0:
            default_trend_site = selected_site if selected_site != 'All' else trend_sites[0]
            trend_site_select = st.selectbox("View Trend for Site:", trend_sites, index=list(trend_sites).index(default_trend_site) if default_trend_site in trend_sites else 0)
            
            site_trend_data = filtered_df[filtered_df['Site ID'] == trend_site_select].sort_values('Supply Date')
            
            if not site_trend_data.empty and site_trend_data['Estimated CPD'].sum() > 0:
                chart_data = site_trend_data.set_index('Supply Date')[['Estimated CPD', 'Approved CPD']]
                st.line_chart(chart_data)
            else:
                st.info("No CPD data available for this site in the selected range.")

        st.markdown("---")

        # --- 11. DETAILED TABLE & EXCEL EXPORT ---
        st.subheader("📋 Detailed Data & Analysis")
        
        def highlight_var(val):
            if val > 0: return 'background-color: #d4edda'
            elif val < 0: return 'background-color: #f8d7da'
            return ''

        def highlight_alert(val):
            if 'CRITICAL' in str(val) or 'OVERDUE' in str(val): return 'background-color: #ffcccc; font-weight: bold;'
            elif 'WARNING' in str(val): return 'background-color: #fff2cc; font-weight: bold;'
            return ''

        display_cols = [
            'Site ID', 'Region', 'Cluster', 'Total QTY Supplied', 'Total QTY Before Supply', 
            'Approved CPD', 'Estimated CPD', 'CPD Variance', 'Variance Status', 
            'Supply Date', 'Estimated Next Supply Date', 'Supply Alert', 'Bobtail number'
        ]
        final_cols = [c for c in display_cols if c in filtered_df.columns]
        display_df = filtered_df[final_cols]

        styled_df = display_df.style.map(highlight_var, subset=['CPD Variance'])
        if 'Supply Alert' in styled_df.columns:
            styled_df = styled_df.map(highlight_alert, subset=['Supply Alert'])
        
        def format_num(x):
            if pd.isnull(x): return ''
            return f"{x:.0f}"
        def format_date(x):
            if pd.isnull(x): return ''
            if hasattr(x, 'strftime'): return x.strftime('%Y-%m-%d')
            return str(x)

        format_dict = {}
        num_cols = ['Total QTY Supplied', 'Total QTY Before Supply', 'Approved CPD', 'Estimated CPD', 'CPD Variance']
        for col in num_cols:
            if col in display_df.columns: format_dict[col] = format_num
        if 'Estimated Next Supply Date' in display_df.columns: format_dict['Estimated Next Supply Date'] = format_date
        if 'Supply Date' in display_df.columns: format_dict['Supply Date'] = format_date

        styled_df = styled_df.format(format_dict)
        st.dataframe(styled_df, use_container_width=True, hide_index=True)

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
    st.info("👆 No data available. Please upload an Excel file or add manual entries from the sidebar.")
