# SPDX-License-Identifier: LGPL-3.0-or-later
import ast
import sqlite3
from pathlib import Path

import pytest

from application import database_use_cases
from services.database import DatabaseState


def test_application_database_layer_has_no_streamlit_imports():
    application_dir = Path(__file__).resolve().parents[1] / "application"
    imported_modules = set()
    for source_path in application_dir.glob("*.py"):
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        imported_modules.update(
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        )
        imported_modules.update(
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        )

    assert not any(
        module == "streamlit" or module.startswith("streamlit.")
        for module in imported_modules
    )


def test_resolve_database_path_accepts_only_one_explicit_database(
    tmp_path,
):
    sql_dir = tmp_path / "SQL"
    sql_dir.mkdir()
    selected = sql_dir / "selected.db"
    unrelated = sql_dir / "unrelated.db"
    selected.touch()
    unrelated.touch()

    assert database_use_cases.resolve_database_path(
        "selected",
        db_dir=sql_dir,
    ) == selected.resolve()
    with pytest.raises(database_use_cases.DatabaseNotFoundError):
        database_use_cases.resolve_database_path(
            "../unrelated",
            db_dir=sql_dir,
        )


def test_create_database_delegates_to_database_service(monkeypatch):
    expected = DatabaseState(database_id="new_db", current_table="main")
    calls = []
    monkeypatch.setattr(
        database_use_cases.database_service,
        "set_database_id",
        lambda database_id: calls.append(database_id) or expected,
    )

    result = database_use_cases.create_database("new_db")

    assert result is expected
    assert calls == ["new_db"]


def test_open_database_delegates_to_database_service(monkeypatch):
    expected = DatabaseState(database_id="existing_db", current_table="main")
    calls = []
    monkeypatch.setattr(
        database_use_cases.database_service,
        "load_existing_database",
        lambda database_id: calls.append(database_id) or expected,
    )

    result = database_use_cases.open_database("existing_db")

    assert result is expected
    assert calls == ["existing_db"]


def test_refresh_database_passes_explicit_table_state(monkeypatch):
    expected = DatabaseState(database_id="test_db", current_table="main")
    calls = []
    monkeypatch.setattr(
        database_use_cases.database_service,
        "update_headers",
        lambda *args: calls.append(args) or expected,
    )

    result = database_use_cases.refresh_database(
        "test_db",
        "main",
        ["CID"],
    )

    assert result is expected
    assert calls == [("test_db", "main", ["CID"])]


def test_get_database_metrics_combines_row_and_group_counts():
    connection = sqlite3.connect(":memory:")
    connection.execute('CREATE TABLE "main" (category TEXT)')
    connection.executemany(
        'INSERT INTO "main" (category) VALUES (?)',
        [("A",), ("A",), ("B",)],
    )

    metrics = database_use_cases.get_database_metrics(
        connection,
        "main",
        "category",
        ["category"],
    )

    assert metrics == database_use_cases.DatabaseMetrics(
        row_count=3,
        group_count=2,
    )


def test_get_table_state_rejects_missing_database_without_opening_it(monkeypatch):
    monkeypatch.setattr(
        database_use_cases.database_service,
        "get_tables",
        lambda database_id: [],
    )
    monkeypatch.setattr(
        database_use_cases.database_service,
        "update_headers",
        lambda *args: pytest.fail("missing database must not be opened"),
    )

    with pytest.raises(database_use_cases.DatabaseNotFoundError):
        database_use_cases.get_table_state("missing", "main")


def test_list_database_tables_returns_available_tables(monkeypatch):
    monkeypatch.setattr(
        database_use_cases.database_service,
        "get_tables",
        lambda database_id: ["main", "curated"],
    )

    assert database_use_cases.list_database_tables("test_db") == [
        "main",
        "curated",
    ]


def test_list_database_tables_rejects_missing_database_without_opening_it(
    monkeypatch,
):
    monkeypatch.setattr(
        database_use_cases.database_service,
        "get_tables",
        lambda database_id: [],
    )
    monkeypatch.setattr(
        database_use_cases.database_service,
        "get_connection",
        lambda *args: pytest.fail("missing database must not be opened"),
    )

    with pytest.raises(database_use_cases.DatabaseNotFoundError):
        database_use_cases.list_database_tables("missing")


