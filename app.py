import io

import re

from datetime import date, datetime, timedelta, timezone


import firebase_admin

import numpy as np

import pandas as pd

import plotly.express as px

import streamlit as st

from firebase_admin import credentials, firestore

from streamlit_cookies_controller import CookieController


# ---------- 0. PAGE CONFIG (must be the first Streamlit call) ----------

st.set_page_config(page_title="Supply & CPD Tracker", layout="wide")


# ASCII keys are compared in code and emoji only ever appear in a display map, so

# copy/paste or an editor that mangles emoji cannot break a branch again.

NEW_SITE_OPTION = "__new_site__"

ADD_WAYBILL_OPTION = "add"

VIEW_WAYBILL_OPTION = "view"

WAYBILL_LABELS = {ADD_WAYBILL_OPTION: "➕ Add New Waybill", VIEW_WAYBILL_OPTION: "📋 View Recent Waybills"}


COHORT_LABELS = {

    "recent": "🟢 Supplied recently",

    "due_soon": "🟡 Due soon",

    "overdue": "🔴 Overdue",

    "steady": "🟠 Supplied in the past – steady",

    "no_data": "⚪ No consumption data",

}

COHORT_COLORS = {

    "recent": "#28a745", "due_soon": "#ffc107", "overdue": "#dc3545",

    "steady": "#fd7e14", "no_data": "#6c757d",

}


COOKIE_TTL_SECONDS = 30 * 24 * 60 * 60

SUPPLY_NUM_COLS = [

    "Qty before supply Tank 1",

    "QTY supplied Tank 1",

    "Qty before supply Tank 2",

    "QTY supplied Tank 2",

    "Approved CPD",

]

WB_NUM_COLS = [

    "Initial QTY (L)", "Loaded QTY (L)", "Loaded QTY (Kg)",

    "Supplied QTY (L)", "Remaining QTY (L)", "Mapped Sites", "Supplied Sites",

]



# ---------- HELPERS ----------

def clean_numeric(val):

    if pd.isnull(val):

        return 0.0

    stripped = re.sub(r"[A-Za-z,\s]", "", str(val))

    match = re.search(r"-?\d+(?:\.\d+)?", stripped)

    return float(match.group()) if match else 0.0



def safe_float(val, default=0.0):

    try:

        num = float(val)

    except (TypeError, ValueError):

        return default

    return num if np.isfinite(num) else default



def secret(key, default=None):

    try:

        return st.secrets[key]

    except Exception:

        return default



BLANK_SITE_VALUES = {"", "nan", "none", "null", "nat", "<na>"}



def is_blank_site(val):

    return str(val).strip().lower() in BLANK_SITE_VALUES



def unwrap_value(val):

    """Firestore returns Timestamp objects; pandas cannot parse them and

    errors='coerce' silently turns every date into NaT."""

    if hasattr(val, "to_datetime"):

        try:

            return val.to_datetime().replace(tzinfo=None)

        except Exception:

            return None

    if isinstance(val, datetime):

        return val.replace(tzinfo=None)

    return val



def to_date_column(series):

    out = pd.to_datetime(series, errors="coerce")

    if getattr(out.dt, "tz", None) is not None:

        out = out.dt.tz_localize(None)

    return out



def get_col(df, name, fill=np.nan):

    if name in df.columns:

        return df[name]

    return pd.Series(fill, index=df.index, dtype="float64")



def num_col(df, name):

    return pd.to_numeric(get_col(df, name), errors="coerce").fillna(0.0)



def apply_eq(mask, df, column, value):

    if column in df.columns and value != "All":

        return mask & (df[column] == value)

    return mask



def in_window(df, column, start, end):

    if column not in df.columns:

        return pd.Series(True, index=df.index)

    ts_start = pd.Timestamp(start)

    ts_end = pd.Timestamp(end) + pd.Timedelta(days=1)

    return (df[column] >= ts_start) & (df[column] < ts_end)



# ---------- 1. SECURITY & LOGIN ----------

controller = CookieController()



def cookie_set(key, value):

    # streamlit_cookies_controller expects a datetime and calls

    # expires.isoformat(), so an integer TTL raises AttributeError.

    try:

        expires = datetime.now(timezone.utc) + timedelta(seconds=COOKIE_TTL_SECONDS)

        controller.set(key, value, expires=expires)

    except Exception:

        # The cookie only saves the login across page reloads; the current

        # session already holds the login in st.session_state.

        pass



def cookie_delete(key):

    for name in ("delete", "remove", "expire"):

        fn = getattr(controller, name, None)

        if callable(fn):

            try:

                fn(key)

                return

            except Exception:

                continue



if controller.get("logged_in") == "true":

    st.session_state.logged_in = True

    st.session_state.role = controller.get("role") or "Team"


if "logged_in" not in st.session_state or not st.session_state.logged_in:

    st.title("🔒 Access Portal")

    tab1, tab2 = st.tabs(["👥 Team Access", "🔑 Admin Login"])

    with tab1:

        st.write("Load data, add waybills, and view basic supply metrics. (No password required)")

        if st.button("Enter as Team"):

            st.session_state.logged_in = True

            st.session_state.role = "Team"

            cookie_set("logged_in", "true")

            cookie_set("role", "Team")

            st.rerun()

    with tab2:

        st.write("Full access to analytics, editing, and database management.")

        password = st.text_input("Enter Admin Password", type="password")

        admin_password = str(secret("admin_password", "admin123"))

        if st.button("Login as Admin"):

            if password == admin_password:

                st.session_state.logged_in = True

                st.session_state.role = "Admin"

                cookie_set("logged_in", "true")

                cookie_set("role", "Admin")

                st.rerun()

            else:

                st.error("Incorrect password.")

    st.stop()


st.title("📊 Supply & CPD Tracker App")


if st.session_state.role == "Admin":

    st.sidebar.success("🔑 Logged in as Admin")

else:

    st.sidebar.info("👥 Logged in as Team Member")


if st.sidebar.button("Logout"):

    st.session_state.logged_in = False

    st.session_state.role = None

    cookie_delete("logged_in")

    cookie_delete("role")

    st.rerun()



# ---------- 2. FIREBASE CONNECTION ----------

@st.cache_resource

def init_firebase():

    try:

        config = dict(secret("firebase_config"))

        cred = credentials.Certificate(config)

        if not firebase_admin._apps:

            # Firestore does not use databaseURL (that is Realtime Database only).

            firebase_admin.initialize_app(cred)

        return firestore.client()

    except Exception as e:

        st.error(f"Database connection failed: {e}")

        return None



db = init_firebase()



def collection_df(collection_name):

    rows = []

    for doc in db.collection(collection_name).stream():

        row = {k: unwrap_value(v) for k, v in (doc.to_dict() or {}).items()}

        row["doc_id"] = doc.id

        rows.append(row)

    return pd.DataFrame(rows)



# ---------- 3. LOAD DATA (SUPPLIES & WAYBILLS) ----------

df_raw = pd.DataFrame()

df_math = pd.DataFrame()

df_waybills = pd.DataFrame()

dropped_supply_rows = 0



