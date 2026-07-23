import streamlit as st
import pandas as pd
from supabase import create_client
import plotly.express as px
import json

st.set_page_config(page_title="E-Commerce Listing Monitor", layout="wide")

# --- CUSTOM STYLING ---
st.markdown("""
    <style>
    .metric-card {
        background-color: #f8f9fa;
        border-radius: 10px;
        padding: 15px;
        border: 1px solid #e0e0e0;
    }
    </style>
""", unsafe_allow_html=True)

# --- HELPER FUNCTION: Safely Parse JSON ---
def parse_json(x):
    if isinstance(x, dict): return x
    if isinstance(x, str) and x.strip() != "":
        try: return json.loads(x)
        except: return {}
    return {}

@st.cache_resource
def init_connection():
    # Insert your Supabase URL and Key here
    url = "https://hityiohhbrzwrevmbxea.supabase.co"
    key = "sb_publishable_GAAYcbnR3sB1MVnzsV1cMA_TdRSwyDL"
    return create_client(url, key)

supabase = init_connection()

# --- HELPER FUNCTION: Pagination (Bypass 1000 Row Limit) ---
def fetch_all_records(table, select="*", eq_col=None, eq_val=None, in_col=None, in_vals=None):
    all_data = []
    page_size = 1000
    start = 0
    
    while True:
        query = supabase.table(table).select(select)
        
        if eq_col and eq_val is not None:
            query = query.eq(eq_col, eq_val)
        if in_col and in_vals is not None:
            query = query.in_(in_col, in_vals)
            
        response = query.range(start, start + page_size - 1).execute()
        data = response.data
        
        if not data:
            break
            
        all_data.extend(data)
        
        if len(data) < page_size:
            break
            
        start += page_size
        
    return all_data

st.title("Listing Monitor")
st.markdown("Track, visualize, and protect your Amazon catalog from unauthorized modifications.")

tab_dump, tab_compare, tab_dashboard, tab_catalog, tab_deepdive, tab_alldata, tab_editor = st.tabs([
    "Data Ingestion", 
    "Run Analysis", 
    "Analytics Dashboard", 
    "Master Catalog",
    "ASIN Deep Dive",
    "Global Delta View",
    "Live Data Editor"
])

# --- TAB 1: DATA INGESTION & MANAGEMENT ---
with tab_dump:
    st.header("Data Ingestion")
    st.write("Upload your monthly or weekly Amazon CSV exports to generate a baseline.")
    
    uploaded_files = st.file_uploader("Upload CSVs", type=["csv"], accept_multiple_files=True)
    
    if st.button("Process & Save Snapshots", type="primary"):
        if uploaded_files:
            with st.spinner('Ingesting full data to Supabase...'):
                for file in uploaded_files:
                    df = pd.read_csv(file)
                    records = []
                    
                    core_cols = ["ASIN", "Brand", "title", "list_price", "bullet_point_1"]
                    
                    for _, row in df.iterrows():
                        raw_data = row.drop(labels=[c for c in core_cols if c in row.index], errors="ignore").fillna("").to_dict()
                        
                        records.append({
                            "batch_name": file.name,
                            "asin": str(row.get("ASIN", "")),
                            "brand": str(row.get("Brand", "")),
                            "title": str(row.get("title", "")),
                            "list_price": str(row.get("list_price", "")),
                            "bullet_point_1": str(row.get("bullet_point_1", "")),
                            "raw_sheet_data": raw_data
                        })
                    
                    for i in range(0, len(records), 500):
                        supabase.table("monthly_snapshots").insert(records[i:i+500]).execute()
                        
                st.success(f"Successfully ingested {len(uploaded_files)} files with ALL columns!")
        else:
            st.error("Please drag and drop at least one file.")

    st.divider()
    st.subheader("Manage Uploaded Files")
    
    existing_batches_data = fetch_all_records("monthly_snapshots", select="batch_name")
    
    if existing_batches_data:
        unique_files = sorted(list(set([row["batch_name"] for row in existing_batches_data])))
        file_to_delete = st.selectbox("Select a file to permanently delete", unique_files)
        
        if st.button("Delete File Data", type="secondary"):
            with st.spinner("Deleting records from database..."):
                supabase.table("monthly_snapshots").delete().eq("batch_name", file_to_delete).execute()
                st.success(f"Successfully deleted all data for '{file_to_delete}'!")
                st.rerun() 
    else:
        st.info("No files currently in the database.")


