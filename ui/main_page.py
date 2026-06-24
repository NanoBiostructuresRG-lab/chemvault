# SPDX-License-Identifier: LGPL-3.0-or-later
import html
import json
import math
import os
import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st
from services.activity_data import (
    ACTIVITY_EXPORT_COLUMNS,
    get_activity_csv_bytes,
    get_activity_row_count,
    get_activity_rows,
    get_activity_summary,
    get_activity_value_stats,
)
from services.db_audit import (
    delete_user_table,
    get_database_schema,
    get_operation_log,
    get_user_table_profiles,
)
from services.database import (
    count_rows,
    count_rows_group_by,
    get_connection,
    load_existing_database,
    set_database_id,
    update_headers,
)
from services.selection import build_preview_table
from services.sql_utils import quote_identifier
from state_keys import (
    ALL_TABLES,
    CURRENT_TABLE,
    DATABASE_ID,
    EXISTING_DB_SELECT,
    GROUP_COUNT_COLUMN,
    HEADERS,
    INPUT_DATABASE_ID,
    SELECTED_HEADERS,
    SET_TEXT_INPUT_LOCKED,
)


def create_main_layout():
    container0 = st.container(
        horizontal=True,
        horizontal_alignment="distribute",
        gap="large",
        border=True,
    )
    st.html("""
        <div style="
            height: 3.25rem;
        "></div>
        """)
    container1 = st.container(horizontal=False, horizontal_alignment="left", border=True)
    st.html("""
        <hr style="
            border: none;
            height: 2px;
            background-color: var(--cv-border);
            margin: 32px 0 24px 0;
        ">
        """)

    container2 = st.container(horizontal=False, horizontal_alignment="left", border=True)
    st.html("""
        <hr style="
            border: none;
            height: 2px;
            background-color: var(--cv-border);
            margin: 32px 0 24px 0;
        ">
        """)
    container3 = st.container(horizontal=False, horizontal_alignment="left", border=True)
    st.html("""
        <hr style="
            border: none;
            height: 2px;
            background-color: var(--cv-border);
            margin: 32px 0 24px 0;
        ">
        """)
    container4 = st.container(horizontal=False, horizontal_alignment="left", border=True)
    return container0, container1, container2, container3, container4


def render_app_identity(container):
    col_logo, col_titulo = container.columns([0.12, 0.88], vertical_alignment="center")

    with col_logo:
        st.image("assets/logo.jpeg", use_container_width=True)

    with col_titulo:
        st.markdown(
            """
            <div style="padding: 0.15rem 0;">
                <div style="
                    font-size: 2.45rem;
                    line-height: 1.05;
                    font-weight: 700;
                    color: var(--cv-heading);
                ">
                    ChemVault
                </div>
                <div style="margin-top: 0.25rem; font-size: 0.98rem; color: var(--cv-muted);">
                    Molecular dataset construction, curation, and export workspace.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def render_database_metrics(container, database_id, current_table, row_count, group_count):
    container.markdown(
        f"""
        <div style="
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
            gap: 0.35rem 1.5rem;
            margin: 0.7rem 0 1rem 0;
            padding: 0.85rem 0;
            border-top: 1px solid var(--cv-border);
            border-bottom: 1px solid var(--cv-border);
        ">
            <div>
                <div style="font-size: 0.76rem; color: var(--cv-muted);">Database</div>
                <div style="
                    font-size: 0.95rem;
                    color: var(--cv-text);
                    overflow-wrap: anywhere;
                ">{html.escape(database_id)}</div>
            </div>
            <div>
                <div style="font-size: 0.76rem; color: var(--cv-muted);">Table</div>
                <div style="font-size: 0.95rem; color: var(--cv-text);">{html.escape(current_table)}</div>
            </div>
            <div>
                <div style="font-size: 0.76rem; color: var(--cv-muted);">Rows</div>
                <div style="font-size: 0.95rem; color: var(--cv-text);">{row_count}</div>
            </div>
            <div>
                <div style="font-size: 0.76rem; color: var(--cv-muted);">Unique groups</div>
                <div style="font-size: 0.95rem; color: var(--cv-text);">{group_count}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _get_protein_traceability_summary(connection):
    cursor = connection.cursor()
    cursor.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='compound_assays'"
    )
    if cursor.fetchone() is None:
        return None

    cursor.execute('SELECT COUNT(DISTINCT CID), COUNT(DISTINCT AID), COUNT(*) FROM "compound_assays"')
    unique_cids, individual_aids, cid_aid_links = cursor.fetchone()
    cursor.execute('SELECT DISTINCT Protein FROM "compound_assays" ORDER BY Protein')
    proteins = [row[0] for row in cursor.fetchall()]

    activity_status = "not_attempted"
    cursor.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='main'")
    if cursor.fetchone() is not None:
        cursor.execute('PRAGMA table_info("main")')
        main_columns = [row[1] for row in cursor.fetchall()]
        if "Activity_Enrichment_Status" in main_columns:
            cursor.execute(
                '''
                SELECT Activity_Enrichment_Status, COUNT(*)
                FROM "main"
                WHERE COALESCE(Activity_Enrichment_Status, '') != ''
                GROUP BY Activity_Enrichment_Status
                ORDER BY COUNT(*) DESC, Activity_Enrichment_Status
                '''
            )
            rows = cursor.fetchall()
            if rows:
                activity_status = ", ".join(f"{status}: {count}" for status, count in rows)

    return {
        "unique_cids": unique_cids,
        "proteins": proteins,
        "individual_aids": individual_aids,
        "cid_aid_links": cid_aid_links,
        "activity_status": activity_status,
    }


