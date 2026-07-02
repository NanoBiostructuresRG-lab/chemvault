# SPDX-License-Identifier: LGPL-3.0-or-later
import os
from dataclasses import dataclass, replace

from services.database_core import get_connection
from services.db_audit import register_operation, register_table_metadata
from services.sql_utils import (
    ensure_main_table,
    get_tables_from_connection,
    quote_identifier,
    table_exists,
)


@dataclass(frozen=True)
class DatabaseState:
    database_id: str = ""
    current_table: str = ""
    headers: tuple[str, ...] = ()
    all_tables: tuple[str, ...] = ()
    selected_headers: tuple[str, ...] = ()
    input_locked: bool | None = None
    message: str = ""
    success: bool = True


def count_rows_group_by(connection, current_table, group_column, headers):
    if group_column == "" or current_table == "":
        return 0
    if group_column not in headers:
        return 0
    cursor = connection.cursor()
    cursor.execute(f"""
        SELECT COUNT(*)
        FROM (
            SELECT {quote_identifier(group_column)}
            FROM {quote_identifier(current_table)}
            GROUP BY {quote_identifier(group_column)}
        )
    """)
    return cursor.fetchone()[0]


def count_rows(connection, current_table):
    if current_table == "" or not table_exists(connection, current_table):
        return 0
    cursor = connection.cursor()
    cursor.execute(f"SELECT COUNT(*) FROM {quote_identifier(current_table)}")
    return cursor.fetchone()[0]


def set_database_id(input_database_id):
    db_name = input_database_id.strip()
    if db_name == "":
        return DatabaseState(
            message="Enter a name for your SQL database",
            success=False,
        )

    db_exists = os.path.isfile(f"SQL/{db_name}.db")
    conn = get_connection(db_name)
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

    state = update_headers(db_name, "main", [])
    return replace(
        state,
        input_locked=True,
        message=f"SQL Database set to {db_name}",
    )


def load_existing_database(existing_database):
    db_name = existing_database
    if db_name == "":
        return DatabaseState(success=False)

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

    current_table = "main" if "main" in tables else tables[0]
    state = update_headers(db_name, current_table, [])
    return replace(state, input_locked=True)


def get_tables(database_id):
    if database_id == "":
        return []
    db_path = f"SQL/{database_id}.db"
    if not os.path.isfile(db_path):
        return []
    conn = get_connection(database_id)
    return get_tables_from_connection(conn)


def update_headers(database_id, current_table="", selected_headers=()):
    if database_id == "":
        return DatabaseState()

    conn = get_connection(database_id)
    tables = get_tables_from_connection(conn)
    if not tables:
        return DatabaseState(database_id=database_id)

    if current_table not in tables:
        current_table = "main" if "main" in tables else tables[0]

    cursor = conn.cursor()
    cursor.execute(f"PRAGMA table_info({quote_identifier(current_table)})")
    columns_info = cursor.fetchall()
    headers = [col[1] for col in columns_info]
    active_selected_headers = [
        column
        for column in selected_headers
        if column in headers
    ]
    return DatabaseState(
        database_id=database_id,
        current_table=current_table,
        headers=tuple(headers),
        all_tables=tuple(tables),
        selected_headers=tuple(active_selected_headers),
    )