# --- TAB 2: RUN ANALYSIS ---
with tab_compare:
    st.header("Catalog Delta Analysis")
    
    response_data = fetch_all_records("monthly_snapshots", select="batch_name")
    
    if not response_data:
        st.info("No snapshots available. Please ingest data first.")
    else:
        saved_files = sorted(list(set([row["batch_name"] for row in response_data])))
        
        col1, col2 = st.columns(2)
        with col1:
            old_file = st.selectbox("Baseline Snapshot (Older)", saved_files)
        with col2:
            new_file = st.selectbox("Target Snapshot (Newer)", saved_files, index=len(saved_files)-1)
            
        if st.button("Run Comparison"):
            st.write("---")
            
            with st.spinner("Pulling data from database (this may take a moment for large files)..."):
                old_data = fetch_all_records("monthly_snapshots", eq_col="batch_name", eq_val=old_file)
                new_data = fetch_all_records("monthly_snapshots", eq_col="batch_name", eq_val=new_file)
            
            df_old, df_new = pd.DataFrame(old_data), pd.DataFrame(new_data)
            
            if df_old.empty or df_new.empty:
                st.error("Missing data in selected snapshots.")
            else:
                if 'raw_sheet_data' in df_old.columns:
                    raw_df_old = pd.json_normalize(df_old['raw_sheet_data'].apply(parse_json).tolist())
                    df_old = pd.concat([df_old.drop(columns=['raw_sheet_data']), raw_df_old], axis=1)
                
                if 'raw_sheet_data' in df_new.columns:
                    raw_df_new = pd.json_normalize(df_new['raw_sheet_data'].apply(parse_json).tolist())
                    df_new = pd.concat([df_new.drop(columns=['raw_sheet_data']), raw_df_new], axis=1)
                
                df_old = df_old.fillna("")
                df_new = df_new.fillna("")

                merged = df_new.merge(df_old, on="asin", suffixes=("_new", "_old"))
                
                changes = []
                for _, row in merged.iterrows():
                    if row.get("title_new", "") != row.get("title_old", ""):
                        changes.append({"asin": row["asin"], "field_changed": "Title", "old_value": row["title_old"], "new_value": row["title_new"]})
                    
                    if row.get("list_price_new", "") != row.get("list_price_old", ""):
                        changes.append({"asin": row["asin"], "field_changed": "Price", "old_value": row["list_price_old"], "new_value": row["list_price_new"]})
                    
                    for i in range(1, 6):
                        bp_col = f"bullet_point_{i}"
                        col_new = f"{bp_col}_new"
                        col_old = f"{bp_col}_old"
                        
                        if col_new in merged.columns or col_old in merged.columns:
                            val_new = str(row.get(col_new, ""))
                            val_old = str(row.get(col_old, ""))
                            
                            if val_new != val_old:
                                changes.append({
                                    "asin": row["asin"], 
                                    "field_changed": f"Bullet Point {i}", 
                                    "old_value": val_old, 
                                    "new_value": val_new
                                })
                
                total_monitored = len(merged)
                items_changed = len(set([c["asin"] for c in changes]))
                health_score = round(((total_monitored - items_changed) / total_monitored) * 100, 1) if total_monitored > 0 else 0

                kpi1, kpi2, kpi3 = st.columns(3)
                kpi1.metric("Total ASINs", total_monitored)
                kpi2.metric("ASINs Altered", items_changed, f"-{items_changed} from baseline", delta_color="inverse")
                kpi3.metric("Catalog Health Score", f"{health_score}%")
                
                if changes:
                    st.session_state['pending_changes'] = changes
                    st.session_state['current_compare'] = new_file
                    st.session_state['previous_compare'] = old_file
                    st.warning(f"Detected {len(changes)} total modifications across {items_changed} ASINs.")
                else:
                    st.success("Catalog is perfectly synchronized. No changes detected.")
                    st.session_state['pending_changes'] = []

        if 'pending_changes' in st.session_state and st.session_state['pending_changes']:
            st.write("---")
            st.subheader("Save Report")
            
            default_report_name = f"{st.session_state['current_compare']} (vs {st.session_state['previous_compare']})"
            custom_report_name = st.text_input("Report Name:", value=default_report_name)

            if st.button("Lock & Flag Modifications to Dashboard", type="primary"):
                if not custom_report_name.strip():
                    st.error("Please provide a valid name for this report.")
                else:
                    report_records = []
                    
                    for change in st.session_state['pending_changes']:
                        report_records.append({
                            "asin": change["asin"],
                            "current_batch": custom_report_name.strip(),
                            "previous_batch": st.session_state['previous_compare'],
                            "field_changed": change["field_changed"],
                            "old_value": change["old_value"],
                            "new_value": change["new_value"],
                            "report_notes": "" 
                        })
                    
                    supabase.table("monitoring_reports").insert(report_records).execute()
                    st.success(f"Modifications successfully locked into report '{custom_report_name}'!")
                    st.session_state['pending_changes'] = []


