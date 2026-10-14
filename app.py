import streamlit as st
import pandas as pd
from datetime import timedelta

# --- PAGE CONFIG ---
st.set_page_config(page_title="Supply & CPD Tracker", layout="wide")
st.title("📊 Supply & CPD Tracker App")

# --- SESSION STATE ---
if 'manual_data' not in st.session_state:
    st.session_state.manual_data = []

# --- 1. INPUT METHOD ---
input_method = st.radio("How would you like to input data?", ("Upload Excel File", "Manual Entry"), horizontal=True)

df = pd.DataFrame()

# --- 2. DATA INGESTION ---
if input_method == "Upload Excel File":
    uploaded_file = st.file_uploader("Upload your Excel or CSV file", type=["xlsx", "csv"])
    if uploaded_file is not None:
        if uploaded_file.name.endswith('.csv'):
            df = pd.read_csv(uploaded_file)
        else:
            df = pd.read_excel(uploaded_file)
        
        # --- BULLETPROOF COLUMN FINDER ---
        def find_col(keywords):
            for col in df.columns:
                c = str(col).lower()
                # Check if ALL keywords exist in the column name
                if all(k in c for k in keywords):
                    return col
            return None

        # Search for columns using flexible keywords
        c_t1_b = find_col(['before', 'tank', '1'])
        c_t1_s = find_col(['suppl', 'tank', '1']) # Matches 'supplied' and 'supply'
        c_t2_b = find_col(['before', 'tank', '2'])
        c_t2_s = find_col(['suppl', 'tank', '2'])
        c_cpd  = find_col(['approved', 'cpd'])
        c_date = find_col(['supply', 'date'])
        c_site = find_col(['site']) 
        c_region = find_col(['region'])
        c_cluster = find_col(['cluster'])
        c_bobtail = find_col(['bobtail'])

        # Map found columns to standard names
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

        # --- VALIDATION: Stop gracefully if columns are missing ---
        required_cols = ['Qty before supply Tank 1', 'QTY supplied Tank 1', 'Qty before supply Tank 2', 'QTY supplied Tank 2', 'Approved CPD', 'Supply Date']
        missing_cols = [col for col in required_cols if col not in df.columns]
        
        if missing_cols:
            st.error(f"❌ I couldn't find the following columns in your file: **{missing_cols}**")
            st.info(f"👉 Your file currently has these columns: **{list(df.columns)}**")
            st.stop() # Stops the app safely without crashing

        # Ensure Date is a date
        if 'Supply Date' in df.columns:
            df['Supply Date'] = pd.to_datetime(df['Supply Date'], errors='coerce')

elif input_method == "Manual Entry":
    st.subheader("Enter Supply Details")
    with st.form("manual_entry_form"):
        col1, col2 = st.columns(2)
        with col1:
            site_id = st.text_input("Site ID")
            region = st.text_input("Region")
            cluster = st.text_input("Cluster")
            qty_before_t1 = st.number_input("Qty before supply Tank 1", min_value=0.0, format="%.2f")
            qty_supplied_t1 = st.number_input("QTY supplied Tank 1", min_value=0.0, format="%.2f")
            qty_before_t2 = st.number_input("Qty before supply Tank 2", min_value=0.0, format="%.2f")
            qty_supplied_t2 = st.number_input("QTY supplied Tank 2", min_value=0.0, format="%.2f")
        with col2:
            approved_cpd = st.number_input("Approved CPD", min_value=0.0, format="%.2f")
            supply_date = st.date_input("Supply Date")
            bobtail = st.text_input("Bobtail number")
            
        submitted = st.form_submit_button("➕ Add Record to List")
        if submitted:
            if not site_id:
                st.error("Please enter at least a Site ID.")
            else:
                new_record = {
                    'Site ID': site_id, 'Region': region, 'Cluster': cluster,
                    'Qty before supply Tank 1': qty_before_t1, 'QTY supplied Tank 1': qty_supplied_t1,
                    'Qty before supply Tank 2': qty_before_t2, 'QTY supplied Tank 2': qty_supplied_t2,
                    'Approved CPD': approved_cpd, 'Supply Date': pd.to_datetime(supply_date), 'Bobtail number': bobtail
                }
                st.session_state.manual_data.append(new_record)
                st.success("Record added!")

    if st.session_state.manual_data:
        st.write("**Current Manual Entries:**")
        temp_df = pd.DataFrame(st.session_state.manual_data)
        st.dataframe(temp_df, use_container_width=True)
        if st.button("️ Clear All Manual Entries"):
            st.session_state.manual_data = []
            st.rerun()
        df = temp_df

