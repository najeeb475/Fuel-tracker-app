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
        
        # --- 1. CLEAN COLUMN NAMES ---
        df.columns = [str(c).strip() for c in df.columns]
        df = df.loc[:, ~df.columns.duplicated()] # Remove accidental duplicate columns

        # --- 2. BULLETPROOF COLUMN FINDER (Case-Insensitive) ---
        def find_col(keywords):
            for col in df.columns:
                c = str(col).lower()
                if all(k in c for k in keywords):
                    return col
            return None

        # Search for columns
        c_t1_b = find_col(['before', 'tank', '1'])
        c_t1_s = find_col(['suppl', 'tank', '1']) 
        c_t2_b = find_col(['before', 'tank', '2'])
        c_t2_s = find_col(['suppl', 'tank', '2'])
        c_cpd  = find_col(['approved', 'cpd'])
        c_date = find_col(['supply', 'date'])
        c_site = find_col(['site']) 
        c_region = find_col(['region'])
        c_cluster = find_col(['cluster'])
        c_bobtail = find_col(['bobtail'])

        # Map to standard names
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
        
        # --- MAGIC FIX: Remove duplicates AGAIN after renaming ---
        # This prevents the TypeError if Excel had hidden duplicate headers
        df = df.loc[:, ~df.columns.duplicated()]

        # --- 3. HANDLE BLANKS FOR 1-TANK SITES ---
        tank_cols = ['Qty before supply Tank 1', 'QTY supplied Tank 1', 'Qty before supply Tank 2', 'QTY supplied Tank 2']
        for col in tank_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0)
            else:
                df[col] = 0.0 # Create column as 0 if it doesn't exist at all

        # Ensure Approved CPD is numeric
        if 'Approved CPD' in df.columns:
            df['Approved CPD'] = pd.to_numeric(df['Approved CPD'], errors='coerce').fillna(0.0)

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
                    'Approved CPD': approved_cpd, 'Supply
