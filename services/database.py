# SPDX-License-Identifier: LGPL-3.0-or-later
import os

import streamlit as st

from services.database_core import get_connection
from services.db_audit import register_operation, register_table_metadata
from services.sql_utils import (
    ensure_main_table,
    get_tables_from_connection,
    quote_identifier,
    table_exists,
)
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


def _get_active_selected_headers():
    headers = st.session_state.get(HEADERS, [])
    selected = st.session_state.get(SELECTED_HEADERS, [])
    return [col for col in selected if col in headers]


def _sync_selected_headers():
    st.session_state[SELECTED_HEADERS] = _get_active_selected_headers()


def count_rows_group_by(connection):
    group_col = st.session_state.get(GROUP_COUNT_COLUMN, "")
    table = st.session_state.get(CURRENT_TABLE, "")
    if group_col == "" or table == "":
        return 0
    if group_col not in st.session_state.get(HEADERS, []):
        return 0
    cursor = connection.cursor()
    cursor.execute(f"""
        SELECT COUNT(*)
        FROM (
            SELECT {quote_identifier(group_col)}
            FROM {quote_identifier(table)}
            GROUP BY {quote_identifier(group_col)}
        )
    """)
    return cursor.fetchone()[0]


def count_rows(connection):
    table = st.session_state.get(CURRENT_TABLE, "")
    if table == "" or not table_exists(connection, table):
        return 0
    cursor = connection.cursor()
    cursor.execute(f"SELECT COUNT(*) FROM {quote_identifier(table)}")
    return cursor.fetchone()[0]


def set_database_id():
    db_name = st.session_state.get(INPUT_DATABASE_ID, "").strip()
    if db_name == "":
        st.toast("Enter a name for your SQL database")
        return
    db_exists = os.path.isfile(f"SQL/{db_name}.db")
    st.session_state[DATABASE_ID] = db_name
    st.session_state[SET_TEXT_INPUT_LOCKED] = True
    st.session_state[CURRENT_TABLE] = "main"
    st.session_state[SELECTED_HEADERS] = []
    conn = get_connection(st.session_state[DATABASE_ID])
    ensure_main_table(conn)
    register_table_metadata(
        conn,
        "main",
        role="base",
        origin="created_empty_database",
        created_by="set_database_id",
        notes="Initial ChemVault main table.",
    )
    if not db_exists:
        register_operation(
            conn,
            "database_created",
            target_table="main",
            created_by="set_database_id",
            details="Created a new ChemVault SQLite database.",
        )
    update_headers()
    st.toast(f"SQL Database set to {st.session_state[DATABASE_ID]}")


def load_existing_database():
    db_name = st.session_state.get(EXISTING_DB_SELECT, "")
    if db_name == "":
        return
    st.session_state[DATABASE_ID] = db_name
    st.session_state[SET_TEXT_INPUT_LOCKED] = True
    st.session_state[SELECTED_HEADERS] = []
    conn = get_connection(db_name)
    tables = get_tables_from_connection(conn)
    if not tables:
        ensure_main_table(conn)
        register_table_metadata(
            conn,
            "main",
            role="base",
            origin="created_empty_database",
            created_by="load_existing_database",
            notes="Initial ChemVault main table.",
        )
        tables = get_tables_from_connection(conn)
    st.session_state[CURRENT_TABLE] = "main" if "main" in tables else tables[0]
    update_headers()


def get_tables():
    if st.session_state.get(DATABASE_ID, "") == "":
        st.session_state[ALL_TABLES] = []
        return []
    db_path = f"SQL/{st.session_state[DATABASE_ID]}.db"
    if not os.path.isfile(db_path):
        st.session_state[ALL_TABLES] = []
        return []
    conn = get_connection(st.session_state[DATABASE_ID])
    tables = get_tables_from_connection(conn)
    st.session_state[ALL_TABLES] = tables
    return tables


def update_headers():
    if st.session_state.get(DATABASE_ID, "") == "":
        st.session_state[HEADERS] = []
        st.session_state[ALL_TABLES] = []
        st.session_state[CURRENT_TABLE] = ""
        st.session_state[SELECTED_HEADERS] = []
        return []

    conn = get_connection(st.session_state[DATABASE_ID])
    tables = get_tables_from_connection(conn)
    st.session_state[ALL_TABLES] = tables

    if not tables:
        st.session_state[HEADERS] = []
        st.session_state[CURRENT_TABLE] = ""
        st.session_state[SELECTED_HEADERS] = []
        return []

    if st.session_state.get(CURRENT_TABLE, "") not in tables:
        st.session_state[CURRENT_TABLE] = "main" if "main" in tables else tables[0]

    table = st.session_state[CURRENT_TABLE]
    cursor = conn.cursor()
    cursor.execute(f"PRAGMA table_info({quote_identifier(table)})")
    columns_info = cursor.fetchall()
    headers = [col[1] for col in columns_info]
    st.session_state[HEADERS] = headers
    _sync_selected_headers()
    return headers
