# SPDX-License-Identifier: LGPL-3.0-or-later
"""Application persistence boundary for structure consolidation."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass

import pandas as pd
from pandas.api.types import (
    is_bool_dtype,
    is_float_dtype,
    is_integer_dtype,
)

from application.database_use_cases import (
    TableNotFoundError,
    resolve_database_path,
)
from services.db_audit import register_operation, register_table_metadata
from services.sql_utils import (
    get_tables_from_connection,
    is_valid_table_name,
    quote_identifier,
    table_exists,
)
from services.structure_consolidation import consolidate_harmonized_structures


@dataclass(frozen=True)
class StructureConsolidationTableResult:
    table_name: str
    source_row_count: int
    valid_source_row_count: int
    unique_structure_count: int
    created_row_count: int
    active_structure_count: int
    inactive_structure_count: int
    conflicting_structure_count: int
    non_binary_structure_count: int
    unusable_row_count: int
    consolidated_duplicate_count: int


def _safe_table_name_part(value: str) -> str:
    value = re.sub(r"[^0-9A-Za-z]+", "_", str(value)).strip("_")
    if not value:
        value = "source"
    if value[0].isdigit():
        value = f"source_{value}"
    return value


def _unique_table_name(connection, source_table: str) -> str:
    base_name = f"{_safe_table_name_part(source_table)}_structure_consolidated"
    if not is_valid_table_name(base_name):
        raise ValueError(f"Invalid derived table name: {base_name}")
    candidate = base_name
    suffix = 2
    while table_exists(connection, candidate):
        candidate = f"{base_name}_{suffix}"
        suffix += 1
    return candidate


def _sqlite_column_type(series: pd.Series) -> str:
    if is_bool_dtype(series.dtype) or is_integer_dtype(series.dtype):
        return "INTEGER"
    if is_float_dtype(series.dtype):
        return "REAL"
    return "TEXT"


def _sqlite_value(value):
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value


def _create_dataframe_table(
    connection,
    table_name: str,
    dataframe: pd.DataFrame,
) -> None:
    columns = list(dataframe.columns)
    if not columns:
        raise ValueError("The consolidated table has no columns.")
    column_sql = ", ".join(
        f"{quote_identifier(column)} {_sqlite_column_type(dataframe[column])}"
        for column in columns
    )
    connection.execute(
        f"CREATE TABLE {quote_identifier(table_name)} ({column_sql})"
    )
    if dataframe.empty:
        return
    placeholders = ", ".join("?" for _ in columns)
    columns_sql = ", ".join(quote_identifier(column) for column in columns)
    rows = [
        tuple(_sqlite_value(value) for value in row)
        for row in dataframe.itertuples(index=False, name=None)
    ]
    connection.executemany(
        f"INSERT INTO {quote_identifier(table_name)} ({columns_sql}) "
        f"VALUES ({placeholders})",
        rows,
    )


def consolidate_structure_table(
    database_id: str,
    source_table: str,
    *,
    db_dir="SQL",
) -> StructureConsolidationTableResult:
    """Consolidate one source table and persist one atomic derived table."""
    db_path = resolve_database_path(database_id, db_dir=db_dir)
    connection = sqlite3.connect(db_path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        if source_table not in get_tables_from_connection(connection):
            raise TableNotFoundError(
                f"Table '{source_table}' was not found in database "
                f"'{database_id}'."
            )

        source_query = f"SELECT * FROM {quote_identifier(source_table)}"
        source = pd.read_sql_query(source_query, connection)
        consolidated = consolidate_harmonized_structures(source)
        table_name = _unique_table_name(connection, source_table)
        _create_dataframe_table(
            connection,
            table_name,
            consolidated.dataframe,
        )

        summary = {
            "source_rows": consolidated.source_row_count,
            "usable_source_rows": consolidated.valid_source_row_count,
            "unique_harmonized_structures": (
                consolidated.unique_structure_count
            ),
            "created_rows": consolidated.created_row_count,
            "consolidated_duplicates": (
                consolidated.consolidated_duplicate_count
            ),
            "active_structures": consolidated.active_structure_count,
            "inactive_structures": consolidated.inactive_structure_count,
            "conflicting_structures": consolidated.conflicting_structure_count,
            "non_binary_structures": consolidated.non_binary_structure_count,
            "unusable_rows": consolidated.unusable_row_count,
        }
        register_table_metadata(
            connection,
            table_name,
            role="derived",
            origin="structure_consolidation",
            source_table=source_table,
            created_by="consolidate_structure_table",
            query_used=source_query,
            notes=json.dumps(summary, sort_keys=True),
            commit=False,
        )
        register_operation(
            connection,
            "structure_consolidation_created",
            target_table=table_name,
            source_table=source_table,
            source_columns=list(source.columns),
            output_columns=list(consolidated.dataframe.columns),
            created_by="consolidate_structure_table",
            details=json.dumps(summary, sort_keys=True),
            query_used=source_query,
            commit=False,
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

    return StructureConsolidationTableResult(
        table_name=table_name,
        source_row_count=consolidated.source_row_count,
        valid_source_row_count=consolidated.valid_source_row_count,
        unique_structure_count=consolidated.unique_structure_count,
        created_row_count=consolidated.created_row_count,
        active_structure_count=consolidated.active_structure_count,
        inactive_structure_count=consolidated.inactive_structure_count,
        conflicting_structure_count=consolidated.conflicting_structure_count,
        non_binary_structure_count=consolidated.non_binary_structure_count,
        unusable_row_count=consolidated.unusable_row_count,
        consolidated_duplicate_count=consolidated.consolidated_duplicate_count,
    )
