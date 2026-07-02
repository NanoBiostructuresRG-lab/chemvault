# SPDX-License-Identifier: LGPL-3.0-or-later
import pandas as pd

from services.database_core import get_connection
from services.sql_utils import quote_identifier


def get_active_selected_headers(headers, selected_headers):
    return [col for col in selected_headers if col in headers]


def sync_selected_headers(headers, selected_headers):
    return get_active_selected_headers(headers, selected_headers)


def build_preview_table(database_id, current_table, headers, selected_headers):
    if database_id == "" or current_table == "":
        return pd.DataFrame()

    active_headers = get_active_selected_headers(headers, selected_headers)
    if len(active_headers) == 0:
        return pd.DataFrame()

    conn = get_connection(database_id)
    cols = ", ".join(quote_identifier(col) for col in active_headers)
    query = f"SELECT {cols} FROM {quote_identifier(current_table)} LIMIT 10"
    return pd.read_sql_query(query, conn)


def get_selected_columns(database_id, current_table, headers, selected_headers):
    if database_id == "" or current_table == "":
        return pd.DataFrame()

    active_headers = get_active_selected_headers(headers, selected_headers)
    if len(active_headers) == 0:
        return pd.DataFrame()

    conn = get_connection(database_id)
    cols = ", ".join(quote_identifier(col) for col in active_headers)
    query = f"SELECT {cols} FROM {quote_identifier(current_table)}"
    return pd.read_sql_query(query, conn)