def render_protein_traceability_summary(container, connection):
    summary = _get_protein_traceability_summary(connection)
    if summary is None:
        return

    protein_text = ", ".join(summary["proteins"]) if summary["proteins"] else "None"
    container.markdown(
        f"""
        <div style="
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(145px, 1fr));
            gap: 0.35rem 1rem;
            margin: -0.3rem 0 1rem 0;
            padding: 0.75rem 0;
            border-bottom: 1px solid var(--cv-border);
        ">
            <div>
                <div style="font-size: 0.72rem; color: var(--cv-muted);">Unique CIDs</div>
                <div style="font-size: 0.93rem; color: var(--cv-text);">{summary["unique_cids"]}</div>
            </div>
            <div>
                <div style="font-size: 0.72rem; color: var(--cv-muted);">Seed proteins</div>
                <div style="font-size: 0.93rem; color: var(--cv-text); overflow-wrap: anywhere;">
                    {html.escape(protein_text)}
                </div>
            </div>
            <div>
                <div style="font-size: 0.72rem; color: var(--cv-muted);">Individual AIDs</div>
                <div style="font-size: 0.93rem; color: var(--cv-text);">{summary["individual_aids"]}</div>
            </div>
            <div>
                <div style="font-size: 0.72rem; color: var(--cv-muted);">CID-AID links</div>
                <div style="font-size: 0.93rem; color: var(--cv-text);">{summary["cid_aid_links"]}</div>
            </div>
            <div>
                <div style="font-size: 0.72rem; color: var(--cv-muted);">Activity enrichment</div>
                <div style="font-size: 0.93rem; color: var(--cv-text); overflow-wrap: anywhere;">
                    {html.escape(summary["activity_status"])}
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _format_audit_label(value):
    if value in (None, ""):
        return "-"
    return str(value).replace("_", " ").title()


def _format_status_labels(statuses):
    if not statuses:
        return "-"
    return ", ".join(_format_audit_label(status) for status in statuses)


def _format_created_at(value):
    if value in (None, ""):
        return "-"
    return str(value).split("T", 1)[0]


def _format_operation_columns(value):
    if value in (None, ""):
        return "-"
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return str(value)
    if isinstance(decoded, list):
        return ", ".join(str(item) for item in decoded)
    return str(decoded)


def _build_table_manager_dataframe(profiles):
    rows = []
    for profile in profiles:
        rows.append(
            {
                "Table": profile["table"],
                "Rows": profile["rows"],
                "Columns": profile["columns"],
                "Role": _format_audit_label(profile.get("role")),
                "Origin": _format_audit_label(profile.get("origin")),
                "Source": profile.get("source_table") or "-",
                "Created": _format_created_at(profile.get("created_at")),
                "Metadata": _format_audit_label(profile.get("metadata_status")),
                "Status": _format_status_labels(profile.get("status", [])),
                "Action": profile.get("recommended_action", "-"),
            }
        )
    return pd.DataFrame(rows)


def _build_operation_history_dataframe(operations):
    rows = []
    for operation in operations:
        rows.append(
            {
                "Created": _format_created_at(operation.get("created_at")),
                "Operation": _format_audit_label(operation.get("operation_type")),
                "Target": operation.get("target_table") or "-",
                "Source": operation.get("source_table") or "-",
                "Columns": _format_operation_columns(operation.get("source_columns")),
                "Status": _format_audit_label(operation.get("status")),
                "Details": operation.get("details") or "-",
            }
        )
    return pd.DataFrame(rows)


def render_database_model_help():
    st.info(
        "A ChemVault SQL Database is a local .db file stored in SQL/. "
        "The main table is the base dataset. Refine creates derived tables, "
        "Curate may enrich the active table, and Export downloads the active "
        "table or an optional filtered subgroup."
    )


def render_table_manager_actions(database_id, profiles):
    deletable_tables = [profile["table"] for profile in profiles if profile["table"] != "main"]
    confirmation_key = (
        "table_manager_delete_confirmation_"
        f"{st.session_state.get('table_manager_delete_nonce', 0)}"
    )

    with st.expander("Manage tables", expanded=False):
        st.caption("Delete derived, temporary, or failed test tables from the active database.")
        if len(deletable_tables) == 0:
            st.info("No deletable derived tables are available.")
            return

        table_to_delete = st.selectbox(
            "Table to delete",
            deletable_tables,
            key="table_manager_delete_select",
        )
        confirmation = st.text_input(
            "Type DELETE to confirm",
            key=confirmation_key,
        )
        delete_ready = confirmation == "DELETE"

        if st.button(
            "Delete selected table",
            key="table_manager_delete_button",
            disabled=not delete_ready,
        ):
            conn = get_connection(database_id)
            try:
                delete_user_table(conn, table_to_delete)
                st.session_state["table_manager_delete_nonce"] = (
                    st.session_state.get("table_manager_delete_nonce", 0) + 1
                )
                st.rerun()
            except ValueError as e:
                st.error(str(e))


def render_operation_history(db_path):
    operations = get_operation_log(db_path)

    st.markdown("#### Operation history")
    st.caption("Review recorded database events such as builds, derived tables, and table cleanup.")
    if len(operations) == 0:
        st.info("No operations have been recorded for this database yet.")
        return

    st.dataframe(
        _build_operation_history_dataframe(operations),
        hide_index=True,
        use_container_width=True,
    )


def _format_activity_option_list(values):
    if not values:
        return "-"
    preview = ", ".join(str(value) for value in values[:8])
    if len(values) > 8:
        preview = f"{preview}, +{len(values) - 8} more"
    return preview


def render_structured_activity_section(connection):
    summary = get_activity_summary(connection)
    if summary is None:
        return

    st.markdown("#### Structured activity")
    st.caption("Inspect and export quantitative PubChem activity without changing molecular tables.")
    if summary["total_rows"] == 0:
        st.info("No structured activity rows are available yet.")
        return

    st.markdown(
        f"""
        <div style="
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(145px, 1fr));
            gap: 0.35rem 1rem;
            margin: 0.2rem 0 0.9rem 0;
            padding: 0.75rem 0;
            border-top: 1px solid var(--cv-border);
            border-bottom: 1px solid var(--cv-border);
        ">
            <div>
                <div style="font-size: 0.72rem; color: var(--cv-muted);">Activity rows</div>
                <div style="font-size: 0.93rem; color: var(--cv-text);">{summary["total_rows"]}</div>
            </div>
            <div>
                <div style="font-size: 0.72rem; color: var(--cv-muted);">CIDs with activity</div>
                <div style="font-size: 0.93rem; color: var(--cv-text);">{summary["unique_cids"]}</div>
            </div>
            <div>
                <div style="font-size: 0.72rem; color: var(--cv-muted);">AIDs with activity</div>
                <div style="font-size: 0.93rem; color: var(--cv-text);">{summary["unique_aids"]}</div>
            </div>
            <div>
                <div style="font-size: 0.72rem; color: var(--cv-muted);">Activity types</div>
                <div style="font-size: 0.93rem; color: var(--cv-text); overflow-wrap: anywhere;">
                    {html.escape(_format_activity_option_list(summary["activity_types"]))}
                </div>
            </div>
            <div>
                <div style="font-size: 0.72rem; color: var(--cv-muted);">Outcomes</div>
                <div style="font-size: 0.93rem; color: var(--cv-text); overflow-wrap: anywhere;">
                    {html.escape(_format_activity_option_list(summary["outcomes"]))}
                </div>
            </div>
            <div>
                <div style="font-size: 0.72rem; color: var(--cv-muted);">Units</div>
                <div style="font-size: 0.93rem; color: var(--cv-text); overflow-wrap: anywhere;">
                    {html.escape(_format_activity_option_list(summary["units"]))}
                </div>
            </div>
            <div>
                <div style="font-size: 0.72rem; color: var(--cv-muted);">Source columns</div>
                <div style="font-size: 0.93rem; color: var(--cv-text); overflow-wrap: anywhere;">
                    {html.escape(_format_activity_option_list(summary["source_columns"]))}
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.expander("Filter structured activity", expanded=False):
        col_a, col_b = st.columns(2)
        with col_a:
            selected_types = st.multiselect(
                "Activity type",
                summary["activity_types"],
                key="activity_filter_type",
            )
            selected_units = st.multiselect(
                "Unit",
                summary["units"],
                key="activity_filter_unit",
            )
        with col_b:
            selected_outcomes = st.multiselect(
                "Outcome",
                summary["outcomes"],
                key="activity_filter_outcome",
            )
            selected_aids = st.multiselect(
                "AID",
                summary["aids"],
                key="activity_filter_aid",
            )

        value_range = None
        if len(selected_types) == 1 and len(selected_units) == 1:
            value_stats = get_activity_value_stats(
                connection,
                activity_types=selected_types,
                outcomes=selected_outcomes,
                units=selected_units,
                aids=selected_aids,
            )
            if value_stats is None or value_stats["total_rows"] == 0:
                st.caption("No activity values match the selected categorical filters.")
            elif value_stats["min_value"] is not None and value_stats["max_value"] is not None:
                st.caption(f"Activity value range for {selected_types[0]} ({selected_units[0]})")
                if value_stats["qualified_rows"] > 0:
                    st.warning(
                        "Some values are qualified by > or <; numeric filtering uses "
                        "the recorded numeric threshold."
                    )
                col_min, col_max = st.columns(2)
                with col_min:
                    min_filter = st.number_input(
                        "Min activity value",
                        min_value=float(value_stats["min_value"]),
                        max_value=float(value_stats["max_value"]),
                        value=float(value_stats["min_value"]),
                        format="%.6g",
                        key="activity_filter_min_value",
                    )
                with col_max:
                    max_filter = st.number_input(
                        "Max activity value",
                        min_value=float(value_stats["min_value"]),
                        max_value=float(value_stats["max_value"]),
                        value=float(value_stats["max_value"]),
                        format="%.6g",
                        key="activity_filter_max_value",
                    )
                value_range = (min(min_filter, max_filter), max(min_filter, max_filter))
        else:
            st.caption(
                "Select exactly one activity type and one unit to enable numeric range filtering."
            )

    filter_kwargs = {
        "activity_types": selected_types,
        "outcomes": selected_outcomes,
        "units": selected_units,
        "aids": selected_aids,
        "value_range": value_range,
    }
    filtered_count = get_activity_row_count(connection, **filter_kwargs)
    preview_rows = get_activity_rows(
        connection,
        **filter_kwargs,
        limit=100,
    )
    preview_df = pd.DataFrame(preview_rows, columns=ACTIVITY_EXPORT_COLUMNS)
    export_csv = get_activity_csv_bytes(connection, **filter_kwargs)
    if filtered_count > 100:
        st.caption(
            f"Showing first 100 of {filtered_count} filtered activity rows. "
            "Download CSV to get the full filtered table."
        )
    else:
        st.caption(f"Showing {filtered_count} filtered activity row{'s' if filtered_count != 1 else ''}.")
    st.dataframe(preview_df, hide_index=True, use_container_width=True)
    st.download_button(
        "Download structured activity CSV",
        data=export_csv,
        file_name="chemvault_structured_activity.csv",
        mime="text/csv",
        disabled=filtered_count == 0,
        key="download_structured_activity_csv",
    )


