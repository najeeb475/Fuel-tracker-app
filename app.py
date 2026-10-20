import streamlit as st
import pandas as pd
from datetime import timedelta, date
import io
import plotly.express as px
import firebase_admin
from firebase_admin import credentials, firestore

# --- 1. SECURITY & LOGIN ---
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.role = None

if not st.session_state.logged_in:
    st.title("🔒 Access Portal")
    st.write("Please select your access level to continue.")
    
    tab1, tab2 = st.tabs(["👥 Team Access (Data Entry & View)", "🔑 Admin Login"])

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

if st.session_state.role == 'Admin':
    st.sidebar.success("🔑 Logged in as Admin")
else:
    st.sidebar.info("👥 Logged in as Team Member")

if st.sidebar.button("Logout"):
    st.session_state.logged_in = False
    st.session_state.role = None
    st.rerun()

# --- 3. CONNECT TO FIREBASE DATABASE ---
@st.cache_resource
def init_firebase():
    try:
        cred = credentials.Certificate(st.secrets["firebase_config"])
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
            qty_before_t1 = st.number_input("Qty before supply Tank 1", min_value=0.0, format="%.2f")
            qty_supplied_t1 = st.number_input("QTY supplied Tank 1", min_value=0.0, format="%.2f")
            qty_before_t2 = st.number_input("Qty before supply Tank 2", min_value=0.0, format="%.2f")
            qty_supplied_t2 = st.number_input("QTY supplied Tank 2", min_value=0.0, format="%.2f")
        with col2:
            approved_cpd = st.number_input("Approved CPD", min_value=0.0, format="%.2f")
            supply_date = st.date_input("Supply Date")
            bobtail = st.text_input("Bobtail number")
            
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
                    'Qty before supply Tank 1': float(qty_before_t1), 
                    'QTY supplied Tank 1': float(qty_supplied_t1),
                    'Qty before supply Tank 2': float(qty_before_t2), 
                    'QTY supplied Tank 2': float(qty_supplied_t2),
                    'Approved CPD': float(approved_cpd), 
                    'Supply Date': supply_date.strftime("%Y-%m-%d"), 
                    'Bobtail number': str(bobtail)
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

        temp_df.rename(columns=rename_map, inplace=True)
        
        required_cols = ['Site ID', 'Region', 'Cluster', 'Qty before supply Tank 1', 'QTY supplied Tank 1', 'Qty before supply Tank 2', 'QTY supplied Tank 2', 'Approved CPD', 'Supply Date', 'Bobtail number']
        for col in required_cols:
            if col not in temp_df.columns: 
                temp_df[col] = 0.0 if 'Qty' in col or 'CPD' in col else ''

        count = 0
        for index, row in temp_df.iterrows():
            date_val = row['Supply Date']
            if hasattr(date_val, 'strftime'): 
                date_val = date_val.strftime("%Y-%m-%d")
            else: 
                date_val = str(date_val)
            
            record = {
                'Site ID': str(row['Site ID']), 
                'Region': str(row['Region']), 
                'Cluster': str(row['Cluster']),
                'Qty before supply Tank 1': float(row['Qty before supply Tank 1']), 
                'QTY supplied Tank 1': float(row['QTY supplied Tank 1']),
                'Qty before supply Tank 2': float(row['Qty before supply Tank 2']), 
                'QTY supplied Tank 2': float(row['QTY supplied Tank 2']),
                'Approved CPD': float(row['Approved CPD']), 
                'Supply Date': date_val, 
                'Bobtail number': str(row['Bobtail number'])
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
            if pct <= 0.
