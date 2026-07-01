# SPDX-License-Identifier: LGPL-3.0-or-later
import sqlite3

from services.database_core import get_connection


def test_get_connection_creates_database_in_requested_directory(tmp_path):
    db_path = tmp_path / "chemvault.db"

    connection = get_connection("chemvault", db_dir=tmp_path)
    connection.close()

    assert db_path.is_file()


def test_get_connection_returns_usable_sqlite_connection(tmp_path):
    connection = get_connection("chemvault", db_dir=tmp_path)

    connection.execute("CREATE TABLE compounds (cid INTEGER)")
    connection.execute("INSERT INTO compounds (cid) VALUES (2244)")
    result = connection.execute("SELECT cid FROM compounds").fetchone()
    connection.close()

    assert isinstance(connection, sqlite3.Connection)
    assert result == (2244,)
