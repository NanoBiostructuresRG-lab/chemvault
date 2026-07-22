# SPDX-License-Identifier: LGPL-3.0-or-later
import sqlite3

from services.sql_utils import (
    ensure_main_table,
    get_tables_from_connection,
    is_user_facing_table_name,
    table_exists,
)


def test_ensure_main_table_creates_main_with_primary_id():
    connection = sqlite3.connect(":memory:")

    ensure_main_table(connection)

    cursor = connection.cursor()
    cursor.execute('PRAGMA table_info("main")')
    columns = cursor.fetchall()
    assert columns[0][1] == "primary_id"
    assert columns[0][2] == "INTEGER"
    assert columns[0][5] == 1


def test_table_exists_detects_existing_and_missing_tables():
    connection = sqlite3.connect(":memory:")
    connection.execute('CREATE TABLE "main" (primary_id INTEGER PRIMARY KEY AUTOINCREMENT)')

    assert table_exists(connection, "main") is True
    assert table_exists(connection, "missing") is False


def test_get_tables_from_connection_excludes_sqlite_internal_tables_and_orders_names():
    connection = sqlite3.connect(":memory:")
    connection.execute('CREATE TABLE "z_table" (id INTEGER PRIMARY KEY AUTOINCREMENT)')
    connection.execute('CREATE TABLE "a_table" (id INTEGER)')
    connection.execute('CREATE TABLE "_chemvault_table_metadata" (table_name TEXT)')
    connection.execute('CREATE TABLE "_chemvault_operation_log" (operation_id INTEGER)')
    connection.execute('CREATE TABLE "compound_assays" (CID TEXT, AID TEXT, Protein TEXT)')
    connection.execute('CREATE TABLE "compound_activities" (CID TEXT, AID TEXT)')
    connection.execute('CREATE TABLE "_chemvault_jobs" (job_id TEXT)')
    connection.execute(
        'CREATE TABLE "_chemvault_modelability_fingerprint_artifacts" '
        '(fingerprint_identity TEXT)'
    )
    connection.execute('CREATE TABLE "_chemvault_future_support" (id INTEGER)')
    connection.execute('INSERT INTO "z_table" DEFAULT VALUES')

    assert get_tables_from_connection(connection) == ["a_table", "z_table"]
    assert not is_user_facing_table_name(
        "_chemvault_modelability_fingerprint_artifacts"
    )
    assert not is_user_facing_table_name("_chemvault_future_support")
    assert is_user_facing_table_name("_chemvaultx")
