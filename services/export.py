# SPDX-License-Identifier: LGPL-3.0-or-later
import csv
import io

from services.database_core import get_connection
from services.selection import get_active_selected_headers
from services.sql_utils import quote_identifier


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


def export_table(database_id, current_table, headers, selected_headers):
    if database_id == "" or current_table == "":
        return _empty_csv_bytes()

    conn = get_connection(database_id)
    active_headers = get_active_selected_headers(headers, selected_headers)

    if len(active_headers) == 0:
        query = f"SELECT * FROM {quote_identifier(current_table)}"
    else:
        cols = ", ".join(quote_identifier(col) for col in active_headers)
        query = f"SELECT {cols} FROM {quote_identifier(current_table)}"

    return _query_to_csv_bytes(conn, query)


def export_table_by_sub_grupo(
    codigo_buscar: str,
    columna_filtro: str,
    database_id,
    current_table,
    headers,
    selected_headers,
):
    if database_id == "" or current_table == "":
        return _empty_csv_bytes()
    if columna_filtro not in headers:
        return _empty_csv_bytes()

    conn = get_connection(database_id)
    active_headers = get_active_selected_headers(headers, selected_headers)

    if len(active_headers) == 0:
        cols = "*"
    else:
        cols = ", ".join(quote_identifier(col) for col in active_headers)

    query = f"""
        SELECT {cols}
        FROM {quote_identifier(current_table)}
        WHERE {quote_identifier(columna_filtro)} LIKE ?
    """

    return _query_to_csv_bytes(conn, query, params=[f"%{codigo_buscar}%"])
