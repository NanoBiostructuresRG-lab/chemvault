# SPDX-License-Identifier: LGPL-3.0-or-later
import sqlite3

import pandas as pd

from services.harmonsmile_cache import (
    CACHE_TABLE,
    DEFAULT_CHUNK_SIZE,
    ensure_harmonsmile_cache,
    get_cached_harmonsmile_cids,
    get_harmonsmile_output_columns,
    normalize_cid,
    normalize_cids,
    normalize_harmonsmile_result,
    prepare_harmonsmile_job,
    read_cids_from_table,
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
