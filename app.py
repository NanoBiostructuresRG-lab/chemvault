import streamlit as st
import pandas as pd
import numpy as np
import os
from PIL import Image
from services.builders import build_from_proteins
from services.database import (
    count_rows,
    count_rows_group_by,
    get_connection,
    load_existing_database,
    set_database_id,
    update_headers,
)
from services.selection import (
    build_preview_table,
    get_active_selected_headers,
    sync_selected_headers,
)
from services.sql_utils import (
    is_valid_table_name,
    quote_identifier,
)
from ui.main_page import (
    render_app_identity,
    render_database_metrics,
    render_footer,
)
from ui.sidebar import render_sidebar
from ui.session_state import initialize_session_state


@st.dialog("Select Proteins", dismissible=False)
def select_proteins():
    st.write("Search CIDs by BioAssays, using a protein as target.")
    st.text_input(label="Protein", key="input_protein", value="P34971")
    if st.button("Add to selection"):
        st.session_state["selected_proteins"].append(st.session_state["input_protein"])
        st.markdown(f"Selected proteins: {st.session_state['selected_proteins']}.")
    if st.button("Confirm selection"):
        if len(st.session_state["selected_proteins"]) == 0:
            st.toast("Select at least one protein")
            print("Select at least one protein")
        elif st.session_state["database_id"] == "":
            st.toast("First, enter a name for your SQL database")
            print("First, enter a name for your SQL database")
        else:
            progreso = st.progress(0)
            st.toast(f"Building database with proteins: {st.session_state['selected_proteins']}")
            build_from_proteins(progreso)
            update_headers()
        st.rerun()
    if st.button("Cancel"):
        st.session_state["selected_proteins"] = []
        st.rerun()


def verify_directories():
    if not os.path.exists("SQL"):
        os.makedirs("SQL")
    if not os.path.exists("artifacts"):
        os.makedirs("artifacts")
    else:
        files = os.listdir("artifacts")
        for file_name in files:
            file_path = os.path.join("artifacts", file_name)
            if os.path.isfile(file_path):
                try:
                    os.remove(file_path)
                except PermissionError:
                    pass
    if not os.path.exists("tempFilesChamanp"):
        os.makedirs("tempFilesChamanp")
    if not os.path.exists("tempFilesHarmonsile"):
        os.makedirs("tempFilesHarmonsile")


initialize_session_state(st.session_state, verify_directories)

logo = Image.open("assets/logo.jpeg")

st.set_page_config(
    page_title="ChemVault",
    page_icon=logo,
    layout="wide"
)

