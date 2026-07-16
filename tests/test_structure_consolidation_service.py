# SPDX-License-Identifier: LGPL-3.0-or-later

import json

import pandas as pd
import pytest

from services.structure_consolidation import (
    StructureConsolidationError,
    consolidate_harmonized_structures,
)


def _row(
    cid,
    aid,
    outcome,
    smiles,
    status="ok",
    inchikey=None,
    activity_type="IC50",
    relation="",
    activity_value=1.0,
    activity_value_raw=None,
    unit="MICROMOLAR",
):
    return {
        "CID": cid,
        "AID": aid,
        "Outcome": outcome,
        "InChIKey": inchikey or f"KEY-{cid}",
        "SMILES_Harmonized": smiles,
        "SMILES_Harmonization_Status": status,
        "SMILES_RDKit": smiles,
        "MW": "100.0",
        "Charge": "0",
        "HeavyAtomCount": "7",
        "Activity_Type": activity_type,
        "Relation": relation,
        "Activity_Value": activity_value,
        "Activity_Value_Raw": (
            str(activity_value)
            if activity_value_raw is None
            else activity_value_raw
        ),
        "Unit": unit,
    }


def test_consolidates_repeated_structure_with_consistent_active_outcome():
    source = pd.DataFrame(
        [
            _row(20, 100, "Active", "CCO"),
            _row(20, 101, "Active", "CCO"),
            _row(20, 102, "Active", "CCO"),
        ]
    )

    result = consolidate_harmonized_structures(source)

    assert result.created_row_count == 1
    assert result.active_structure_count == 1
    assert result.inactive_structure_count == 0
    assert result.consolidated_duplicate_count == 2

    row = result.dataframe.iloc[0]

    assert row["Outcome"] == "Active"
    assert row["Reference_CID"] == "20"
    assert row["Reference_AID"] == "100"
    assert json.loads(row["Source_CIDs"]) == ["20"]
    assert json.loads(row["Source_AIDs"]) == ["100", "101", "102"]
    assert row["Source_Row_Count"] == 3
    assert row["Source_AID_Count"] == 3

    assert row["MW"] == "100.0"
    assert row["Charge"] == "0"
    assert row["HeavyAtomCount"] == "7"
    assert "MolecularWeight" not in result.dataframe.columns


def test_consolidates_distinct_cids_with_same_harmonized_structure():
    source = pd.DataFrame(
        [
            _row(200, 10, "Inactive", "CCC"),
            _row(100, 20, "Inactive", "CCC"),
        ]
    )

    result = consolidate_harmonized_structures(source)

    assert result.created_row_count == 1
    row = result.dataframe.iloc[0]
    assert row["Outcome"] == "Inactive"
    assert row["Reference_CID"] == "100"
    assert json.loads(row["Source_CIDs"]) == ["100", "200"]
    assert row["Source_Row_Count"] == 2


def test_reference_is_independent_of_source_row_order():
    rows = [
        {
            **_row(20, 200, "Active", "CCO"),
            "InChIKey": "KEY-LATER-AID",
            "MW": "101.0",
        },
        {
            **_row(20, 100, "Active", "CCO"),
            "InChIKey": "KEY-EARLIER-AID",
            "MW": "99.0",
        },
    ]

    forward = consolidate_harmonized_structures(pd.DataFrame(rows))
    reversed_result = consolidate_harmonized_structures(
        pd.DataFrame(list(reversed(rows)))
    )

    pd.testing.assert_frame_equal(forward.dataframe, reversed_result.dataframe)
    reference = forward.dataframe.iloc[0]
    assert reference["Reference_CID"] == "20"
    assert reference["Reference_AID"] == "100"
    assert reference["InChIKey"] == "KEY-EARLIER-AID"
    assert reference["MW"] == "99.0"


def test_geometric_mean_converts_nm_and_selects_nearest_in_log_space():
    source = pd.DataFrame(
        [
            _row(
                10,
                100,
                "Active",
                "CCO",
                relation="=",
                activity_value=100,
                unit="NANOMOLAR",
            ),
            _row(20, 200, "Active", "CCO", activity_value=1),
            _row(30, 300, "Active", "CCO", activity_value=10),
        ]
    )

    row = consolidate_harmonized_structures(source).dataframe.iloc[0]

    assert row["Geometric_Mean_Activity_uM"] == pytest.approx(1.0)
    assert row["Reference_CID"] == "20"
    assert row["Reference_AID"] == "200"
    assert row["Reference_Activity_Type"] == "IC50"
    assert row["Reference_Relation"] == ""
    assert row["Reference_Activity_Value"] == 1.0
    assert row["Reference_Activity_Value_Raw"] == "1"
    assert row["Reference_Unit"] == "MICROMOLAR"
    assert row["Reference_Activity_Value_uM"] == 1.0
    assert row["Reference_Selection_Status"] == "selected"


