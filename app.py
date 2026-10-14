import streamlit as st
import pandas as pd
from datetime import timedelta

# --- PAGE CONFIG ---
st.set_page_config(page_title="Supply & CPD Tracker", layout="wide")
st.title("📊 Supply & CPD Tracker App")

# --- SESSION STATE (To hold manual entries) ---
if 'manual_data' not in st.session_state:
    st.session_state.manual_data = []

# --- 1. INPUT METHOD SELECTION ---
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
        
        # Clean column names (remove accidental spaces)
        df.columns = df.columns.str.strip()

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
                    'Approved CPD': approved_cpd, 'Supply Date': supply_date, 'Bobtail number': bobtail
                }
                st.session_state.manual_data.append(new_record)
                st.success("Record added! Add more below or switch to 'Upload Excel' to view results.")

    # Show current manual entries
    if st.session_state.manual_data:
        st.write("**Current Manual Entries:**")
        temp_df = pd.DataFrame(st.session_state.manual_data)
        st.dataframe(temp_df, use_container_width=True)
        if st.button("🗑️ Clear All Manual Entries"):
            st.session_state.manual_data = []
            st.rerun()
        
        df = temp_df

# --- 3. THE ACTION ENGINE (Processing the Data) ---
if not df.empty:
    st.divider()
    st.subheader("📈 Processed Data & Analysis")
    
    # Ensure numeric columns are actually numbers (handles Excel text-formatted numbers)
    numeric_cols = ['Qty before supply Tank 1', 'QTY supplied Tank 1', 'Qty before supply Tank 2', 
                    'QTY supplied Tank 2', 'Approved CPD']
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

    # ACTION A: Calculate Total QTY Supplied
    df['Total QTY Supplied'] = df['QTY supplied Tank 1'] + df['QTY supplied Tank 2']

    # ACTION B: Estimate CPD 
    # >>> EDIT THIS FORMULA TO MATCH YOUR ACTUAL BUSINESS LOGIC <<<
    # Example: Estimated CPD = Total QTY * 0.05 
    df['Estimated CPD'] = df['Total QTY Supplied'] * 0.05 

    # ACTION C: Compare Approved vs Estimated & Calculate Variance
    df['CPD Variance'] = df['Approved CPD'] - df['Estimated CPD']
    
    # Create a visual status column for easy reading
    def get_variance_status(variance, approved):
        if approved == 0: return "⚪ N/A"
        pct_diff = abs(variance) / approved
        if pct_diff <= 0.05: return "🟢 On Target (<=5%)"
        elif pct_diff <= 0.15: return "🟡 Slight Variance"
        else: return "🔴 High Variance"

    df['Variance Status'] = df.apply(lambda row: get_variance_status(row['CPD Variance'], row['Approved CPD']), axis=1)

    # ACTION D: Estimate Data for Next Supply
    # >>> EDIT THIS FORMULA TO MATCH YOUR ACTUAL BUSINESS LOGIC <<<
    # Example: Next supply is exactly 7 days after the current supply date
    if 'Supply Date' in df.columns:
        df['Supply Date'] = pd.to_datetime(df['Supply Date'])
        df['Estimated Next Supply Date'] = df['Supply Date'] + timedelta(days=7)

    # --- 4. DISPLAY WITH HIGHLIGHTING ---
    # Highlight the Variance column (Green if positive/under budget, Red if negative/over budget)
    def highlight_variance(val):
        if val > 0:
            return 'background-color: #d4edda' # Light Green
        elif val < 0:
            return 'background-color: #f8d7da' # Light Red
        else:
            return ''

    # Apply styling
    styled_df = df.style.map(highlight_variance, subset=['CPD Variance'])
    
    # Format dates for cleaner display
    if 'Estimated Next Supply Date' in styled_df.columns:
        styled_df = styled_df.format({'Estimated Next Supply Date': lambda x: x.strftime('%Y-%m-%d') if pd.notnull(x) else ''})

    st.dataframe(styled_df, use_container_width=True, hide_index=True)

    # Download button for the processed data
    csv = df.to_csv(index=False).encode('utf-8')
    st.download_button(
        label="📥 Download Processed Data as CSV",
        data=csv,
        file_name="processed_supply_data.csv",
        mime="text/csv"
    )

else:
    if input_method == "Upload Excel File":
        st.info("👆 Please upload an Excel or CSV file to begin.")
    else:
        st.info("👆 Please add records using the form above to see the analysis.")
