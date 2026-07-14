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
    assert row["Representative_CID"] == "20"
    assert row["Representative_AID"] == "100"
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
    assert row["Representative_CID"] == "100"
    assert json.loads(row["Source_CIDs"]) == ["100", "200"]
    assert row["Source_Row_Count"] == 2


def test_representative_is_independent_of_source_row_order():
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
    representative = forward.dataframe.iloc[0]
    assert representative["Representative_CID"] == "20"
    assert representative["Representative_AID"] == "100"
    assert representative["InChIKey"] == "KEY-EARLIER-AID"
    assert representative["MW"] == "99.0"


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
        [_row(1, 1, "Active", "", status="failed")]
    )

    result = consolidate_harmonized_structures(source)

    assert result.dataframe.empty
    assert "SMILES_Harmonized" in result.dataframe.columns
    assert "Source_CIDs" in result.dataframe.columns
    assert "Source_AIDs" in result.dataframe.columns


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