def test_cid_and_aid_break_only_equal_log_distance_ties():
    source = pd.DataFrame(
        [
            _row(20, 50, "Active", "CCO", activity_value=1),
            _row(10, 90, "Active", "CCO", activity_value=100),
            _row(10, 80, "Active", "CCO", activity_value=1),
            _row(20, 60, "Active", "CCO", activity_value=100),
        ]
    )

    row = consolidate_harmonized_structures(source).dataframe.iloc[0]

    assert row["Geometric_Mean_Activity_uM"] == pytest.approx(10.0)
    assert row["Reference_CID"] == "10"
    assert row["Reference_AID"] == "80"


def test_censored_observations_are_not_in_geometric_mean():
    source = pd.DataFrame(
        [
            _row(1, 1, "Inactive", "CCC", relation="<", activity_value=1),
            _row(2, 2, "Inactive", "CCC", relation="<=", activity_value=2),
            _row(3, 3, "Inactive", "CCC", relation=">", activity_value=30),
            _row(4, 4, "Inactive", "CCC", relation=">=", activity_value=40),
            _row(5, 5, "Inactive", "CCC", relation="=", activity_value=10),
        ]
    )

    row = consolidate_harmonized_structures(source).dataframe.iloc[0]

    assert row["Geometric_Mean_Activity_uM"] == pytest.approx(10.0)
    assert row["Reference_CID"] == "5"


def test_invalid_or_unconvertible_values_are_not_in_geometric_mean():
    source = pd.DataFrame(
        [
            _row(1, 1, "Active", "CCN", activity_value=10),
            _row(2, 2, "Active", "CCN", activity_value=0),
            _row(3, 3, "Active", "CCN", activity_value=-1),
            _row(4, 4, "Active", "CCN", activity_value=float("nan")),
            _row(5, 5, "Active", "CCN", activity_value=float("inf")),
            _row(6, 6, "Active", "CCN", activity_value="not-a-number"),
            _row(7, 7, "Active", "CCN", activity_value=100, unit="MILLIMOLAR"),
        ]
    )

    row = consolidate_harmonized_structures(source).dataframe.iloc[0]

    assert row["Geometric_Mean_Activity_uM"] == pytest.approx(10.0)
    assert row["Reference_CID"] == "1"


def test_no_eligible_activity_keeps_structure_with_null_reference_fields():
    source = pd.DataFrame(
        [
            _row(1, 1, "Active", "COC", relation=">", activity_value=10),
            _row(2, 2, "Active", "COC", activity_value=0),
            _row(3, 3, "Active", "COC", activity_value=1, unit="MOLAR"),
        ]
    )

    row = consolidate_harmonized_structures(source).dataframe.iloc[0]

    assert row["Outcome"] == "Active"
    assert row["Reference_Selection_Status"] == "no_eligible_activity"
    reference_fields = [
        "Reference_CID",
        "Reference_AID",
        "Reference_Activity_Type",
        "Reference_Relation",
        "Reference_Activity_Value",
        "Reference_Activity_Value_Raw",
        "Reference_Unit",
        "Reference_Activity_Value_uM",
        "Geometric_Mean_Activity_uM",
    ]
    assert all(pd.isna(row[column]) for column in reference_fields)


def test_mixed_activity_types_fail_clearly():
    source = pd.DataFrame(
        [
            _row(1, 1, "Active", "CCO", activity_type="IC50"),
            _row(2, 2, "Active", "CCC", activity_type="Ki"),
        ]
    )

    with pytest.raises(
        StructureConsolidationError,
        match="exactly one non-empty Activity_Type.*IC50, Ki",
    ):
        consolidate_harmonized_structures(source)


