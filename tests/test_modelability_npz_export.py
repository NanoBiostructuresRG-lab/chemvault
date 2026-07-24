# SPDX-License-Identifier: LGPL-3.0-or-later

import hashlib
import io
import json
import sqlite3
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from application import modelability_index as use_case
from application.modelability_index import ModelabilityIndexUseCaseError
from services.modelability_fingerprint_artifacts import (
    FINGERPRINT_ARTIFACTS_TABLE,
    MATRIX_FORMAT,
    MATRIX_FORMAT_VERSION,
    FingerprintArtifactError,
    build_fingerprint_artifact,
    restore_or_calculate_fingerprint_artifact,
)


DATABASE_ID = "P37231"
SOURCE_TABLE = "activity_subset_EC50_structure_consolidated"


def _prepared_input():
    source = pd.DataFrame(
        {
            "SMILES_Harmonized": ["CCO", "CCC"],
            "Outcome": ["Active", "Inactive"],
            "Reference_Selection_Status": ["selected", "selected"],
        }
    )
    return use_case.prepare_modelability_input(source)


def _persist_artifact(connection, prepared, *, source_table=SOURCE_TABLE):
    expectation = use_case._fingerprint_artifact_expectation(
        prepared,
        source_table=source_table,
    )
    matrix = np.zeros(
        (len(prepared.smiles), expectation.fp_size),
        dtype=np.uint8,
    )
    matrix[0, 0] = 1
    matrix[1, 1] = 1

    calculated = build_fingerprint_artifact(
        matrix,
        prepared.smiles,
        profile=expectation.profile,
        profile_hash=expectation.profile_hash,
        ordered_input_hash=expectation.ordered_input_hash,
        molraptor_version=expectation.molraptor_version,
        rdkit_version=expectation.rdkit_version,
    )
    artifact, source = restore_or_calculate_fingerprint_artifact(
        connection,
        expectation=expectation,
        calculate=lambda: calculated,
    )

    assert source == "calculated"
    return expectation, artifact


def test_exports_self_contained_npz_without_calling_molraptor(monkeypatch):
    connection = sqlite3.connect(":memory:")
    try:
        prepared = _prepared_input()
        expectation, artifact = _persist_artifact(connection, prepared)

        def must_not_encode(*_args, **_kwargs):
            raise AssertionError("MOLRAPTOR was called during NPZ export")

        monkeypatch.setattr(
            use_case,
            "encode_fingerprints",
            must_not_encode,
        )

        payload, filename = use_case.export_modelability_fingerprints_npz(
            connection,
            prepared,
            database_id=DATABASE_ID,
            source_table=SOURCE_TABLE,
        )

        assert filename == (
            f"P37231_EC50_fingerprints_"
            f"{prepared.analysis_identity[:8]}.npz"
        )

        with np.load(io.BytesIO(payload), allow_pickle=False) as exported:
            assert set(exported.files) == {
                "X",
                "SMILES_Harmonized",
                "Outcome",
                "y",
                "row_index",
                "structure_id",
                "metadata_json",
            }

            np.testing.assert_array_equal(exported["X"], artifact.matrix)
            np.testing.assert_array_equal(
                exported["SMILES_Harmonized"],
                np.asarray(prepared.smiles, dtype=np.str_),
            )
            np.testing.assert_array_equal(
                exported["Outcome"],
                np.asarray(prepared.outcomes, dtype=np.str_),
            )
            np.testing.assert_array_equal(
                exported["y"],
                np.asarray([0, 1], dtype=np.uint8),
            )
            np.testing.assert_array_equal(
                exported["row_index"],
                np.asarray([0, 1], dtype=np.int64),
            )

            expected_structure_ids = np.asarray(
                [
                    hashlib.sha256(smiles.encode("utf-8")).hexdigest()
                    for smiles in prepared.smiles
                ],
                dtype="<U64",
            )
            np.testing.assert_array_equal(
                exported["structure_id"],
                expected_structure_ids,
            )

            assert exported["X"].dtype == np.dtype(np.uint8)
            assert exported["y"].dtype == np.dtype(np.uint8)
            assert exported["row_index"].dtype == np.dtype(np.int64)
            assert exported["SMILES_Harmonized"].dtype.kind == "U"
            assert exported["Outcome"].dtype.kind == "U"
            assert exported["structure_id"].dtype.kind == "U"
            assert exported["metadata_json"].dtype.kind == "U"
            assert exported["metadata_json"].shape == ()

            metadata = json.loads(exported["metadata_json"].item())

        assert set(metadata) == {
            "schema_name",
            "schema_version",
            "database_id",
            "source_table",
            "population_identity",
            "fingerprint_identity",
            "analysis_identity",
            "fingerprint_artifact_sha256",
            "fingerprint_profile",
            "molraptor_profile_hash",
            "molraptor_ordered_input_hash",
            "molraptor_version",
            "rdkit_version",
            "artifact_contract",
            "artifact_contract_version",
            "matrix_format",
            "matrix_format_version",
            "outcome_mapping",
        }
        assert metadata["schema_name"] == (
            "chemvault_modelability_fingerprints"
        )
        assert metadata["schema_version"] == 1
        assert metadata["database_id"] == DATABASE_ID
        assert metadata["source_table"] == SOURCE_TABLE
        assert metadata["population_identity"] == (
            prepared.population_identity
        )
        assert metadata["fingerprint_identity"] == (
            prepared.fingerprint_identity
        )
        assert metadata["analysis_identity"] == prepared.analysis_identity
        assert metadata["fingerprint_artifact_sha256"] == artifact.sha256
        assert metadata["fingerprint_profile"] == dict(expectation.profile)
        assert metadata["molraptor_profile_hash"] == (
            expectation.profile_hash
        )
        assert metadata["molraptor_ordered_input_hash"] == (
            expectation.ordered_input_hash
        )
        assert metadata["molraptor_version"] == (
            expectation.molraptor_version
        )
        assert metadata["rdkit_version"] == expectation.rdkit_version
        assert metadata["artifact_contract"] == (
            expectation.artifact_contract
        )
        assert metadata["artifact_contract_version"] == (
            expectation.artifact_contract_version
        )
        assert metadata["matrix_format"] == MATRIX_FORMAT
        assert metadata["matrix_format_version"] == MATRIX_FORMAT_VERSION
        assert metadata["outcome_mapping"] == {
            "Inactive": 0,
            "Active": 1,
        }
    finally:
        connection.close()


