# SPDX-License-Identifier: LGPL-3.0-or-later
import pytest
import pandas as pd
import sqlite3

from services import curation
from services.curation import agregar_df_por_pk, is_cid_header, run_chamanp, run_harmonsmile


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("CID", True),
        ("CIDs", True),
        ("PubChem CID", True),
        ("PubChem_CID", True),
        ("compound-cid", True),
        ("SMILES", False),
        ("primary_id", False),
        ("PubChem SID", False),
    ],
)
def test_is_cid_header_characterizes_accepted_cid_names(header, expected):
    assert is_cid_header(header) is expected


def test_run_harmonsmile_delegates_to_pubchem_ingest(monkeypatch):
    input_df = pd.DataFrame([{"CID": "1"}])
    output_df = pd.DataFrame([{"PubChem_CID": "1", "SMILES": "CCO"}])
    calls = []

    def fake_ingest(df):
        calls.append(df)
        return output_df

    monkeypatch.setattr(curation, "use_PubchemIngest", fake_ingest)

    assert run_harmonsmile(input_df) is output_df
    assert calls == [input_df]


def test_run_chamanp_delegates_to_chamanp(monkeypatch):
    input_df = pd.DataFrame([{"identifier": "mol-1"}])
    calls = []

    def fake_chamanp(df, identifier_col, smiles_col, collections_col):
        calls.append((df, identifier_col, smiles_col, collections_col))

    monkeypatch.setattr(curation, "use_chamanp", fake_chamanp)

    assert run_chamanp(input_df, "identifier", "canonical_smiles", "collections") is None
    assert calls == [(input_df, "identifier", "canonical_smiles", "collections")]


def create_merge_db():
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
    return connection


def test_agregar_df_por_pk_adds_new_columns_and_updates_matching_rows(monkeypatch):
    connection = create_merge_db()
    df = pd.DataFrame(
        [
            {"PubChem_CID": "1", "MW": "46.07", "XLogP": "-0.1"},
            {"PubChem_CID": "3", "MW": "45.08", "XLogP": "0.2"},
        ]
    )
    monkeypatch.setattr(curation, "get_connection", lambda db_name: connection)
    monkeypatch.setattr(curation.st, "session_state", {"database_id": "test_db", "current_table": "main"})

    assert agregar_df_por_pk(df, "CID", "PubChem_CID") is True

    cursor = connection.cursor()
    cursor.execute('PRAGMA table_info("main")')
    columns = [row[1] for row in cursor.fetchall()]
    cursor.execute('SELECT CID, existing_col, MW, XLogP FROM "main" ORDER BY CID')
    rows = cursor.fetchall()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='_temp_updates'")

    assert columns == ["CID", "existing_col", "MW", "XLogP"]
    assert rows == [
        ("1", "keep-a", "46.07", "-0.1"),
        ("2", "keep-b", None, None),
        ("3", "keep-c", "45.08", "0.2"),
    ]
    assert cursor.fetchone() is None


def test_agregar_df_por_pk_updates_existing_columns_without_adding_duplicate(monkeypatch):
    connection = create_merge_db()
    connection.execute('ALTER TABLE "main" ADD COLUMN MW TEXT')
    df = pd.DataFrame([{"PubChem_CID": "2", "MW": "44.10"}])
    monkeypatch.setattr(curation, "get_connection", lambda db_name: connection)
    monkeypatch.setattr(curation.st, "session_state", {"database_id": "test_db", "current_table": "main"})

    assert agregar_df_por_pk(df, "CID", "PubChem_CID") is True

    cursor = connection.cursor()
    cursor.execute('PRAGMA table_info("main")')
    columns = [row[1] for row in cursor.fetchall()]
    cursor.execute('SELECT MW FROM "main" WHERE CID = "2"')

    assert columns == ["CID", "existing_col", "MW"]
    assert cursor.fetchone() == ("44.10",)


def test_agregar_df_por_pk_returns_false_when_dataframe_has_no_update_columns(monkeypatch):
    connection = create_merge_db()
    df = pd.DataFrame([{"PubChem_CID": "1"}])
    monkeypatch.setattr(curation, "get_connection", lambda db_name: connection)
    monkeypatch.setattr(curation.st, "session_state", {"database_id": "test_db", "current_table": "main"})

    assert agregar_df_por_pk(df, "CID", "PubChem_CID") is False


def test_agregar_df_por_pk_rolls_back_and_returns_false_on_sql_error(monkeypatch):
    connection = create_merge_db()
    df = pd.DataFrame([{"PubChem_CID": "1", "bad-column": "value"}])
    errors = []
    monkeypatch.setattr(curation, "get_connection", lambda db_name: connection)
    monkeypatch.setattr(
        curation.st,
        "session_state",
        {"database_id": "test_db", "current_table": "main"},
    )
    monkeypatch.setattr(curation.st, "error", lambda message: errors.append(message))

    assert agregar_df_por_pk(df, "CID", "PubChem_CID") is False

    cursor = connection.cursor()
    cursor.execute('PRAGMA table_info("main")')
    columns = [row[1] for row in cursor.fetchall()]
    assert columns == ["CID", "existing_col"]
    assert errors and errors[0].startswith("Error updating the database:")
