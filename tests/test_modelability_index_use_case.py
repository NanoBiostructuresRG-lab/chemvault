# SPDX-License-Identifier: LGPL-3.0-or-later

import sqlite3
from types import SimpleNamespace

import pandas as pd
import pytest

from application import modelability_index as use_case
from application.modelability_index import ModelabilityIndexUseCaseError


def _source():
    return pd.DataFrame(
        [
            {
                "SMILES_Harmonized": "CCO",
                "Outcome": " active ",
                "Reference_Selection_Status": " Selected ",
            },
            {
                "SMILES_Harmonized": "CCCO",
                "Outcome": " ACTIVE ",
                "Reference_Selection_Status": " No_Eligible_Activity ",
            },
            {
                "SMILES_Harmonized": "c1ccccc1",
                "Outcome": "inactive",
                "Reference_Selection_Status": "SELECTED",
            },
            {
                "SMILES_Harmonized": "c1ccncc1",
                "Outcome": " Inactive ",
                "Reference_Selection_Status": "no_eligible_activity",
            },
        ]
    )


def test_uses_normalized_consolidated_binary_rows_with_fixed_provenance(
    monkeypatch,
):
    assert use_case.POPULATION_POLICY == "consolidated_binary_outcomes/v1"
    real_encode = use_case.encode_fingerprints

    def checked_encode(smiles, profile):
        assert profile is use_case._FINGERPRINT_PROFILE
        return real_encode(smiles, profile)

    monkeypatch.setattr(use_case, "encode_fingerprints", checked_encode)

    result = use_case.calculate_dataframe_modelability_index(
        _source(),
        source_table="structures",
    )

    assert result.structure_count == 4
    assert result.active_count == 2
    assert result.inactive_count == 2
    assert {item["outcome"] for item in result.diagnostics} == {
        "Active",
        "Inactive",
    }
    assert {item["smiles"] for item in result.diagnostics} == {
        "CCO",
        "CCCO",
        "c1ccccc1",
        "c1ccncc1",
    }

    provenance = result.provenance
    assert provenance["source_table"] == "structures"
    assert provenance["fingerprint_profile"] == {
        "profile_schema_version": "1.0",
        "algorithm": "morgan",
        "output_type": "binary-bit-vector",
        "radius": 2,
        "fp_size": 2048,
        "include_chirality": False,
        "use_bond_types": True,
        "include_ring_membership": True,
        "include_redundant_environments": False,
        "invariant_policy": "rdkit-default",
    }
    assert provenance["molraptor_version"] == "0.3.0"
    assert provenance["rdkit_version"]
    assert provenance["molraptor_profile_hash"]
    assert provenance["molraptor_ordered_input_hash"]
    assert provenance["chemvault_analysis_hash"]
    assert provenance["similarity_metric"] == "tanimoto"
    assert provenance["neighbor_rule"] == "single_nearest_neighbor"
    assert provenance["tie_policy"] == "lowest_ordered_index"
    assert provenance["aggregation"] == "macro_average"


def test_source_row_order_does_not_change_result():
    source = _source()

    forward = use_case.calculate_dataframe_modelability_index(source)
    reverse = use_case.calculate_dataframe_modelability_index(
        source.iloc[::-1].reset_index(drop=True)
    )

    assert forward == reverse


def test_analysis_hash_includes_outcomes_but_molraptor_hash_does_not():
    original = _source()
    relabeled = _source()
    relabeled.loc[0, "Outcome"] = "Inactive"
    relabeled.loc[2, "Outcome"] = "Active"

    first = use_case.calculate_dataframe_modelability_index(original)
    second = use_case.calculate_dataframe_modelability_index(relabeled)

    assert (
        first.provenance["molraptor_ordered_input_hash"]
        == second.provenance["molraptor_ordered_input_hash"]
    )
    assert (
        first.provenance["chemvault_analysis_hash"]
        != second.provenance["chemvault_analysis_hash"]
    )


def test_any_molraptor_invalid_input_fails_without_partial_calculation(
    monkeypatch,
):
    encoding = SimpleNamespace(
        invalid_count=1,
        input_statuses=(
            SimpleNamespace(
                input_index=0,
                input_smiles="BAD",
                status="invalid",
                invalid_reason="parse_failure",
            ),
        ),
    )
    monkeypatch.setattr(
        use_case,
        "encode_fingerprints",
        lambda smiles, profile: encoding,
    )

    def must_not_calculate(*args, **kwargs):
        raise AssertionError("partial Modelability Index was calculated")

    monkeypatch.setattr(
        use_case,
        "calculate_modelability_index",
        must_not_calculate,
    )
    source = pd.DataFrame(
        {
            "SMILES_Harmonized": ["BAD", "CCO"],
            "Outcome": ["Active", "Inactive"],
            "Reference_Selection_Status": ["selected", "selected"],
        }
    )

    with pytest.raises(
        ModelabilityIndexUseCaseError,
        match=r"MOLRAPTOR rejected.*BAD.*parse_failure",
    ):
        use_case.calculate_dataframe_modelability_index(source)