st.markdown(
    """
    <style>
        :root {
            --cv-bg: #ffffff;
            --cv-panel-bg: #ffffff;
            --cv-sidebar-bg: #f8fafc;
            --cv-muted-bg: #f3f4f6;
            --cv-border: #d6dbe1;
            --cv-border-strong: rgba(71, 85, 105, 0.24);
            --cv-text: #111827;
            --cv-heading: #1f2937;
            --cv-muted: #6b7280;
            --cv-link: #4b5563;
            --cv-control-border: #64748b;
            --cv-accent: #b45309;
            --cv-accent-text: #78350f;
            --cv-accent-bg: #fff7ed;
            --cv-code-bg: #111827;
            --cv-code-text: #f9fafb;
            --cv-shadow-soft: 0 8px 24px rgba(15, 23, 42, 0.04);
            --cv-radius: 0.55rem;
        }

        section[data-testid="stSidebar"] {
            background-color: var(--cv-sidebar-bg);
        }

        section[data-testid="stSidebar"] [data-testid="stVerticalBlock"] {
            gap: 0.8rem;
        }

        section[data-testid="stSidebar"] h1,
        section[data-testid="stSidebar"] h2,
        section[data-testid="stSidebar"] h3 {
            color: var(--cv-heading);
        }

        section[data-testid="stSidebar"] h2,
        section[data-testid="stSidebar"] h3 {
            margin-bottom: 0.15rem;
        }

        section[data-testid="stSidebar"] [data-testid="stCaptionContainer"] {
            color: var(--cv-muted);
            line-height: 1.35;
        }

        section[data-testid="stSidebar"] [data-testid="stVerticalBlockBorderWrapper"] {
            background-color: var(--cv-panel-bg);
            border-color: var(--cv-border-strong);
            box-shadow: var(--cv-shadow-soft);
            border-radius: var(--cv-radius);
        }

        section[data-testid="stSidebar"] [data-testid="stVerticalBlockBorderWrapper"] [data-testid="stVerticalBlock"] {
            gap: 0.55rem;
        }

        section[data-testid="stSidebar"] div[data-testid="stButton"],
        section[data-testid="stSidebar"] div[data-testid="stDownloadButton"] {
            width: 100%;
        }

        section[data-testid="stSidebar"] div[data-testid="stButton"] > button,
        section[data-testid="stSidebar"] div[data-testid="stDownloadButton"] > button {
            width: 100%;
            justify-content: center;
            border-color: var(--cv-control-border);
            color: var(--cv-heading);
            background-color: var(--cv-panel-bg);
            min-height: 2.35rem;
        }

        section[data-testid="stSidebar"] div[data-testid="stButton"] > button:hover,
        section[data-testid="stSidebar"] div[data-testid="stDownloadButton"] > button:hover {
            border-color: var(--cv-accent);
            color: var(--cv-accent-text);
            background-color: var(--cv-accent-bg);
        }
    </style>
    """,
    unsafe_allow_html=True,
)

# Keep shared table state synchronized before rendering the sidebar.
if st.session_state.get("database_id", "") != "":
    update_headers()
else:
    sync_selected_headers()


def clear_depurado_preview():
    st.session_state["custom_query"] = ""


def construir_linea_query():
    new_table_name = st.session_state.get("new_table_name", "").strip()
    selected_headers = get_active_selected_headers()
    current_table = st.session_state.get("current_table", "")

    if not is_valid_table_name(new_table_name):
        raise ValueError(
            "Enter a valid table name: use letters, numbers, and underscores; "
            "do not start with a number."
        )
    if current_table == "":
        raise ValueError("Select a source table before creating a new table.")
    if len(selected_headers) == 0:
        raise ValueError("Select at least one column before creating a new table.")

    cols = ", ".join(quote_identifier(col) for col in selected_headers)
    base_query = f"""
    CREATE TABLE {quote_identifier(new_table_name)} AS
    SELECT {cols} FROM {quote_identifier(current_table)}
    """
    filter_clause = ""
    match st.session_state.get("type_of_filter", "None"):
        case "None":
            pass
        case "GROUP BY":
            group_col = st.session_state.get("group_by_column", "")
            if group_col not in selected_headers:
                raise ValueError("The GROUP BY column must be one of the selected columns.")
            filter_clause = f"GROUP BY {quote_identifier(group_col)}"
        case "WHERE":
            where_col = st.session_state.get("where_column", "")
            condition = st.session_state.get("where_condition", "").strip()
            if where_col not in st.session_state.get("headers", []):
                raise ValueError("Select a valid column for WHERE.")
            if condition == "":
                raise ValueError("Enter a WHERE condition.")
            filter_clause = f"WHERE {quote_identifier(where_col)} {condition}"
        case "ORDER BY":
            order_col = st.session_state.get("order_by_column", "")
            direction = st.session_state.get("order_direction", "ASC")
            if order_col not in selected_headers:
                raise ValueError("The ORDER BY column must be one of the selected columns.")
            filter_clause = f"ORDER BY {quote_identifier(order_col)} {direction}"
    return base_query + filter_clause

render_sidebar(select_proteins, clear_depurado_preview, construir_linea_query)

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
render_app_identity(container0)

