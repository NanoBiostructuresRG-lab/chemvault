# SPDX-License-Identifier: LGPL-3.0-or-later
import pandas as pd
import streamlit as st

from services.database import get_connection
from services.sql_utils import quote_identifier
from state_keys import CURRENT_TABLE, DATABASE_ID, HEADERS, SELECTED_HEADERS


def get_active_selected_headers():
    headers = st.session_state.get(HEADERS, [])
    selected = st.session_state.get(SELECTED_HEADERS, [])
    return [col for col in selected if col in headers]


def sync_selected_headers():
    st.session_state[SELECTED_HEADERS] = get_active_selected_headers()


def build_preview_table():
    if st.session_state.get(DATABASE_ID, "") == "" or st.session_state.get(CURRENT_TABLE, "") == "":
        return pd.DataFrame()

    selected_headers = get_active_selected_headers()
    if len(selected_headers) == 0:
        return pd.DataFrame()

    conn = get_connection(st.session_state[DATABASE_ID])
    table = st.session_state[CURRENT_TABLE]
    cols = ", ".join(quote_identifier(col) for col in selected_headers)
    query = f"SELECT {cols} FROM {quote_identifier(table)} LIMIT 10"
    return pd.read_sql_query(query, conn)


def get_selected_columns():
    if st.session_state.get(DATABASE_ID, "") == "" or st.session_state.get(CURRENT_TABLE, "") == "":
        return pd.DataFrame()

    selected_headers = get_active_selected_headers()
    if len(selected_headers) == 0:
        return pd.DataFrame()

    conn = get_connection(st.session_state[DATABASE_ID])
    table = st.session_state[CURRENT_TABLE]
    cols = ", ".join(quote_identifier(col) for col in selected_headers)
    query = f"SELECT {cols} FROM {quote_identifier(table)}"
    return pd.read_sql_query(query, conn)