def test_sqlite_reader_uses_all_required_columns_and_prepared_boundary(
    tmp_path,
    monkeypatch,
):
    db_dir = tmp_path / "SQL"
    db_dir.mkdir()
    connection = sqlite3.connect(db_dir / "target.db")
    _source().to_sql("structures", connection, index=False)
    connection.close()
    captured = {}
    sentinel = object()

    def capture_prepared(connection, prepared, *, source_table):
        captured["connection"] = connection
        captured["prepared"] = prepared
        captured["source_table"] = source_table
        return sentinel

    monkeypatch.setattr(
        use_case,
        "calculate_persisted_prepared_modelability_index",
        capture_prepared,
    )

    result = use_case.calculate_table_modelability_index(
        "target",
        "structures",
        db_dir=db_dir,
    )

    assert result is sentinel
    assert isinstance(captured["connection"], sqlite3.Connection)
    assert isinstance(
        captured["prepared"],
        use_case.PreparedModelabilityInput,
    )
    assert captured["prepared"].smiles == (
        "CCCO",
        "CCO",
        "c1ccccc1",
        "c1ccncc1",
    )
    assert captured["prepared"].outcomes == (
        "Active",
        "Active",
        "Inactive",
        "Inactive",
    )
    assert captured["source_table"] == "structures"


def test_table_preparation_checks_real_schema_without_loading_rows(monkeypatch):
    connection = sqlite3.connect(":memory:")
    connection.execute(
        "CREATE TABLE structures (SMILES_Harmonized TEXT, Outcome TEXT)"
    )

    def must_not_read_data(*_args, **_kwargs):
        raise AssertionError("the data SELECT was executed")

    monkeypatch.setattr(use_case.pd, "read_sql_query", must_not_read_data)

    with pytest.raises(
        ModelabilityIndexUseCaseError,
        match=(
            "The source table is missing required columns: "
            "Reference_Selection_Status"
        ),
    ):
        use_case.prepare_table_modelability_input(connection, "structures")

    connection.close()


def test_rejects_missing_columns_and_non_binary_outcomes():
    with pytest.raises(ModelabilityIndexUseCaseError, match="Outcome"):
        use_case.calculate_dataframe_modelability_index(
            pd.DataFrame({"SMILES_Harmonized": ["CCO"]})
        )

    with pytest.raises(
        ModelabilityIndexUseCaseError,
        match="only Active or Inactive",
    ):
        use_case.calculate_dataframe_modelability_index(
            pd.DataFrame(
                {
                    "SMILES_Harmonized": ["CCO", "CCC"],
                    "Outcome": ["Active", "Unknown"],
                    "Reference_Selection_Status": ["selected", "selected"],
                }
            )
        )


@pytest.mark.parametrize(
    "invalid_status",
    ["", "excluded"],
    ids=["blank", "unexpected"],
)
def test_rejects_invalid_reference_status_before_encoding(
    monkeypatch,
    invalid_status,
):
    source = pd.DataFrame(
        {
            "SMILES_Harmonized": ["CCO", "CCC"],
            "Outcome": ["Active", "Inactive"],
            "Reference_Selection_Status": ["selected", invalid_status],
        }
    )

    def must_not_encode(*_args, **_kwargs):
        raise AssertionError("MOLRAPTOR was called")

    monkeypatch.setattr(use_case, "encode_fingerprints", must_not_encode)

    with pytest.raises(
        ModelabilityIndexUseCaseError,
        match=(
            "Reference_Selection_Status must contain only selected or "
            "no_eligible_activity"
        ),
    ):
        use_case.calculate_dataframe_modelability_index(source)


@pytest.mark.parametrize("row_count", [0, 1], ids=["empty", "one_row"])
def test_rejects_too_few_structures_before_encoding(monkeypatch, row_count):
    source = pd.DataFrame(
        {
            "SMILES_Harmonized": ["CCO"],
            "Outcome": ["Active"],
            "Reference_Selection_Status": ["selected"],
        }
    ).iloc[:row_count]

    def must_not_encode(*args, **kwargs):
        raise AssertionError("MOLRAPTOR was called")

    monkeypatch.setattr(use_case, "encode_fingerprints", must_not_encode)

    with pytest.raises(ModelabilityIndexUseCaseError, match="At least two"):
        use_case.calculate_dataframe_modelability_index(source)


def test_rejects_consolidated_population_without_both_classes_before_encoding(
    monkeypatch,
):
    source = pd.DataFrame(
        {
            "SMILES_Harmonized": ["CCO", "CCC", "CCN"],
            "Outcome": ["Active", "Active", "Active"],
            "Reference_Selection_Status": [
                "selected",
                "selected",
                "no_eligible_activity",
            ],
        }
    )

    def must_not_encode(*_args, **_kwargs):
        raise AssertionError("MOLRAPTOR was called")

    monkeypatch.setattr(use_case, "encode_fingerprints", must_not_encode)

    with pytest.raises(
        ModelabilityIndexUseCaseError,
        match="Both Active and Inactive",
    ):
        use_case.calculate_dataframe_modelability_index(source)


def test_selected_active_and_no_eligible_activity_inactive_are_valid():
    source = pd.DataFrame(
        {
            "SMILES_Harmonized": ["CCO", "CCC"],
            "Outcome": ["Active", "Inactive"],
            "Reference_Selection_Status": [
                "selected",
                "no_eligible_activity",
            ],
        }
    )

    prepared = use_case.prepare_modelability_input(source)

    assert prepared.smiles == ("CCC", "CCO")
    assert prepared.outcomes == ("Inactive", "Active")