def render_table_manager_card(container):
    with container:
        st.subheader("Table Manager")
        st.caption("Review tables, provenance, operation history, and cleanup options.")
        if st.session_state[DATABASE_ID] == "":
            st.info("Select or create a database to review its tables.")
            return

        database_id = st.session_state[DATABASE_ID]
        current_table = st.session_state.get(CURRENT_TABLE, "")
        db_path = Path("SQL") / f"{database_id}.db"

        try:
            profiles = get_user_table_profiles(db_path)
            schema = get_database_schema(db_path)
        except FileNotFoundError as e:
            st.warning(str(e))
            return

        if len(profiles) == 0:
            st.info("No tables were found in the active database.")
            return

        render_database_model_help()
        st.markdown("#### Tables")
        st.caption("Review table provenance, size, and inferred status before choosing what to use next.")
        st.dataframe(
            _build_table_manager_dataframe(profiles),
            hide_index=True,
            use_container_width=True,
        )
        render_table_manager_actions(database_id, profiles)
        render_operation_history(db_path)
        with sqlite3.connect(db_path) as activity_conn:
            render_structured_activity_section(activity_conn)

        active_schema = next(
            (table for table in schema if table["table"] == current_table),
            None,
        )
        if active_schema is None or len(active_schema["columns"]) == 0:
            st.info("No schema information was found for the active table.")
            return

        st.markdown("#### Active table schema")
        st.dataframe(
            pd.DataFrame(active_schema["columns"])[
                ["name", "data_type", "primary_key", "not_null", "default_value"]
            ],
            hide_index=True,
        )


