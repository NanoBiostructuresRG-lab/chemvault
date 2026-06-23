# SPDX-License-Identifier: LGPL-3.0-or-later
import sqlite3

import pandas as pd

from services.harmonsmile_cache import (
    CACHE_TABLE,
    DEFAULT_CHUNK_SIZE,
    chunk_cids,
    ensure_harmonsmile_cache,
    get_cached_harmonsmile_cids,
    get_harmonsmile_output_columns,
    mark_harmonsmile_cache_failed,
    merge_harmonsmile_cache_to_table,
    normalize_cid,
    normalize_cids,
    normalize_harmonsmile_result,
    prepare_harmonsmile_job,
    read_cids_from_table,
    run_harmonsmile_chunks,
    upsert_harmonsmile_cache,
)
from services.sql_utils import get_tables_from_connection


def test_normalize_cid_accepts_positive_integer_like_values():
    assert normalize_cid("123") == "123"
    assert normalize_cid("00123") == "123"
    assert normalize_cid(123) == "123"
    assert normalize_cid("123.0") == "123"


def test_normalize_cid_rejects_invalid_values():
    assert normalize_cid("") is None
    assert normalize_cid(None) is None
    assert normalize_cid("CHEMBL25") is None
    assert normalize_cid("123.4") is None
    assert normalize_cid("0") is None
    assert normalize_cid("-1") is None


def test_normalize_cids_deduplicates_and_reports_invalid_values():
    cids, invalid = normalize_cids(["1", "1.0", "2", "bad", None, "2"])

    assert cids == ["1", "2"]
    assert invalid == ["bad", None]


def test_normalize_harmonsmile_result_standardizes_columns_and_cids():
    df = pd.DataFrame(
        [
            {"PubChem CID": "1.0", "Molecular Formula": "H2O", "XLogP:": "0"},
            {"PubChem CID": "bad", "Molecular Formula": "invalid", "XLogP:": "invalid"},
        ]
    )

    result = normalize_harmonsmile_result(df)

    assert result.columns.tolist() == ["PubChem_CID", "Molecular_Formula", "XLogP"]
    assert result.to_dict("records") == [
        {"PubChem_CID": "1", "Molecular_Formula": "H2O", "XLogP": "0"}
    ]
    assert get_harmonsmile_output_columns(df) == ["Molecular_Formula", "XLogP"]


def test_default_chunk_size_documents_future_harmonsmile_runner_design():
    assert DEFAULT_CHUNK_SIZE == 500


def test_chunk_cids_uses_requested_chunk_size():
    assert list(chunk_cids(["1", "2", "3", "4", "5"], chunk_size=2)) == [
        ["1", "2"],
        ["3", "4"],
        ["5"],
    ]


def test_ensure_harmonsmile_cache_creates_internal_table():
    connection = sqlite3.connect(":memory:")

    ensure_harmonsmile_cache(connection)

    cursor = connection.cursor()
    cursor.execute(f'PRAGMA table_info("{CACHE_TABLE}")')
    columns = [row[1] for row in cursor.fetchall()]

    assert columns == ["PubChem_CID", "status", "fetched_at", "error_message"]
    assert get_tables_from_connection(connection) == []


def test_upsert_harmonsmile_cache_adds_dynamic_columns_and_reads_cached_cids():
    connection = sqlite3.connect(":memory:")
    df = pd.DataFrame(
        [
            {"PubChem_CID": "1", "SMILES": "CCO", "Molecular Formula": "C2H6O"},
            {"PubChem_CID": "2", "SMILES": "CCC", "Molecular Formula": "C3H8"},
        ]
    )

    inserted = upsert_harmonsmile_cache(connection, df)

    cursor = connection.cursor()
    cursor.execute(f'PRAGMA table_info("{CACHE_TABLE}")')
    columns = [row[1] for row in cursor.fetchall()]
    cursor.execute(
        f'''
        SELECT PubChem_CID, status, error_message, SMILES, Molecular_Formula
        FROM "{CACHE_TABLE}"
        ORDER BY PubChem_CID
        '''
    )

    assert inserted == 2
    assert columns == [
        "PubChem_CID",
        "status",
        "fetched_at",
        "error_message",
        "SMILES",
        "Molecular_Formula",
    ]
    assert cursor.fetchall() == [
        ("1", "success", None, "CCO", "C2H6O"),
        ("2", "success", None, "CCC", "C3H8"),
    ]
    assert get_cached_harmonsmile_cids(connection, ["1", "2", "3", "bad"]) == {"1", "2"}


