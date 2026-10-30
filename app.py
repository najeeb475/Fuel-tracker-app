                fig_hist = px.line(chart_data, x="Supply Date", y="Value", color="CPD Type",
                                   markers=True, title=f"CPD History for {history_site}")
                st.plotly_chart(fig_hist, use_container_width=True)
        else:
            st.subheader("📜 Site Supply History")
            history_site = st.selectbox("Select Site ID to view history:", sorted(df_math["Site ID"].unique().tolist()))
            site_hist_df = df_math[df_math["Site ID"] == history_site].sort_values("Supply Date")
            hist_cols = ["Supply Date", "Type of supply", "Total QTY Supplied", "Supply Alert", "Bobtail number"]
            st.dataframe(site_hist_df[[c for c in hist_cols if c in site_hist_df.columns]],
                         hide_index=True, use_container_width=True)

        st.markdown("---")
        st.subheader("📋 Current Status (Latest Record per Site)")
        df_latest = filtered_math_df.sort_values("Supply Date").drop_duplicates(subset=["Site ID"], keep="last")

        if st.session_state.role == "Admin":
            display_cols = ["Site ID", "Region", "Cluster", "Zones", "Type of supply", "Total QTY Supplied",
                            "Total QTY Before Supply", "Approved CPD", "Estimated CPD", "CPD Variance",
                            "Variance Status", "Supply Date", "Estimated Next Supply Date", "Supply Alert",
                            "Bobtail number"]
        else:
            display_cols = ["Site ID", "Region", "Cluster", "Zones", "Type of supply", "Total QTY Supplied",
                            "Total QTY Before Supply", "Supply Date", "Estimated Next Supply Date",
                            "Supply Alert", "Bobtail number"]

        st.dataframe(df_latest[[c for c in display_cols if c in df_latest.columns]],
                     use_container_width=True, hide_index=True)

        # ---------- WAYBILL TRACKER ----------
        st.markdown("---")
        st.subheader("🚛 Waybill Tracker & Truck Variance Analysis")
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
                final_wb_show = [c for c in wb_cols_show if c in filtered_wb.columns]

                def highlight_truck_var(val):
                    text = str(val)
                    if "Variance" in text:
                        return "background-color: #ffcccc; font-weight: bold;"
                    if "✅" in text:
                        return "background-color: #d4edda;"
                    return ""

                styled_wb = filtered_wb[final_wb_show].style
                if "Truck Variance Status" in final_wb_show:
                    apply_map = getattr(styled_wb, "map", None) or styled_wb.applymap
                    apply_map(highlight_truck_var, subset=["Truck Variance Status"])

                st.dataframe(styled_wb, use_container_width=True, hide_index=True)

                w_col1, w_col2, w_col3, w_col4 = st.columns(4)
                w_col1.metric("Total Trucks Dispatched", len(filtered_wb))
                if "Loaded QTY (L)" in filtered_wb.columns:
                    w_col2.metric("Total Fuel Dispatched (L)", f"{filtered_wb['Loaded QTY (L)'].sum():,.2f} L")
                if "Loaded QTY (Kg)" in filtered_wb.columns:
                    w_col3.metric("Total Fuel Dispatched (Kg)", f"{filtered_wb['Loaded QTY (Kg)'].sum():,.2f} Kg")
                if "Supplied Sites" in filtered_wb.columns and "Mapped Sites" in filtered_wb.columns:
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
            export_supply_df = fmt_date_cols(filtered_math_df, ["Supply Date"]).drop(columns=["_status_key"], errors="ignore")

            output_supply = io.BytesIO()
            with pd.ExcelWriter(output_supply, engine="openpyxl") as writer:
                export_supply_df.to_excel(writer, index=False, sheet_name="Site Supplies")
                if not filtered_sites.empty:
                    fmt_date_cols(filtered_sites, ["Last Supply Date"]).to_excel(
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
                export_wb_df = fmt_date_cols(filtered_wb, ["Trip Start Date", "Trip End Date"])

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
