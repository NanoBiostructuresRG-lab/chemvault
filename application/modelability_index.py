# SPDX-License-Identifier: LGPL-3.0-or-later
"""Application boundary for Modelability Index analysis."""

from __future__ import annotations

import hashlib
import io
import json
import sqlite3
from dataclasses import dataclass

import numpy as np
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
from services.modelability_fingerprint_artifacts import (
    MATRIX_FORMAT,
    MATRIX_FORMAT_VERSION,
    FingerprintArtifact,
    FingerprintArtifactExpectation,
    build_fingerprint_artifact,
    read_fingerprint_artifact,
    restore_or_calculate_fingerprint_artifact,
)
from services.sql_utils import get_tables_from_connection, quote_identifier


REQUIRED_COLUMNS = (
    "SMILES_Harmonized",
    "Outcome",
    "Reference_Selection_Status",
)
_FINGERPRINT_PROFILE = MorganFingerprintProfile()
_BINARY_OUTCOMES = {"active": "Active", "inactive": "Inactive"}
POPULATION_POLICY = "consolidated_binary_outcomes/v1"
MODELABILITY_INDEX_CONTRACT_VERSION = "modelability_index/v1"
SIMILARITY_METRIC = "tanimoto"
NEIGHBOR_RULE = "single_nearest_neighbor"
TIE_POLICY = "lowest_ordered_index"
AGGREGATION_METHOD = "macro_average"
FINGERPRINT_ARTIFACT_CONTRACT = "modelability_fingerprint_artifact"
FINGERPRINT_ARTIFACT_CONTRACT_VERSION = 1
_OUTCOME_MAPPING = {"Inactive": 0, "Active": 1}


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
    fingerprint_identity: str = ""
    population_identity: str = ""


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