def render_database_card(container):
    if st.session_state[DATABASE_ID] == "":
        container.subheader("Database")
        container.caption("Create or select the active molecular database.")
        container.text_input(
            label="SQL Database name",
            value=st.session_state[DATABASE_ID],
            key=INPUT_DATABASE_ID,
            on_change=set_database_id,
            disabled=st.session_state[SET_TEXT_INPUT_LOCKED],
        )
        dbs = [file_name.replace(".db", "") for file_name in os.listdir("SQL")]
        container.selectbox(
            "Or select an existing SQL database",
            dbs,
            key=EXISTING_DB_SELECT,
            on_change=load_existing_database,
        )
        return

    update_headers()
    container.subheader("Database")
    container.caption("Active table and row summary.")
    table_options = st.session_state.get(ALL_TABLES, [])
    if len(table_options) == 0:
        container.warning("The database does not contain tables.")
        return

    if st.session_state.get(CURRENT_TABLE, "") not in table_options:
        st.session_state[CURRENT_TABLE] = table_options[0]
    conn = get_connection(st.session_state[DATABASE_ID])
    row_count = count_rows(conn)
    if len(st.session_state.get(HEADERS, [])) > 0:
        if st.session_state.get(GROUP_COUNT_COLUMN, "") not in st.session_state[HEADERS]:
            st.session_state[GROUP_COUNT_COLUMN] = st.session_state[HEADERS][0]
    group_count = count_rows_group_by(conn)
    render_database_metrics(
        container,
        st.session_state[DATABASE_ID],
        st.session_state[CURRENT_TABLE],
        row_count,
        group_count,
    )
    render_protein_traceability_summary(container, conn)
    container.markdown("#### Table controls")
    container.selectbox(
        "Select table",
        table_options,
        key=CURRENT_TABLE,
        on_change=update_headers,
    )
    if len(st.session_state.get(HEADERS, [])) > 0:
        container.selectbox(
            "Count unique groups by",
            st.session_state[HEADERS],
            key=GROUP_COUNT_COLUMN,
        )