# --- TAB 3: ANALYTICS DASHBOARD & REPORT MANAGEMENT ---
with tab_dashboard:
    report_batches_data = fetch_all_records("monitoring_reports", select="current_batch")
    
    if not report_batches_data:
        st.info("No flagged reports available yet.")
    else:
        saved_report_files = sorted(list(set([row["current_batch"] for row in report_batches_data])), reverse=True)
        
        col_title, col_filter = st.columns([2, 1])
        with col_title:
            st.header("Modification Intelligence")
        with col_filter:
            selected_report = st.selectbox("Filter by Snapshot / Report", saved_report_files, label_visibility="collapsed")
        
        report_data = fetch_all_records("monitoring_reports", eq_col="current_batch", eq_val=selected_report)
        df_report = pd.DataFrame(report_data)
        
        if not df_report.empty:
            unique_asins = df_report['asin'].nunique()
            total_flags = len(df_report)
            top_change = df_report['field_changed'].mode()[0]
            
            dash1, dash2, dash3 = st.columns(3)
            dash1.metric("Affected ASINs", unique_asins)
            dash2.metric("Total Flagged Attributes", total_flags)
            dash3.metric("Most Targeted Field", top_change)
            
            st.divider()

            st.subheader("Distribution of Modifications")
            fig_pie = px.pie(df_report, names='field_changed', hole=0.5, color_discrete_sequence=px.colors.qualitative.Pastel)
            fig_pie.update_layout(margin=dict(t=0, b=0, l=0, r=0))
            st.plotly_chart(fig_pie, use_container_width=True)

            st.divider()

            st.subheader("Deep Dive: Flagged Entries")
            search_query = st.text_input("Search reports by ASIN or keyword...")
            if search_query:
                mask = df_report.apply(lambda row: row.astype(str).str.contains(search_query, case=False).any(), axis=1)
                df_filtered = df_report[mask]
            else:
                df_filtered = df_report

            st.dataframe(
                df_filtered[['asin', 'field_changed', 'old_value', 'new_value']],
                column_config={
                    "asin": "ASIN",
                    "field_changed": "Altered Field",
                    "old_value": "Old Value",
                    "new_value": "New Value"
                },
                hide_index=True,
                use_container_width=True
            )

            # --- NEW: Export Report Button ---
            st.write("")
            csv_export = df_filtered[['asin', 'field_changed', 'old_value', 'new_value']].to_csv(index=False).encode('utf-8')
            st.download_button(
                label="Download Report as CSV (Ready for Google Sheets)",
                data=csv_export,
                file_name=f"{selected_report}_Report.csv",
                mime="text/csv",
                type="primary"
            )

            st.divider()
            st.subheader("Manage Reports")
            st.write(f"Warning: This will permanently delete the flagged report for **{selected_report}**.")
            
            if st.button("Delete This Report", type="secondary"):
                with st.spinner("Deleting report from database..."):
                    supabase.table("monitoring_reports").delete().eq("current_batch", selected_report).execute()
                    st.success(f"Report '{selected_report}' successfully deleted!")
                    st.rerun()


