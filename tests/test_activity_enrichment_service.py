# SPDX-License-Identifier: LGPL-3.0-or-later
import sqlite3

from services.activity_enrichment import (
    build_activity_jobs_from_compound_assays,
    chunk_aid_jobs,
    ensure_compound_activities_table,
    run_activity_enrichment_from_compound_assays,
    run_pubchem_activity_enrichment,
)


def activity_payload(aid, cid, value):
    return {
        str(cid): {
            "records": [
                {
                    "CID": str(cid),
                    "AID": str(aid),
                    "Activity_Type": "Ki",
                    "Relation": "",
                    "Activity_Value": float(value),
                    "Activity_Value_Raw": str(value),
                    "Unit": "NANOMOLAR",
                    "Outcome": "Active",
                    "Source_Column": "Ki",
                    "Activity_Status": "enriched",
                    "Result_Tag": "1",
                }
            ]
        }
    }


def aid_jobs():
    return [
        {"protein": "P1", "aid": "11", "cids": ["101"]},
        {"protein": "P1", "aid": "22", "cids": ["202"]},
        {"protein": "P2", "aid": "33", "cids": ["303"]},
    ]


def test_activity_runner_processes_aids_in_chunks_and_emits_progress():
    connection = sqlite3.connect(":memory:")
    snapshots = []
    calls = []

    def fetcher(aid):
        calls.append(aid)
        return activity_payload(aid, {"11": "101", "22": "202", "33": "303"}[aid], aid)

    result = run_pubchem_activity_enrichment(
        connection,
        aid_jobs(),
        fetcher,
        chunk_size=2,
        progress_callback=snapshots.append,
    )

    assert calls == ["11", "22", "33"]
    assert result["status"] == "success"
    assert result["total_aids"] == 3
    assert result["processed_aids"] == 3
    assert result["successful_aids"] == 3
    assert result["failed_aids"] == 0
    assert result["inserted_rows"] == 3
    assert [snapshot["status"] for snapshot in snapshots] == [
        "started",
        "running",
        "chunk_completed",
        "running",
        "chunk_completed",
        "success",
    ]


