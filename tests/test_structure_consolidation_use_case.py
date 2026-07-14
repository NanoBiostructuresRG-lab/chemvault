# SPDX-License-Identifier: LGPL-3.0-or-later
import json
import sqlite3

import pandas as pd
import pytest

from application import structure_consolidation as use_case
from services.db_audit import ensure_operation_log, ensure_table_metadata
from services.sql_utils import get_tables_from_connection


def _source_dataframe():
    return pd.DataFrame(
        [
            {
                "CID": "1",
                "AID": "10",
                "Outcome": "Active",
                "InChIKey": "KEY-CCO",
                "SMILES_Harmonized": "CCO",
                "SMILES_Harmonization_Status": "ok",
                "SMILES_RDKit": "CCO",
                "MW": "46.07",
            },
            {
                "CID": "1",
                "AID": "11",
                "Outcome": "Active",
                "InChIKey": "KEY-CCO",
                "SMILES_Harmonized": "CCO",
                "SMILES_Harmonization_Status": "ok_with_warnings",
                "SMILES_RDKit": "CCO",
                "MW": "46.07",
            },
            {
                "CID": "2",
                "AID": "20",
                "Outcome": "Inactive",
                "InChIKey": "KEY-CCC",
                "SMILES_Harmonized": "CCC",
                "SMILES_Harmonization_Status": "ok",
                "SMILES_RDKit": "CCC",
                "MW": "44.10",
            },
            {
                "CID": "3",
                "AID": "30",
                "Outcome": "Active",
                "InChIKey": "KEY-CCN",
                "SMILES_Harmonized": "CCN",
                "SMILES_Harmonization_Status": "ok",
                "SMILES_RDKit": "CCN",
                "MW": "45.08",
            },
            {
                "CID": "3",
                "AID": "31",
                "Outcome": "Inactive",
                "InChIKey": "KEY-CCN",
                "SMILES_Harmonized": "CCN",
                "SMILES_Harmonization_Status": "ok",
                "SMILES_RDKit": "CCN",
                "MW": "45.08",
            },
            {
                "CID": "4",
                "AID": "40",
                "Outcome": "Active",
                "InChIKey": "",
                "SMILES_Harmonized": "",
                "SMILES_Harmonization_Status": "failed",
                "SMILES_RDKit": None,
                "MW": None,
            },
        ]
    )


def _create_database(tmp_path):
    sql_dir = tmp_path / "SQL"
    sql_dir.mkdir()
    db_path = sql_dir / "generic.db"
    source = _source_dataframe()
    connection = sqlite3.connect(db_path)
    source.to_sql("screening_results", connection, index=False)
    connection.close()
    return sql_dir, db_path, source


def test_generic_source_creates_real_derived_table_without_mutating_source(
    tmp_path,
):
    sql_dir, db_path, source = _create_database(tmp_path)

    result = use_case.consolidate_structure_table(
        "generic",
        "screening_results",
        db_dir=sql_dir,
    )

    assert result.table_name == "screening_results_structure_consolidated"
    assert result.source_row_count == 6
    assert result.created_row_count == 2
    assert result.active_structure_count == 1
    assert result.inactive_structure_count == 1
    assert result.conflicting_structure_count == 1
    assert result.unusable_row_count == 1

    connection = sqlite3.connect(db_path)
    assert connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (result.table_name,),
    ).fetchone() == (1,)
    derived = pd.read_sql_query(
        f'SELECT * FROM "{result.table_name}" ORDER BY SMILES_Harmonized',
        connection,
    )
    persisted_source = pd.read_sql_query(
        'SELECT * FROM "screening_results"',
        connection,
    )
    connection.close()

    assert list(derived["SMILES_Harmonized"]) == ["CCC", "CCO"]
    assert list(derived["Outcome"]) == ["Inactive", "Active"]
    cco = derived.loc[derived["SMILES_Harmonized"] == "CCO"].iloc[0]
    assert json.loads(cco["Source_CIDs"]) == ["1"]
    assert json.loads(cco["Source_AIDs"]) == ["10", "11"]
    assert cco["MW"] == "46.07"
    pd.testing.assert_frame_equal(persisted_source, source)


def test_derived_table_naming_is_unique(tmp_path):
    sql_dir, db_path, _source = _create_database(tmp_path)

    first = use_case.consolidate_structure_table(
        "generic", "screening_results", db_dir=sql_dir
    )
    second = use_case.consolidate_structure_table(
        "generic", "screening_results", db_dir=sql_dir
    )

    assert first.table_name == "screening_results_structure_consolidated"
    assert second.table_name == "screening_results_structure_consolidated_2"
    connection = sqlite3.connect(db_path)
    assert set(get_tables_from_connection(connection)) == {
        "screening_results",
        first.table_name,
        second.table_name,
    }
    connection.close()


def test_created_table_registers_metadata_and_operation_provenance(tmp_path):
    sql_dir, db_path, _source = _create_database(tmp_path)

    result = use_case.consolidate_structure_table(
        "generic", "screening_results", db_dir=sql_dir
    )

    connection = sqlite3.connect(db_path)
    metadata = connection.execute(
        """
        SELECT role, origin, source_table, created_by
        FROM _chemvault_table_metadata
        WHERE table_name = ?
        """,
        (result.table_name,),
    ).fetchone()
    operation = connection.execute(
        """
        SELECT operation_type, target_table, source_table, status, details
        FROM _chemvault_operation_log
        WHERE target_table = ?
        """,
        (result.table_name,),
    ).fetchone()
    connection.close()

    assert metadata == (
        "derived",
        "structure_consolidation",
        "screening_results",
        "consolidate_structure_table",
    )
    assert operation[:4] == (
        "structure_consolidation_created",
        result.table_name,
        "screening_results",
        "success",
    )
    details = json.loads(operation[4])
    assert details["created_rows"] == 2
    assert details["usable_source_rows"] == 5
    assert details["unique_harmonized_structures"] == 3
    assert details["consolidated_duplicates"] == 1


def test_failure_rolls_back_table_metadata_and_success_log(
    tmp_path,
    monkeypatch,
):
    sql_dir, db_path, _source = _create_database(tmp_path)
    connection = sqlite3.connect(db_path)
    ensure_table_metadata(connection, commit=False)
    ensure_operation_log(connection, commit=False)
    connection.commit()
    connection.close()

    def fail_operation(*_args, **_kwargs):
        raise RuntimeError("audit write failed")

    monkeypatch.setattr(use_case, "register_operation", fail_operation)

    with pytest.raises(RuntimeError, match="audit write failed"):
        use_case.consolidate_structure_table(
            "generic", "screening_results", db_dir=sql_dir
        )

    connection = sqlite3.connect(db_path)
    assert get_tables_from_connection(connection) == ["screening_results"]
    assert connection.execute(
        "SELECT COUNT(*) FROM _chemvault_table_metadata"
    ).fetchone() == (0,)
    assert connection.execute(
        "SELECT COUNT(*) FROM _chemvault_operation_log "
        "WHERE operation_type = 'structure_consolidation_created'"
    ).fetchone() == (0,)
    connection.close()
