# SPDX-License-Identifier: LGPL-3.0-or-later
import sqlite3

from ui.main_page import (
    ACTIVITY_SUMMARY_COLUMNS,
    _filter_visible_column_options,
    _get_activity_enrichment_job_summary,
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


def test_activity_enrichment_job_summary_handles_missing_compound_assays():
    connection = sqlite3.connect(":memory:")

    assert _get_activity_enrichment_job_summary(connection) is None


def test_activity_enrichment_job_summary_handles_empty_compound_assays():
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE compound_assays (CID TEXT, AID TEXT, Protein TEXT)")

    assert _get_activity_enrichment_job_summary(connection) is None


def test_activity_enrichment_job_summary_counts_distinct_protein_aid_pairs():
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE compound_assays (CID TEXT, AID TEXT, Protein TEXT)")
    connection.executemany(
        "INSERT INTO compound_assays (CID, AID, Protein) VALUES (?, ?, ?)",
        [
            ("101", "11", "P1"),
            ("101", "11", "P1"),
            ("102", "11", "P1"),
            ("103", "11", "P2"),
            ("104", "12", "P1"),
        ],
    )

    summary = _get_activity_enrichment_job_summary(connection)

    assert summary == {
        "total_aids": 3,
        "cid_aid_links": 5,
        "proteins": ["P1", "P2"],
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