if st.session_state["database_id"] == "":
    container1.subheader("Database")
    container1.caption("Create or select the active molecular database.")
    container1.text_input(
        label="SQL Database name",
        value=st.session_state["database_id"],
        key="input_database_id",
        on_change=set_database_id,
        disabled=st.session_state["set_text_input_locked"]
    )
    files = os.listdir("SQL")
    dbs = []
    for file_name in files:
        dbs.append(file_name.replace(".db", ""))
    container1.selectbox(
        "Or select an existing SQL database",
        dbs,
        key="existing_db_select",
        on_change=load_existing_database,
    )
else:
    update_headers()
    container1.subheader("Database")
    container1.caption("Active table and row summary.")
    table_options = st.session_state.get("all_tables", [])
    if len(table_options) > 0:
        if st.session_state.get("current_table", "") not in table_options:
            st.session_state["current_table"] = table_options[0]
        row_count = count_rows(get_connection(st.session_state["database_id"]))
        if len(st.session_state.get("headers", [])) > 0:
            if st.session_state.get("grupo_a_contar", "") not in st.session_state["headers"]:
                st.session_state["grupo_a_contar"] = st.session_state["headers"][0]
        group_count = count_rows_group_by(get_connection(st.session_state["database_id"]))
        render_database_metrics(
            container1,
            st.session_state["database_id"],
            st.session_state["current_table"],
            row_count,
            group_count,
        )
        container1.markdown("#### Table controls")
        container1.selectbox(
            "Select table",
            table_options,
            key="current_table",
            on_change=update_headers,
        )
        if len(st.session_state.get("headers", [])) > 0:
            container1.selectbox(
                "Count unique groups by",
                st.session_state["headers"],
                key="grupo_a_contar",
            )
    else:
        container1.warning("The database does not contain tables.")

with container2:
    st.subheader("Columns")
    st.caption("Select columns to preview, refine, curate, or export.")
    options = st.session_state["headers"]
    if len(options) > 0:
        st.pills(
            "Headers",
            options,
            selection_mode="multi",
            key="selected_headers",
            label_visibility="collapsed",
        )

        selected_count = len(st.session_state["selected_headers"])
        if selected_count > 0:
            selected_columns = ", ".join(st.session_state["selected_headers"])
            st.markdown(
                f"**{selected_count} column{'s' if selected_count != 1 else ''} selected:** "
                f"{selected_columns}"
            )
            st.markdown("#### Selected columns preview")
            st.dataframe(build_preview_table(), hide_index=True)
        else:
            st.info("Select one or more columns to preview data and enable downstream actions.")
    else:
        st.info("No columns are available in the current table.")


with container3:
    st.subheader("Table information")
    st.caption("Column types and maintenance tools for the active table.")
    if st.session_state["database_id"] != "" and len(st.session_state["headers"]) > 0:
        conn = get_connection(st.session_state["database_id"])
        cursor = conn.cursor()
        cursor.execute(f"PRAGMA table_info({quote_identifier(st.session_state['current_table'])})")
        columns_info = cursor.fetchall()
        if columns_info:
            headers_types_df = pd.DataFrame(
                [(col[1], col[2]) for col in columns_info],
                columns=["Column", "Data type"]
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
                            f"ALTER TABLE {st.session_state['current_table']} "
                            f"ADD COLUMN {col_to_change}_new {new_type}"
                        )
                        cursor.execute(
                            f"UPDATE {st.session_state['current_table']} "
                            f"SET {col_to_change}_new = CAST({col_to_change} AS {new_type})"
                        )
                        cursor.execute(
                            f"ALTER TABLE {st.session_state['current_table']} "
                            f"DROP COLUMN {col_to_change}"
                        )
                        cursor.execute(
                            f"ALTER TABLE {st.session_state['current_table']} "
                            f"RENAME COLUMN {col_to_change}_new TO {col_to_change}"
                        )
                        conn.commit()
                        st.success(f"Column '{col_to_change}' changed to {new_type}")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error changing type: {e}")
        else:
            st.markdown("No column type information was found.")
    else:
        st.info("Select a database with columns to view additional information.")

render_footer()