def render_columns_card(container):
    with container:
        st.subheader("Columns")
        st.caption("Select columns to preview, refine, curate, or export.")
        options = st.session_state[HEADERS]
        if len(options) == 0:
            st.info("No columns are available in the current table.")
            return

        st.pills(
            "Headers",
            options,
            selection_mode="multi",
            key=SELECTED_HEADERS,
            label_visibility="collapsed",
        )

        selected_count = len(st.session_state[SELECTED_HEADERS])
        if selected_count == 0:
            st.info("Select one or more columns to preview data and enable downstream actions.")
            return

        selected_columns = ", ".join(st.session_state[SELECTED_HEADERS])
        st.markdown(
            f"**{selected_count} column{'s' if selected_count != 1 else ''} selected:** "
            f"{selected_columns}"
        )
        st.markdown("#### Selected columns preview")
        st.dataframe(build_preview_table(), hide_index=True)


def _can_cast_value(value, target_type):
    if value is None or str(value).strip() == "":
        return True

    text = str(value).strip()
    try:
        match target_type:
            case "INTEGER":
                int(text)
            case "REAL":
                return math.isfinite(float(text))
            case _:
                return True
    except ValueError:
        return False
    return True


def _find_incompatible_type_values(connection, table, column, target_type, limit=5):
    if target_type not in {"INTEGER", "REAL"}:
        return []

    cursor = connection.cursor()
    cursor.execute(f"""
        SELECT DISTINCT {quote_identifier(column)}
        FROM {quote_identifier(table)}
        WHERE {quote_identifier(column)} IS NOT NULL
    """)

    incompatible = []
    for row in cursor.fetchall():
        value = row[0]
        if not _can_cast_value(value, target_type):
            incompatible.append(value)
            if len(incompatible) >= limit:
                break
    return incompatible


