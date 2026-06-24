# SPDX-License-Identifier: LGPL-3.0-or-later
import sqlite3

import pytest

from services.db_audit import (
    METADATA_TABLE,
    OPERATION_LOG_TABLE,
    count_rows,
    delete_user_table,
    ensure_operation_log,
    ensure_table_metadata,
    get_database_schema,
    get_database_summary,
    get_operation_log,
    get_table_metadata,
    get_table_profiles,
    get_table_row_counts,
    get_user_table_profiles,
    list_database_files,
    list_tables,
    recommend_table_action,
    register_operation,
    register_table_metadata,
)


def create_test_db(db_path):
    with sqlite3.connect(db_path) as con:
        cur = con.cursor()
        cur.execute("""
            CREATE TABLE main (
                primary_id INTEGER PRIMARY KEY AUTOINCREMENT,
                CID TEXT NOT NULL,
                MW REAL DEFAULT 0
            )
        """)
        cur.executemany(
            "INSERT INTO main (CID, MW) VALUES (?, ?)",
            [
                ("1", 46.07),
                ("2", 44.09),
            ],
        )
        cur.execute("CREATE TABLE derived (CID TEXT)")
        con.commit()


def test_list_database_files_returns_sorted_db_paths(tmp_path):
    (tmp_path / "b.db").write_bytes(b"")
    (tmp_path / "a.db").write_bytes(b"")
    (tmp_path / "notes.txt").write_text("ignore", encoding="utf-8")

    result = list_database_files(tmp_path)

    assert [path.name for path in result] == ["a.db", "b.db"]


def test_list_database_files_rejects_missing_directory(tmp_path):
    with pytest.raises(FileNotFoundError):
        list_database_files(tmp_path / "missing")


def test_table_names_and_row_counts_are_structured(tmp_path):
    db_path = tmp_path / "test.db"
    create_test_db(db_path)

    assert list_tables(db_path) == ["derived", "main", "sqlite_sequence"]
    assert count_rows(db_path, "main") == 2
    assert get_table_row_counts(db_path) == [
        {"table": "derived", "rows": 0},
        {"table": "main", "rows": 2},
        {"table": "sqlite_sequence", "rows": 1},
    ]


def test_database_schema_returns_column_metadata(tmp_path):
    db_path = tmp_path / "test.db"
    create_test_db(db_path)

    schema = get_database_schema(db_path)
    main_schema = next(table for table in schema if table["table"] == "main")

    assert main_schema["columns"] == [
        {
            "cid": 0,
            "name": "primary_id",
            "data_type": "INTEGER",
            "not_null": False,
            "default_value": None,
            "primary_key": True,
        },
        {
            "cid": 1,
            "name": "CID",
            "data_type": "TEXT",
            "not_null": True,
            "default_value": None,
            "primary_key": False,
        },
        {
            "cid": 2,
            "name": "MW",
            "data_type": "REAL",
            "not_null": False,
            "default_value": "0",
            "primary_key": False,
        },
    ]


def test_database_summary_combines_counts_and_schema(tmp_path):
    db_path = tmp_path / "test.db"
    create_test_db(db_path)

    summary = get_database_summary(db_path)

    assert summary["path"] == db_path
    assert summary["tables"][1] == {"table": "main", "rows": 2}
    assert summary["schema"][1]["table"] == "main"
    assert summary["profiles"][1]["table"] == "main"


def test_table_profiles_classify_base_and_structure_only_tables(tmp_path):
    db_path = tmp_path / "test.db"
    create_test_db(db_path)

    profiles = {profile["table"]: profile for profile in get_table_profiles(db_path)}

    assert profiles["main"]["origin"] == "base"
    assert profiles["main"]["status"] == ["ok", "few_columns"]
    assert profiles["derived"]["origin"] == "derived_inferred"
    assert profiles["derived"]["status"] == ["structure_only", "few_columns"]
    assert profiles["derived"]["role"] == "derived"
    assert profiles["derived"]["metadata_status"] == "inferred"
    assert profiles["main"]["recommended_action"] == "Keep as base"
    assert profiles["derived"]["recommended_action"] == "Review or delete"


def test_table_profiles_detect_temporary_test_and_harmonsmile_candidates(tmp_path):
    db_path = tmp_path / "test.db"
    with sqlite3.connect(db_path) as con:
        cur = con.cursor()
        cur.execute("CREATE TABLE stale_b (CID TEXT)")
        cur.execute("CREATE TABLE Nueva_tabla_test (CID TEXT, SMILES TEXT)")
        cur.execute("CREATE TABLE harmonsmile_result (CID TEXT, SMILES TEXT, Charge TEXT)")
        cur.execute("INSERT INTO harmonsmile_result VALUES ('1', 'CCO', '0')")
        con.commit()

    profiles = {profile["table"]: profile for profile in get_table_profiles(db_path)}

    assert "possible_temporary" in profiles["stale_b"]["status"]
    assert "possible_test_table" in profiles["Nueva_tabla_test"]["status"]
    assert profiles["harmonsmile_result"]["origin"] == "possible_harmonsmile"
    assert "possible_harmonsmile_output" in profiles["harmonsmile_result"]["status"]