def _fingerprint_identity(population_identity: str) -> str:
    payload = {
        "artifact_contract": FINGERPRINT_ARTIFACT_CONTRACT,
        "artifact_contract_version": FINGERPRINT_ARTIFACT_CONTRACT_VERSION,
        "fingerprint_profile": _FINGERPRINT_PROFILE.serialize(),
        "molraptor_version": MOLRAPTOR_VERSION,
        "population_identity": population_identity,
        "rdkit_version": RDKIT_VERSION,
    }
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def _population_identity(smiles: tuple[str, ...]) -> str:
    payload = {
        "ordered_smiles_harmonized": list(smiles),
        "population_policy": POPULATION_POLICY,
    }
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def _molraptor_profile_hash() -> str:
    serialized = json.dumps(
        _FINGERPRINT_PROFILE.serialize(),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def _molraptor_ordered_input_hash(smiles: tuple[str, ...]) -> str:
    serialized = json.dumps(
        smiles,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=False,
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
    eligible_status = selection_status.isin(
        {"selected", "no_eligible_activity"}
    )
    if not eligible_status.all():
        invalid_rows = ", ".join(
            str(index) for index in selection_status.index[~eligible_status]
        )
        raise ModelabilityIndexUseCaseError(
            "Reference_Selection_Status must contain only selected or "
            f"no_eligible_activity; invalid rows: {invalid_rows}."
        )
    prepared = prepared.loc[
        eligible_status,
        ["SMILES_Harmonized", "Outcome"],
    ].copy()
    prepared["SMILES_Harmonized"] = prepared["SMILES_Harmonized"].map(
        _clean_text
    )
    duplicates = prepared["SMILES_Harmonized"].duplicated(keep=False)
    if duplicates.any():
        duplicate_smiles = ", ".join(
            sorted(set(prepared.loc[duplicates, "SMILES_Harmonized"]))
        )
        raise ModelabilityIndexUseCaseError(
            "SMILES_Harmonized values must be unique; duplicates: "
            f"{duplicate_smiles}."
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
            "At least two consolidated structures are required."
        )

    smiles = tuple(prepared["SMILES_Harmonized"])
    outcomes = tuple(prepared["Outcome"])
    if set(outcomes) != {"Active", "Inactive"}:
        raise ModelabilityIndexUseCaseError(
            "Both Active and Inactive outcomes are required."
        )
    population_identity = _population_identity(smiles)
    return PreparedModelabilityInput(
        smiles=smiles,
        outcomes=outcomes,
        analysis_identity=_analysis_identity(smiles, outcomes),
        fingerprint_identity=_fingerprint_identity(population_identity),
        population_identity=population_identity,
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
    artifact = _calculate_fingerprint_artifact(prepared)
    return _calculate_with_fingerprint_artifact(
        prepared,
        artifact,
        fingerprint_source="calculated",
        source_table=source_table,
    )


def _calculate_fingerprint_artifact(
    prepared: PreparedModelabilityInput,
) -> FingerprintArtifact:
    smiles = prepared.smiles
    encoding = encode_fingerprints(smiles, _FINGERPRINT_PROFILE)

    if encoding.invalid_count:
        raise ModelabilityIndexUseCaseError(
            _invalid_encoding_message(encoding)
        )

    return build_fingerprint_artifact(
        encoding.fingerprints,
        smiles,
        profile=encoding.profile,
        profile_hash=str(encoding.profile_hash),
        ordered_input_hash=str(encoding.ordered_input_hash),
        molraptor_version=str(encoding.molraptor_version),
        rdkit_version=str(encoding.rdkit_version),
    )


def _calculate_with_fingerprint_artifact(
    prepared: PreparedModelabilityInput,
    artifact: FingerprintArtifact,
    *,
    fingerprint_source: str,
    source_table: str | None,
) -> ModelabilityIndexUseCaseResult:
    smiles = prepared.smiles
    outcomes = prepared.outcomes

    try:
        numerical = calculate_modelability_index(
            artifact.matrix,
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
        "fingerprint_profile": dict(_FINGERPRINT_PROFILE.serialize()),
        "molraptor_profile_hash": artifact.profile_hash,
        "molraptor_ordered_input_hash": artifact.ordered_input_hash,
        "chemvault_analysis_hash": prepared.analysis_identity,
        "molraptor_version": MOLRAPTOR_VERSION,
        "rdkit_version": RDKIT_VERSION,
        "fingerprint_source": fingerprint_source,
        "fingerprint_identity": (
            prepared.fingerprint_identity
            or _fingerprint_identity(
                prepared.population_identity or _population_identity(smiles)
            )
        ),
        "population_identity": (
            prepared.population_identity or _population_identity(smiles)
        ),
        "fingerprint_artifact_sha256": artifact.sha256,
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


def calculate_persisted_prepared_modelability_index(
    connection,
    prepared: PreparedModelabilityInput,
    *,
    source_table: str,
) -> ModelabilityIndexUseCaseResult:
    """Calculate Modelability with a reusable SQLite fingerprint artifact."""
    artifact, fingerprint_source = ensure_persisted_modelability_fingerprint_artifact(
        connection,
        prepared,
        source_table=source_table,
    )
    return _calculate_with_fingerprint_artifact(
        prepared,
        artifact,
        fingerprint_source=fingerprint_source,
        source_table=source_table,
    )


def ensure_persisted_modelability_fingerprint_artifact(
    connection,
    prepared: PreparedModelabilityInput,
    *,
    source_table: str,
) -> tuple[FingerprintArtifact, str]:
    """Restore or calculate the persisted fingerprint artifact only."""
    expectation = _fingerprint_artifact_expectation(
        prepared,
        source_table=source_table,
    )
    return restore_or_calculate_fingerprint_artifact(
        connection,
        expectation=expectation,
        calculate=lambda: _calculate_fingerprint_artifact(prepared),
    )


def _fingerprint_artifact_expectation(
    prepared: PreparedModelabilityInput,
    *,
    source_table: str,
) -> FingerprintArtifactExpectation:
    population_identity = (
        prepared.population_identity or _population_identity(prepared.smiles)
    )
    fingerprint_identity = (
        prepared.fingerprint_identity
        or _fingerprint_identity(population_identity)
    )
    return FingerprintArtifactExpectation(
        source_table=source_table,
        fingerprint_identity=fingerprint_identity,
        artifact_contract=FINGERPRINT_ARTIFACT_CONTRACT,
        artifact_contract_version=FINGERPRINT_ARTIFACT_CONTRACT_VERSION,
        population_identity=population_identity,
        profile=_FINGERPRINT_PROFILE.serialize(),
        profile_hash=_molraptor_profile_hash(),
        ordered_input_hash=_molraptor_ordered_input_hash(prepared.smiles),
        molraptor_version=MOLRAPTOR_VERSION,
        rdkit_version=RDKIT_VERSION,
        ordered_smiles=prepared.smiles,
        row_count=len(prepared.smiles),
        fp_size=_FINGERPRINT_PROFILE.fp_size,
    )


def export_modelability_fingerprints_npz(
    connection,
    prepared: PreparedModelabilityInput,
    *,
    database_id: str,
    source_table: str,
) -> tuple[bytes, str]:
    """Build an in-memory NPZ from an existing validated fingerprint artifact."""
    prefix = "activity_subset_"
    suffix = "_structure_consolidated"
    parsed_table_name = source_table
    table_name_base, separator, numeric_suffix = source_table.rpartition("_")
    if separator and numeric_suffix.isdigit() and int(numeric_suffix) >= 2:
        parsed_table_name = table_name_base
    if (
        not parsed_table_name.startswith(prefix)
        or not parsed_table_name.endswith(suffix)
        or len(parsed_table_name) <= len(prefix) + len(suffix)
    ):
        raise ModelabilityIndexUseCaseError(
            "Modelability source table does not contain an activity type."
        )
    activity_type = parsed_table_name[len(prefix):-len(suffix)]
    if len(prepared.outcomes) != len(prepared.smiles):
        raise ModelabilityIndexUseCaseError(
            "The number of outcomes must match the fingerprint rows."
        )
    if (
        _analysis_identity(prepared.smiles, prepared.outcomes)
        != prepared.analysis_identity
    ):
        raise ModelabilityIndexUseCaseError(
            "Prepared Modelability analysis identity does not match its rows."
        )
    expectation = _fingerprint_artifact_expectation(
        prepared,
        source_table=source_table,
    )
    artifact = read_fingerprint_artifact(
        connection,
        expectation=expectation,
    )

    try:
        outcomes = np.asarray(prepared.outcomes, dtype=np.str_)
        y = np.asarray(
            [_OUTCOME_MAPPING[outcome] for outcome in prepared.outcomes],
            dtype=np.uint8,
        )
    except KeyError as error:
        raise ModelabilityIndexUseCaseError(
            "Outcome must contain only Active or Inactive."
        ) from error

    metadata = {
        "analysis_identity": prepared.analysis_identity,
        "artifact_contract": expectation.artifact_contract,
        "artifact_contract_version": expectation.artifact_contract_version,
        "database_id": database_id,
        "fingerprint_artifact_sha256": artifact.sha256,
        "fingerprint_identity": expectation.fingerprint_identity,
        "fingerprint_profile": dict(artifact.profile),
        "matrix_format": MATRIX_FORMAT,
        "matrix_format_version": MATRIX_FORMAT_VERSION,
        "molraptor_ordered_input_hash": artifact.ordered_input_hash,
        "molraptor_profile_hash": artifact.profile_hash,
        "molraptor_version": artifact.molraptor_version,
        "outcome_mapping": dict(_OUTCOME_MAPPING),
        "population_identity": expectation.population_identity,
        "rdkit_version": artifact.rdkit_version,
        "schema_name": "chemvault_modelability_fingerprints",
        "schema_version": 1,
        "source_table": source_table,
    }
    metadata_json = json.dumps(
        metadata,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    smiles = np.asarray(prepared.smiles, dtype=np.str_)
    structure_ids = np.asarray(
        [
            hashlib.sha256(smiles_value.encode("utf-8")).hexdigest()
            for smiles_value in prepared.smiles
        ],
        dtype="<U64",
    )
    stream = io.BytesIO()
    np.savez_compressed(
        stream,
        X=artifact.matrix,
        SMILES_Harmonized=smiles,
        Outcome=outcomes,
        y=y,
        row_index=np.arange(len(prepared.smiles), dtype=np.int64),
        structure_id=structure_ids,
        metadata_json=np.asarray(metadata_json, dtype=np.str_),
    )

    filename = (
        f"{database_id}_{activity_type}_fingerprints_"
        f"{prepared.analysis_identity[:8]}.npz"
    )
    return stream.getvalue(), filename


def export_table_modelability_fingerprints_npz(
    database_id: str,
    source_table: str,
    analysis_identity: str,
    *,
    db_dir="SQL",
) -> tuple[bytes, str]:
    """Export fingerprints only when the current table matches the result."""
    db_path = resolve_database_path(database_id, db_dir=db_dir)
    connection = sqlite3.connect(db_path)
    try:
        prepared = prepare_table_modelability_input(
            connection,
            source_table,
            database_id=database_id,
        )
        if prepared.analysis_identity != analysis_identity:
            raise ModelabilityIndexUseCaseError(
                "Modelability source changed after the displayed result."
            )
        return export_modelability_fingerprints_npz(
            connection,
            prepared,
            database_id=database_id,
            source_table=source_table,
        )
    finally:
        connection.close()


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
        return calculate_persisted_prepared_modelability_index(
            connection,
            prepared,
            source_table=source_table,
        )
    finally:
        connection.close()
