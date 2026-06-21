# SPDX-License-Identifier: LGPL-3.0-or-later
#============================================
# python -m pytest tests\test_db_audit.py -q
#============================================
import sqlite3

from tools.db_audit import (
    assert_clean_database,
    count_rows,
    inspect_database,
    list_tables,
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


def test_inspect_database_returns_success_for_existing_db(tmp_path):
    db_path = tmp_path / "test.db"
    create_test_db(db_path)

    result = inspect_database(db_path)

    assert result == 0


def test_inspect_database_returns_failure_for_missing_db(tmp_path):
    db_path = tmp_path / "missing.db"

    result = inspect_database(db_path)

    assert result == 1


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