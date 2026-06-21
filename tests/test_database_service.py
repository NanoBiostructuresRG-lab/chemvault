import sqlite3

from services import database


def test_count_rows_returns_zero_without_active_table(monkeypatch):
    connection = sqlite3.connect(":memory:")
    monkeypatch.setattr(database.st, "session_state", {"current_table": ""})

    assert database.count_rows(connection) == 0


def test_count_rows_uses_current_table(monkeypatch):
    connection = sqlite3.connect(":memory:")
    connection.execute('CREATE TABLE "main" (id INTEGER)')
    connection.executemany('INSERT INTO "main" (id) VALUES (?)', [(1,), (2,)])
    monkeypatch.setattr(database.st, "session_state", {"current_table": "main"})

    assert database.count_rows(connection) == 2


def test_count_rows_group_by_counts_unique_groups(monkeypatch):
    connection = sqlite3.connect(":memory:")
    connection.execute('CREATE TABLE "main" (category TEXT)')
    connection.executemany(
        'INSERT INTO "main" (category) VALUES (?)',
        [("A",), ("A",), ("B",)],
    )
    monkeypatch.setattr(
        database.st,
        "session_state",
        {
            "current_table": "main",
            "headers": ["category"],
            "grupo_a_contar": "category",
        },
    )

    assert database.count_rows_group_by(connection) == 2


def test_update_headers_syncs_tables_headers_and_selected_headers(monkeypatch):
    connection = sqlite3.connect(":memory:")
    connection.execute('CREATE TABLE "main" (CID TEXT, SMILES TEXT)')
    session_state = {
        "database_id": "test_db",
        "current_table": "main",
        "headers": [],
        "all_tables": [],
        "selected_headers": ["CID", "stale_column"],
    }
    monkeypatch.setattr(database.st, "session_state", session_state)
    monkeypatch.setattr(database, "get_connection", lambda db_name: connection)

    headers = database.update_headers()

    assert headers == ["CID", "SMILES"]
    assert session_state["all_tables"] == ["main"]
    assert session_state["headers"] == ["CID", "SMILES"]
    assert session_state["selected_headers"] == ["CID"]
