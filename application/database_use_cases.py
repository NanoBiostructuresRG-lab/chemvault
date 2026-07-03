# SPDX-License-Identifier: LGPL-3.0-or-later
"""Application use cases for database selection and inspection."""
from dataclasses import dataclass
from pathlib import Path

from services import database as database_service
from services import db_audit
from services.database import DatabaseState


@dataclass(frozen=True)
class DatabaseMetrics:
    row_count: int
    group_count: int


class DatabaseNotFoundError(LookupError):
    """Raised when a requested local database is unavailable."""


class TableNotFoundError(LookupError):
    """Raised when a requested table is unavailable."""


class InvalidColumnError(ValueError):
    """Raised when a requested column is unavailable."""


def create_database(input_database_id: str) -> DatabaseState:
    return database_service.set_database_id(input_database_id)


def open_database(database_id: str) -> DatabaseState:
    return database_service.load_existing_database(database_id)


def refresh_database(
    database_id: str,
    current_table: str = "",
    selected_headers=(),
) -> DatabaseState:
    return database_service.update_headers(
        database_id,
        current_table,
        selected_headers,
    )


def get_database_metrics(
    connection,
    current_table: str,
    group_column: str,
    headers,
) -> DatabaseMetrics:
    return DatabaseMetrics(
        row_count=database_service.count_rows(connection, current_table),
        group_count=database_service.count_rows_group_by(
            connection,
            current_table,
            group_column,
            headers,
        ),
    )


def list_database_tables(database_id: str) -> list[str]:
    tables = database_service.get_tables(database_id)
    if not tables:
        raise DatabaseNotFoundError(
            f"Database '{database_id}' was not found or contains no tables."
        )
    return tables


def get_table_state(database_id: str, current_table: str) -> DatabaseState:
    tables = list_database_tables(database_id)
    if current_table not in tables:
        raise TableNotFoundError(
            f"Table '{current_table}' was not found in database '{database_id}'."
        )
    return database_service.update_headers(database_id, current_table, [])


def get_table_metrics(
    database_id: str,
    current_table: str,
    group_column: str = "",
) -> DatabaseMetrics:
    state = get_table_state(database_id, current_table)
    if group_column and group_column not in state.headers:
        raise InvalidColumnError(f"Unknown column: {group_column}")
    connection = database_service.get_connection(database_id)
    return get_database_metrics(
        connection,
        state.current_table,
        group_column,
        state.headers,
    )


def get_table_schema(
    database_id: str,
    current_table: str,
) -> tuple[dict[str, object], ...]:
    """Inspect the SQLite schema for a validated user table."""
    get_table_state(database_id, current_table)
    schema = db_audit.get_table_schema(
        Path("SQL") / f"{database_id}.db",
        current_table,
    )
    return tuple(schema["columns"])
