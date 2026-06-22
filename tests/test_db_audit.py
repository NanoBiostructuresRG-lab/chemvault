# SPDX-License-Identifier: LGPL-3.0-or-later
#============================================
# python -m pytest tests\test_db_audit.py -q
#============================================
import sqlite3

import pytest

from services.db_audit import METADATA_TABLE
from tools.db_audit import (
    assert_clean_database,
    count_rows,
    inspect_database,
    inspect_schema,
    list_databases,
    list_tables,
    parse_expected_rows,
)


def create_test_db(db_path):
    with sqlite3.connect(db_path) as con:
        cur = con.cursor()
        cur.execute("CREATE TABLE main (CID INTEGER, SMILES TEXT)")
        cur.executemany(
            "INSERT INTO main (CID, SMILES) VALUES (?, ?)",
            [
                (1, "CCO"),
                (2, "CCC"),
            ],
        )
        cur.execute("CREATE TABLE stale_query_b (CID INTEGER)")
        con.commit()


def test_list_tables_and_count_rows(tmp_path):
    db_path = tmp_path / "test.db"
    create_test_db(db_path)

    tables = list_tables(db_path)

    assert tables == ["main", "stale_query_b"]
    assert count_rows(db_path, "main") == 2
    assert count_rows(db_path, "stale_query_b") == 0


def test_list_databases_lists_only_db_files(tmp_path, capsys):
    (tmp_path / "a.db").write_bytes(b"")
    (tmp_path / "b.txt").write_text("not a database", encoding="utf-8")
    (tmp_path / "c.db").write_bytes(b"")

    result = list_databases(tmp_path)
    output = capsys.readouterr().out

    assert result == 0
    assert "- a.db" in output
    assert "- c.db" in output
    assert "b.txt" not in output


def test_list_databases_returns_failure_for_missing_directory(tmp_path):
    result = list_databases(tmp_path / "missing")

    assert result == 1


def test_inspect_database_returns_success_for_existing_db(tmp_path):
    db_path = tmp_path / "test.db"
    create_test_db(db_path)

    result = inspect_database(db_path)

    assert result == 0


def test_inspect_database_returns_failure_for_missing_db(tmp_path):
    db_path = tmp_path / "missing.db"

    result = inspect_database(db_path)

    assert result == 1


def test_inspect_schema_prints_table_columns(tmp_path, capsys):
    db_path = tmp_path / "test.db"
    create_test_db(db_path)

    result = inspect_schema(db_path)
    output = capsys.readouterr().out

    assert result == 0
    assert "Schema:" in output
    assert "- main" in output
    assert "CID | INTEGER" in output
    assert "SMILES | TEXT" in output


def test_inspect_schema_returns_failure_for_missing_db(tmp_path):
    result = inspect_schema(tmp_path / "missing.db")

    assert result == 1


def test_parse_expected_rows_accepts_grouped_values():
    result = parse_expected_rows([["main=102", "Nueva_tabla=102"]])

    assert result == {"main": 102, "Nueva_tabla": 102}


def test_parse_expected_rows_accepts_repeated_flag_values():
    result = parse_expected_rows([["main=102"], ["Nueva_tabla=102"]])

    assert result == {"main": 102, "Nueva_tabla": 102}


def test_parse_expected_rows_rejects_missing_equals():
    with pytest.raises(ValueError, match="Invalid --expect-row value"):
        parse_expected_rows([["main"]])


def test_parse_expected_rows_rejects_non_integer_count():
    with pytest.raises(ValueError):
        parse_expected_rows([["main=abc"]])


def test_assert_clean_database_accepts_expected_state(tmp_path):
    db_path = tmp_path / "test.db"

    with sqlite3.connect(db_path) as con:
        cur = con.cursor()
        cur.execute("CREATE TABLE main (CID INTEGER, SMILES TEXT)")
        cur.executemany(
            "INSERT INTO main (CID, SMILES) VALUES (?, ?)",
            [
                (1, "CCO"),
                (2, "CCC"),
            ],
        )
        con.commit()

    result = assert_clean_database(
        db_path,
        allowed_tables=["main"],
        expected_rows={"main": 2},
    )

    assert result == 0


def test_assert_clean_database_ignores_chemvault_metadata_table(tmp_path):
    db_path = tmp_path / "test.db"

    with sqlite3.connect(db_path) as con:
        cur = con.cursor()
        cur.execute("CREATE TABLE main (CID INTEGER, SMILES TEXT)")
        cur.execute(
            f"CREATE TABLE {METADATA_TABLE} (table_name TEXT PRIMARY KEY)"
        )
        cur.execute("INSERT INTO main (CID, SMILES) VALUES (?, ?)", (1, "CCO"))
        con.commit()

    result = assert_clean_database(
        db_path,
        allowed_tables=["main"],
        expected_rows={"main": 1},
    )

    assert result == 0


def test_assert_clean_database_ignores_sqlite_sequence_table(tmp_path):
    db_path = tmp_path / "test.db"

    with sqlite3.connect(db_path) as con:
        cur = con.cursor()
        cur.execute("CREATE TABLE main (primary_id INTEGER PRIMARY KEY AUTOINCREMENT, CID INTEGER)")
        cur.execute("INSERT INTO main (CID) VALUES (?)", (1,))
        con.commit()

    result = assert_clean_database(
        db_path,
        allowed_tables=["main"],
        expected_rows={"main": 1},
    )

    assert result == 0


def test_assert_clean_database_fails_with_unexpected_table(tmp_path):
    db_path = tmp_path / "test.db"
    create_test_db(db_path)

    result = assert_clean_database(
        db_path,
        allowed_tables=["main"],
        expected_rows={"main": 2},
    )

    assert result == 1


def test_assert_clean_database_fails_with_wrong_row_count(tmp_path):
    db_path = tmp_path / "test.db"

    with sqlite3.connect(db_path) as con:
        cur = con.cursor()
        cur.execute("CREATE TABLE main (CID INTEGER, SMILES TEXT)")
        cur.execute("INSERT INTO main (CID, SMILES) VALUES (?, ?)", (1, "CCO"))
        con.commit()

    result = assert_clean_database(
        db_path,
        allowed_tables=["main"],
        expected_rows={"main": 102},
    )

    assert result == 1
