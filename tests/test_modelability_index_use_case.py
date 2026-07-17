# SPDX-License-Identifier: LGPL-3.0-or-later

import sqlite3
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from molraptor import MorganFingerprintProfile

from application import modelability_index as use_case
from application.database_use_cases import TableNotFoundError
from application.modelability_index import (
    ModelabilityIndexUseCaseError,
)


def _source(rows=None):
    if rows is None:
        rows = [
            {
                "SMILES_Harmonized": "CCO",
                "Outcome": "Active",
                "Reference_Selection_Status": "selected",
            },
            {
                "SMILES_Harmonized": "CCCO",
                "Outcome": "Active",
                "Reference_Selection_Status": "no_eligible_activity",
            },
            {
                "SMILES_Harmonized": "c1ccccc1",
                "Outcome": "Inactive",
                "Reference_Selection_Status": "selected",
            },
            {
                "SMILES_Harmonized": "c1ccncc1",
                "Outcome": "Inactive",
                "Reference_Selection_Status": "no_eligible_activity",
            },
        ]
    return pd.DataFrame(rows)


def test_uses_all_binary_structures_without_reference_status_filter():
    result = use_case.calculate_dataframe_modelability_index(_source())

    assert result.source_row_count == 4
    assert result.encoded_structure_count == 4
    assert result.excluded_structure_count == 0
    assert result.active_count == 2
    assert result.inactive_count == 2
    assert len(result.diagnostics) == 4

    assert result.molraptor_version == "0.2.0"
    assert result.fingerprint_profile["algorithm"] == "morgan"
    assert result.fingerprint_profile["radius"] == 2
    assert result.fingerprint_profile["fp_size"] == 2048
    assert result.fingerprint_shape == (4, 2048)
    assert result.fingerprint_dtype == "uint8"


def test_result_is_independent_of_source_row_order():
    source = _source()

    forward = use_case.calculate_dataframe_modelability_index(source)
    reversed_result = use_case.calculate_dataframe_modelability_index(
        source.iloc[::-1].reset_index(drop=True)
    )

    assert forward.modelability_index == reversed_result.modelability_index
    assert forward.active_contribution == reversed_result.active_contribution
    assert (
        forward.inactive_contribution
        == reversed_result.inactive_contribution
    )
    assert forward.ordered_input_hash == reversed_result.ordered_input_hash

    forward_pairs = tuple(
        (
            item.smiles_harmonized,
            item.nearest_neighbor_smiles_harmonized,
            item.tanimoto_similarity,
        )
        for item in forward.diagnostics
    )
    reversed_pairs = tuple(
        (
            item.smiles_harmonized,
            item.nearest_neighbor_smiles_harmonized,
            item.tanimoto_similarity,
        )
        for item in reversed_result.diagnostics
    )
    assert forward_pairs == reversed_pairs


def test_maps_invalid_encoding_to_traceable_exclusion(monkeypatch):
    source = _source(
        [
            {
                "SMILES_Harmonized": "AA",
                "Outcome": "Active",
            },
            {
                "SMILES_Harmonized": "AB",
                "Outcome": "Active",
            },
            {
                "SMILES_Harmonized": "BAD",
                "Outcome": "Active",
            },
            {
                "SMILES_Harmonized": "BA",
                "Outcome": "Inactive",
            },
            {
                "SMILES_Harmonized": "BB",
                "Outcome": "Inactive",
            },
        ]
    )

    def fake_encode(smiles, profile):
        assert smiles == ("AA", "AB", "BA", "BAD", "BB")
        return SimpleNamespace(
            fingerprints=np.asarray(
                [
                    [1, 1, 0, 0],
                    [1, 1, 0, 1],
                    [0, 0, 1, 1],
                    [0, 0, 1, 0],
                ],
                dtype=np.uint8,
            ),
            profile=profile.model_dump(mode="json"),
            valid_indices=(0, 1, 2, 4),
            input_statuses=(
                SimpleNamespace(
                    input_index=0,
                    input_smiles="AA",
                    status="valid",
                    rdkit_canonical_smiles="AA",
                    fingerprint_index=0,
                    invalid_reason=None,
                ),
                SimpleNamespace(
                    input_index=1,
                    input_smiles="AB",
                    status="valid",
                    rdkit_canonical_smiles="AB",
                    fingerprint_index=1,
                    invalid_reason=None,
                ),
                SimpleNamespace(
                    input_index=2,
                    input_smiles="BA",
                    status="valid",
                    rdkit_canonical_smiles="BA",
                    fingerprint_index=2,
                    invalid_reason=None,
                ),
                SimpleNamespace(
                    input_index=3,
                    input_smiles="BAD",
                    status="invalid",
                    rdkit_canonical_smiles=None,
                    fingerprint_index=None,
                    invalid_reason="parse_failure",
                ),
                SimpleNamespace(
                    input_index=4,
                    input_smiles="BB",
                    status="valid",
                    rdkit_canonical_smiles="BB",
                    fingerprint_index=3,
                    invalid_reason=None,
                ),
            ),
            valid_count=4,
            invalid_count=1,
            matrix_shape=(4, 4),
            matrix_dtype="uint8",
            molraptor_version="0.2.0",
            rdkit_version="test",
            ordered_input_hash="input-hash",
            profile_hash="profile-hash",
        )

    monkeypatch.setattr(use_case, "encode_fingerprints", fake_encode)

    result = use_case.calculate_dataframe_modelability_index(source)

    assert result.encoded_structure_count == 4
    assert result.excluded_structure_count == 1
    assert result.modelability_index == pytest.approx(1.0)

    assert result.exclusions == (
        use_case.ModelabilityEncodingExclusion(
            input_index=3,
            source_row_index=2,
            smiles_harmonized="BAD",
            outcome="Active",
            reason="parse_failure",
        ),
    )


