# SPDX-License-Identifier: LGPL-3.0-or-later
import io
import sqlite3

import pytest

from services import builders


def test_build_from_csv_creates_main_table_from_uploaded_csv(monkeypatch):
    connection = sqlite3.connect(":memory:")
    csv_file = io.StringIO("CID, canonical smiles\n1,CCO\n2,CCC\n")

    monkeypatch.setattr(builders, "get_connection", lambda db_name: connection)
    monkeypatch.setattr(builders.os.path, "isfile", lambda path: False)

    current_table = builders.build_from_csv(csv_file, "test_db", "")

    cursor = connection.cursor()
    cursor.execute('PRAGMA table_info("main")')
    columns = [row[1] for row in cursor.fetchall()]
    cursor.execute('SELECT "CID", "canonical_smiles" FROM "main" ORDER BY primary_id')
    rows = cursor.fetchall()

    assert current_table == "main"
    assert columns == ["primary_id", "CID", "canonical_smiles"]
    assert rows == [("1", "CCO"), ("2", "CCC")]
    cursor.execute('SELECT operation_type FROM "_chemvault_operation_log"')
    assert cursor.fetchall() == [("csv_loaded",)]


def test_build_from_csv_uses_current_table_when_present(monkeypatch):
    connection = sqlite3.connect(":memory:")
    csv_file = io.StringIO("CID\n1\n")

    monkeypatch.setattr(builders, "get_connection", lambda db_name: connection)
    monkeypatch.setattr(builders.os.path, "isfile", lambda path: False)

    current_table = builders.build_from_csv(
        csv_file,
        "test_db",
        "custom_table",
    )

    cursor = connection.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    assert cursor.fetchall() == [
        ("custom_table",),
        ("sqlite_sequence",),
        ("_chemvault_table_metadata",),
        ("_chemvault_operation_log",),
    ]
    assert current_table == "custom_table"


def test_build_from_proteins_returns_main_and_delegates_to_pubchem(monkeypatch):
    connection = object()
    calls = []
    progreso = object()

    monkeypatch.setattr(builders, "get_connection", lambda db_name: connection)
    monkeypatch.setattr(
        builders,
        "register_protein_search_build",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        builders,
        "obtener_CIDs_Pubchem",
        lambda conn, proteins, progress: calls.append((conn, proteins, progress)),
    )

    current_table = builders.build_from_proteins(
        "protein_db",
        ["P34971"],
        progreso,
    )

    assert current_table == "main"
    assert calls == [(connection, ["P34971"], progreso)]


def test_run_protein_search_dispatches_to_worker_job(monkeypatch):
    expected = (object(), object(), "main")
    monkeypatch.setattr(
        builders,
        "launch_protein_search_job",
        lambda database_id, selected_proteins: expected,
    )
    monkeypatch.setattr(
        builders,
        "build_from_proteins",
        lambda *args: pytest.fail("synchronous fallback must not run"),
    )

    assert builders.run_protein_search("protein_db", ["P34971"]) == expected


def test_launch_protein_search_job_delegates_explicit_values(monkeypatch):
    expected = (object(), object())
    calls = []
    monkeypatch.setattr(
        builders,
        "start_pubchem_search",
        lambda database_id, proteins: calls.append((database_id, proteins)) or expected,
    )

    result = builders.launch_protein_search_job("protein_db", ["P34971"])

    assert result == (*expected, "main")
    assert calls == [("protein_db", ["P34971"])]