# --- TAB 4: MASTER CATALOG ---
with tab_catalog:
    st.header("Master Catalog Viewer")
    st.write("Browse and search through your raw product data across multiple files.")
    
    catalog_batches_data = fetch_all_records("monthly_snapshots", select="batch_name")
    
    if not catalog_batches_data:
        st.info("No data in the catalog yet. Upload a CSV in the 'Data Ingestion' tab.")
    else:
        all_snapshots = sorted(list(set([row["batch_name"] for row in catalog_batches_data])), reverse=True)
        
        selected_snapshots = st.multiselect(
            "Select Files to View", 
            options=all_snapshots, 
            default=[all_snapshots[0]] 
        )
        
        if selected_snapshots:
            with st.spinner("Fetching full catalog (this may take a few seconds)..."):
                raw_catalog_data = fetch_all_records("monthly_snapshots", in_col="batch_name", in_vals=selected_snapshots)
                
            df_catalog = pd.DataFrame(raw_catalog_data)
            
            if not df_catalog.empty:
                if 'raw_sheet_data' in df_catalog.columns:
                    parsed_json_list = df_catalog['raw_sheet_data'].apply(parse_json).tolist()
                    raw_df = pd.json_normalize(parsed_json_list)
                    
                    df_catalog = df_catalog.drop(columns=['id', 'created_at', 'raw_sheet_data'], errors='ignore')
                    df_catalog = pd.concat([df_catalog, raw_df], axis=1)
                
                cols = ['batch_name'] + [c for c in df_catalog.columns if c != 'batch_name']
                df_catalog = df_catalog[cols]

                catalog_search = st.text_input("Search selected files (by ASIN, Title, Brand)...")
                
                if catalog_search:
                    mask = df_catalog.apply(lambda row: row.astype(str).str.contains(catalog_search, case=False).any(), axis=1)
                    df_catalog_filtered = df_catalog[mask]
                else:
                    df_catalog_filtered = df_catalog
                
                st.metric("Total Products in View", len(df_catalog_filtered))
                
                st.dataframe(
                    df_catalog_filtered,
                    hide_index=True,
                    use_container_width=True
                )


# --- TAB 5: ASIN DEEP DIVE ---
with tab_deepdive:
    st.header("ASIN Deep Dive Comparison")
    st.write("Inspect every single column for a specific ASIN across two different snapshots.")
    
    dd_batches_data = fetch_all_records("monthly_snapshots", select="batch_name")
    
    if not dd_batches_data:
        st.info("No snapshots available. Please ingest data first.")
    else:
        dd_files = sorted(list(set([row["batch_name"] for row in dd_batches_data])))
        
        dd_col1, dd_col2 = st.columns(2)
        with dd_col1:
            dd_old = st.selectbox("Baseline Snapshot (Older)", dd_files, key="dd_old")
        with dd_col2:
            dd_new = st.selectbox("Target Snapshot (Newer)", dd_files, index=len(dd_files)-1, key="dd_new")
            
        asin_to_search = st.text_input("Enter ASIN to inspect:", placeholder="e.g. B08FX...")
        
        show_only_diff = st.checkbox("Show only fields with changes", value=False)
        
        if st.button("Run Deep Dive", type="primary"):
            if not asin_to_search:
                st.error("Please enter an ASIN to search.")
            else:
                with st.spinner("Fetching and comparing all raw data..."):
                    old_asin_data = supabase.table("monthly_snapshots").select("*").eq("batch_name", dd_old).eq("asin", asin_to_search).limit(10).execute().data
                    new_asin_data = supabase.table("monthly_snapshots").select("*").eq("batch_name", dd_new).eq("asin", asin_to_search).limit(10).execute().data
                    
                    if not old_asin_data and not new_asin_data:
                        st.warning(f"ASIN '{asin_to_search}' was not found in either snapshot.")
                    else:
                        dict_old = {}
                        if old_asin_data:
                            row_o = old_asin_data[0]
                            dict_old = {k: row_o[k] for k in ["asin", "brand", "title", "list_price", "bullet_point_1"]}
                            dict_old.update(parse_json(row_o.get("raw_sheet_data", {})))
                            
                        dict_new = {}
                        if new_asin_data:
                            row_n = new_asin_data[0]
                            dict_new = {k: row_n[k] for k in ["asin", "brand", "title", "list_price", "bullet_point_1"]}
                            dict_new.update(parse_json(row_n.get("raw_sheet_data", {})))
                            
                        all_keys = sorted(list(set(list(dict_old.keys()) + list(dict_new.keys()))))
                        
                        comparison_rows = []
                        for k in all_keys:
                            val_o = str(dict_old.get(k, ""))
                            val_n = str(dict_new.get(k, ""))
                            changed = val_o != val_n
                            
                            if show_only_diff and not changed:
                                continue
                                
                            comparison_rows.append({
                                "Field": k,
                                "Older Value": val_o,
                                "Newer Value": val_n,
                                "Changed?": "Yes" if changed else "No"
                            })
                            
                        if not comparison_rows:
                            st.success(f"No differences found for ASIN '{asin_to_search}' between these two files.")
                        else:
                            df_comp = pd.DataFrame(comparison_rows)
                            
                            def highlight_changes(row):
                                if row["Changed?"] == "Yes":
                                    return ['background-color: #ffcccc; color: #900'] * len(row)
                                return [''] * len(row)
                                
                            st.dataframe(
                                df_comp.style.apply(highlight_changes, axis=1),
                                use_container_width=True,
                                hide_index=True
                            )


