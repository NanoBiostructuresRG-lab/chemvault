import html

import streamlit as st

from services.builders import build_from_csv
from services.database import get_connection, update_headers
from services.sql_utils import table_exists
from state_keys import (
    CURRENT_TABLE,
    CUSTOM_QUERY,
    DATABASE_ID,
    DEPURADO_SUCCESS_MESSAGE,
    DEPURADO_SUCCESS_TABLE,
    GROUP_BY_COLUMN,
    HEADERS,
    NEW_TABLE_NAME,
    ORDER_BY_COLUMN,
    ORDER_DIRECTION,
    SELECTED_HEADERS,
    SET_TEXT_INPUT_LOCKED,
    TYPE_OF_FILTER,
    WHERE_COLUMN,
    WHERE_CONDITION,
)


def render_build_card(select_proteins_callback):
    with st.container(border=True):
        st.subheader("Build")
        st.caption("Start from proteins or upload a CSV dataset.")
        ### por proteina ###
        if st.button("Search Proteins"):
            select_proteins_callback()
        ### por csv ###
        uploaded_file = st.file_uploader("Upload CSV", type=["csv"])
        if uploaded_file != None:
                st.session_state[SET_TEXT_INPUT_LOCKED] = True
                db_name = uploaded_file.name.replace(".csv", "")
                st.session_state[DATABASE_ID] = db_name
                st.session_state[CURRENT_TABLE] = "main"
                build_from_csv(uploaded_file)
                update_headers()
                st.rerun()


def render_refine_card(clear_preview_callback, build_query_callback):
    with st.container(border=True):
        st.subheader("Refine")
        st.caption("Create derived tables from the active column selection.")
        st.text_input(label="New table name", key=NEW_TABLE_NAME, value="New_table", on_change=clear_preview_callback)
        if st.session_state.get(TYPE_OF_FILTER) == "Ninguno":
            st.session_state[TYPE_OF_FILTER] = "None"
        st.selectbox("Additional filter", ["None", "GROUP BY", "WHERE", "ORDER BY"], key=TYPE_OF_FILTER, on_change=clear_preview_callback)
        match st.session_state[TYPE_OF_FILTER]:
            case "None":
                pass
            case "GROUP BY":
                st.selectbox("Column to group", st.session_state[SELECTED_HEADERS], key=GROUP_BY_COLUMN, on_change=clear_preview_callback)
            case "WHERE":
                st.selectbox("Column to filter", st.session_state[HEADERS], key=WHERE_COLUMN, on_change=clear_preview_callback)
                st.text_input("Condition (example: > 100, = 'HarmonSmile', etc)", key=WHERE_CONDITION, on_change=clear_preview_callback)
            case "ORDER BY":
                st.selectbox("Column to sort", st.session_state[SELECTED_HEADERS], key=ORDER_BY_COLUMN, on_change=clear_preview_callback)
                st.selectbox("Sort direction", ["ASC", "DESC"], key=ORDER_DIRECTION, on_change=clear_preview_callback)
        if st.button("Preview SQL"):
            try:
                st.session_state[CUSTOM_QUERY] = build_query_callback()
            except ValueError as e:
                st.session_state[CUSTOM_QUERY] = ""
                st.error(str(e))
        if st.session_state.get(CUSTOM_QUERY, "") != "":
            compact_query = html.escape(" ".join(st.session_state[CUSTOM_QUERY].split()))
            st.markdown("**SQL preview**")
            st.markdown(
                f'''
                <div style="background-color:var(--cv-code-bg); color:var(--cv-code-text); padding:0.85rem 1rem;
                            border-radius:var(--cv-radius); font-family:monospace; font-size:0.9rem;
                            line-height:1.5; overflow-x:auto; margin-bottom:0.85rem;">
                    {compact_query}
                </div>
                ''',
                unsafe_allow_html=True,
            )

        if st.button("Create table from current selection"):
            conn = get_connection(st.session_state[DATABASE_ID])
            cursor = conn.cursor()
            try:
                query_to_run = build_query_callback()
                new_table_name = st.session_state[NEW_TABLE_NAME].strip()
                if table_exists(conn, new_table_name):
                    raise ValueError(f"Table '{new_table_name}' already exists. Use another name or delete it first.")
                cursor.execute(query_to_run)
                conn.commit()
                st.session_state[CURRENT_TABLE] = new_table_name
                st.session_state[SELECTED_HEADERS] = []
                st.session_state[CUSTOM_QUERY] = query_to_run
                update_headers()
                st.session_state[DEPURADO_SUCCESS_TABLE] = new_table_name
                st.session_state[DEPURADO_SUCCESS_MESSAGE] = f"Table '{new_table_name}' was created successfully."
                st.rerun()
            except Exception as e:
                conn.rollback()
                st.error(f"Could not create the table: {e}")

        created_table = st.session_state.get(DEPURADO_SUCCESS_TABLE, "")
        if created_table and created_table == st.session_state.get(CURRENT_TABLE, ""):
            st.success(st.session_state.get(DEPURADO_SUCCESS_MESSAGE, f"Table '{created_table}' was created successfully."))