def prepare_supplies(df):

    global dropped_supply_rows

    if df.empty:

        return df, pd.DataFrame()


    df = df.copy()

    if "Site ID" not in df.columns and "Site" in df.columns:

        df = df.rename(columns={"Site": "Site ID"})

    if "Supply Date" not in df.columns and "Date" in df.columns:

        df = df.rename(columns={"Date": "Supply Date"})


    if "Site ID" in df.columns:

        df["Site ID"] = df["Site ID"].astype(str).str.strip()

    if "Supply Date" in df.columns:

        df["Supply Date"] = to_date_column(df["Supply Date"])

    for col in SUPPLY_NUM_COLS:

        if col in df.columns:

            df[col] = df[col].apply(clean_numeric).fillna(0.0)

    if "Zones" in df.columns:

        df["Zones"] = df["Zones"].astype(str).str.strip().str.upper()


    if "Site ID" not in df.columns or "Supply Date" not in df.columns:

        return df, pd.DataFrame()


    usable = ~df["Site ID"].apply(is_blank_site) & df["Supply Date"].notna()

    dropped_supply_rows = int((~usable).sum())

    df = df[usable].copy()

    if df.empty:

        return df, pd.DataFrame()


    agg_candidates = {

        "QTY supplied Tank 1": "sum", "QTY supplied Tank 2": "sum",

        "Qty before supply Tank 1": "sum", "Qty before supply Tank 2": "sum",

        "Approved CPD": "mean", "Region": "first", "Cluster": "first",

        "Zones": "first", "Bobtail number": "last", "Type of supply": "last",

        "doc_id": "first",

    }

    agg_dict = {k: v for k, v in agg_candidates.items() if k in df.columns}

    df_math = df.groupby(["Site ID", "Supply Date"], as_index=False).agg(agg_dict)

    return df, df_math



def check_truck_variance(row):

    prev = row["Prev Remaining QTY (L)"]

    if pd.isnull(prev):

        return "First Trip"

    if prev == 0:

        return "N/A"

    pct = abs(row["Initial QTY (L)"] - prev) / abs(prev) * 100

    return f"🚨 {pct:.1f}% Variance" if pct > 3.0 else "✅ OK"



def prepare_waybills(df):

    if df.empty:

        return df


    df = df.copy()

    if "Trip Start Date" not in df.columns and "Waybill Date" in df.columns:

        df["Trip Start Date"] = df["Waybill Date"]


    for col in ("Trip Start Date", "Trip End Date"):

        if col in df.columns:

            df[col] = to_date_column(df[col])


    for col in WB_NUM_COLS:

        if col in df.columns:

            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)


    if "Mapped Sites" in df.columns and "Supplied Sites" in df.columns:

        df["Site Variance"] = df["Mapped Sites"] - df["Supplied Sites"]


    sort_cols = [c for c in ("Truck Number", "Trip Start Date") if c in df.columns]

    if sort_cols:

        df = df.sort_values(sort_cols)


    if {"Loaded QTY (L)", "Supplied QTY (L)", "Initial QTY (L)"} <= set(df.columns):

        df["Delivery Difference (L)"] = (

            df["Loaded QTY (L)"] + df["Initial QTY (L)"] - df["Supplied QTY (L)"]

        )


    if "Truck Number" in df.columns and "Remaining QTY (L)" in df.columns:

        df["Prev Remaining QTY (L)"] = df.groupby("Truck Number")["Remaining QTY (L)"].shift(1)

    if "Initial QTY (L)" in df.columns and "Prev Remaining QTY (L)" in df.columns:

        df["Truck Variance Status"] = df.apply(check_truck_variance, axis=1)


    if "Trip Start Date" in df.columns:

        df = df.sort_values("Trip Start Date", ascending=False)

    return df



if db:

    try:

        df_raw, df_math = prepare_supplies(collection_df("supplies"))

    except Exception as e:

        st.warning(f"Supplies load issue: {e}")

    try:

        df_waybills = prepare_waybills(collection_df("waybills"))

    except Exception as e:

        st.warning(f"Waybills load issue: {e}")

    st.sidebar.info(f"📊 Loaded {len(df_raw)} supply records & {len(df_waybills)} waybills.")

    if dropped_supply_rows:

        st.sidebar.warning(

            f"⚠️ {dropped_supply_rows} supply rows skipped (missing/invalid Site ID or Supply Date)."

        )


# ---------- 4. DATA INPUT (Role-Based) ----------

st.sidebar.header("📥 Data Input")


if st.session_state.role == "Admin":

    input_options = ("Manual Entry", "Edit Single Record", "Bulk Edit (Spreadsheet)", "Upload Excel File")

else:

    input_options = ("Manual Entry", "Upload Excel File")


input_method = st.sidebar.radio("How would you like to input data?", input_options, horizontal=True)


if input_method == "Manual Entry":

    st.sidebar.subheader("Enter Supply Details")

    with st.sidebar.form("manual_entry_form"):

        if not df_raw.empty and "Site ID" in df_raw.columns:

            existing_sites = sorted({s for s in df_raw["Site ID"].astype(str) if not is_blank_site(s)})

            site_choice = st.selectbox(

                "Select Site", [NEW_SITE_OPTION] + existing_sites,

                format_func=lambda v: "➕ New Site" if v == NEW_SITE_OPTION else v,

            )

            if site_choice == NEW_SITE_OPTION:

                site_id = st.text_input("New Site ID")

                region = st.text_input("Region")

                cluster = st.text_input("Cluster")

                zone = st.selectbox("Zones", ["A1", "A2", "A3"])

            else:

                site_id = site_choice

                site_df = df_raw[df_raw["Site ID"] == str(site_id)]

                if not site_df.empty:

                    last_record = site_df.sort_values("Supply Date").iloc[-1]

                    region = str(last_record.get("Region", "") or "")

                    cluster = str(last_record.get("Cluster", "") or "")

                    zone = str(last_record.get("Zones", "A1") or "A1")

                    st.success(f"Existing site: {site_id}")

                else:

                    region, cluster, zone = "", "", "A1"

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

            if st.session_state.role == "Admin":

                approved_cpd = st.number_input("Approved CPD", min_value=0.0, format="%.2f")

            else:

                approved_cpd = 0.0

            supply_date = st.date_input("Supply Date")

            bobtail = st.text_input("Bobtail number")

            supply_type = st.text_input("Type of supply", value="Oct 1st supply")


        submitted = st.form_submit_button("💾 Save to Database")

        if submitted:

            if not site_id:

                st.error("Please enter a Site ID.")

            elif not db:

                st.error("Database not connected.")

            else:

                record = {

                    "Site ID": str(site_id).strip(),

                    "Region": str(region), "Cluster": str(cluster),

                    "Zones": str(zone).strip().upper(),

                    "Qty before supply Tank 1": float(qty_before_t1),

                    "QTY supplied Tank 1": float(qty_supplied_t1),

                    "Qty before supply Tank 2": float(qty_before_t2),

                    "QTY supplied Tank 2": float(qty_supplied_t2),

                    "Approved CPD": float(approved_cpd),

                    "Supply Date": supply_date.strftime("%Y-%m-%d"),

                    "Bobtail number": str(bobtail),

                    "Type of supply": str(supply_type).strip(),

                }

                db.collection("supplies").add(record)

                st.success("✅ Saved successfully!")

                st.rerun()