def test_get_operation_history_validates_database_and_delegates_to_audit(
    monkeypatch,
):
    stored = {
        "operation_id": 2,
        "operation_type": "table_created",
        "target_table": "curated",
        "source_table": "main",
        "source_columns": '["CID"]',
        "output_columns": '["CID"]',
        "created_at": "2026-07-03T12:00:00+00:00",
        "created_by": "test",
        "status": "success",
        "details": None,
        "query_used": "SELECT CID FROM main",
    }
    expected = ({
        "operation_type": "table_created",
        "target_table": "curated",
        "source_table": "main",
        "source_columns": '["CID"]',
        "created_at": "2026-07-03T12:00:00+00:00",
        "status": "success",
        "details": None,
    },)
    calls = []
    monkeypatch.setattr(
        database_use_cases,
        "list_database_tables",
        lambda database_id: calls.append(("validate", database_id)) or ["main"],
    )
    monkeypatch.setattr(
        database_use_cases.db_audit,
        "get_operation_log",
        lambda db_path: calls.append(("history", db_path)) or [stored],
    )

    result = database_use_cases.get_operation_history("test_db")

    assert result == expected
    assert calls == [
        ("validate", "test_db"),
        ("history", Path("SQL") / "test_db.db"),
    ]


def test_get_table_state_rejects_missing_table(monkeypatch):
    monkeypatch.setattr(
        database_use_cases.database_service,
        "get_tables",
        lambda database_id: ["main"],
    )

    with pytest.raises(database_use_cases.TableNotFoundError):
        database_use_cases.get_table_state("test_db", "missing")


def test_get_table_metrics_opens_validated_database(monkeypatch):
    state = DatabaseState(
        database_id="test_db",
        current_table="main",
        headers=("category",),
    )
    connection = object()
    expected = database_use_cases.DatabaseMetrics(row_count=3, group_count=2)
    calls = []
    monkeypatch.setattr(
        database_use_cases,
        "get_table_state",
        lambda database_id, table: state,
    )
    monkeypatch.setattr(
        database_use_cases.database_service,
        "get_connection",
        lambda database_id: connection,
    )
    monkeypatch.setattr(
        database_use_cases,
        "get_database_metrics",
        lambda *args: calls.append(args) or expected,
    )

    result = database_use_cases.get_table_metrics(
        "test_db",
        "main",
        "category",
    )

    assert result is expected
    assert calls == [(connection, "main", "category", ("category",))]


def test_get_table_metrics_allows_empty_group_column(monkeypatch):
    state = DatabaseState(
        database_id="test_db",
        current_table="main",
        headers=("category",),
    )
    connection = object()
    expected = database_use_cases.DatabaseMetrics(row_count=3, group_count=0)
    monkeypatch.setattr(database_use_cases, "get_table_state", lambda *args: state)
    monkeypatch.setattr(
        database_use_cases.database_service,
        "get_connection",
        lambda database_id: connection,
    )
    monkeypatch.setattr(
        database_use_cases,
        "get_database_metrics",
        lambda *args: expected,
    )

    assert database_use_cases.get_table_metrics("test_db", "main") is expected


def test_get_table_metrics_rejects_unknown_group_column_before_query(monkeypatch):
    state = DatabaseState(
        database_id="test_db",
        current_table="main",
        headers=("category",),
    )
    monkeypatch.setattr(database_use_cases, "get_table_state", lambda *args: state)
    monkeypatch.setattr(
        database_use_cases.database_service,
        "get_connection",
        lambda *args: pytest.fail("invalid column must not open the database"),
    )
    monkeypatch.setattr(
        database_use_cases,
        "get_database_metrics",
        lambda *args: pytest.fail("invalid column must not execute metrics query"),
    )

    with pytest.raises(
        database_use_cases.InvalidColumnError,
        match="Unknown column: missing",
    ):
        database_use_cases.get_table_metrics("test_db", "main", "missing")


def test_get_table_schema_validates_table_and_delegates_to_audit_service(
    monkeypatch,
):
    expected = {
        "table": "main",
        "columns": ({"name": "CID", "data_type": "TEXT"},),
    }
    calls = []
    monkeypatch.setattr(
        database_use_cases,
        "get_table_state",
        lambda *args: calls.append(("validate", args)) or DatabaseState(),
    )
    monkeypatch.setattr(
        database_use_cases.db_audit,
        "get_table_schema",
        lambda *args: calls.append(("schema", args)) or expected,
    )

    result = database_use_cases.get_table_schema("test_db", "main")

    assert result == expected["columns"]
    assert calls == [
        ("validate", ("test_db", "main")),
        ("schema", (Path("SQL/test_db.db"), "main")),
    ]
