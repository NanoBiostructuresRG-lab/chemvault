# SPDX-License-Identifier: LGPL-3.0-or-later

import sqlite3

import numpy as np
import pandas as pd

from application import modelability_index as use_case
from services.modelability_fingerprint_artifacts import (
    FINGERPRINT_ARTIFACTS_TABLE,
    FingerprintArtifactExpectation,
    build_fingerprint_artifact,
    restore_or_calculate_fingerprint_artifact,
)


def _expectation(
    *,
    source_table="structures",
    fingerprint_identity="fingerprint-1",
):
    return FingerprintArtifactExpectation(
        source_table=source_table,
        fingerprint_identity=fingerprint_identity,
        artifact_contract="modelability_fingerprint_artifact",
        artifact_contract_version=1,
        population_identity="population-1",
        profile={"algorithm": "morgan", "fp_size": 4},
        profile_hash="profile-hash",
        ordered_input_hash="input-hash",
        molraptor_version="0.3.0",
        rdkit_version="test-rdkit",
        ordered_smiles=("CCC", "CCO"),
        row_count=2,
        fp_size=4,
    )


def _artifact(expectation, matrix=None):
    if matrix is None:
        matrix = np.array(
            [
                [1, 0, 0, 1],
                [0, 1, 1, 0],
            ],
            dtype=np.uint8,
        )

    return build_fingerprint_artifact(
        matrix,
        expectation.ordered_smiles,
        profile=expectation.profile,
        profile_hash=expectation.profile_hash,
        ordered_input_hash=expectation.ordered_input_hash,
        molraptor_version=expectation.molraptor_version,
        rdkit_version=expectation.rdkit_version,
    )


def test_calculates_and_persists_fingerprint_artifact():
    connection = sqlite3.connect(":memory:")
    expectation = _expectation()
    calculated = _artifact(expectation)

    artifact, source = restore_or_calculate_fingerprint_artifact(
        connection,
        expectation=expectation,
        calculate=lambda: calculated,
    )

    assert source == "calculated"
    assert np.array_equal(artifact.matrix, calculated.matrix)

    stored = connection.execute(
        f"""
        SELECT
            source_table,
            fingerprint_identity,
            artifact_contract,
            artifact_contract_version,
            population_identity,
            matrix_format,
            matrix_format_version,
            matrix_dtype,
            checksum
        FROM {FINGERPRINT_ARTIFACTS_TABLE}
        """
    ).fetchone()

    assert stored == (
        "structures",
        "fingerprint-1",
        "modelability_fingerprint_artifact",
        1,
        "population-1",
        "npy-zlib",
        1,
        "uint8",
        artifact.sha256,
    )

    connection.close()


def test_restores_valid_artifact_without_recalculation():
    connection = sqlite3.connect(":memory:")
    expectation = _expectation()

    first, first_source = restore_or_calculate_fingerprint_artifact(
        connection,
        expectation=expectation,
        calculate=lambda: _artifact(expectation),
    )

    def must_not_calculate():
        raise AssertionError("MOLRAPTOR fingerprint calculation was repeated")

    restored, restored_source = restore_or_calculate_fingerprint_artifact(
        connection,
        expectation=expectation,
        calculate=must_not_calculate,
    )

    assert first_source == "calculated"
    assert restored_source == "restored"
    assert restored.sha256 == first.sha256
    assert np.array_equal(restored.matrix, first.matrix)

    connection.close()


def test_outcome_change_reuses_same_fingerprint_artifact(monkeypatch):
    original = pd.DataFrame(
        {
            "SMILES_Harmonized": ["CCO", "CCC"],
            "Outcome": ["Active", "Inactive"],
            "Reference_Selection_Status": ["selected", "selected"],
        }
    )
    relabeled = original.copy()
    relabeled["Outcome"] = ["Inactive", "Active"]

    first_input = use_case.prepare_modelability_input(original)
    second_input = use_case.prepare_modelability_input(relabeled)

    assert first_input.analysis_identity != second_input.analysis_identity
    assert (
        first_input.population_identity
        == second_input.population_identity
    )
    assert (
        first_input.fingerprint_identity
        == second_input.fingerprint_identity
    )

    matrix = np.zeros(
        (
            len(first_input.smiles),
            use_case._FINGERPRINT_PROFILE.fp_size,
        ),
        dtype=np.uint8,
    )
    matrix[0, 0] = 1
    matrix[1, 1] = 1

    calculated_artifact = build_fingerprint_artifact(
        matrix,
        first_input.smiles,
        profile=use_case._FINGERPRINT_PROFILE.serialize(),
        profile_hash=use_case._molraptor_profile_hash(),
        ordered_input_hash=use_case._molraptor_ordered_input_hash(
            first_input.smiles
        ),
        molraptor_version=use_case.MOLRAPTOR_VERSION,
        rdkit_version=use_case.RDKIT_VERSION,
    )

    calculation_calls = []

    def calculate(prepared):
        calculation_calls.append(prepared)
        return calculated_artifact

    monkeypatch.setattr(
        use_case,
        "_calculate_fingerprint_artifact",
        calculate,
    )

    connection = sqlite3.connect(":memory:")

    first_result = (
        use_case.calculate_persisted_prepared_modelability_index(
            connection,
            first_input,
            source_table="structures",
        )
    )
    second_result = (
        use_case.calculate_persisted_prepared_modelability_index(
            connection,
            second_input,
            source_table="structures",
        )
    )

    assert len(calculation_calls) == 1
    assert first_result.provenance["fingerprint_source"] == "calculated"
    assert second_result.provenance["fingerprint_source"] == "restored"
    assert (
        first_result.provenance["fingerprint_identity"]
        == second_result.provenance["fingerprint_identity"]
    )

    connection.close()


def test_corrupt_artifact_is_recalculated_and_replaced():
    connection = sqlite3.connect(":memory:")
    expectation = _expectation()

    original, original_source = restore_or_calculate_fingerprint_artifact(
        connection,
        expectation=expectation,
        calculate=lambda: _artifact(expectation),
    )
    assert original_source == "calculated"

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

    replacement_matrix = np.array(
        [
            [1, 1, 0, 0],
            [0, 0, 1, 1],
        ],
        dtype=np.uint8,
    )
    replacement = _artifact(expectation, replacement_matrix)
    calculation_calls = []

    def recalculate():
        calculation_calls.append(True)
        return replacement

    recovered, recovered_source = (
        restore_or_calculate_fingerprint_artifact(
            connection,
            expectation=expectation,
            calculate=recalculate,
        )
    )

    assert recovered_source == "calculated"
    assert len(calculation_calls) == 1
    assert recovered.sha256 != original.sha256
    assert np.array_equal(recovered.matrix, replacement_matrix)

    def must_not_calculate():
        raise AssertionError("repaired artifact was not restored")

    restored, restored_source = restore_or_calculate_fingerprint_artifact(
        connection,
        expectation=expectation,
        calculate=must_not_calculate,
    )

    assert restored_source == "restored"
    assert restored.sha256 == recovered.sha256
    assert np.array_equal(restored.matrix, replacement_matrix)

    connection.close()