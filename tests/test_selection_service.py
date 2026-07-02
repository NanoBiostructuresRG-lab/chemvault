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


def test_get_active_selected_headers_drops_stale_columns():
    result = selection.get_active_selected_headers(
        ["CID", "SMILES"],
        ["CID", "stale_column", "SMILES"],
    )

    assert result == ["CID", "SMILES"]


def test_sync_selected_headers_returns_active_selection():
    result = selection.sync_selected_headers(
        ["CID"],
        ["CID", "SMILES"],
    )

    assert result == ["CID"]


def test_build_preview_table_returns_empty_without_selection():
    assert selection.build_preview_table("test_db", "main", ["CID"], []).empty


def test_build_preview_table_limits_to_selected_columns(monkeypatch):
    connection = create_selection_db()
    monkeypatch.setattr(selection, "get_connection", lambda db_name: connection)
    result = selection.build_preview_table(
        "test_db",
        "main",
        ["CID", "SMILES", "MW"],
        ["CID", "stale_column", "SMILES"],
    )

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
    result = selection.get_selected_columns(
        "test_db",
        "main",
        ["CID", "SMILES", "MW"],
        ["CID", "MW"],
    )

    expected = pd.DataFrame(
        [
            {"CID": "1", "MW": "46.07"},
            {"CID": "2", "MW": "44.10"},
        ]
    )
    pd.testing.assert_frame_equal(result, expected)
