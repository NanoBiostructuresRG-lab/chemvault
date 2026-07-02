# SPDX-License-Identifier: LGPL-3.0-or-later
import ast
import sqlite3
from pathlib import Path

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
