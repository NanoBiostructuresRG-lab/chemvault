# SPDX-License-Identifier: LGPL-3.0-or-later
"""Application boundary for Modelability Index analysis."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass

import pandas as pd
from molraptor import MorganFingerprintProfile, encode_fingerprints

from application.database_use_cases import (
    TableNotFoundError,
    resolve_database_path,
)
from services.modelability_index import (
    ModelabilityIndexError,
    calculate_modelability_index,
)
from services.sql_utils import get_tables_from_connection, quote_identifier


REQUIRED_COLUMNS = ("SMILES_Harmonized", "Outcome")
_FINGERPRINT_PROFILE = MorganFingerprintProfile()
_BINARY_OUTCOMES = {"active": "Active", "inactive": "Inactive"}


class ModelabilityIndexUseCaseError(ValueError):
    """Raised when a source table cannot produce a complete analysis."""


@dataclass(frozen=True)
class ModelabilityIndexUseCaseResult:
    structure_count: int
    active_count: int
    inactive_count: int
    active_concordance: float
    inactive_concordance: float
    modelability_index: float
    diagnostics: tuple[dict[str, object], ...]
    provenance: dict[str, object]


def _clean_text(value) -> str:
    return "" if pd.isna(value) else str(value).strip()


def _prepare_source(dataframe: pd.DataFrame) -> pd.DataFrame:
    missing = [
        column for column in REQUIRED_COLUMNS if column not in dataframe.columns
    ]
    if missing:
        raise ModelabilityIndexUseCaseError(
            "The source table is missing required columns: " + ", ".join(missing)
        )

    prepared = dataframe.loc[:, REQUIRED_COLUMNS].copy()
    prepared["SMILES_Harmonized"] = prepared["SMILES_Harmonized"].map(
        _clean_text
    )
    normalized = prepared["Outcome"].map(
        lambda value: _BINARY_OUTCOMES.get(_clean_text(value).lower())
    )
    if normalized.isna().any():
        invalid_rows = ", ".join(
            str(index) for index in normalized.index[normalized.isna()]
        )
        raise ModelabilityIndexUseCaseError(
            "Outcome must contain only Active or Inactive; "
            f"invalid rows: {invalid_rows}."
        )
    prepared["Outcome"] = normalized
    return prepared.sort_values(
        ["SMILES_Harmonized", "Outcome"],
        kind="stable",
    ).reset_index(drop=True)


def _analysis_hash(prepared: pd.DataFrame) -> str:
    pairs = list(
        prepared.loc[:, REQUIRED_COLUMNS].itertuples(index=False, name=None)
    )
    payload = json.dumps(
        pairs,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _invalid_encoding_message(encoding) -> str:
    details = ", ".join(
        f"{status.input_index}={status.input_smiles!r} ({status.invalid_reason})"
        for status in encoding.input_statuses
        if status.status == "invalid"
    )
    return "MOLRAPTOR rejected one or more structures: " + details


def calculate_dataframe_modelability_index(
    dataframe: pd.DataFrame,
    *,
    source_table: str | None = None,
) -> ModelabilityIndexUseCaseResult:
    """Calculate a complete Modelability Index for a consolidated table."""
    prepared = _prepare_source(dataframe)
    if len(prepared) < 2:
        raise ModelabilityIndexUseCaseError(
            "At least two structures are required."
        )
    smiles = tuple(prepared["SMILES_Harmonized"])
    outcomes = tuple(prepared["Outcome"])
    encoding = encode_fingerprints(smiles, _FINGERPRINT_PROFILE)

    if encoding.invalid_count:
        raise ModelabilityIndexUseCaseError(
            _invalid_encoding_message(encoding)
        )

    try:
        numerical = calculate_modelability_index(
            encoding.fingerprints,
            outcomes,
        )
    except ModelabilityIndexError as error:
        raise ModelabilityIndexUseCaseError(str(error)) from error

    diagnostics = tuple(
        {
            "smiles": smiles[index],
            "outcome": outcomes[index],
            "nearest_neighbor_smiles": smiles[neighbor_index],
            "nearest_neighbor_outcome": outcomes[neighbor_index],
            "tanimoto_similarity": numerical.neighbor_similarities[index],
            "concordant": numerical.concordant[index],
        }
        for index, neighbor_index in enumerate(numerical.neighbor_indices)
    )
    provenance = {
        "source_table": source_table,
        "fingerprint_profile": dict(encoding.profile),
        "molraptor_profile_hash": str(encoding.profile_hash),
        "molraptor_ordered_input_hash": str(encoding.ordered_input_hash),
        "chemvault_analysis_hash": _analysis_hash(prepared),
        "molraptor_version": str(encoding.molraptor_version),
        "rdkit_version": str(encoding.rdkit_version),
        "similarity_metric": "tanimoto",
        "neighbor_rule": "single_nearest_neighbor",
        "tie_policy": "lowest_ordered_index",
        "aggregation": "macro_average",
    }

    return ModelabilityIndexUseCaseResult(
        structure_count=len(prepared),
        active_count=outcomes.count("Active"),
        inactive_count=outcomes.count("Inactive"),
        active_concordance=numerical.active_concordance,
        inactive_concordance=numerical.inactive_concordance,
        modelability_index=numerical.modelability_index,
        diagnostics=diagnostics,
        provenance=provenance,
    )


def calculate_table_modelability_index(
    database_id: str,
    source_table: str,
    *,
    db_dir="SQL",
) -> ModelabilityIndexUseCaseResult:
    """Read the two analysis columns from SQLite and calculate modelability."""
    db_path = resolve_database_path(database_id, db_dir=db_dir)
    connection = sqlite3.connect(db_path)
    try:
        if source_table not in get_tables_from_connection(connection):
            raise TableNotFoundError(
                f"Table '{source_table}' was not found in database "
                f"'{database_id}'."
            )
        columns_sql = ", ".join(
            quote_identifier(column) for column in REQUIRED_COLUMNS
        )
        source = pd.read_sql_query(
            f"SELECT {columns_sql} FROM {quote_identifier(source_table)}",
            connection,
        )
    finally:
        connection.close()

    return calculate_dataframe_modelability_index(
        source,
        source_table=source_table,
    )
