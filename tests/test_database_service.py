# SPDX-License-Identifier: LGPL-3.0-or-later
import sqlite3

from services import database
from services.db_audit import get_operation_log


def test_count_rows_returns_zero_without_active_table():
    connection = sqlite3.connect(":memory:")

    assert database.count_rows(connection, "") == 0


def test_count_rows_uses_current_table():
    connection = sqlite3.connect(":memory:")
    connection.execute('CREATE TABLE "main" (id INTEGER)')
    connection.executemany('INSERT INTO "main" (id) VALUES (?)', [(1,), (2,)])

    assert database.count_rows(connection, "main") == 2


def test_count_rows_group_by_counts_unique_groups():
    connection = sqlite3.connect(":memory:")
    connection.execute('CREATE TABLE "main" (category TEXT)')
    connection.executemany(
        'INSERT INTO "main" (category) VALUES (?)',
        [("A",), ("A",), ("B",)],
    )

    result = database.count_rows_group_by(
        connection,
        "main",
        "category",
        ["category"],
    )

    assert result == 2


def test_update_headers_returns_tables_headers_and_selected_headers(monkeypatch):
    connection = sqlite3.connect(":memory:")
    connection.execute('CREATE TABLE "main" (CID TEXT, SMILES TEXT)')
    monkeypatch.setattr(database, "get_connection", lambda db_name: connection)

    state = database.update_headers(
        "test_db",
        "main",
        ["CID", "stale_column"],
    )

    assert state.database_id == "test_db"
    assert state.current_table == "main"
    assert state.all_tables == ("main",)
    assert state.headers == ("CID", "SMILES")
    assert state.selected_headers == ("CID",)


def test_set_database_id_returns_state_and_registers_new_database(
    monkeypatch,
    tmp_path,
):
    db_path = tmp_path / "test.db"
    connection = sqlite3.connect(db_path)
    monkeypatch.setattr(database, "get_connection", lambda db_name: connection)
    monkeypatch.setattr(database.os.path, "isfile", lambda path: False)

    state = database.set_database_id("test_db")

    operations = get_operation_log(db_path)
    assert state.database_id == "test_db"
    assert state.current_table == "main"
    assert state.input_locked is True
    assert state.message == "SQL Database set to test_db"
    assert state.success is True
    assert operations[0]["operation_type"] == "database_created"
    assert operations[0]["target_table"] == "main"


def test_set_database_id_returns_message_for_blank_name():
    state = database.set_database_id("  ")

    assert state.success is False
    assert state.message == "Enter a name for your SQL database"