def _is_identifier_like_column(column):
    normalized = str(column).strip().lower().replace("_", "").replace("-", "").replace(" ", "")
    identifier_tokens = {
        "id",
        "ids",
        "identifier",
        "identifiers",
        "cid",
        "cids",
        "pubchemcid",
        "pubchemcids",
        "compoundcid",
        "compoundcids",
        "chembl",
        "chemblid",
        "chemblids",
        "coconut",
        "coconutid",
        "coconutids",
    }
    return normalized in identifier_tokens or normalized.endswith("id") or normalized.endswith("ids")


def render_table_maintenance_card(container):
    with container:
        st.subheader("Table Maintenance")
        st.caption("Inspect schema and apply advanced type changes for the active table.")
        if st.session_state[DATABASE_ID] == "" or len(st.session_state[HEADERS]) == 0:
            st.info("Select a database with columns to view additional information.")
            return

        conn = get_connection(st.session_state[DATABASE_ID])
        cursor = conn.cursor()
        cursor.execute(f"PRAGMA table_info({quote_identifier(st.session_state[CURRENT_TABLE])})")
        columns_info = cursor.fetchall()
        if not columns_info:
            st.markdown("No column type information was found.")
            return

        headers_types_df = pd.DataFrame(
            [(col[1], col[2]) for col in columns_info],
            columns=["Column", "Data type"],
        )
        st.markdown("Current schema for the active table.")
        st.dataframe(headers_types_df, hide_index=True)

        with st.expander("Advanced: change column type", expanded=False):
            st.caption("This updates the SQLite column type for the selected column.")
            st.warning(
                "Use this only when you are sure the selected values can be converted safely."
            )
            col_to_change = st.selectbox(
                "Select column",
                [col[1] for col in columns_info],
                key="col_to_change_select",
            )
            new_type = st.selectbox(
                "New type",
                ["TEXT", "INTEGER", "REAL"],
                key="new_col_type_select",
            )

            if st.button("Apply column type change"):
                try:
                    table_name = st.session_state[CURRENT_TABLE]
                    if _is_identifier_like_column(col_to_change) and new_type != "TEXT":
                        st.error(
                            f"Column '{col_to_change}' looks like an identifier. "
                            "Keep identifier-like columns as TEXT to preserve exact values."
                        )
                        return

                    incompatible_values = _find_incompatible_type_values(
                        conn,
                        table_name,
                        col_to_change,
                        new_type,
                    )
                    if incompatible_values:
                        examples = ", ".join(str(value) for value in incompatible_values)
                        st.error(
                            f"Column '{col_to_change}' cannot be safely converted to {new_type}. "
                            f"Non-numeric examples: {examples}"
                        )
                        return

                    temp_col = f"{col_to_change}_new"
                    cursor.execute(
                        f"ALTER TABLE {quote_identifier(table_name)} "
                        f"ADD COLUMN {quote_identifier(temp_col)} {new_type}"
                    )
                    cursor.execute(
                        f"UPDATE {quote_identifier(table_name)} "
                        f"SET {quote_identifier(temp_col)} = "
                        f"CAST({quote_identifier(col_to_change)} AS {new_type})"
                    )
                    cursor.execute(
                        f"ALTER TABLE {quote_identifier(table_name)} "
                        f"DROP COLUMN {quote_identifier(col_to_change)}"
                    )
                    cursor.execute(
                        f"ALTER TABLE {quote_identifier(table_name)} "
                        f"RENAME COLUMN {quote_identifier(temp_col)} TO {quote_identifier(col_to_change)}"
                    )
                    conn.commit()
                    st.success(f"Column '{col_to_change}' changed to {new_type}")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error changing type: {e}")


def render_footer():
    st.markdown(
        """
        <footer style="
            margin-top: 3rem;
            padding-top: 1rem;
            border-top: 1px solid var(--cv-border);
            text-align: center;
            color: var(--cv-muted);
            font-size: 0.85rem;
            line-height: 1.6;
        ">
            <div>D.R. © ChemVault 2026</div>
            <div>
                Developed by the
                <a href="https://nanobiostructuresrg.github.io/" style="color: var(--cv-link);">
                    Nano]°[Biostructures RG
                </a>
                at Tecnológico de Monterrey.
            </div>
        </footer>
        """,
        unsafe_allow_html=True,
    )
