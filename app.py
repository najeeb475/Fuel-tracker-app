                order = [k for k in ("recent", "due_soon", "overdue", "steady", "no_data")
                         if k in set(cohort_counts["Supply Cohort Key"])]
                cohort_counts["Supply Cohort Key"] = pd.Categorical(
                    cohort_counts["Supply Cohort Key"], categories=order, ordered=True)
                cohort_counts = cohort_counts.sort_values("Supply Cohort Key").reset_index(drop=True)
                cohort_counts["Supply Cohort"] = cohort_counts["Supply Cohort Key"].map(COHORT_LABELS)
                fig_cohort = px.bar(cohort_counts, x="Supply Cohort", y="Sites",
                                    color="Supply Cohort", color_discrete_map=cohort_colors, text="Sites")
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
                    color_discrete_map=cohort_colors)
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