# --- TAB 6: GLOBAL DELTA VIEW (ALL CHANGES) ---
with tab_alldata:
    st.header("Global Delta View")
    st.write("Compare two entire catalog snapshots side-by-side. View all columns and data for all matched ASINs.")
    
    delta_batches_data = fetch_all_records("monthly_snapshots", select="batch_name")
    
    if not delta_batches_data:
        st.info("No snapshots available. Please ingest data first.")
    else:
        delta_files = sorted(list(set([row["batch_name"] for row in delta_batches_data])))
        
        delta_col1, delta_col2 = st.columns(2)
        with delta_col1:
            delta_old = st.selectbox("Baseline Snapshot (Older)", delta_files, key="delta_old_sel")
        with delta_col2:
            delta_new = st.selectbox("Target Snapshot (Newer)", delta_files, index=len(delta_files)-1, key="delta_new_sel")
            
        show_only_modified_rows = st.checkbox("Only show ASINs that have at least one change", value=False)
            
        if st.button("Generate Full Catalog Comparison", type="primary"):
            with st.spinner("Cross-referencing all columns across all ASINs (this may take a minute)..."):
                
                old_data_full = fetch_all_records("monthly_snapshots", eq_col="batch_name", eq_val=delta_old)
                new_data_full = fetch_all_records("monthly_snapshots", eq_col="batch_name", eq_val=delta_new)
                
                df_old_full, df_new_full = pd.DataFrame(old_data_full), pd.DataFrame(new_data_full)
                
                if df_old_full.empty or df_new_full.empty:
                    st.error("Missing data in selected snapshots.")
                else:
                    if 'raw_sheet_data' in df_old_full.columns:
                        raw_df_old = pd.json_normalize(df_old_full['raw_sheet_data'].apply(parse_json).tolist())
                        df_old_full = pd.concat([df_old_full.drop(columns=['raw_sheet_data']), raw_df_old], axis=1)
                        
                    if 'raw_sheet_data' in df_new_full.columns:
                        raw_df_new = pd.json_normalize(df_new_full['raw_sheet_data'].apply(parse_json).tolist())
                        df_new_full = pd.concat([df_new_full.drop(columns=['raw_sheet_data']), raw_df_new], axis=1)
                        
                    cols_to_drop = ["id", "created_at", "batch_name"]
                    df_old_full = df_old_full.drop(columns=[c for c in cols_to_drop if c in df_old_full.columns])
                    df_new_full = df_new_full.drop(columns=[c for c in cols_to_drop if c in df_new_full.columns])
                    
                    df_old_full = df_old_full.fillna("")
                    df_new_full = df_new_full.fillna("")
                    
                    merged_full = df_new_full.merge(df_old_full, on="asin", suffixes=("_new", "_old"))
                    
                    all_base_cols = set()
                    for c in df_old_full.columns: all_base_cols.add(c)
                    for c in df_new_full.columns: all_base_cols.add(c)
                    if "asin" in all_base_cols:
                        all_base_cols.remove("asin")
                        
                    core_order = ["title", "list_price", "brand", "bullet_point_1", "bullet_point_2", "bullet_point_3", "bullet_point_4", "bullet_point_5"]
                    sorted_base_cols = []
                    for c in core_order:
                        if c in all_base_cols:
                            sorted_base_cols.append(c)
                            all_base_cols.remove(c)
                    sorted_base_cols.extend(sorted(list(all_base_cols)))
                    
                    ordered_cols = ["asin"]
                    col_mapping = {"asin": "ASIN"}
                    
                    for col in sorted_base_cols:
                        col_o = f"{col}_old"
                        col_n = f"{col}_new"
                        ordered_cols.extend([col_o, col_n])
                        col_mapping[col_o] = f"{col} (Old)"
                        col_mapping[col_n] = f"{col} (New)"
                        
                    for c in ordered_cols:
                        if c not in merged_full.columns:
                            merged_full[c] = ""
                            
                    df_display = merged_full[ordered_cols].rename(columns=col_mapping)
                    
                    if show_only_modified_rows:
                        def row_has_change(row):
                            for col in sorted_base_cols:
                                if row[f"{col} (Old)"] != row[f"{col} (New)"]:
                                    return True
                            return False
                        mask = df_display.apply(row_has_change, axis=1)
                        df_display = df_display[mask]
                        
                    st.metric("Total Products in View", len(df_display))

                    search_global = st.text_input("Filter table by ASIN or keyword...")
                    if search_global:
                        search_mask = df_display.apply(lambda row: row.astype(str).str.contains(search_global, case=False).any(), axis=1)
                        df_display = df_display[search_mask]
                        
                    def highlight_wide_changes(row):
                        styles = [''] * len(row)
                        cols = row.index.tolist()
                        for i, col in enumerate(cols):
                            if col.endswith("(Old)"):
                                base_name = col.replace(" (Old)", "")
                                new_col = f"{base_name} (New)"
                                if new_col in cols and row[col] != row[new_col]:
                                    styles[i] = 'background-color: #ffcccc; color: #900'
                            elif col.endswith("(New)"):
                                base_name = col.replace(" (New)", "")
                                old_col = f"{base_name} (Old)"
                                if old_col in cols and row[col] != row[old_col]:
                                    styles[i] = 'background-color: #ffcccc; color: #900'
                        return styles

                    st.dataframe(
                        df_display.style.apply(highlight_wide_changes, axis=1),
                        hide_index=True,
                        use_container_width=True
                    )