def test_table_profiles_detect_possible_duplicates(tmp_path):
    db_path = tmp_path / "test.db"
    with sqlite3.connect(db_path) as con:
        cur = con.cursor()
        cur.execute("CREATE TABLE derived_a (CID TEXT, SMILES TEXT)")
        cur.execute("CREATE TABLE derived_b (CID TEXT, SMILES TEXT)")
        cur.execute("INSERT INTO derived_a VALUES ('1', 'CCO')")
        cur.execute("INSERT INTO derived_b VALUES ('1', 'CCO')")
        con.commit()

    profiles = {profile["table"]: profile for profile in get_table_profiles(db_path)}

    assert "possible_duplicate" in profiles["derived_a"]["status"]
    assert "possible_duplicate" in profiles["derived_b"]["status"]
    assert profiles["derived_a"]["recommended_action"] == "Compare before use"
    assert profiles["derived_b"]["recommended_action"] == "Compare before use"


def test_recommend_table_action_marks_registered_clean_tables_as_available():
    profile = {
        "table": "derived_result",
        "status": ["ok"],
        "metadata_status": "registered",
    }

    assert recommend_table_action(profile) == "Available"


def test_recommend_table_action_marks_inferred_tables_for_review():
    profile = {
        "table": "legacy_result",
        "status": ["ok"],
        "metadata_status": "inferred",
    }

    assert recommend_table_action(profile) == "Review provenance"


def test_get_table_metadata_returns_empty_mapping_without_metadata_table(tmp_path):
    db_path = tmp_path / "test.db"
    create_test_db(db_path)

    assert get_table_metadata(db_path) == {}


def test_register_table_metadata_persists_registered_provenance(tmp_path):
    db_path = tmp_path / "test.db"
    with sqlite3.connect(db_path) as con:
        con.execute("CREATE TABLE main (CID TEXT)")
        register_table_metadata(
            con,
            "main",
            role="base",
            origin="csv_upload",
            source_table=None,
            created_by="test",
            query_used=None,
            notes="Registered in test.",
        )

    metadata = get_table_metadata(db_path)

    assert list_tables(db_path) == [METADATA_TABLE, "main"]
    assert metadata["main"]["role"] == "base"
    assert metadata["main"]["origin"] == "csv_upload"
    assert metadata["main"]["created_by"] == "test"
    assert metadata["main"]["notes"] == "Registered in test."


def test_ensure_table_metadata_creates_internal_table(tmp_path):
    db_path = tmp_path / "test.db"
    with sqlite3.connect(db_path) as con:
        ensure_table_metadata(con)

    with sqlite3.connect(db_path) as con:
        cur = con.cursor()
        cur.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (METADATA_TABLE,),
        )
        assert cur.fetchone() == (1,)


def test_ensure_operation_log_creates_internal_table(tmp_path):
    db_path = tmp_path / "test.db"
    with sqlite3.connect(db_path) as con:
        ensure_operation_log(con)

    with sqlite3.connect(db_path) as con:
        cur = con.cursor()
        cur.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (OPERATION_LOG_TABLE,),
        )
        assert cur.fetchone() == (1,)


def test_get_operation_log_returns_empty_list_without_operation_table(tmp_path):
    db_path = tmp_path / "test.db"
    create_test_db(db_path)

    assert get_operation_log(db_path) == []


def test_register_operation_persists_operation_log_entry(tmp_path):
    db_path = tmp_path / "test.db"
    with sqlite3.connect(db_path) as con:
        operation_id = register_operation(
            con,
            operation_type="refine_table_created",
            target_table="derived_result",
            source_table="main",
            source_columns=["CID", "SMILES"],
            output_columns=("CID",),
            created_by="test",
            details="Created from selected columns.",
            query_used='CREATE TABLE "derived_result" AS SELECT "CID" FROM "main"',
        )

    operations = get_operation_log(db_path)

    assert operation_id == 1
    assert list_tables(db_path) == [OPERATION_LOG_TABLE, "sqlite_sequence"]
    assert operations[0]["operation_id"] == 1
    assert operations[0]["operation_type"] == "refine_table_created"
    assert operations[0]["target_table"] == "derived_result"
    assert operations[0]["source_table"] == "main"
    assert operations[0]["source_columns"] == '["CID", "SMILES"]'
    assert operations[0]["output_columns"] == '["CID"]'
    assert operations[0]["created_by"] == "test"
    assert operations[0]["status"] == "success"
    assert operations[0]["details"] == "Created from selected columns."
    assert operations[0]["query_used"] == 'CREATE TABLE "derived_result" AS SELECT "CID" FROM "main"'


