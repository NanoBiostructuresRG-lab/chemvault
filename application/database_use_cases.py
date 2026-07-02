# SPDX-License-Identifier: LGPL-3.0-or-later
"""Application use cases for database selection and inspection."""
from dataclasses import dataclass

from services import database as database_service
from services.database import DatabaseState


@dataclass(frozen=True)
class DatabaseMetrics:
    row_count: int
    group_count: int


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