def test_upsert_harmonsmile_cache_updates_existing_rows():
    connection = sqlite3.connect(":memory:")
    upsert_harmonsmile_cache(
        connection,
        pd.DataFrame([{"PubChem_CID": "1", "SMILES": "old"}]),
    )

    upsert_harmonsmile_cache(
        connection,
        pd.DataFrame([{"PubChem_CID": "1", "SMILES": "new", "MW": "46.07"}]),
    )

    cursor = connection.cursor()
    cursor.execute(f'SELECT PubChem_CID, SMILES, MW FROM "{CACHE_TABLE}"')

    assert cursor.fetchone() == ("1", "new", "46.07")


def test_mark_harmonsmile_cache_failed_records_error_status():
    connection = sqlite3.connect(":memory:")

    count = mark_harmonsmile_cache_failed(connection, ["1", "2"], "network error")

    cursor = connection.cursor()
    cursor.execute(
        f'''
        SELECT PubChem_CID, status, error_message
        FROM "{CACHE_TABLE}"
        ORDER BY PubChem_CID
        '''
    )

    assert count == 2
    assert cursor.fetchall() == [
        ("1", "failed", "network error"),
        ("2", "failed", "network error"),
    ]


def test_read_cids_from_table_reads_selected_column_values():
    connection = sqlite3.connect(":memory:")
    connection.execute('CREATE TABLE "active table" ("CID value" TEXT, other TEXT)')
    connection.executemany(
        'INSERT INTO "active table" ("CID value", other) VALUES (?, ?)',
        [("1", "a"), ("2", "b")],
    )

    assert read_cids_from_table(connection, "active table", "CID value") == ["1", "2"]


def test_prepare_harmonsmile_job_splits_cached_pending_and_invalid_cids():
    connection = sqlite3.connect(":memory:")
    connection.execute('CREATE TABLE "main" (CID TEXT)')
    connection.executemany(
        'INSERT INTO "main" (CID) VALUES (?)',
        [
            ("1",),
            ("1.0",),
            ("2",),
            ("bad",),
            ("3",),
            ("",),
            (None,),
        ],
    )
    upsert_harmonsmile_cache(
        connection,
        pd.DataFrame(
            [
                {"PubChem_CID": "1", "SMILES": "CCO"},
                {"PubChem_CID": "3", "SMILES": "CCC"},
            ]
        ),
    )

    job = prepare_harmonsmile_job(connection, "main", "CID")

    assert job == {
        "source_table": "main",
        "cid_column": "CID",
        "total_cids": 3,
        "valid_cids": ["1", "2", "3"],
        "cached_cids": ["1", "3"],
        "pending_cids": ["2"],
        "invalid_cids": ["bad", "", None],
    }


def test_prepare_harmonsmile_job_ignores_failed_cache_rows():
    connection = sqlite3.connect(":memory:")
    connection.execute('CREATE TABLE "main" (CID TEXT)')
    connection.executemany(
        'INSERT INTO "main" (CID) VALUES (?)',
        [("1",), ("2",)],
    )
    upsert_harmonsmile_cache(
        connection,
        pd.DataFrame([{"PubChem_CID": "1", "SMILES": "CCO"}]),
        status="failed",
        error_message="temporary failure",
    )

    job = prepare_harmonsmile_job(connection, "main", "CID")

    assert job["cached_cids"] == []
    assert job["pending_cids"] == ["1", "2"]


