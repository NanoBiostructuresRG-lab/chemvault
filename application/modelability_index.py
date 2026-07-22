# SPDX-License-Identifier: LGPL-3.0-or-later
"""Application boundary for Modelability Index analysis."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass

import pandas as pd
from molraptor import (
    MorganFingerprintProfile,
    __version__ as MOLRAPTOR_VERSION,
    encode_fingerprints,
)
from rdkit import __version__ as RDKIT_VERSION

from application.database_use_cases import (
    TableNotFoundError,
    resolve_database_path,
)
from services.modelability_index import (
    ModelabilityIndexError,
    calculate_modelability_index,
)
from services.sql_utils import get_tables_from_connection, quote_identifier


REQUIRED_COLUMNS = (
    "SMILES_Harmonized",
    "Outcome",
    "Reference_Selection_Status",
)
_FINGERPRINT_PROFILE = MorganFingerprintProfile()
_BINARY_OUTCOMES = {"active": "Active", "inactive": "Inactive"}
POPULATION_POLICY = "reference_selected_only/v1"
MODELABILITY_INDEX_CONTRACT_VERSION = "modelability_index/v1"
SIMILARITY_METRIC = "tanimoto"
NEIGHBOR_RULE = "single_nearest_neighbor"
TIE_POLICY = "lowest_ordered_index"
AGGREGATION_METHOD = "macro_average"


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


@dataclass(frozen=True)
class PreparedModelabilityInput:
    smiles: tuple[str, ...]
    outcomes: tuple[str, ...]
    analysis_identity: str


def _clean_text(value) -> str:
    return "" if pd.isna(value) else str(value).strip()


def _analysis_identity(
    smiles: tuple[str, ...],
    outcomes: tuple[str, ...],
) -> str:
    payload = {
        "aggregation": AGGREGATION_METHOD,
        "fingerprint_profile": _FINGERPRINT_PROFILE.serialize(),
        "modelability_index_contract_version": (
            MODELABILITY_INDEX_CONTRACT_VERSION
        ),
        "molraptor_version": MOLRAPTOR_VERSION,
        "neighbor_rule": NEIGHBOR_RULE,
        "ordered_input_pairs": list(zip(smiles, outcomes)),
        "population_policy": POPULATION_POLICY,
        "rdkit_version": RDKIT_VERSION,
        "similarity_metric": SIMILARITY_METRIC,
        "tie_policy": TIE_POLICY,
    }
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def prepare_modelability_input(
    dataframe: pd.DataFrame,
) -> PreparedModelabilityInput:
    missing = [
        column for column in REQUIRED_COLUMNS if column not in dataframe.columns
    ]
    if missing:
        raise ModelabilityIndexUseCaseError(
            "The source table is missing required columns: " + ", ".join(missing)
        )

    prepared = dataframe.loc[:, REQUIRED_COLUMNS].copy()
    selection_status = prepared["Reference_Selection_Status"].map(
        lambda value: _clean_text(value).lower()
    )
    prepared = prepared.loc[
        selection_status == "selected",
        ["SMILES_Harmonized", "Outcome"],
    ].copy()
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
    prepared = prepared.sort_values(
        ["SMILES_Harmonized", "Outcome"],
        kind="stable",
    ).reset_index(drop=True)
    if len(prepared) < 2:
        raise ModelabilityIndexUseCaseError(
            "At least two selected structures are required."
        )

    smiles = tuple(prepared["SMILES_Harmonized"])
    outcomes = tuple(prepared["Outcome"])
    if set(outcomes) != {"Active", "Inactive"}:
        raise ModelabilityIndexUseCaseError(
            "Both Active and Inactive outcomes are required."
        )
    return PreparedModelabilityInput(
        smiles=smiles,
        outcomes=outcomes,
        analysis_identity=_analysis_identity(smiles, outcomes),
    )


def prepare_table_modelability_input(
    connection,
    source_table: str,
    *,
    database_id: str | None = None,
) -> PreparedModelabilityInput:
    if source_table not in get_tables_from_connection(connection):
        database_detail = (
            f" in database '{database_id}'" if database_id is not None else ""
        )
        raise TableNotFoundError(
            f"Table '{source_table}' was not found{database_detail}."
        )
    schema_rows = connection.execute(
        f"PRAGMA table_info({quote_identifier(source_table)})"
    ).fetchall()
    column_names = {row[1] for row in schema_rows}
    missing = [
        column for column in REQUIRED_COLUMNS if column not in column_names
    ]
    if missing:
        raise ModelabilityIndexUseCaseError(
            "The source table is missing required columns: " + ", ".join(missing)
        )
    columns_sql = ", ".join(
        quote_identifier(column) for column in REQUIRED_COLUMNS
    )
    source = pd.read_sql_query(
        f"SELECT {columns_sql} FROM {quote_identifier(source_table)}",
        connection,
    )
    return prepare_modelability_input(source)


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
    prepared = prepare_modelability_input(dataframe)
    return calculate_prepared_modelability_index(
        prepared,
        source_table=source_table,
    )


def calculate_prepared_modelability_index(
    prepared: PreparedModelabilityInput,
    *,
    source_table: str | None = None,
) -> ModelabilityIndexUseCaseResult:
    """Calculate Modelability from an already validated prepared input."""
    smiles = prepared.smiles
    outcomes = prepared.outcomes
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
        "chemvault_analysis_hash": prepared.analysis_identity,
        "molraptor_version": str(encoding.molraptor_version),
        "rdkit_version": str(encoding.rdkit_version),
        "similarity_metric": SIMILARITY_METRIC,
        "neighbor_rule": NEIGHBOR_RULE,
        "tie_policy": TIE_POLICY,
        "aggregation": AGGREGATION_METHOD,
    }

    return ModelabilityIndexUseCaseResult(
        structure_count=len(smiles),
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
        prepared = prepare_table_modelability_input(
            connection,
            source_table,
            database_id=database_id,
        )
    finally:
        connection.close()

    return calculate_prepared_modelability_index(
        prepared,
        source_table=source_table,
    )