def test_activity_runner_inserts_rows_into_compound_activities():
    connection = sqlite3.connect(":memory:")

    run_pubchem_activity_enrichment(
        connection,
        [aid_jobs()[0]],
        lambda aid: activity_payload(aid, "101", "10"),
    )

    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT CID, AID, Protein, Activity_Type, Activity_Value, Unit, Outcome
        FROM compound_activities
        """
    )

    assert cursor.fetchall() == [
        ("101", "11", "P1", "Ki", 10.0, "NANOMOLAR", "Active")
    ]


def test_activity_runner_does_not_duplicate_rows_when_rerun():
    connection = sqlite3.connect(":memory:")
    jobs = [aid_jobs()[0]]
    fetcher = lambda aid: activity_payload(aid, "101", "10")

    first = run_pubchem_activity_enrichment(connection, jobs, fetcher)
    second = run_pubchem_activity_enrichment(connection, jobs, fetcher)

    cursor = connection.cursor()
    cursor.execute("SELECT COUNT(*) FROM compound_activities")

    assert first["inserted_rows"] == 1
    assert second["inserted_rows"] == 0
    assert cursor.fetchone() == (1,)


def test_activity_runner_continues_after_failed_aid_when_enabled():
    connection = sqlite3.connect(":memory:")

    def fetcher(aid):
        if aid == "22":
            raise RuntimeError("PubChem failed")
        return activity_payload(aid, {"11": "101", "33": "303"}[aid], aid)

    result = run_pubchem_activity_enrichment(
        connection,
        aid_jobs(),
        fetcher,
        chunk_size=1,
        continue_on_error=True,
    )

    cursor = connection.cursor()
    cursor.execute("SELECT AID, CID FROM compound_activities ORDER BY AID")

    assert result["status"] == "success"
    assert result["processed_aids"] == 3
    assert result["successful_aids"] == 2
    assert result["failed_aids"] == 1
    assert result["failed_aid_values"] == ["22"]
    assert cursor.fetchall() == [("11", "101"), ("33", "303")]


def test_activity_runner_stops_on_failed_aid_when_disabled():
    connection = sqlite3.connect(":memory:")
    snapshots = []

    def fetcher(aid):
        if aid == "22":
            raise RuntimeError("PubChem failed")
        return activity_payload(aid, "101", "10")

    result = run_pubchem_activity_enrichment(
        connection,
        aid_jobs()[:2],
        fetcher,
        chunk_size=2,
        progress_callback=snapshots.append,
        continue_on_error=False,
    )

    cursor = connection.cursor()
    cursor.execute("SELECT AID, CID FROM compound_activities")

    assert result["status"] == "failed"
    assert result["processed_aids"] == 2
    assert result["successful_aids"] == 1
    assert result["failed_aids"] == 1
    assert result["error_message"] == "PubChem failed"
    assert cursor.fetchall() == [("11", "101")]
    assert snapshots[-1]["status"] == "failed"


def test_ensure_compound_activities_table_is_idempotent():
    connection = sqlite3.connect(":memory:")

    ensure_compound_activities_table(connection)
    ensure_compound_activities_table(connection)

    cursor = connection.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")

    assert cursor.fetchall() == [("compound_activities",)]


def test_chunk_aid_jobs_rejects_non_positive_chunk_size():
    for chunk_size in (0, -1):
        try:
            list(chunk_aid_jobs(aid_jobs(), chunk_size=chunk_size))
        except ValueError as exc:
            assert str(exc) == "chunk_size must be greater than zero."
        else:
            raise AssertionError("Expected ValueError")


def test_build_activity_jobs_from_compound_assays_groups_by_protein_and_aid():
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE compound_assays (CID TEXT, AID TEXT, Protein TEXT)")
    connection.executemany(
        "INSERT INTO compound_assays (CID, AID, Protein) VALUES (?, ?, ?)",
        [
            ("101", "11", "P1"),
            ("102", "11", "P1"),
            ("101", "11", "P1"),
            ("201", "11", "P2"),
            ("301", "22", "P1"),
        ],
    )

    jobs = build_activity_jobs_from_compound_assays(connection)

    assert jobs == [
        {"protein": "P1", "aid": "11", "cids": ["101", "102"]},
        {"protein": "P1", "aid": "22", "cids": ["301"]},
        {"protein": "P2", "aid": "11", "cids": ["201"]},
    ]


def test_run_activity_enrichment_from_compound_assays_fills_compound_activities():
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE compound_assays (CID TEXT, AID TEXT, Protein TEXT)")
    connection.executemany(
        "INSERT INTO compound_assays (CID, AID, Protein) VALUES (?, ?, ?)",
        [("101", "11", "P1"), ("202", "22", "P1")],
    )

    result = run_activity_enrichment_from_compound_assays(
        connection,
        lambda aid: activity_payload(aid, {"11": "101", "22": "202"}[aid], aid),
        chunk_size=1,
    )

    cursor = connection.cursor()
    cursor.execute("SELECT AID, Protein, CID FROM compound_activities ORDER BY AID")

    assert result["total_aids"] == 2
    assert result["inserted_rows"] == 2
    assert cursor.fetchall() == [("11", "P1", "101"), ("22", "P1", "202")]


def test_run_activity_enrichment_from_compound_assays_handles_missing_or_empty_source_table():
    missing_connection = sqlite3.connect(":memory:")

    missing_result = run_activity_enrichment_from_compound_assays(
        missing_connection,
        lambda aid: activity_payload(aid, "101", "10"),
    )

    empty_connection = sqlite3.connect(":memory:")
    empty_connection.execute("CREATE TABLE compound_assays (CID TEXT, AID TEXT, Protein TEXT)")
    empty_result = run_activity_enrichment_from_compound_assays(
        empty_connection,
        lambda aid: activity_payload(aid, "101", "10"),
    )

    assert missing_result["total_aids"] == 0
    assert missing_result["inserted_rows"] == 0
    assert empty_result["total_aids"] == 0
    assert empty_result["inserted_rows"] == 0


def test_run_activity_enrichment_from_compound_assays_is_idempotent():
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE compound_assays (CID TEXT, AID TEXT, Protein TEXT)")
    connection.execute(
        "INSERT INTO compound_assays (CID, AID, Protein) VALUES ('101', '11', 'P1')"
    )
    fetcher = lambda aid: activity_payload(aid, "101", "10")

    first = run_activity_enrichment_from_compound_assays(connection, fetcher)
    second = run_activity_enrichment_from_compound_assays(connection, fetcher)

    cursor = connection.cursor()
    cursor.execute("SELECT COUNT(*) FROM compound_activities")

    assert first["inserted_rows"] == 1
    assert second["inserted_rows"] == 0
    assert cursor.fetchone() == (1,)