def test_run_harmonsmile_chunks_processes_pending_cids_and_caches_each_chunk():
    connection = sqlite3.connect(":memory:")
    calls = []

    def fake_harmonsmile_runner(chunk_df):
        calls.append(chunk_df.copy())
        return pd.DataFrame(
            {
                "PubChem CID": chunk_df["CID"],
                "SMILES": [f"SMILES-{cid}" for cid in chunk_df["CID"]],
            }
        )

    snapshots = []
    result = run_harmonsmile_chunks(
        connection,
        ["1", "2", "3", "bad"],
        fake_harmonsmile_runner,
        chunk_size=2,
        progress_callback=snapshots.append,
    )

    cursor = connection.cursor()
    cursor.execute(
        f'''
        SELECT PubChem_CID, status, SMILES
        FROM "{CACHE_TABLE}"
        ORDER BY PubChem_CID
        '''
    )

    assert [call.to_dict("list") for call in calls] == [
        {"CID": ["1", "2"]},
        {"CID": ["3"]},
    ]
    expected_result = {
        "status": "success",
        "chunk_index": 2,
        "total_chunks": 2,
        "processed_cids": ["1", "2", "3"],
        "failed_cids": [],
        "invalid_cids": ["bad"],
        "error_message": None,
    }
    for key, value in expected_result.items():
        assert result[key] == value
    assert result["progress"]["status"] == "success"
    assert result["progress"]["total_cids"] == 3
    assert result["progress"]["successful_cids"] == 3
    assert [snapshot["status"] for snapshot in snapshots] == [
        "started",
        "running",
        "chunk_completed",
        "running",
        "chunk_completed",
        "success",
    ]
    assert snapshots[-1]["processed_cids"] == 3
    assert snapshots[-1]["failed_cids"] == 0
    assert cursor.fetchall() == [
        ("1", "success", "SMILES-1"),
        ("2", "success", "SMILES-2"),
        ("3", "success", "SMILES-3"),
    ]


def test_run_harmonsmile_chunks_records_failed_chunk_and_stops():
    connection = sqlite3.connect(":memory:")
    calls = []

    def fake_harmonsmile_runner(chunk_df):
        calls.append(chunk_df.copy())
        if chunk_df["CID"].tolist() == ["3", "4"]:
            raise RuntimeError("PubChem unavailable")
        return pd.DataFrame(
            {
                "PubChem_CID": chunk_df["CID"],
                "SMILES": [f"SMILES-{cid}" for cid in chunk_df["CID"]],
            }
        )

    snapshots = []
    result = run_harmonsmile_chunks(
        connection,
        ["1", "2", "3", "4", "5"],
        fake_harmonsmile_runner,
        chunk_size=2,
        progress_callback=snapshots.append,
    )

    cursor = connection.cursor()
    cursor.execute(
        f'''
        SELECT PubChem_CID, status, error_message, SMILES
        FROM "{CACHE_TABLE}"
        ORDER BY PubChem_CID
        '''
    )

    assert [call.to_dict("list") for call in calls] == [
        {"CID": ["1", "2"]},
        {"CID": ["3", "4"]},
    ]
    assert result == {
        "status": "failed",
        "chunk_index": 2,
        "total_chunks": 3,
        "processed_cids": ["1", "2"],
        "failed_cids": ["3", "4"],
        "missing_cids": [],
        "invalid_cids": [],
        "error_message": "PubChem unavailable",
    }
    assert [snapshot["status"] for snapshot in snapshots] == [
        "started",
        "running",
        "chunk_completed",
        "running",
        "failed",
    ]
    assert snapshots[-1]["stopped_by_exception"] is True
    assert snapshots[-1]["failed_cids"] == 2
    assert snapshots[-1]["failed_cid_values"] == ["3", "4"]
    assert cursor.fetchall() == [
        ("1", "success", None, "SMILES-1"),
        ("2", "success", None, "SMILES-2"),
        ("3", "failed", "PubChem unavailable", None),
        ("4", "failed", "PubChem unavailable", None),
    ]


def test_run_harmonsmile_chunks_marks_missing_chunk_results_as_failed():
    connection = sqlite3.connect(":memory:")

    def partial_harmonsmile_runner(chunk_df):
        return pd.DataFrame(
            {
                "PubChem_CID": ["1", "3"],
                "SMILES": ["SMILES-1", "SMILES-3"],
            }
        )

    snapshots = []
    result = run_harmonsmile_chunks(
        connection,
        ["1", "2", "3"],
        partial_harmonsmile_runner,
        chunk_size=3,
        progress_callback=snapshots.append,
    )

    cursor = connection.cursor()
    cursor.execute(
        f'''
        SELECT PubChem_CID, status, error_message, SMILES
        FROM "{CACHE_TABLE}"
        ORDER BY PubChem_CID
        '''
    )

    expected_result = {
        "status": "success",
        "chunk_index": 1,
        "total_chunks": 1,
        "processed_cids": ["1", "3"],
        "failed_cids": ["2"],
        "missing_cids": ["2"],
        "invalid_cids": [],
        "error_message": None,
    }
    for key, value in expected_result.items():
        assert result[key] == value
    assert snapshots[2]["status"] == "chunk_completed"
    assert snapshots[2]["missing_cids"] == 1
    assert snapshots[2]["missing_cid_values"] == ["2"]
    assert snapshots[-1]["failed_cids"] == 1
    assert cursor.fetchall() == [
        ("1", "success", None, "SMILES-1"),
        (
            "2",
            "failed",
            "Missing HARMONSMILE result for CID in processed chunk",
            None,
        ),
        ("3", "success", None, "SMILES-3"),
    ]


