# SPDX-License-Identifier: LGPL-3.0-or-later
import csv
import io
import streamlit as st

from services.database import get_connection
from services.sql_utils import quote_identifier
from state_keys import CURRENT_TABLE, DATABASE_ID, HEADERS, SELECTED_HEADERS


def _get_active_selected_headers():
    headers = st.session_state.get(HEADERS, [])
    selected = st.session_state.get(SELECTED_HEADERS, [])
    return [col for col in selected if col in headers]


EXPORT_FETCH_SIZE = 5000


def _empty_csv_bytes():
    return b"\n"


def _query_to_csv_bytes(connection, query, params=None, fetch_size=EXPORT_FETCH_SIZE):
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    cursor = connection.cursor()
    cursor.execute(query, params or [])
    writer.writerow([description[0] for description in cursor.description])

    while True:
        rows = cursor.fetchmany(fetch_size)
        if not rows:
            break
        writer.writerows(rows)

    return buffer.getvalue().encode("utf-8")


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

    return _query_to_csv_bytes(conn, query)


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

    return _query_to_csv_bytes(conn, query, params=[f"%{codigo_buscar}%"])