# --- 3. THE ACTION ENGINE ---
if not df.empty:
    st.divider()
    st.subheader(" Processed Data & Analysis")
    
    # Ensure numeric
    for col in ['Qty before supply Tank 1', 'QTY supplied Tank 1', 'Qty before supply Tank 2', 'QTY supplied Tank 2', 'Approved CPD']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

    # Totals
    df['Total QTY Before Supply'] = df['Qty before supply Tank 1'] + df['Qty before supply Tank 2']
    df['Total QTY Supplied'] = df['QTY supplied Tank 1'] + df['QTY supplied Tank 2']

    if 'Supply Date' in df.columns and 'Site ID' in df.columns:
        df = df.sort_values(by=['Site ID', 'Supply Date'])

        # Previous row data
        df['Prev_Total_Supplied'] = df.groupby('Site ID')['Total QTY Supplied'].shift(1)
        df['Prev_Total_Before'] = df.groupby('Site ID')['Total QTY Before Supply'].shift(1)
        df['Prev_Supply_Date'] = df.groupby('Site ID')['Supply Date'].shift(1)

        df['Days_Diff'] = (df['Supply Date'] - df['Prev_Supply_Date']).dt.days
        df['Total_Consumed'] = (df['Prev_Total_Before'] + df['Prev_Total_Supplied']) - df['Total QTY Before Supply']

        # Estimated CPD
        df['Estimated CPD'] = df['Total_Consumed'] / df['Days_Diff']
        df['Estimated CPD'] = df['Estimated CPD'].where(df['Days_Diff'] > 0, 0) 

        # Next Supply Date
        df['Days_Fuel_Last'] = df['Total QTY Supplied'] / df['Estimated CPD']
        df['Days_Fuel_Last'] = df['Days_Fuel_Last'].where(df['Estimated CPD'] > 0, 0) 
        df['Estimated Next Supply Date'] = df.apply(
            lambda row: row['Supply Date'] + timedelta(days=row['Days_Fuel_Last']) if row['Days_Fuel_Last'] > 0 else pd.NaT, axis=1
        )

        # Variance
        df['CPD Variance'] = df['Approved CPD'] - df['Estimated CPD']
        
        def get_status(var, app):
            if app == 0: return "⚪ N/A"
            pct = abs(var) / app
            if pct <= 0.05: return "🟢 On Target"
            elif pct <= 0.15: return "🟡 Slight Variance"
            else: return "🔴 High Variance"
        df['Variance Status'] = df.apply(lambda r: get_status(r['CPD Variance'], r['Approved CPD']), axis=1)

    # --- 4. DISPLAY ---
    def highlight_var(val):
        if val > 0: return 'background-color: #d4edda'
        elif val < 0: return 'background-color: #f8d7da'
        return ''

    display_cols = ['Site ID', 'Region', 'Cluster', 'Total QTY Supplied', 'Approved CPD', 
                    'Estimated CPD', 'CPD Variance', 'Variance Status', 'Supply Date', 'Estimated Next Supply Date', 'Bobtail number']
    final_cols = [c for c in display_cols if c in df.columns]
    display_df = df[final_cols]

    styled_df = display_df.style.map(highlight_var, subset=['CPD Variance'])
    if 'Estimated Next Supply Date' in styled_df.columns:
        styled_df = styled_df.format({'Estimated Next Supply Date': lambda x: x.strftime('%Y-%m-%d') if pd.notnull(x) else ''})
    if 'Supply Date' in styled_df.columns:
        styled_df = styled_df.format({'Supply Date': lambda x: x.strftime('%Y-%m-%d') if pd.notnull(x) else ''})

    st.dataframe(styled_df, use_container_width=True, hide_index=True)

    csv = display_df.to_csv(index=False).encode('utf-8')
    st.download_button(label="📥 Download Processed Data", data=csv, file_name="processed_supply_data.csv", mime="text/csv")

else:
    if input_method == "Upload Excel File":
        st.info("👆 Please upload an Excel or CSV file to begin.")
    else:
        st.info("👆 Please add records using the form above.")
