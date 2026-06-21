# SPDX-License-Identifier: LGPL-3.0-or-later
import sqlite3

import pandas as pd

from services import selection


def create_selection_db():
    connection = sqlite3.connect(":memory:")
    connection.execute('CREATE TABLE "main" (CID TEXT, SMILES TEXT, MW TEXT)')
    connection.executemany(
        'INSERT INTO "main" (CID, SMILES, MW) VALUES (?, ?, ?)',
        [
            ("1", "CCO", "46.07"),
            ("2", "CCC", "44.10"),
        ],
    )
    return connection


def test_get_active_selected_headers_drops_stale_columns(monkeypatch):
    monkeypatch.setattr(
        selection.st,
        "session_state",
        {
            "headers": ["CID", "SMILES"],
            "selected_headers": ["CID", "stale_column", "SMILES"],
        },
    )

    assert selection.get_active_selected_headers() == ["CID", "SMILES"]


def test_sync_selected_headers_updates_session_state(monkeypatch):
    session_state = {
        "headers": ["CID"],
        "selected_headers": ["CID", "SMILES"],
    }
    monkeypatch.setattr(selection.st, "session_state", session_state)

    selection.sync_selected_headers()

    assert session_state["selected_headers"] == ["CID"]


def test_build_preview_table_returns_empty_without_selection(monkeypatch):
    monkeypatch.setattr(
        selection.st,
        "session_state",
        {
            "database_id": "test_db",
            "current_table": "main",
            "headers": ["CID"],
            "selected_headers": [],
        },
    )

    assert selection.build_preview_table().empty


def test_build_preview_table_limits_to_selected_columns(monkeypatch):
    connection = create_selection_db()
    monkeypatch.setattr(selection, "get_connection", lambda db_name: connection)
    monkeypatch.setattr(
        selection.st,
        "session_state",
        {
            "database_id": "test_db",
            "current_table": "main",
            "headers": ["CID", "SMILES", "MW"],
            "selected_headers": ["CID", "stale_column", "SMILES"],
        },
    )

    result = selection.build_preview_table()

    expected = pd.DataFrame(
        [
            {"CID": "1", "SMILES": "CCO"},
            {"CID": "2", "SMILES": "CCC"},
        ]
    )
    pd.testing.assert_frame_equal(result, expected)


def test_get_selected_columns_returns_all_selected_rows(monkeypatch):
    connection = create_selection_db()
    monkeypatch.setattr(selection, "get_connection", lambda db_name: connection)
    monkeypatch.setattr(
        selection.st,
        "session_state",
        {
            "database_id": "test_db",
            "current_table": "main",
            "headers": ["CID", "SMILES", "MW"],
            "selected_headers": ["CID", "MW"],
        },
    )

    result = selection.get_selected_columns()

    expected = pd.DataFrame(
        [
            {"CID": "1", "MW": "46.07"},
            {"CID": "2", "MW": "44.10"},
        ]
    )
    pd.testing.assert_frame_equal(result, expected)
