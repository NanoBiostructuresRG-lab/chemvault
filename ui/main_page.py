import html
import os

import pandas as pd
import streamlit as st
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
    return container0, container1, container2, container3


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
    row_count = count_rows(get_connection(st.session_state[DATABASE_ID]))
    if len(st.session_state.get(HEADERS, [])) > 0:
        if st.session_state.get(GROUP_COUNT_COLUMN, "") not in st.session_state[HEADERS]:
            st.session_state[GROUP_COUNT_COLUMN] = st.session_state[HEADERS][0]
    group_count = count_rows_group_by(get_connection(st.session_state[DATABASE_ID]))
    render_database_metrics(
        container,
        st.session_state[DATABASE_ID],
        st.session_state[CURRENT_TABLE],
        row_count,
        group_count,
    )
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


def render_table_information_card(container):
    with container:
        st.subheader("Table information")
        st.caption("Column types and maintenance tools for the active table.")
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
                ["TEXT", "INTEGER", "REAL", "BLOB"],
                key="new_col_type_select",
            )

            if st.button("Apply column type change"):
                try:
                    cursor.execute(
                        f"ALTER TABLE {st.session_state[CURRENT_TABLE]} "
                        f"ADD COLUMN {col_to_change}_new {new_type}"
                    )
                    cursor.execute(
                        f"UPDATE {st.session_state[CURRENT_TABLE]} "
                        f"SET {col_to_change}_new = CAST({col_to_change} AS {new_type})"
                    )
                    cursor.execute(
                        f"ALTER TABLE {st.session_state[CURRENT_TABLE]} "
                        f"DROP COLUMN {col_to_change}"
                    )
                    cursor.execute(
                        f"ALTER TABLE {st.session_state[CURRENT_TABLE]} "
                        f"RENAME COLUMN {col_to_change}_new TO {col_to_change}"
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
