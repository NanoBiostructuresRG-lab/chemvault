# SPDX-License-Identifier: LGPL-3.0-or-later
import sqlite3

from ui.main_page import (
    ACTIVITY_SUMMARY_COLUMNS,
    _filter_visible_column_options,
    _get_protein_traceability_summary,
)


def test_filter_visible_column_options_hides_only_activity_summary_columns():
    headers = [
        "primary_id",
        "CID",
        "AIDs",
        "Proteins",
        "Compound_Name",
        "Activity_Type",
        "Activity_Value",
        "Activity_Enrichment_Status",
        "Activity_Value_Raw",
    ]
    selected_headers = ["CID", "Activity_Type", "Activity_Value", "Activity_Value_Raw"]

    options, selected = _filter_visible_column_options(headers, selected_headers)

    assert options == [
        "primary_id",
        "CID",
        "AIDs",
        "Proteins",
        "Compound_Name",
        "Activity_Value_Raw",
    ]
    assert selected == ["CID", "Activity_Value_Raw"]


def test_activity_summary_columns_are_exact_legacy_main_columns():
    assert ACTIVITY_SUMMARY_COLUMNS == {
        "Activity_Type",
        "Activity_Value",
        "Activity_Enrichment_Status",
    }


def test_protein_traceability_summary_exposes_skipped_activity_status_count():
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE compound_assays (CID TEXT, AID TEXT, Protein TEXT)")
    connection.execute(
        """
        CREATE TABLE main (
            CID TEXT,
            Activity_Enrichment_Status TEXT
        )
        """
    )
    connection.executemany(
        "INSERT INTO compound_assays (CID, AID, Protein) VALUES (?, ?, ?)",
        [("1", "11", "P34971"), ("2", "12", "P34971")],
    )
    connection.executemany(
        "INSERT INTO main (CID, Activity_Enrichment_Status) VALUES (?, ?)",
        [("1", "skipped_aid_limit"), ("2", "skipped_aid_limit")],
    )

    summary = _get_protein_traceability_summary(connection)

    assert summary["activity_status"] == "skipped_aid_limit: 2"
    assert summary["activity_status_counts"] == {"skipped_aid_limit": 2}