def test_summary_metrics_use_retained_groups_and_satisfy_invariants():
    source = pd.DataFrame(
        [
            _row(1, 1, "Active", "CCO", activity_value=1),
            _row(1, 2, "Active", "CCO", activity_value=2),
            _row(1, 3, "Active", "CCO", activity_value=4),
            _row(2, 4, "Inactive", "CCC", relation=">", activity_value=10),
            _row(3, 5, "Active", "CCN"),
            _row(3, 6, "Inactive", "CCN"),
            _row(3, 7, "Inactive", "CCN"),
        ]
    )

    result = consolidate_harmonized_structures(source)

    assert result.created_row_count == 2
    assert result.active_structure_count + result.inactive_structure_count == 2
    assert result.selected_reference_count == 1
    assert result.no_eligible_activity_count == 1
    assert result.selected_reference_count + result.no_eligible_activity_count == 2
    assert result.represented_source_row_count == 4
    assert result.consolidated_duplicate_count == 2
    assert (
        result.represented_source_row_count - result.created_row_count
        == result.consolidated_duplicate_count
    )


def test_outcome_evidence_uses_aid_unions_and_source_row_sums():
    source = pd.DataFrame(
        [
            _row(1, 10, "Active", "CCO"),
            _row(2, 11, "Active", "CCO"),
            _row(3, 11, "Active", "CCN"),
            _row(4, 12, "Active", "CCN"),
            _row(5, 20, "Inactive", "CCC"),
            _row(6, 20, "Inactive", "CCC"),
        ]
    )

    result = consolidate_harmonized_structures(source)

    assert result.active_structure_count == 2
    assert result.active_distinct_aid_count == 3
    assert result.active_source_observation_count == 4
    assert result.inactive_structure_count == 1
    assert result.inactive_distinct_aid_count == 1
    assert result.inactive_source_observation_count == 2
    assert result.represented_source_row_count == 6
    assert "Active_Distinct_AID_Count" not in result.dataframe.columns
    assert "Inactive_Distinct_AID_Count" not in result.dataframe.columns


def test_excludes_structure_with_active_inactive_conflict():
    source = pd.DataFrame(
        [
            _row(10, 1, "Active", "CCN"),
            _row(10, 2, "Inactive", "CCN"),
        ]
    )

    result = consolidate_harmonized_structures(source)

    assert result.created_row_count == 0
    assert result.conflicting_structure_count == 1
    assert result.excluded_conflicts[0]["reason"] == (
        "active_inactive_conflict"
    )


def test_active_inactive_conflict_takes_priority_over_extra_outcomes():
    source = pd.DataFrame(
        [
            _row(10, 1, "Active", "CCN"),
            _row(10, 2, "Inactive", "CCN"),
            _row(10, 3, "Inconclusive", "CCN"),
        ]
    )

    result = consolidate_harmonized_structures(source)

    assert result.conflicting_structure_count == 1
    assert result.non_binary_structure_count == 0


def test_excludes_failed_unsupported_and_missing_structures():
    source = pd.DataFrame(
        [
            _row(1, 1, "Active", "", status="failed"),
            _row(2, 2, "Inactive", "", status="unsupported"),
            _row(3, 3, "Active", "CCO", status="ok"),
        ]
    )

    result = consolidate_harmonized_structures(source)

    assert result.created_row_count == 1
    assert result.unusable_row_count == 2
    assert len(result.excluded_unusable) == 2


def test_excludes_non_binary_outcomes():
    source = pd.DataFrame(
        [
            _row(1, 1, "Inconclusive", "COC"),
            _row(1, 2, "Inconclusive", "COC"),
        ]
    )

    result = consolidate_harmonized_structures(source)

    assert result.created_row_count == 0
    assert result.non_binary_structure_count == 1


def test_all_excluded_input_still_returns_persistable_columns():
    source = pd.DataFrame(
        [
            _row(1, 1, "Active", "CCO"),
            _row(1, 2, "Inactive", "CCO"),
        ]
    )

    result = consolidate_harmonized_structures(source)

    assert result.dataframe.empty
    assert "SMILES_Harmonized" in result.dataframe.columns
    assert "Source_CIDs" in result.dataframe.columns
    assert "Source_AIDs" in result.dataframe.columns
    assert "Reference_CID" in result.dataframe.columns
    assert "Geometric_Mean_Activity_uM" in result.dataframe.columns


def test_does_not_modify_source_dataframe():
    source = pd.DataFrame([_row(1, 1, "Active", "CCO")])
    original = source.copy(deep=True)

    consolidate_harmonized_structures(source)

    pd.testing.assert_frame_equal(source, original)


def test_rejects_missing_required_columns():
    source = pd.DataFrame({"CID": [1], "Outcome": ["Active"]})

    with pytest.raises(
        StructureConsolidationError,
        match="missing required columns",
    ):
        consolidate_harmonized_structures(source)
