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


CONSOLIDATION_SQLITE_TYPES = {
    "SMILES_Harmonized": "TEXT",
    "InChIKey": "TEXT",
    "Outcome": "TEXT",
    "Reference_CID": "TEXT",
    "Reference_AID": "TEXT",
    "Reference_Activity_Type": "TEXT",
    "Reference_Relation": "TEXT",
    "Reference_Activity_Value": "REAL",
    "Reference_Activity_Value_Raw": "TEXT",
    "Reference_Unit": "TEXT",
    "Reference_Activity_Value_uM": "REAL",
    "Geometric_Mean_Activity_uM": "REAL",
    "Reference_Selection_Status": "TEXT",
    "Source_CIDs": "TEXT",
    "Source_AIDs": "TEXT",
    "Source_Row_Count": "INTEGER",
    "Source_AID_Count": "INTEGER",
}


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
    represented_source_row_count: int
    selected_reference_count: int
    no_eligible_activity_count: int


@dataclass(frozen=True)
class StructureConsolidationSummary:
    source_table: str
    source_row_count: int
    valid_source_row_count: int
    unusable_row_count: int
    unique_structure_count: int
    conflicting_structure_count: int
    non_binary_structure_count: int
    created_row_count: int
    active_structure_count: int
    inactive_structure_count: int
    active_distinct_aid_count: int
    active_source_observation_count: int
    inactive_distinct_aid_count: int
    inactive_source_observation_count: int
    represented_source_row_count: int
    consolidated_duplicate_count: int
    selected_reference_count: int
    no_eligible_activity_count: int

    def has_valid_invariants(self) -> bool:
        counts = tuple(
            value
            for field, value in self.__dict__.items()
            if field != "source_table"
        )
        return (
            self.source_table != ""
            and all(isinstance(value, int) and value >= 0 for value in counts)
            and self.source_row_count
            == self.valid_source_row_count + self.unusable_row_count
            and self.active_structure_count + self.inactive_structure_count
            == self.created_row_count
            and self.active_source_observation_count
            + self.inactive_source_observation_count
            == self.represented_source_row_count
            and self.active_distinct_aid_count
            <= self.active_source_observation_count
            and self.inactive_distinct_aid_count
            <= self.inactive_source_observation_count
            and self.selected_reference_count
            + self.no_eligible_activity_count
            == self.created_row_count
            and self.represented_source_row_count - self.created_row_count
            == self.consolidated_duplicate_count
        )


_PERSISTED_SUMMARY_FIELDS = {
    "source_row_count": "source_rows",
    "valid_source_row_count": "usable_source_rows",
    "unusable_row_count": "unusable_rows",
    "unique_structure_count": "unique_harmonized_structures",
    "conflicting_structure_count": "conflicting_structures",
    "non_binary_structure_count": "non_binary_structures",
    "created_row_count": "created_rows",
    "active_structure_count": "active_structures",
    "inactive_structure_count": "inactive_structures",
    "active_distinct_aid_count": "active_distinct_aids",
    "active_source_observation_count": "active_source_observations",
    "inactive_distinct_aid_count": "inactive_distinct_aids",
    "inactive_source_observation_count": "inactive_source_observations",
    "represented_source_row_count": "represented_source_row_count",
    "consolidated_duplicate_count": "consolidated_duplicates",
    "selected_reference_count": "selected_reference_count",
    "no_eligible_activity_count": "no_eligible_activity_count",
}


def _persisted_summary(summary: StructureConsolidationSummary) -> dict:
    return {
        persisted_name: getattr(summary, field_name)
        for field_name, persisted_name in _PERSISTED_SUMMARY_FIELDS.items()
    }


def structure_consolidation_summary_from_metadata(
    *,
    origin: str | None,
    source_table: str | None,
    notes: str | None,
) -> StructureConsolidationSummary | None:
    """Decode a complete persisted consolidation summary, if available."""
    if origin != "structure_consolidation" or not source_table or not notes:
        return None
    try:
        persisted = json.loads(notes)
        values = {
            field_name: int(persisted[persisted_name])
            for field_name, persisted_name in _PERSISTED_SUMMARY_FIELDS.items()
        }
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None

    summary = StructureConsolidationSummary(
        source_table=str(source_table),
        **values,
    )
    return summary if summary.has_valid_invariants() else None


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
        f"{quote_identifier(column)} "
        f"{CONSOLIDATION_SQLITE_TYPES.get(
            column,
            _sqlite_column_type(dataframe[column]),
        )}"
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

        summary = StructureConsolidationSummary(
            source_table=source_table,
            source_row_count=consolidated.source_row_count,
            valid_source_row_count=consolidated.valid_source_row_count,
            unusable_row_count=consolidated.unusable_row_count,
            unique_structure_count=consolidated.unique_structure_count,
            conflicting_structure_count=(
                consolidated.conflicting_structure_count
            ),
            non_binary_structure_count=(
                consolidated.non_binary_structure_count
            ),
            created_row_count=consolidated.created_row_count,
            active_structure_count=consolidated.active_structure_count,
            inactive_structure_count=consolidated.inactive_structure_count,
            active_distinct_aid_count=(
                consolidated.active_distinct_aid_count
            ),
            active_source_observation_count=(
                consolidated.active_source_observation_count
            ),
            inactive_distinct_aid_count=(
                consolidated.inactive_distinct_aid_count
            ),
            inactive_source_observation_count=(
                consolidated.inactive_source_observation_count
            ),
            represented_source_row_count=(
                consolidated.represented_source_row_count
            ),
            consolidated_duplicate_count=(
                consolidated.consolidated_duplicate_count
            ),
            selected_reference_count=consolidated.selected_reference_count,
            no_eligible_activity_count=(
                consolidated.no_eligible_activity_count
            ),
        )
        if not summary.has_valid_invariants():
            raise ValueError("Invalid structure consolidation summary metrics.")
        persisted_summary = _persisted_summary(summary)
        register_table_metadata(
            connection,
            table_name,
            role="derived",
            origin="structure_consolidation",
            source_table=source_table,
            created_by="consolidate_structure_table",
            query_used=source_query,
            notes=json.dumps(persisted_summary, sort_keys=True),
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
            details=json.dumps(persisted_summary, sort_keys=True),
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
        represented_source_row_count=(
            consolidated.represented_source_row_count
        ),
        selected_reference_count=consolidated.selected_reference_count,
        no_eligible_activity_count=consolidated.no_eligible_activity_count,
    )
