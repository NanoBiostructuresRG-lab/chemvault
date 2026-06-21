# SPDX-License-Identifier: LGPL-3.0-or-later
import streamlit as st
import numpy as np
import os
from PIL import Image
from services.database import (
    update_headers,
)
from services.selection import (
    get_active_selected_headers,
    sync_selected_headers,
)
from services.sql_utils import (
    is_valid_table_name,
    quote_identifier,
)
from state_keys import (
    CURRENT_TABLE,
    CUSTOM_QUERY,
    DATABASE_ID,
    GROUP_BY_COLUMN,
    HEADERS,
    NEW_TABLE_NAME,
    ORDER_BY_COLUMN,
    ORDER_DIRECTION,
    TYPE_OF_FILTER,
    WHERE_COLUMN,
    WHERE_CONDITION,
)
from ui.dialogs import select_proteins
from ui.main_page import (
    create_main_layout,
    render_app_identity,
    render_columns_card,
    render_database_card,
    render_footer,
    render_table_information_card,
)
from ui.sidebar import render_sidebar
from ui.session_state import initialize_session_state
from ui.theme import apply_global_theme


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

apply_global_theme()

# Keep shared table state synchronized before rendering the sidebar.
if st.session_state.get(DATABASE_ID, "") != "":
    update_headers()
else:
    sync_selected_headers()


def clear_depurado_preview():
    st.session_state[CUSTOM_QUERY] = ""


def construir_linea_query():
    new_table_name = st.session_state.get(NEW_TABLE_NAME, "").strip()
    selected_headers = get_active_selected_headers()
    current_table = st.session_state.get(CURRENT_TABLE, "")

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
    match st.session_state.get(TYPE_OF_FILTER, "None"):
        case "None":
            pass
        case "GROUP BY":
            group_col = st.session_state.get(GROUP_BY_COLUMN, "")
            if group_col not in selected_headers:
                raise ValueError("The GROUP BY column must be one of the selected columns.")
            filter_clause = f"GROUP BY {quote_identifier(group_col)}"
        case "WHERE":
            where_col = st.session_state.get(WHERE_COLUMN, "")
            condition = st.session_state.get(WHERE_CONDITION, "").strip()
            if where_col not in st.session_state.get(HEADERS, []):
                raise ValueError("Select a valid column for WHERE.")
            if condition == "":
                raise ValueError("Enter a WHERE condition.")
            filter_clause = f"WHERE {quote_identifier(where_col)} {condition}"
        case "ORDER BY":
            order_col = st.session_state.get(ORDER_BY_COLUMN, "")
            direction = st.session_state.get(ORDER_DIRECTION, "ASC")
            if order_col not in selected_headers:
                raise ValueError("The ORDER BY column must be one of the selected columns.")
            filter_clause = f"ORDER BY {quote_identifier(order_col)} {direction}"
    return base_query + filter_clause

render_sidebar(select_proteins, clear_depurado_preview, construir_linea_query)

container0, container1, container2, container3 = create_main_layout()
render_app_identity(container0)
render_database_card(container1)
render_columns_card(container2)
render_table_information_card(container3)
render_footer()