elif input_method == "Edit Single Record":

    st.sidebar.subheader("✏️ Edit / Update Single Record")

    if not df_raw.empty and {"Site ID", "Supply Date", "doc_id"} <= set(df_raw.columns):

        edit_site = st.sidebar.selectbox("1. Select Site ID", sorted(df_raw["Site ID"].unique().tolist()))

        site_dates = df_raw.loc[df_raw["Site ID"] == edit_site, "Supply Date"].dropna().sort_values(ascending=False)

        date_options = [d.date() for d in site_dates]

        edit_date = st.sidebar.selectbox("2. Select Date to Edit", date_options) if date_options else None

        row_data_df = df_raw[

            (df_raw["Site ID"] == str(edit_site)) & (df_raw["Supply Date"].dt.date == edit_date)

        ] if edit_date else pd.DataFrame()

        if not row_data_df.empty:

            row_data = row_data_df.iloc[0]

            doc_id = row_data["doc_id"]

            st.sidebar.info(f"Editing record ID: {str(doc_id)[:8]}...")

            with st.sidebar.form("edit_form"):

                st.markdown("**Update Values:**")

                new_cpd = st.number_input("Approved CPD", value=safe_float(row_data.get("Approved CPD")), format="%.2f")

                new_q_b_t1 = st.number_input("Qty before supply Tank 1", value=safe_float(row_data.get("Qty before supply Tank 1")), format="%.2f")

                new_q_s_t1 = st.number_input("QTY supplied Tank 1", value=safe_float(row_data.get("QTY supplied Tank 1")), format="%.2f")

                new_q_b_t2 = st.number_input("Qty before supply Tank 2", value=safe_float(row_data.get("Qty before supply Tank 2")), format="%.2f")

                new_q_s_t2 = st.number_input("QTY supplied Tank 2", value=safe_float(row_data.get("QTY supplied Tank 2")), format="%.2f")

                new_bobtail = st.text_input("Bobtail number", value=str(row_data.get("Bobtail number", "") or ""))

                new_type = st.text_input("Type of supply", value=str(row_data.get("Type of supply", "") or ""))

                col_btn1, col_btn2 = st.columns(2)

                with col_btn1:

                    save_changes = st.form_submit_button("✅ Save", type="primary")

                with col_btn2:

                    delete_record = st.form_submit_button("🗑️ Delete", type="secondary")

            if not db:

                st.sidebar.error("Database not connected.")

            elif save_changes:

                db.collection("supplies").document(doc_id).update({

                    "Approved CPD": float(new_cpd),

                    "Qty before supply Tank 1": float(new_q_b_t1),

                    "QTY supplied Tank 1": float(new_q_s_t1),

                    "Qty before supply Tank 2": float(new_q_b_t2),

                    "QTY supplied Tank 2": float(new_q_s_t2),

                    "Bobtail number": str(new_bobtail),

                    "Type of supply": str(new_type),

                })

                st.sidebar.success("✅ Record updated!")

                st.rerun()

            elif delete_record:

                db.collection("supplies").document(doc_id).delete()

                st.sidebar.success("🗑️ Record deleted!")

                st.rerun()

        else:

            st.sidebar.warning("Could not find this specific record.")

    else:

        st.sidebar.warning("No data available to edit.")


elif input_method == "Bulk Edit (Spreadsheet)":

    st.sidebar.subheader("✏️ Bulk Update Records")

    if not df_raw.empty and "Supply Date" in df_raw.columns:

        unique_dates = sorted({d.date() for d in df_raw["Supply Date"].dropna()}, reverse=True)

        selected_bulk_date = st.sidebar.date_input("Select Date to Edit", value=unique_dates[0] if unique_dates else date.today())

        bulk_df = df_raw[df_raw["Supply Date"].dt.date == selected_bulk_date].copy()

        if not bulk_df.empty:

            st.sidebar.success(f"Found {len(bulk_df)} records for {selected_bulk_date}")

            editable_cols = ["Approved CPD", "Qty before supply Tank 1", "QTY supplied Tank 1",

                             "Qty before supply Tank 2", "QTY supplied Tank 2", "Bobtail number", "Type of supply"]

            editable_cols = [c for c in editable_cols if c in bulk_df.columns]

            numeric_edit = [c for c in editable_cols if c in SUPPLY_NUM_COLS]

            cols_to_show = [c for c in ["Site ID", "Region", "Zones", "doc_id"] + editable_cols if c in bulk_df.columns]

            st.subheader(f"Edit Records for {selected_bulk_date}")

            st.write("Click on any cell below to change the value. When finished, click 'Save All Changes'.")

            edited_df = st.data_editor(

                bulk_df[cols_to_show].drop(columns=["doc_id"], errors="ignore"),

                num_rows="fixed", use_container_width=True, key="bulk_editor",

            )

            if st.button("💾 Save All Changes to Database", type="primary"):

                if not db:

                    st.error("Database not connected.")

                else:

                    batch = db.batch()

                    count = 0

                    for idx in edited_df.index:

                        doc_id = bulk_df.loc[idx, "doc_id"]

                        update_data = {}

                        for col in editable_cols:

                            val = edited_df.loc[idx, col]

                            if col in numeric_edit:

                                update_data[col] = clean_numeric(val)

                            else:

                                update_data[col] = "" if pd.isnull(val) else str(val)

                        batch.update(db.collection("supplies").document(doc_id), update_data)

                        count += 1

                        if count % 400 == 0:

                            batch.commit()

                            batch = db.batch()

                    batch.commit()

                    st.success(f"✅ Successfully updated {count} records in the database!")

                    st.rerun()

        else:

            st.warning("No records found for this date.")

    else:

        st.warning("Database is empty.")


elif input_method == "Upload Excel File":

    st.sidebar.subheader("Upload Excel to Database")

    uploaded_file = st.sidebar.file_uploader("Choose your Excel or CSV file", type=["xlsx", "csv"])

    if uploaded_file is not None:

        st.session_state["file_to_upload"] = uploaded_file

        st.sidebar.success(f"✅ File '{uploaded_file.name}' is ready.")

    if "file_to_upload" in st.session_state:

        if st.sidebar.button("🚀 CLICK HERE TO UPLOAD DATA TO DASHBOARD", type="primary"):

            file_to_process = st.session_state["file_to_upload"]

            if not db:

                st.sidebar.error("❌ Database not connected.")

            else:

                try:

                    file_to_process.seek(0)  # the buffer is consumed on the previous read

                    if file_to_process.name.lower().endswith(".csv"):

                        temp_df = pd.read_csv(file_to_process)

                    else:

                        temp_df = pd.read_excel(file_to_process)

                    if temp_df.empty:

                        st.sidebar.error("❌ The file appears to be empty.")

                        st.stop()


                    temp_df.columns = [str(c).strip() for c in temp_df.columns]


                    def find_col(keywords, exclude=()):

                        for col in temp_df.columns:

                            c = str(col).lower()

                            if any(x in c for x in exclude):

                                continue

                            if all(k in c for k in keywords):

                                return col

                        return None


                    rename_map = {}

                    pairs = [

                        (["before", "tank", "1"], (), "Qty before supply Tank 1"),

                        (["suppl", "tank", "1"], ("before",), "QTY supplied Tank 1"),

                        (["before", "tank", "2"], (), "Qty before supply Tank 2"),

                        (["suppl", "tank", "2"], ("before",), "QTY supplied Tank 2"),

                        (["approved", "cpd"], (), "Approved CPD"),

                        (["cpd"], (), "Approved CPD"),

                        (["supply", "date"], (), "Supply Date"),

                        (["date"], ("start", "end"), "Supply Date"),

                        (["site", "id"], (), "Site ID"),

                        (["site"], ("website", "variance", "mapped", "sites"), "Site ID"),

                        (["region"], (), "Region"),

                        (["cluster"], (), "Cluster"),

                        (["bobtail"], (), "Bobtail number"),

                        (["zone"], (), "Zones"),

                        (["type", "supply"], (), "Type of supply"),

                    ]

                    for keywords, exclude, target in pairs:

                        if target in rename_map.values():

                            continue

                        found = find_col(keywords, exclude)

                        if found:

                            rename_map[found] = target

                    temp_df.rename(columns=rename_map, inplace=True)


                    for col in ["Site ID", "Region", "Cluster", "Bobtail number"]:

                        if col not in temp_df.columns:

                            temp_df[col] = ""

                    for col in SUPPLY_NUM_COLS:

                        if col not in temp_df.columns:

                            temp_df[col] = 0.0

                    if "Zones" not in temp_df.columns:

                        temp_df["Zones"] = "A1"

                    if "Type of supply" not in temp_df.columns:

                        temp_df["Type of supply"] = "1st supply"


                    temp_df["Site ID"] = temp_df["Site ID"].astype(str).str.strip()

                    if "Supply Date" not in temp_df.columns:

                        temp_df["Supply Date"] = pd.NaT

                    temp_df["__date__"] = to_date_column(temp_df["Supply Date"])


                    existing = {}

                    if not df_raw.empty and {"Site ID", "Supply Date", "doc_id"} <= set(df_raw.columns):

                        for _, r in df_raw.iterrows():

                            if pd.notnull(r["Supply Date"]):

                                existing[(str(r["Site ID"]), r["Supply Date"].date())] = r["doc_id"]


                    count = 0

                    skipped = 0

                    new_rows = 0

                    total_rows = len(temp_df)

                    progress_bar = st.sidebar.progress(0.0)

                    batch = db.batch()

                    pending = 0


                    for _, row in temp_df.iterrows():

                        supply_day = row["__date__"]

                        if pd.isnull(supply_day) or is_blank_site(row["Site ID"]):

                            skipped += 1

                        else:

                            record = {

                                "Site ID": str(row["Site ID"]),

                                "Region": str(row["Region"]),

                                "Cluster": str(row["Cluster"]),

                                "Zones": str(row.get("Zones", "A1")).strip().upper(),

                                "Qty before supply Tank 1": clean_numeric(row["Qty before supply Tank 1"]),

                                "QTY supplied Tank 1": clean_numeric(row["QTY supplied Tank 1"]),

                                "Qty before supply Tank 2": clean_numeric(row["Qty before supply Tank 2"]),

                                "QTY supplied Tank 2": clean_numeric(row["QTY supplied Tank 2"]),

                                "Approved CPD": clean_numeric(row["Approved CPD"]),

                                "Supply Date": supply_day.strftime("%Y-%m-%d"),

                                "Bobtail number": str(row["Bobtail number"]),

                                "Type of supply": str(row.get("Type of supply", "1st supply")).strip(),

                            }

                            doc_id = existing.get((str(row["Site ID"]), supply_day.date()))

                            if doc_id:

                                batch.update(db.collection("supplies").document(doc_id), record)

                            else:

                                batch.set(db.collection("supplies").document(), record)

                                new_rows += 1

                            count += 1

                            pending += 1

                            if pending >= 400:

                                batch.commit()

                                batch = db.batch()

                                pending = 0

                        progress_bar.progress(min((count + skipped) / max(total_rows, 1), 1.0))


                    batch.commit()

                    st.sidebar.success(f"✅ Wrote {count} rows ({new_rows} new, {count - new_rows} updated).")

                    if skipped:

                        st.sidebar.warning(f"⚠️ Skipped {skipped} rows with no Site ID or an unparseable Supply Date.")

                    del st.session_state["file_to_upload"]

                    st.rerun()

                except Exception as e:

                    st.sidebar.error(f"❌ Upload failed: {e}")