# --- TAB 7: LIVE DATA EDITOR ---
with tab_editor:
    st.header("Live Data Editor")
    st.write("Edit your catalog snapshots directly within the grid. Double-click any cell to modify the text. You can also add or delete rows.")
    
    editor_batches_data = fetch_all_records("monthly_snapshots", select="batch_name")
    
    if not editor_batches_data:
        st.info("No snapshots available to edit. Please ingest data first.")
    else:
        editor_files = sorted(list(set([row["batch_name"] for row in editor_batches_data])))
        selected_edit_file = st.selectbox("Select Snapshot to Edit", editor_files, key="editor_file_sel")
        
        if selected_edit_file:
            with st.spinner("Loading editable grid (this may take a few seconds for large files)..."):
                raw_edit_data = fetch_all_records("monthly_snapshots", eq_col="batch_name", eq_val=selected_edit_file)
                
            if raw_edit_data:
                df_edit = pd.DataFrame(raw_edit_data)
                
                if 'raw_sheet_data' in df_edit.columns:
                    parsed_json_list = df_edit['raw_sheet_data'].apply(parse_json).tolist()
                    raw_df_edit = pd.json_normalize(parsed_json_list)
                    
                    df_edit = df_edit.drop(columns=['id', 'created_at', 'raw_sheet_data'], errors='ignore')
                    df_edit = pd.concat([df_edit, raw_df_edit], axis=1)
                
                # Make sure batch_name stays hidden or read-only, but we will force it during save anyway
                cols = [c for c in df_edit.columns if c != 'batch_name']
                df_edit = df_edit[cols]
                
                edited_df = st.data_editor(
                    df_edit,
                    use_container_width=True,
                    num_rows="dynamic",
                    key=f"editor_grid_{selected_edit_file}"
                )
                
                st.write("---")
                if st.button("Save Changes to Database", type="primary"):
                    with st.spinner("Repackaging data and applying updates to the database..."):
                        
                        records = []
                        core_cols_lower = ["asin", "brand", "title", "list_price", "bullet_point_1"]
                        
                        for _, row in edited_df.iterrows():
                            # Extract JSON columns dynamically
                            raw_data = row.drop(labels=[c for c in core_cols_lower if c in row.index], errors="ignore").fillna("").to_dict()
                            
                            records.append({
                                "batch_name": selected_edit_file, # Ensure it saves back to the correct file
                                "asin": str(row.get("asin", "")),
                                "brand": str(row.get("brand", "")),
                                "title": str(row.get("title", "")),
                                "list_price": str(row.get("list_price", "")),
                                "bullet_point_1": str(row.get("bullet_point_1", "")),
                                "raw_sheet_data": raw_data
                            })
                            
                        # Delete the old snapshot entirely
                        supabase.table("monthly_snapshots").delete().eq("batch_name", selected_edit_file).execute()
                        
                        # Re-insert the new edited chunk
                        for i in range(0, len(records), 500):
                            supabase.table("monthly_snapshots").insert(records[i:i+500]).execute()
                            
                        st.success(f"Changes successfully saved to '{selected_edit_file}'!")