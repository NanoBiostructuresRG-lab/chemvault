# SPDX-License-Identifier: LGPL-3.0-or-later
"""Application use case for modelability analysis of consolidated structures."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

import pandas as pd
from molraptor import MorganFingerprintProfile, encode_fingerprints

from application.database_use_cases import (
    TableNotFoundError,
    resolve_database_path,
)
from services.modelability_index import (
    DEFAULT_BLOCK_SIZE,
    ModelabilityIndexError,
    calculate_modelability_index,
)
from services.sql_utils import (
    get_tables_from_connection,
    quote_identifier,
)


REQUIRED_COLUMNS = {
    "SMILES_Harmonized",
    "Outcome",
}

BINARY_OUTCOMES = {
    "active": "Active",
    "inactive": "Inactive",
}


class ModelabilityIndexUseCaseError(ValueError):
    """Raised when a source table cannot be evaluated safely."""


@dataclass(frozen=True)
class ModelabilityEncodingExclusion:
    input_index: int
    source_row_index: int
    smiles_harmonized: str
    outcome: str
    reason: str


@dataclass(frozen=True)
class ModelabilityStructureDiagnostic:
    input_index: int
    source_row_index: int
    smiles_harmonized: str
    outcome: str
    nearest_neighbor_input_index: int
    nearest_neighbor_source_row_index: int
    nearest_neighbor_smiles_harmonized: str
    nearest_neighbor_outcome: str
    tanimoto_similarity: float
    outcome_concordant: bool
    nearest_neighbor_tie_count: int


@dataclass(frozen=True)
class ModelabilityIndexUseCaseResult:
    source_table: str | None
    source_row_count: int
    encoded_structure_count: int
    excluded_structure_count: int
    modelability_index: float
    active_contribution: float
    inactive_contribution: float
    active_count: int
    inactive_count: int
    concordant_structure_count: int
    discordant_structure_count: int
    tie_affected_structure_count: int
    fingerprint_profile: dict[str, object]
    fingerprint_profile_hash: str
    ordered_input_hash: str
    molraptor_version: str
    rdkit_version: str
    fingerprint_shape: tuple[int, int]
    fingerprint_dtype: str
    exclusions: tuple[ModelabilityEncodingExclusion, ...]
    diagnostics: tuple[ModelabilityStructureDiagnostic, ...]


def _clean_text(value) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip()


def _normalize_outcome(value) -> str | None:
    return BINARY_OUTCOMES.get(_clean_text(value).lower())


def _prepare_source(dataframe: pd.DataFrame) -> pd.DataFrame:
    missing = sorted(REQUIRED_COLUMNS.difference(dataframe.columns))
    if missing:
        raise ModelabilityIndexUseCaseError(
            "The source table is missing required columns: "
            + ", ".join(missing)
        )

    if dataframe.empty:
        raise ModelabilityIndexUseCaseError(
            "The source table contains no structures."
        )

    prepared = dataframe.loc[
        :,
        ["SMILES_Harmonized", "Outcome"],
    ].copy()

    prepared["__source_row_index"] = range(len(prepared))
    prepared["SMILES_Harmonized"] = prepared[
        "SMILES_Harmonized"
    ].map(_clean_text)
    prepared["__normalized_outcome"] = prepared["Outcome"].map(
        _normalize_outcome
    )

    invalid_outcome_rows = prepared.index[
        prepared["__normalized_outcome"].isna()
    ].tolist()

    if invalid_outcome_rows:
        source_indices = [
            int(prepared.loc[index, "__source_row_index"])
            for index in invalid_outcome_rows
        ]
        values = [
            _clean_text(prepared.loc[index, "Outcome"])
            for index in invalid_outcome_rows
        ]
        details = ", ".join(
            f"{row_index}={value!r}"
            for row_index, value in zip(
                source_indices,
                values,
                strict=True,
            )
        )
        raise ModelabilityIndexUseCaseError(
            "Outcome must contain only Active or Inactive; "
            f"invalid source rows: {details}."
        )

    prepared["Outcome"] = prepared["__normalized_outcome"]

    duplicate_mask = (
        prepared["SMILES_Harmonized"].ne("")
        & prepared["SMILES_Harmonized"].duplicated(keep=False)
    )
    duplicate_smiles = sorted(
        set(prepared.loc[duplicate_mask, "SMILES_Harmonized"])
    )

    if duplicate_smiles:
        raise ModelabilityIndexUseCaseError(
            "The source table must contain one row per harmonized "
            "structure; duplicated SMILES_Harmonized values: "
            + ", ".join(duplicate_smiles)
        )

    return prepared.sort_values(
        by=[
            "SMILES_Harmonized",
            "Outcome",
            "__source_row_index",
        ],
        kind="stable",
    ).reset_index(drop=True)


def _validate_encoding_contract(encoding, input_count: int) -> None:
    fingerprints = encoding.fingerprints
    valid_indices = tuple(int(index) for index in encoding.valid_indices)

    if encoding.valid_count != len(valid_indices):
        raise ModelabilityIndexUseCaseError(
            "MOLRAPTOR returned inconsistent valid-count metadata."
        )

    if encoding.invalid_count != input_count - encoding.valid_count:
        raise ModelabilityIndexUseCaseError(
            "MOLRAPTOR returned inconsistent invalid-count metadata."
        )

    if fingerprints.ndim != 2:
        raise ModelabilityIndexUseCaseError(
            "MOLRAPTOR returned a non-matrix fingerprint result."
        )

    if fingerprints.shape[0] != encoding.valid_count:
        raise ModelabilityIndexUseCaseError(
            "MOLRAPTOR fingerprint rows do not match valid inputs."
        )

    if tuple(fingerprints.shape) != tuple(encoding.matrix_shape):
        raise ModelabilityIndexUseCaseError(
            "MOLRAPTOR fingerprint shape metadata is inconsistent."
        )

    if len(encoding.input_statuses) != input_count:
        raise ModelabilityIndexUseCaseError(
            "MOLRAPTOR did not return one status per input."
        )

    expected_valid_indices = tuple(
        int(status.input_index)
        for status in encoding.input_statuses
        if status.status == "valid"
    )

    if expected_valid_indices != valid_indices:
        raise ModelabilityIndexUseCaseError(
            "MOLRAPTOR valid-index metadata is inconsistent."
        )

    for fingerprint_index, input_index in enumerate(valid_indices):
        status = encoding.input_statuses[input_index]
        if status.fingerprint_index != fingerprint_index:
            raise ModelabilityIndexUseCaseError(
                "MOLRAPTOR fingerprint-index metadata is inconsistent."
            )


def calculate_dataframe_modelability_index(
    dataframe: pd.DataFrame,
    *,
    source_table: str | None = None,
    profile: MorganFingerprintProfile | None = None,
    block_size: int = DEFAULT_BLOCK_SIZE,
) -> ModelabilityIndexUseCaseResult:
    """Calculate modelability for one consolidated table held in memory."""
    prepared = _prepare_source(dataframe)
    active_profile = profile or MorganFingerprintProfile()

    smiles = tuple(prepared["SMILES_Harmonized"])
    encoding = encode_fingerprints(smiles, active_profile)
    _validate_encoding_contract(encoding, len(prepared))

    valid_input_indices = tuple(
        int(index) for index in encoding.valid_indices
    )
    valid_outcomes = tuple(
        str(prepared.iloc[index]["Outcome"])
        for index in valid_input_indices
    )

    try:
        core_result = calculate_modelability_index(
            encoding.fingerprints,
            valid_outcomes,
            block_size=block_size,
        )
    except ModelabilityIndexError as error:
        raise ModelabilityIndexUseCaseError(str(error)) from error

    exclusions = tuple(
        ModelabilityEncodingExclusion(
            input_index=int(status.input_index),
            source_row_index=int(
                prepared.iloc[status.input_index]["__source_row_index"]
            ),
            smiles_harmonized=str(status.input_smiles),
            outcome=str(
                prepared.iloc[status.input_index]["Outcome"]
            ),
            reason=str(status.invalid_reason or status.status),
        )
        for status in encoding.input_statuses
        if status.status != "valid"
    )

    diagnostics: list[ModelabilityStructureDiagnostic] = []

    for diagnostic in core_result.diagnostics:
        input_index = valid_input_indices[diagnostic.input_index]
        neighbor_input_index = valid_input_indices[
            diagnostic.nearest_neighbor_index
        ]

        row = prepared.iloc[input_index]
        neighbor_row = prepared.iloc[neighbor_input_index]

        diagnostics.append(
            ModelabilityStructureDiagnostic(
                input_index=input_index,
                source_row_index=int(row["__source_row_index"]),
                smiles_harmonized=str(row["SMILES_Harmonized"]),
                outcome=str(row["Outcome"]),
                nearest_neighbor_input_index=neighbor_input_index,
                nearest_neighbor_source_row_index=int(
                    neighbor_row["__source_row_index"]
                ),
                nearest_neighbor_smiles_harmonized=str(
                    neighbor_row["SMILES_Harmonized"]
                ),
                nearest_neighbor_outcome=str(
                    neighbor_row["Outcome"]
                ),
                tanimoto_similarity=(
                    diagnostic.nearest_neighbor_similarity
                ),
                outcome_concordant=diagnostic.outcome_concordant,
                nearest_neighbor_tie_count=(
                    diagnostic.nearest_neighbor_tie_count
                ),
            )
        )

    return ModelabilityIndexUseCaseResult(
        source_table=source_table,
        source_row_count=len(prepared),
        encoded_structure_count=encoding.valid_count,
        excluded_structure_count=encoding.invalid_count,
        modelability_index=core_result.modelability_index,
        active_contribution=core_result.active_contribution,
        inactive_contribution=core_result.inactive_contribution,
        active_count=core_result.active_count,
        inactive_count=core_result.inactive_count,
        concordant_structure_count=(
            core_result.concordant_structure_count
        ),
        discordant_structure_count=(
            core_result.discordant_structure_count
        ),
        tie_affected_structure_count=(
            core_result.tie_affected_structure_count
        ),
        fingerprint_profile=dict(encoding.profile),
        fingerprint_profile_hash=str(encoding.profile_hash),
        ordered_input_hash=str(encoding.ordered_input_hash),
        molraptor_version=str(encoding.molraptor_version),
        rdkit_version=str(encoding.rdkit_version),
        fingerprint_shape=tuple(encoding.matrix_shape),
        fingerprint_dtype=str(encoding.matrix_dtype),
        exclusions=exclusions,
        diagnostics=tuple(diagnostics),
    )


def calculate_table_modelability_index(
    database_id: str,
    source_table: str,
    *,
    db_dir="SQL",
    profile: MorganFingerprintProfile | None = None,
    block_size: int = DEFAULT_BLOCK_SIZE,
) -> ModelabilityIndexUseCaseResult:
    """Read one consolidated SQLite table and calculate modelability."""
    db_path = resolve_database_path(database_id, db_dir=db_dir)
    connection = sqlite3.connect(db_path)

    try:
        if source_table not in get_tables_from_connection(connection):
            raise TableNotFoundError(
                f"Table '{source_table}' was not found in database "
                f"'{database_id}'."
            )

        columns_sql = ", ".join(
            quote_identifier(column)
            for column in sorted(REQUIRED_COLUMNS)
        )
        query = (
            f"SELECT {columns_sql} "
            f"FROM {quote_identifier(source_table)}"
        )
        source = pd.read_sql_query(query, connection)
    finally:
        connection.close()

    return calculate_dataframe_modelability_index(
        source,
        source_table=source_table,
        profile=profile,
        block_size=block_size,
    )