# ---------- 4.5 WAYBILL MANAGEMENT ----------

st.sidebar.markdown("---")

st.sidebar.header("🚛 Waybill Management")

waybill_action = st.sidebar.radio(

    "Select Waybill Action", [ADD_WAYBILL_OPTION, VIEW_WAYBILL_OPTION],

    format_func=lambda v: WAYBILL_LABELS.get(v, v),

)


if waybill_action == ADD_WAYBILL_OPTION:

    st.sidebar.subheader("Log Truck Waybill")

    if not db:

        st.sidebar.error("Database not connected.")

    else:

        with st.sidebar.form("waybill_form"):

            waybill_no = st.text_input("Waybill Number / ID")

            truck_no = st.text_input("Truck / Bobtail Number")

            driver_name = st.text_input("Driver Name (Optional)")


            col_d1, col_d2 = st.columns(2)

            with col_d1:

                trip_start_date = st.date_input("Trip Start Date", value=date.today())

            with col_d2:

                trip_end_date = st.date_input("Trip End Date", value=date.today())


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

                    db.collection("waybills").add({

                        "Waybill Number": str(waybill_no).strip(),

                        "Truck Number": str(truck_no).strip(),

                        "Driver Name": str(driver_name).strip(),

                        "Trip Start Date": trip_start_date.strftime("%Y-%m-%d"),

                        "Trip End Date": trip_end_date.strftime("%Y-%m-%d"),

                        "Initial QTY (L)": float(initial_qty_l),

                        "Loaded QTY (L)": float(loaded_qty_l),

                        "Loaded QTY (Kg)": float(loaded_qty_kg),

                        "Supplied QTY (L)": float(supplied_qty_l),

                        "Remaining QTY (L)": float(remaining_qty_l),

                        "Mapped Sites": int(mapped_sites),

                        "Supplied Sites": int(supplied_sites),

                        "Added By": st.session_state.role,

                    })

                    st.sidebar.success("✅ Waybill saved successfully!")

                    st.rerun()


elif waybill_action == VIEW_WAYBILL_OPTION:

    st.sidebar.subheader("Recent Waybills")

    if not df_waybills.empty:

        wb_display_cols = ["Trip Start Date", "Waybill Number", "Truck Number", "Loaded QTY (L)", "Supplied Sites"]

        final_wb_cols = [c for c in wb_display_cols if c in df_waybills.columns]

        st.sidebar.dataframe(df_waybills[final_wb_cols].head(10), hide_index=True, use_container_width=True)

    else:

        st.sidebar.info("No waybills logged yet.")


# ---------- 5. ADMIN CONTROLS ----------

if st.session_state.role == "Admin":

    st.sidebar.markdown("---")

    st.sidebar.subheader("🔑 Admin Controls")

    if st.sidebar.button("🗑️ Clear Database"):

        st.session_state.confirm_clear = True

    if st.session_state.get("confirm_clear") and st.sidebar.checkbox(

        "Are you sure? This deletes everything permanently.", key="confirm_clear_box"

    ):

        if not db:

            st.sidebar.error("Database not connected.")

        else:

            total = 0

            for name in ("supplies", "waybills"):

                batch = db.batch()

                pending = 0

                for doc in db.collection(name).stream():

                    batch.delete(doc.reference)

                    total += 1

                    pending += 1

                    if pending >= 400:

                        batch.commit()

                        batch = db.batch()

                        pending = 0

                batch.commit()

            st.success(f"All databases cleared! ({total} documents deleted)")

            st.session_state.confirm_clear = False

            st.rerun()


# ---------- 6. CONSUMPTION MODEL ----------