def test_export_accepts_numbered_consolidated_table_name():
    connection = sqlite3.connect(":memory:")
    source_table = "activity_subset_IC50_structure_consolidated_2"
    try:
        prepared = _prepared_input()
        _persist_artifact(
            connection,
            prepared,
            source_table=source_table,
        )

        payload, filename = use_case.export_modelability_fingerprints_npz(
            connection,
            prepared,
            database_id=DATABASE_ID,
            source_table=source_table,
        )

        assert payload
        assert filename == (
            f"P37231_IC50_fingerprints_"
            f"{prepared.analysis_identity[:8]}.npz"
        )
    finally:
        connection.close()


def test_export_rejects_mismatched_analysis_identity():
    connection = sqlite3.connect(":memory:")
    try:
        prepared = _prepared_input()
        invalid = replace(
            prepared,
            analysis_identity="0" * 64,
        )

        with pytest.raises(
            ModelabilityIndexUseCaseError,
            match="analysis identity does not match",
        ):
            use_case.export_modelability_fingerprints_npz(
                connection,
                invalid,
                database_id=DATABASE_ID,
                source_table=SOURCE_TABLE,
            )
    finally:
        connection.close()


def test_export_rejects_source_table_without_activity_type():
    connection = sqlite3.connect(":memory:")
    try:
        prepared = _prepared_input()

        with pytest.raises(
            ModelabilityIndexUseCaseError,
            match="does not contain an activity type",
        ):
            use_case.export_modelability_fingerprints_npz(
                connection,
                prepared,
                database_id=DATABASE_ID,
                source_table="structures",
            )
    finally:
        connection.close()


def test_export_rejects_missing_fingerprint_artifact():
    connection = sqlite3.connect(":memory:")
    try:
        prepared = _prepared_input()

        with pytest.raises(
            FingerprintArtifactError,
            match="missing, corrupt, or incompatible",
        ):
            use_case.export_modelability_fingerprints_npz(
                connection,
                prepared,
                database_id=DATABASE_ID,
                source_table=SOURCE_TABLE,
            )
    finally:
        connection.close()


def test_export_rejects_corrupt_fingerprint_artifact():
    connection = sqlite3.connect(":memory:")
    try:
        prepared = _prepared_input()
        expectation, _artifact = _persist_artifact(connection, prepared)

        connection.execute(
            f"""
            UPDATE {FINGERPRINT_ARTIFACTS_TABLE}
            SET matrix_payload = ?
            WHERE source_table = ?
              AND fingerprint_identity = ?
            """,
            (
                sqlite3.Binary(b"corrupt-payload"),
                expectation.source_table,
                expectation.fingerprint_identity,
            ),
        )
        connection.commit()

        with pytest.raises(
            FingerprintArtifactError,
            match="missing, corrupt, or incompatible",
        ):
            use_case.export_modelability_fingerprints_npz(
                connection,
                prepared,
                database_id=DATABASE_ID,
                source_table=SOURCE_TABLE,
            )
    finally:
        connection.close()