def test_merge_harmonsmile_cache_to_table_adds_columns_and_updates_successful_rows():
    connection = sqlite3.connect(":memory:")
    connection.execute('CREATE TABLE "main" (CID TEXT, existing_col TEXT)')
    connection.executemany(
        'INSERT INTO "main" (CID, existing_col) VALUES (?, ?)',
        [
            ("1", "keep-a"),
            ("2", "keep-b"),
            ("3", "keep-c"),
        ],
    )
    upsert_harmonsmile_cache(
        connection,
        pd.DataFrame(
            [
                {"PubChem_CID": "1", "SMILES": "CCO", "MW": "46.07"},
                {"PubChem_CID": "3", "SMILES": "CCC", "MW": "44.10"},
            ]
        ),
    )
    mark_harmonsmile_cache_failed(connection, ["2"], "missing")

    updated_rows = merge_harmonsmile_cache_to_table(connection, "main", "CID")

    cursor = connection.cursor()
    cursor.execute('PRAGMA table_info("main")')
    columns = [row[1] for row in cursor.fetchall()]
    cursor.execute('SELECT CID, existing_col, SMILES, MW FROM "main" ORDER BY CID')

    assert updated_rows == 2
    assert columns == ["CID", "existing_col", "SMILES", "MW"]
    assert cursor.fetchall() == [
        ("1", "keep-a", "CCO", "46.07"),
        ("2", "keep-b", None, None),
        ("3", "keep-c", "CCC", "44.10"),
    ]


def test_merge_harmonsmile_cache_to_table_limits_merge_to_requested_cids():
    connection = sqlite3.connect(":memory:")
    connection.execute('CREATE TABLE "main" (CID TEXT)')
    connection.executemany(
        'INSERT INTO "main" (CID) VALUES (?)',
        [("1",), ("2",)],
    )
    upsert_harmonsmile_cache(
        connection,
        pd.DataFrame(
            [
                {"PubChem_CID": "1", "SMILES": "CCO"},
                {"PubChem_CID": "2", "SMILES": "CCC"},
            ]
        ),
    )

    updated_rows = merge_harmonsmile_cache_to_table(
        connection,
        "main",
        "CID",
        cids=["2"],
    )

    cursor = connection.cursor()
    cursor.execute('SELECT CID, SMILES FROM "main" ORDER BY CID')

    assert updated_rows == 1
    assert cursor.fetchall() == [
        ("1", None),
        ("2", "CCC"),
    ]


def test_merge_harmonsmile_cache_to_table_does_not_write_internal_cache_columns():
    connection = sqlite3.connect(":memory:")
    connection.execute('CREATE TABLE "main" (CID TEXT)')
    connection.execute('INSERT INTO "main" (CID) VALUES ("1")')
    upsert_harmonsmile_cache(
        connection,
        pd.DataFrame([{"PubChem_CID": "1", "SMILES": "CCO"}]),
    )

    merge_harmonsmile_cache_to_table(connection, "main", "CID")

    cursor = connection.cursor()
    cursor.execute('PRAGMA table_info("main")')
    columns = [row[1] for row in cursor.fetchall()]

    assert columns == ["CID", "SMILES"]


def test_merge_harmonsmile_cache_to_table_returns_zero_without_successful_rows():
    connection = sqlite3.connect(":memory:")
    connection.execute('CREATE TABLE "main" (CID TEXT)')
    connection.execute('INSERT INTO "main" (CID) VALUES ("1")')
    mark_harmonsmile_cache_failed(connection, ["1"], "failed")

    updated_rows = merge_harmonsmile_cache_to_table(connection, "main", "CID")

    cursor = connection.cursor()
    cursor.execute('PRAGMA table_info("main")')

    assert updated_rows == 0
    assert [row[1] for row in cursor.fetchall()] == ["CID"]