def build_consumption_model(base_df, today, recent_days, due_soon_days):

    d = base_df.sort_values(["Site ID", "Supply Date"]).reset_index(drop=True).copy()


    supplied = num_col(d, "QTY supplied Tank 1") + num_col(d, "QTY supplied Tank 2")

    before = num_col(d, "Qty before supply Tank 1") + num_col(d, "Qty before supply Tank 2")

    d["Total QTY Supplied"] = supplied

    d["Total QTY Before Supply"] = before

    d["Total_QTY_After_Supply"] = before + supplied


    grp = d.groupby("Site ID", sort=False)

    d["Prev_Total_Before"] = grp["Total QTY Before Supply"].shift(1)

    d["Prev_Total_Supplied"] = grp["Total QTY Supplied"].shift(1)

    d["Prev_Supply_Date"] = grp["Supply Date"].shift(1)

    d["Days_Diff"] = (d["Supply Date"] - d["Prev_Supply_Date"]).dt.days


    d["Total_Consumed"] = d["Prev_Total_Before"] + d["Prev_Total_Supplied"] - d["Total QTY Before Supply"]

    d["Reading Check"] = np.where(d["Total_Consumed"] < 0, "⚠️ Negative consumption", "")


    valid = d["Days_Diff"].gt(0) & d["Total_Consumed"].notna()

    d["Estimated CPD"] = np.nan

    d.loc[valid, "Estimated CPD"] = (

        d.loc[valid, "Total_Consumed"].clip(lower=0) / d.loc[valid, "Days_Diff"]

    )


    approved = num_col(d, "Approved CPD")

    d["Approved CPD"] = approved

    d["Days_Fuel_Last"] = np.nan

    can_run = d["Estimated CPD"].gt(0)

    d.loc[can_run, "Days_Fuel_Last"] = (

        d.loc[can_run, "Total_QTY_After_Supply"] / d.loc[can_run, "Estimated CPD"]

    )


    next_dates = []

    for supply_date, days_last in zip(d["Supply Date"], d["Days_Fuel_Last"]):

        if pd.notnull(days_last) and days_last > 0 and pd.notnull(supply_date):

            next_dates.append((supply_date + timedelta(days=float(days_last))).date())

        else:

            next_dates.append(None)

    d["Estimated Next Supply Date"] = next_dates


    d["Supply Alert"] = [_supply_alert(nd, today) for nd in d["Estimated Next Supply Date"]]


    d["CPD Variance"] = approved - d["Estimated CPD"]

    status_key = d.apply(_variance_key, axis=1)

    d["_status_key"] = status_key

    labels = {"target": "🟢 On Target", "slight": "🟡 Slight Variance",

              "high": "🔴 High Variance", "na": "⚪ N/A"}

    d["Variance Status"] = status_key.map(labels)


    sites = []

    for site, g in d.groupby("Site ID", sort=False):

        g = g.sort_values("Supply Date")

        last = g.iloc[-1]

        cpd_series = g["Estimated CPD"].dropna()

        site_approved = safe_float(last.get("Approved CPD"))


        if not cpd_series.empty:

            cpd = float(cpd_series.iloc[-1])

            cpd_basis = "Last supply gap"

        elif site_approved > 0:

            cpd = site_approved

            cpd_basis = "Approved CPD (no history)"

        else:

            cpd = np.nan

            cpd_basis = "Unknown"


        avg_cpd = float(cpd_series.mean()) if not cpd_series.empty else np.nan

        gaps = g["Days_Diff"].dropna()

        avg_gap = float(gaps.mean()) if not gaps.empty else np.nan


        last_date = last["Supply Date"]

        days_since = (pd.Timestamp(today) - last_date).days if pd.notnull(last_date) else np.nan

        level_now = last["Total_QTY_After_Supply"]

        projected_level = max(level_now - cpd * days_since, 0.0) if pd.notnull(cpd) and pd.notnull(days_since) else np.nan

        days_left = projected_level / cpd if pd.notnull(cpd) and cpd > 0 and pd.notnull(projected_level) else np.nan


        next_supply = last["Estimated Next Supply Date"]

        days_to_next = (next_supply - today).days if next_supply else np.nan

        category = _classify(days_since, days_to_next, cpd, recent_days, due_soon_days)


        sites.append({

            "Site ID": site,

            "Region": last.get("Region", ""),

            "Cluster": last.get("Cluster", ""),

            "Zones": last.get("Zones", ""),

            "Type of supply": last.get("Type of supply", ""),

            "Last Supply Date": last_date,

            "Days Since Last Supply": days_since,

            "Approved CPD": site_approved,

            "CPD": cpd,

            "Avg CPD (history)": avg_cpd,

            "CPD Basis": cpd_basis,

            "Avg Days Between Supplies": avg_gap,

            "Qty After Last Supply": level_now,

            "Projected Qty Today": projected_level,

            "Projected Days Left": days_left,

            "Estimated Next Supply Date": next_supply,

            "Days Until Next": days_to_next,

            "Supply Cohort Key": category,

            "Supply Cohort": COHORT_LABELS[category],

            "Supply Alert": last["Supply Alert"],

            "Variance Status": last["Variance Status"],

            "Total QTY Supplied": last["Total QTY Supplied"],

            "Bobtail number": last.get("Bobtail number", ""),

        })


    sites_df = pd.DataFrame(sites)

    if not sites_df.empty:

        sites_df["Cohort"] = np.where(

            sites_df["Days Since Last Supply"] <= recent_days, "Supplied recently", "Supplied in the past"

        )

    return d, sites_df



def _variance_key(row):

    cpd = row["Estimated CPD"]

    app = row["Approved CPD"]

    if pd.isnull(cpd) or cpd == 0 or app == 0:

        return "na"

    pct = abs(app - cpd) / app

    return "target" if pct <= 0.05 else ("slight" if pct <= 0.15 else "high")



def _supply_alert(next_date, today):

    if next_date is None or pd.isnull(next_date):

        return ""

    days_diff = (next_date - today).days

    if days_diff < 0:

        return "🚨 OVERDUE"

    if days_diff == 0:

        return "🚨 CRITICAL: Supply Today"

    if days_diff <= 2:

        return f"🟡 WARNING: Supply in {days_diff} days"

    return ""



def _classify(days_since, days_to_next, cpd, recent_days, due_soon_days):

    if pd.isna(cpd) or cpd <= 0:

        return "no_data"

    if pd.notna(days_to_next) and days_to_next < 0:

        return "overdue"

    if pd.notna(days_since) and days_since <= recent_days:

        return "recent"

    if pd.notna(days_to_next) and days_to_next <= due_soon_days:

        return "due_soon"

    return "steady"



def fmt_date_cols(df, columns):

    out = df.copy()

    for cname in columns:

        if cname in out.columns and pd.api.types.is_datetime64_any_dtype(out[cname]):

            out[cname] = out[cname].dt.strftime("%Y-%m-%d")

    return out



def cohort_comparison(sites_df, recent_days):

    if sites_df.empty:

        return pd.DataFrame()

    rows = []

    for label, sub in sites_df.groupby("Cohort", sort=False):

        known = sub[sub["CPD"].notna() & (sub["CPD"] > 0)].copy()

        app = known["Approved CPD"].replace(0, np.nan)

        variance = ((known["CPD"] - app) / app * 100).mean() if not known.empty else np.nan

        rows.append({

            "Cohort": label,

            "Sites": len(sub),

            "Supplied within": f"≤ {recent_days} days" if label == "Supplied recently" else f"> {recent_days} days",

            "Avg CPD (L/day)": round(known["CPD"].mean(), 2) if not known.empty else np.nan,

            "Median CPD (L/day)": round(known["CPD"].median(), 2) if not known.empty else np.nan,

            "Avg Approved CPD": round(app.mean(), 2) if not known.empty else np.nan,

            "Avg Variance vs Approved %": round(variance, 1) if pd.notna(variance) else np.nan,

            "Avg Days Between Supplies": round(sub["Avg Days Between Supplies"].mean(), 1),

            "Avg Days Since Supply": round(sub["Days Since Last Supply"].mean(), 1),

            "Total Supplied (L)": round(sub["Total QTY Supplied"].sum(), 1),

        })

    return pd.DataFrame(rows)



# ---------- 7. DASHBOARD LOGIC ----------

role = st.session_state.role

is_admin = role == "Admin"


# Team members get the raw waybill columns only: no variance or difference

# columns are ever selected for their tables or exports.

TEAM_WAYBILL_COLS = [

    "Waybill Number", "Truck Number", "Driver Name", "Trip Start Date", "Trip End Date",

    "Initial QTY (L)", "Loaded QTY (L)", "Loaded QTY (Kg)", "Supplied QTY (L)",

    "Remaining QTY (L)", "Mapped Sites", "Supplied Sites",

]


