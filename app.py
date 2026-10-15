import streamlit as st
import pandas as pd
from datetime import timedelta, date

# --- PAGE CONFIG ---
st.set_page_config(page_title="Supply & CPD Tracker", layout="wide")
st.title("📊 Supply & CPD Tracker App")

# --- SESSION STATE ---
if 'manual_data' not in st.session_state:
    st.session_state.manual_data = []

# --- 1. INPUT METHOD ---
input_method = st.radio(
    "How would you like to input data?", 
    ("Upload Excel File", "Manual Entry"), 
    horizontal=True
)

df = pd.DataFrame()

# --- 2. DATA INGESTION ---
if input_method == "Upload Excel File":
    uploaded_file = st.file_uploader("Upload your Excel or CSV file", type=["xlsx", "csv"])
    
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
    st.subheader("Enter Supply Details")
    with st.form("manual_entry_form"):
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
        st.write("**Current Manual Entries:**")
        temp_df = pd.DataFrame(st.session_state.manual_data)
        st.dataframe(temp_df, use_container_width=True)
        if st.button("🗑️ Clear All Manual Entries"): st.session_state.manual_data = []; st.rerun()
        df = temp_df

# --- 3. THE ACTION ENGINE ---
if not df.empty:
    st.divider()
    
    if 'Supply Date' in df.columns and 'Site ID' in df.columns:
        # Sort oldest to newest
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

        # --- SUPPLY ALERT SYSTEM ---
        today = pd.Timestamp.today().date()
        def get_supply_alert(next_date):
            if pd.isnull(next_date): return ""
            days_diff = (next_date - today).days
            if days_diff < 0: return " OVERDUE"
            elif days_diff == 0: return "🔴 CRITICAL: Supply Today"
            elif days_diff <= 2: return f"🟡 WARNING: Supply in {days_diff} days"
            else: return ""
        df['Supply Alert'] = df['Estimated Next Supply Date'].apply(get_supply_alert)

    # --- NEW: DATE RANGE FILTER ---
    st.subheader(" Select Date Range")
    min_date = df['Supply Date'].min().date()
    max_date = df['Supply Date'].max().date()
    
    col_start, col_end = st.columns(2)
    with col_start:
        start_date = st.date_input("Start Date", value=min_date, min_value=min_date, max_value=max_date)
    with col_end:
        end_date = st.date_input("End Date", value=max_date, min_value=min_date, max_value=max_date)

    # Filter the data for Dashboard and Table
    # We keep the full 'df' for calculations, but use 'filtered_df' for display
    filtered_df = df[
        (df['Supply Date'].dt.date >= start_date) & 
        (df['Supply Date'].dt.date <= end_date)
    ].copy()

    if filtered_df.empty:
        st.warning("No data found for the selected date range.")
    else:
        # --- 4. SUMMARY DASHBOARD (Using Filtered Data) ---
        st.subheader("📊 Summary Dashboard")
        
        total_sites = filtered_df['Site ID'].nunique()
        total_supplied = filtered_df['Total QTY Supplied'].sum()
        high_variance_count = (filtered_df['Variance Status'] == ' High Variance').sum()
        
        urgent_supplies = filtered_df['Supply Alert'].apply(lambda x: 1 if 'CRITICAL' in str(x) or 'WARNING' in str(x) or 'OVERDUE' in str(x) else 0).sum()

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total Sites Tracked", total_sites)
        col2.metric("Total Fuel Supplied", f"{total_supplied:,.0f} L")
        col3.metric("High Variance Sites", high_variance_count, delta="-" if high_variance_count > 0 else "0")
        col4.metric("Urgent Supplies Needed", urgent_supplies, delta="Action Required" if urgent_supplies > 0 else "All Good")

        st.markdown("---")

        # Charts
        chart_col1, chart_col2 = st.columns(2)
        
        with chart_col1:
            st.subheader("Total QTY Supplied by Region")
            if 'Region' in filtered_df.columns:
                region_data = filtered_df.groupby('Region')['Total QTY Supplied'].sum()
                st.bar_chart(region_data)

        with chart_col2:
            st.subheader("Variance Status Distribution")
            if 'Variance Status' in filtered_df.columns:
                status_counts = filtered_df['Variance Status'].value_counts()
                st.bar_chart(status_counts)

        st.markdown("---")
        st.subheader("📈 Detailed Data & Analysis")
        
        # Highlighting
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

        csv = display_df.to_csv(index=False).encode('utf-8')
        st.download_button(label="📥 Download Filtered Data", data=csv, file_name=f"supply_data_{start_date}_to_{end_date}.csv", mime="text/csv")

else:
    if input_method == "Upload Excel File": st.info("👆 Please upload an Excel or CSV file to begin.")
    else: st.info(" Please add records using the form above.")
