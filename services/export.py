# SPDX-License-Identifier: LGPL-3.0-or-later
import pandas as pd
import streamlit as st

from services.database import get_connection
from services.sql_utils import quote_identifier
from state_keys import CURRENT_TABLE, DATABASE_ID, HEADERS, SELECTED_HEADERS


def _get_active_selected_headers():
    headers = st.session_state.get(HEADERS, [])
    selected = st.session_state.get(SELECTED_HEADERS, [])
    return [col for col in selected if col in headers]


def _empty_csv_bytes():
    return pd.DataFrame().to_csv(index=False).encode("utf-8")


def export_table():
    if st.session_state.get(DATABASE_ID, "") == "" or st.session_state.get(CURRENT_TABLE, "") == "":
        return _empty_csv_bytes()

    conn = get_connection(st.session_state[DATABASE_ID])
    table = st.session_state[CURRENT_TABLE]
    selected_headers = _get_active_selected_headers()

    if len(selected_headers) == 0:
        query = f"SELECT * FROM {quote_identifier(table)}"
    else:
        cols = ", ".join(quote_identifier(col) for col in selected_headers)
        query = f"SELECT {cols} FROM {quote_identifier(table)}"

    df = pd.read_sql_query(query, conn)
    return df.to_csv(index=False).encode("utf-8")


def export_table_by_sub_grupo(codigo_buscar: str, columna_filtro: str):
    if st.session_state.get(DATABASE_ID, "") == "" or st.session_state.get(CURRENT_TABLE, "") == "":
        return _empty_csv_bytes()
    if columna_filtro not in st.session_state.get(HEADERS, []):
        return _empty_csv_bytes()

    conn = get_connection(st.session_state[DATABASE_ID])
    table = st.session_state[CURRENT_TABLE]
    selected_headers = _get_active_selected_headers()

    if len(selected_headers) == 0:
        cols = "*"
    else:
        cols = ", ".join(quote_identifier(col) for col in selected_headers)

    query = f"""
        SELECT {cols}
        FROM {quote_identifier(table)}
        WHERE {quote_identifier(columna_filtro)} LIKE ?
    """

    df = pd.read_sql_query(query, conn, params=[f"%{codigo_buscar}%"])
    return df.to_csv(index=False).encode("utf-8")