if not df_math.empty:

    st.divider()


    today = pd.Timestamp.today().normalize()


    if is_admin:

        recent_window = st.sidebar.slider("Sites supplied within N days = 'recent'", 1, 60, 14,

                                          help="Cohort split used by the consumption analysis.")

        due_soon_window = st.sidebar.slider("Flag as 'Due soon' when next supply is within N days", 1, 60, 15)

        df_math, df_sites = build_consumption_model(df_math, today.date(), recent_window, due_soon_window)

    else:

        # Team sessions never build the consumption model, so no CPD, projection

        # or variance value is computed, let alone rendered.

        recent_window, due_soon_window = 14, 15

        df_sites = pd.DataFrame()


    st.sidebar.header("🔍 Filters")

    valid_dates = df_math["Supply Date"].dropna()

    if not valid_dates.empty:

        min_date = valid_dates.min().date()

        max_date = valid_dates.max().date()

        start_date = st.sidebar.date_input("Start Date", value=min_date, min_value=min_date, max_value=max_date)

        end_date = st.sidebar.date_input("End Date", value=max_date, min_value=min_date, max_value=max_date)

    else:

        start_date = st.sidebar.date_input("Start Date", value=date(2023, 1, 1))

        end_date = st.sidebar.date_input("End Date", value=date(2026, 12, 31))


    def unique_options(column):

        if column in df_math.columns:

            vals = [str(v) for v in df_math[column].dropna().unique()]

            return ["All"] + sorted(vals)

        return ["All"]


    selected_region = st.sidebar.selectbox("Region", unique_options("Region"))

    selected_cluster = st.sidebar.selectbox("Cluster", unique_options("Cluster"))

    selected_zone = st.sidebar.selectbox("Zones", unique_options("Zones"))

    selected_supply_type = st.sidebar.selectbox("Type of Supply", unique_options("Type of supply"))

    selected_site = st.sidebar.selectbox("Site ID", unique_options("Site ID"))


    filter_map = {"Region": selected_region, "Cluster": selected_cluster, "Zones": selected_zone,

                  "Type of supply": selected_supply_type, "Site ID": selected_site}


    mask_math = in_window(df_math, "Supply Date", start_date, end_date)

    for cname, value in filter_map.items():

        mask_math = apply_eq(mask_math, df_math, cname, value)

    filtered_math_df = df_math[mask_math].copy()


    if not is_admin:

        # The consumption model normally adds this column; team gets the same

        # total straight from the stored tank quantities instead.

        filtered_math_df["Total QTY Supplied"] = (

            num_col(filtered_math_df, "QTY supplied Tank 1")

            + num_col(filtered_math_df, "QTY supplied Tank 2")

        )


    mask_raw = in_window(df_raw, "Supply Date", start_date, end_date)

    for cname, value in filter_map.items():

        mask_raw = apply_eq(mask_raw, df_raw, cname, value)

    filtered_raw_df = df_raw[mask_raw].copy()


    mask_sites = pd.Series(True, index=df_sites.index)

    for cname, value in filter_map.items():

        mask_sites = apply_eq(mask_sites, df_sites, cname, value)

    filtered_sites = df_sites[mask_sites].copy()


    if filtered_math_df.empty:

        st.warning("No data found for the selected filters.")

    else:

        st.subheader("📊 Summary Dashboard")

        sites_supplied = filtered_math_df.loc[filtered_math_df["Total QTY Supplied"] > 0, "Site ID"].nunique()

        t1 = pd.to_numeric(get_col(filtered_raw_df, "QTY supplied Tank 1"), errors="coerce").fillna(0)

        t2 = pd.to_numeric(get_col(filtered_raw_df, "QTY supplied Tank 2"), errors="coerce").fillna(0)

        total_supplied = float(t1.sum() + t2.sum())

        total_waybills = len(df_waybills)


        if is_admin:

            total_sites_tracked = df_math["Site ID"].nunique()


            valid_var = filtered_math_df[

                (filtered_math_df["Estimated CPD"] > 0) & (filtered_math_df["Approved CPD"] > 0)

            ]

            high_variance_count = int(

                ((valid_var["CPD Variance"].abs() / valid_var["Approved CPD"]) > 0.15).sum()

            ) if not valid_var.empty else 0


            if "Supply Alert" in filtered_sites.columns:

                is_urgent = filtered_sites["Supply Alert"].astype(str).str.contains("OVERDUE|CRITICAL|WARNING")

                urgent_supplies = int(filtered_sites.loc[is_urgent, "Site ID"].nunique())

            else:

                urgent_supplies = 0


            col1, col2, col3, col4, col5, col6 = st.columns(6)

            col1.metric("Total Sites Tracked", total_sites_tracked)

            col2.metric("Sites Supplied (window)", sites_supplied)

            col3.metric("Total Fuel Supplied", f"{total_supplied:,.2f} L")

            col4.metric("High Variance", high_variance_count)

            col5.metric("Urgent Sites", urgent_supplies)

            col6.metric("Waybills Logged", total_waybills)

        else:

            col1, col2, col3 = st.columns(3)

            col1.metric("Sites Supplied (window)", sites_supplied)

            col2.metric("Total Fuel Supplied", f"{total_supplied:,.2f} L")

            col3.metric("Waybills Logged", total_waybills)

            st.caption(

                "Team access shows how many sites were supplied and the fuel delivered. "

                "Consumption, CPD, projection and variance analysis are Admin-only."

            )


        st.markdown("---")

        st.subheader("📍 Sites by Zone")

        if "Zones" in filtered_math_df.columns:

            z1, z2, z3 = st.columns(3)

            with z1:

                st.metric("Zone A1", filtered_math_df[filtered_math_df["Zones"] == "A1"]["Site ID"].nunique())

            with z2:

                st.metric("Zone A2", filtered_math_df[filtered_math_df["Zones"] == "A2"]["Site ID"].nunique())

            with z3:

                st.metric("Zone A3", filtered_math_df[filtered_math_df["Zones"] == "A3"]["Site ID"].nunique())


        st.markdown("---")

        st.subheader("🚛 Sites by Supply Type")

        if "Type of supply" in filtered_math_df.columns:

            supply_counts = filtered_math_df.groupby("Type of supply")["Site ID"].nunique().sort_values(ascending=False)

            if len(supply_counts) > 0:

                cols = st.columns(min(len(supply_counts), 4))

                for i, (stype, count) in enumerate(supply_counts.items()):

                    with cols[i % 4]:

                        st.metric(str(stype).title(), count)

        st.markdown("---")


        if is_admin:

            chart_col1, chart_col2 = st.columns(2)

            with chart_col1:

                st.subheader("Total QTY Supplied by Region")

                if "Region" in filtered_math_df.columns:

                    st.bar_chart(filtered_math_df.groupby("Region")["Total QTY Supplied"].sum(),

                                 use_container_width=True)

            with chart_col2:

                st.subheader("Variance Status Distribution")

                status_counts = filtered_math_df["_status_key"].value_counts().rename_axis("_status_key").reset_index(name="Count")

                labels = {"target": "🟢 On Target", "slight": "🟡 Slight Variance",

                          "high": "🔴 High Variance", "na": "⚪ N/A"}

                color_map = {"🟢 On Target": "#28a745", "🟡 Slight Variance": "#ffc107",

                             "🔴 High Variance": "#dc3545", "⚪ N/A": "#6c757d"}

                status_counts["Status"] = status_counts["_status_key"].map(labels)

                fig = px.bar(status_counts, x="Status", y="Count", color="Status",

                             color_discrete_map=color_map, text="Count")

                fig.update_layout(showlegend=False, yaxis_title="Count", xaxis_title="")

                st.plotly_chart(fig, use_container_width=True)

        else:

            st.subheader("Total QTY Supplied by Region")

            if "Region" in filtered_math_df.columns:

                st.bar_chart(filtered_math_df.groupby("Region")["Total QTY Supplied"].sum(),

                             use_container_width=True)


        # ---------- 7.5 CONSUMPTION ANALYSIS: RECENT vs PAST SUPPLY ----------

        # Admin only: this whole block is built from the consumption model that

        # team sessions never compute.

        if is_admin:

            st.markdown("---")

            st.subheader("🔥 Consumption Analysis — Sites supplied recently vs in the past")

            st.caption(

                f"'Recently' = last supply within {recent_window} days of {today.date()}. "

                "CPD is derived from the gap between consecutive supplies: "

                "(before_prev + supplied_prev − before_current) ÷ days between supplies."

            )


            if filtered_sites.empty:

                st.info("No site-level consumption data for the current filters.")

            else:

                cohort_tbl = cohort_comparison(filtered_sites, recent_window)

                st.dataframe(cohort_tbl, use_container_width=True, hide_index=True)


                c1, c2, c3, c4 = st.columns(4)

                recent_grp = filtered_sites[filtered_sites["Cohort"] == "Supplied recently"]

                past_grp = filtered_sites[filtered_sites["Cohort"] != "Supplied recently"]

                c1.metric("Sites supplied recently", len(recent_grp))

                c2.metric("Sites last supplied earlier", len(past_grp))

                c3.metric("Overdue sites", int((filtered_sites["Supply Cohort Key"] == "overdue").sum()))

                c4.metric("Sites with no CPD data", int((filtered_sites["Supply Cohort Key"] == "no_data").sum()))


                layout_col1, layout_col2 = st.columns(2)

                with layout_col1:

                    st.markdown("**Sites by supply status**")

                    label_colors = {COHORT_LABELS[k]: c for k, c in COHORT_COLORS.items()}

                    cohort_counts = (filtered_sites.groupby("Supply Cohort Key", observed=True)

                                     .size().rename("Sites").reset_index())

                    order = [k for k in ("recent", "due_soon", "overdue", "steady", "no_data")

                             if k in set(cohort_counts["Supply Cohort Key"])]

                    cohort_counts["Supply Cohort Key"] = pd.Categorical(

                        cohort_counts["Supply Cohort Key"], categories=order, ordered=True)

                    cohort_counts = cohort_counts.sort_values("Supply Cohort Key").reset_index(drop=True)

                    cohort_counts["Supply Cohort"] = cohort_counts["Supply Cohort Key"].map(COHORT_LABELS)

                    fig_cohort = px.bar(cohort_counts, x="Supply Cohort", y="Sites",

                                        color="Supply Cohort", color_discrete_map=label_colors, text="Sites")

                    fig_cohort.update_layout(showlegend=False, xaxis_title="", yaxis_title="Sites")

                    st.plotly_chart(fig_cohort, use_container_width=True)


                with layout_col2:

                    st.markdown("**Average CPD by supply status**")

                    cpd_by_cohort = (filtered_sites[filtered_sites["CPD"].notna()]

                                     .groupby("Supply Cohort")

                                     .agg(Avg_CPD=("CPD", "mean"), Approved=("Approved CPD", "mean"),

                                          Sites=("Site ID", "nunique"))

                                     .reset_index())

                    if not cpd_by_cohort.empty:

                        fig_cpd = px.bar(cpd_by_cohort.melt(id_vars=["Supply Cohort", "Sites"],

                                                            value_vars=["Avg_CPD", "Approved"],

                                                            var_name="Metric", value_name="L/day"),

                                         x="Supply Cohort", y="L/day", color="Metric",

                                         hover_data=["Sites"])

                        fig_cpd.update_layout(xaxis_title="", yaxis_title="Litres per day")

                        st.plotly_chart(fig_cpd, use_container_width=True)


                st.markdown("**Supply vs consumption by month**")

                monthly = filtered_math_df.copy()

                if not monthly.empty:

                    monthly["Month"] = monthly["Supply Date"].dt.to_period("M").astype(str)

                    monthly_tbl = monthly.groupby("Month").agg(

                        Supplied=("Total QTY Supplied", "sum"),

                        Consumed=("Total_Consumed", "sum"),

                        Sites=("Site ID", "nunique"),

                    ).reset_index()

                    monthly_tbl["Gap (Supplied − Consumed)"] = monthly_tbl["Supplied"] - monthly_tbl["Consumed"]

                    fig_month = px.line(

                        monthly_tbl.melt(id_vars="Month", value_vars=["Supplied", "Consumed"],

                                         var_name="Flow", value_name="Litres"),

                        x="Month", y="Litres", color="Flow", markers=True)

                    st.plotly_chart(fig_month, use_container_width=True)

                    st.dataframe(monthly_tbl, use_container_width=True, hide_index=True)


                st.markdown("**Burn rate vs time since last supply**")

                scatter_df = filtered_sites[filtered_sites["CPD"].notna() & filtered_sites["Days Since Last Supply"].notna()]

                if not scatter_df.empty:

                    fig_scatter = px.scatter(

                        scatter_df, x="Days Since Last Supply", y="CPD", color="Supply Cohort",

                        size="Qty After Last Supply", hover_name="Site ID",

                        hover_data=["Approved CPD", "Projected Days Left", "Estimated Next Supply Date"],

                        color_discrete_map=label_colors)

                    avg_approved = scatter_df["Approved CPD"].replace(0, np.nan).mean()

                    if pd.notna(avg_approved):

                        fig_scatter.add_hline(y=float(avg_approved), line_dash="dot",

                                              annotation_text="Avg approved CPD")

                    fig_scatter.update_layout(xaxis_title="Days since last supply",

                                              yaxis_title="Estimated CPD (L/day)")

                    st.plotly_chart(fig_scatter, use_container_width=True)


                st.markdown("**Site-level consumption status**")

                site_cols = ["Site ID", "Region", "Cluster", "Zones", "Type of supply", "Last Supply Date",

                             "Days Since Last Supply", "Supply Cohort", "Approved CPD", "CPD", "CPD Basis",

                             "Avg Days Between Supplies", "Qty After Last Supply", "Projected Qty Today",

                             "Projected Days Left", "Estimated Next Supply Date", "Supply Alert", "Variance Status"]

                status_view = fmt_date_cols(

                    filtered_sites[[c for c in site_cols if c in filtered_sites.columns]],

                    ["Last Supply Date"],

                )

                numeric_view = ["Days Since Last Supply", "Approved CPD", "CPD", "Avg Days Between Supplies",

                                "Qty After Last Supply", "Projected Qty Today", "Projected Days Left"]

                for cname in numeric_view:

                    if cname in status_view.columns:

                        status_view[cname] = status_view[cname].round(2)

                st.dataframe(status_view, use_container_width=True, hide_index=True)


        st.markdown("---")

        st.subheader("📜 Site History & CPD Trend")

        st.write("Select a site below to see its Estimated CPD history across all months.")

        if is_admin:

            history_site = st.selectbox("Select Site ID to view history:", sorted(df_math["Site ID"].unique().tolist()))

            site_hist_df = df_math[df_math["Site ID"] == history_site].sort_values("Supply Date")

            hist_cols = ["Supply Date", "Type of supply", "Total QTY Supplied", "Total_Consumed",

                         "Days_Diff", "Estimated CPD", "Approved CPD", "CPD Variance",

                         "Variance Status", "Reading Check"]

            st.dataframe(site_hist_df[[c for c in hist_cols if c in site_hist_df.columns]],

                         hide_index=True, use_container_width=True)

            if not site_hist_df.empty:

                chart_data = site_hist_df[["Supply Date", "Estimated CPD", "Approved CPD"]].melt(

                    id_vars="Supply Date", value_vars=["Estimated CPD", "Approved CPD"],

                    var_name="CPD Type", value_name="Value")

                fig_hist = px.line(chart_data, x="Supply Date", y="Value", color="CPD Type",

                                   markers=True, title=f"CPD History for {history_site}")

                st.plotly_chart(fig_hist, use_container_width=True)

        else:

            st.subheader("📜 Site Supply History")

            history_site = st.selectbox("Select Site ID to view history:", sorted(df_math["Site ID"].unique().tolist()))

            site_hist_df = df_math[df_math["Site ID"] == history_site].sort_values("Supply Date").copy()

            site_hist_df["Total QTY Supplied"] = (

                num_col(site_hist_df, "QTY supplied Tank 1")

                + num_col(site_hist_df, "QTY supplied Tank 2")

            )

            hist_cols = ["Supply Date", "Type of supply", "QTY supplied Tank 1", "QTY supplied Tank 2",

                         "Total QTY Supplied", "Bobtail number"]

            st.dataframe(site_hist_df[[c for c in hist_cols if c in site_hist_df.columns]],

                         hide_index=True, use_container_width=True)


        st.markdown("---")

        st.subheader("📋 Current Status (Latest Record per Site)")

        df_latest = filtered_math_df.sort_values("Supply Date").drop_duplicates(subset=["Site ID"], keep="last")


        if is_admin:

            display_cols = ["Site ID", "Region", "Cluster", "Zones", "Type of supply", "Total QTY Supplied",

                            "Total QTY Before Supply", "Approved CPD", "Estimated CPD", "CPD Variance",

                            "Variance Status", "Supply Date", "Estimated Next Supply Date", "Supply Alert",

                            "Bobtail number"]

        else:

            display_cols = ["Site ID", "Region", "Cluster", "Zones", "Type of supply",

                            "QTY supplied Tank 1", "QTY supplied Tank 2", "Total QTY Supplied",

                            "Supply Date", "Bobtail number"]


        st.dataframe(df_latest[[c for c in display_cols if c in df_latest.columns]],

                     use_container_width=True, hide_index=True)


        # ---------- WAYBILL TRACKER ----------

        st.markdown("---")

        st.subheader("🚛 Waybill Tracker" + (" & Truck Variance Analysis" if is_admin else ""))

        if not df_waybills.empty:

            valid_wb_dates = df_waybills["Trip Start Date"].dropna() if "Trip Start Date" in df_waybills.columns else pd.Series(dtype="datetime64[ns]")

            if not valid_wb_dates.empty:

                wb_min = valid_wb_dates.min().date()

                wb_max = valid_wb_dates.max().date()

                wb_filter_date = st.date_input("Filter Waybills by Trip Start Date", value=wb_max,

                                               min_value=wb_min, max_value=wb_max)

                filtered_wb = df_waybills[df_waybills["Trip Start Date"].dt.date == wb_filter_date]

            else:

                filtered_wb = df_waybills

                wb_filter_date = date.today()

        else:

            filtered_wb = pd.DataFrame()

            wb_filter_date = date.today()


        if not df_waybills.empty:

            if filtered_wb.empty:

                st.info("No waybills logged for the selected date.")

            else:

                wb_cols_show = ["Waybill Number", "Truck Number", "Driver Name", "Trip Start Date",

                                "Trip End Date", "Initial QTY (L)", "Loaded QTY (L)", "Loaded QTY (Kg)",

                                "Supplied QTY (L)", "Remaining QTY (L)", "Delivery Difference (L)",

                                "Prev Remaining QTY (L)", "Mapped Sites", "Supplied Sites",

                                "Site Variance", "Truck Variance Status"]

                if is_admin:

                    final_wb_show = [c for c in wb_cols_show if c in filtered_wb.columns]

                else:

                    final_wb_show = [c for c in TEAM_WAYBILL_COLS if c in filtered_wb.columns]


                def highlight_truck_var(val):

                    text = str(val)

                    if "Variance" in text:

                        return "background-color: #ffcccc; font-weight: bold;"

                    if "✅" in text:

                        return "background-color: #d4edda;"

                    return ""


                styled_wb = filtered_wb[final_wb_show].style

                if is_admin and "Truck Variance Status" in final_wb_show:

                    apply_map = getattr(styled_wb, "map", None) or styled_wb.applymap

                    apply_map(highlight_truck_var, subset=["Truck Variance Status"])


                st.dataframe(styled_wb, use_container_width=True, hide_index=True)


                w_col1, w_col2, w_col3, w_col4 = st.columns(4)

                w_col1.metric("Total Trucks Dispatched", len(filtered_wb))

                if "Loaded QTY (L)" in filtered_wb.columns:

                    w_col2.metric("Total Fuel Dispatched (L)", f"{filtered_wb['Loaded QTY (L)'].sum():,.2f} L")

                if "Loaded QTY (Kg)" in filtered_wb.columns:

                    w_col3.metric("Total Fuel Dispatched (Kg)", f"{filtered_wb['Loaded QTY (Kg)'].sum():,.2f} Kg")

                if is_admin and "Supplied Sites" in filtered_wb.columns and "Mapped Sites" in filtered_wb.columns:

                    total_mapped = int(filtered_wb["Mapped Sites"].sum())

                    total_supplied_wb = int(filtered_wb["Supplied Sites"].sum())

                    w_col4.metric("Sites: Mapped vs Supplied", f"{total_supplied_wb} / {total_mapped}")

        else:

            st.info("No waybills have been logged yet. Use the sidebar to add the first one!")


        # ---------- EXPORT ----------

        st.markdown("---")

        st.subheader("📥 Export Data to Excel")

        st.write("Download the currently filtered data for your records.")


        col_exp1, col_exp2 = st.columns(2)


        with col_exp1:

            st.markdown("**1. Site Supply Data**")

            drop_cols = ["_status_key"] if is_admin else ["_status_key", "Approved CPD"]

            export_supply_df = fmt_date_cols(filtered_math_df, ["Supply Date"]).drop(

                columns=drop_cols, errors="ignore"

            )


            output_supply = io.BytesIO()

            with pd.ExcelWriter(output_supply, engine="openpyxl") as writer:

                export_supply_df.to_excel(writer, index=False, sheet_name="Site Supplies")

                if is_admin and not filtered_sites.empty:

                    fmt_date_cols(filtered_sites.drop(columns=["Supply Cohort Key"], errors="ignore"),

                                  ["Last Supply Date"]).to_excel(

                        writer, index=False, sheet_name="Consumption Status")


            st.download_button(

                label="📥 Download Supply Data (.xlsx)",

                data=output_supply.getvalue(),

                file_name=f"site_supplies_{start_date}_to_{end_date}.xlsx",

                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",

            )


        with col_exp2:

            st.markdown("**2. Waybill Data**")

            if not filtered_wb.empty:

                if is_admin:

                    export_wb_df = fmt_date_cols(filtered_wb, ["Trip Start Date", "Trip End Date"])

                else:

                    export_wb_df = fmt_date_cols(

                        filtered_wb[[c for c in TEAM_WAYBILL_COLS if c in filtered_wb.columns]],

                        ["Trip Start Date", "Trip End Date"],

                    )


                output_wb = io.BytesIO()

                with pd.ExcelWriter(output_wb, engine="openpyxl") as writer:

                    export_wb_df.to_excel(writer, index=False, sheet_name="Waybills")


                st.download_button(

                    label="📥 Download Waybill Data (.xlsx)",

                    data=output_wb.getvalue(),

                    file_name=f"waybills_{wb_filter_date}.xlsx",

                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",

                )

            else:

                st.info("No waybill data available to download.")


else:

    st.info("👆 Database is empty. Use the sidebar to upload an Excel file or add manual entries!")