def test_custom_profile_is_passed_to_molraptor():
    profile = MorganFingerprintProfile(
        radius=3,
        fp_size=512,
        include_chirality=True,
    )

    result = use_case.calculate_dataframe_modelability_index(
        _source(),
        profile=profile,
    )

    assert result.fingerprint_profile["radius"] == 3
    assert result.fingerprint_profile["fp_size"] == 512
    assert result.fingerprint_profile["include_chirality"] is True
    assert result.fingerprint_shape == (4, 512)


def test_rejects_missing_required_columns():
    with pytest.raises(
        ModelabilityIndexUseCaseError,
        match="missing required columns: Outcome",
    ):
        use_case.calculate_dataframe_modelability_index(
            pd.DataFrame({"SMILES_Harmonized": ["CCO"]})
        )


def test_rejects_non_binary_outcome():
    with pytest.raises(
        ModelabilityIndexUseCaseError,
        match="only Active or Inactive",
    ):
        use_case.calculate_dataframe_modelability_index(
            _source(
                [
                    {
                        "SMILES_Harmonized": "CCO",
                        "Outcome": "Active",
                    },
                    {
                        "SMILES_Harmonized": "CCC",
                        "Outcome": "Unknown",
                    },
                ]
            )
        )


def test_rejects_duplicate_harmonized_structures():
    with pytest.raises(
        ModelabilityIndexUseCaseError,
        match="duplicated SMILES_Harmonized values: CCO",
    ):
        use_case.calculate_dataframe_modelability_index(
            _source(
                [
                    {
                        "SMILES_Harmonized": "CCO",
                        "Outcome": "Active",
                    },
                    {
                        "SMILES_Harmonized": "CCO",
                        "Outcome": "Inactive",
                    },
                ]
            )
        )


def test_wraps_core_population_error_after_encoding():
    with pytest.raises(
        ModelabilityIndexUseCaseError,
        match="at least two structures",
    ):
        use_case.calculate_dataframe_modelability_index(
            _source(
                [
                    {
                        "SMILES_Harmonized": "CCO",
                        "Outcome": "Active",
                    },
                    {
                        "SMILES_Harmonized": "CCCO",
                        "Outcome": "Active",
                    },
                    {
                        "SMILES_Harmonized": "c1ccccc1",
                        "Outcome": "Inactive",
                    },
                ]
            )
        )


def test_reads_selected_columns_from_existing_sqlite_table(tmp_path):
    db_dir = tmp_path / "SQL"
    db_dir.mkdir()
    db_path = db_dir / "target.db"

    connection = sqlite3.connect(db_path)
    _source().to_sql(
        "activity_subset_EC50_structure_consolidated",
        connection,
        index=False,
    )
    connection.close()

    result = use_case.calculate_table_modelability_index(
        "target",
        "activity_subset_EC50_structure_consolidated",
        db_dir=db_dir,
    )

    assert (
        result.source_table
        == "activity_subset_EC50_structure_consolidated"
    )
    assert result.source_row_count == 4
    assert result.active_count == 2
    assert result.inactive_count == 2


def test_rejects_missing_sqlite_table(tmp_path):
    db_dir = tmp_path / "SQL"
    db_dir.mkdir()
    sqlite3.connect(db_dir / "target.db").close()

    with pytest.raises(TableNotFoundError, match="was not found"):
        use_case.calculate_table_modelability_index(
            "target",
            "missing",
            db_dir=db_dir,
        )