def test_operation_log_returns_newest_entries_first(tmp_path):
    db_path = tmp_path / "test.db"
    with sqlite3.connect(db_path) as con:
        register_operation(con, "database_created", target_table="main")
        register_operation(con, "refine_table_created", target_table="derived_result")

    operations = get_operation_log(db_path)

    assert [operation["operation_type"] for operation in operations] == [
        "refine_table_created",
        "database_created",
    ]


def test_register_operation_rejects_required_blank_values():
    connection = sqlite3.connect(":memory:")

    with pytest.raises(ValueError, match="operation_type is required"):
        register_operation(connection, "")
    with pytest.raises(ValueError, match="status is required"):
        register_operation(connection, "database_created", status="")


def test_table_profiles_prefer_registered_metadata_over_inference(tmp_path):
    db_path = tmp_path / "test.db"
    with sqlite3.connect(db_path) as con:
        cur = con.cursor()
        cur.execute("CREATE TABLE main (CID TEXT, SMILES TEXT)")
        cur.execute("CREATE TABLE derived_result (CID TEXT, SMILES TEXT)")
        register_table_metadata(
            con,
            "derived_result",
            role="derived",
            origin="refine",
            source_table="main",
            created_by="test",
            query_used='CREATE TABLE "derived_result" AS SELECT "CID" FROM "main"',
            notes="Derived table.",
        )

    profiles = {profile["table"]: profile for profile in get_table_profiles(db_path)}

    assert profiles["derived_result"]["role"] == "derived"
    assert profiles["derived_result"]["origin"] == "refine"
    assert profiles["derived_result"]["source_table"] == "main"
    assert profiles["derived_result"]["metadata_status"] == "registered"


def test_user_table_profiles_exclude_internal_tables(tmp_path):
    db_path = tmp_path / "test.db"
    with sqlite3.connect(db_path) as con:
        cur = con.cursor()
        cur.execute("CREATE TABLE main (primary_id INTEGER PRIMARY KEY AUTOINCREMENT, CID TEXT)")
        cur.execute("CREATE TABLE compound_assays (CID TEXT, AID TEXT, Protein TEXT)")
        cur.execute("CREATE TABLE compound_activities (CID TEXT, AID TEXT)")
        cur.execute("INSERT INTO main (CID) VALUES ('1')")
        ensure_table_metadata(con)

    profiles = get_user_table_profiles(db_path)

    assert [profile["table"] for profile in profiles] == ["main"]


def test_delete_user_table_removes_table_and_metadata(tmp_path):
    db_path = tmp_path / "test.db"
    with sqlite3.connect(db_path) as con:
        cur = con.cursor()
        cur.execute("CREATE TABLE main (CID TEXT)")
        cur.execute("CREATE TABLE derived_result (CID TEXT)")
        register_table_metadata(
            con,
            "derived_result",
            role="derived",
            origin="refine",
            source_table="main",
        )
        delete_user_table(con, "derived_result")

    assert list_tables(db_path) == [OPERATION_LOG_TABLE, METADATA_TABLE, "main", "sqlite_sequence"]
    assert get_table_metadata(db_path) == {}
    operations = get_operation_log(db_path)
    assert operations[0]["operation_type"] == "table_deleted"
    assert operations[0]["target_table"] == "derived_result"
    assert operations[0]["created_by"] == "delete_user_table"


def test_delete_user_table_rejects_main_and_internal_tables(tmp_path):
    db_path = tmp_path / "test.db"
    with sqlite3.connect(db_path) as con:
        cur = con.cursor()
        cur.execute("CREATE TABLE main (primary_id INTEGER PRIMARY KEY AUTOINCREMENT)")
        cur.execute("INSERT INTO main DEFAULT VALUES")
        ensure_table_metadata(con)

        with pytest.raises(ValueError, match="main table cannot be deleted"):
            delete_user_table(con, "main")
        with pytest.raises(ValueError, match="Internal SQLite or ChemVault"):
            delete_user_table(con, METADATA_TABLE)
        with pytest.raises(ValueError, match="Internal SQLite or ChemVault"):
            delete_user_table(con, "compound_activities")
        with pytest.raises(ValueError, match="Internal SQLite or ChemVault"):
            delete_user_table(con, "sqlite_sequence")


def test_delete_user_table_rejects_missing_table(tmp_path):
    db_path = tmp_path / "test.db"
    with sqlite3.connect(db_path) as con:
        with pytest.raises(ValueError, match="Table not found"):
            delete_user_table(con, "missing")
