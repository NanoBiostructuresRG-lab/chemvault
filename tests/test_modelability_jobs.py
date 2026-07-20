# SPDX-License-Identifier: LGPL-3.0-or-later

import os
import sqlite3

import pytest

from application import modelability_jobs
from application.job_contracts import job_status_from_record
from application.modelability_index import ModelabilityIndexUseCaseResult
from application.modelability_jobs import (
    InvalidModelabilitySourceError,
    MODELABILITY_INTERRUPTED_MESSAGE,
    create_modelability_job,
    execute_modelability_job,
    fail_orphaned_modelability_jobs,
)
from application.scientific_jobs import (
    create_scientific_job,
    execute_scientific_job,
    get_scientific_job_status,
)
from services.database_core import get_connection
from services.db_audit import register_table_metadata
from services.job_models import JobStatus, JobType
from services.job_store import JobStore
from services.sql_utils import get_tables_from_connection


MODELABILITY_TABLE = "activity_subset_IC50_structure_consolidated"


def _activity_subset_source(table_name):
    return table_name.split("_structure_consolidated", 1)[0]


def _create_database(
    tmp_path,
    monkeypatch,
    tables=(MODELABILITY_TABLE,),
    *,
    register_consolidated=True,
):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "SQL").mkdir()
    connection = sqlite3.connect(tmp_path / "SQL" / "test_db.db")
    for table in tables:
        connection.execute(
            f'CREATE TABLE "{table}" '
            '(SMILES_Harmonized TEXT, Outcome TEXT)'
        )
        connection.executemany(
            f'INSERT INTO "{table}" VALUES (?, ?)',
            [("CCO", "Active"), ("CCC", "Inactive")],
        )
        if register_consolidated:
            source_table = _activity_subset_source(table)
            connection.execute(f'CREATE TABLE "{source_table}" (CID TEXT)')
            register_table_metadata(
                connection,
                source_table,
                role="derived",
                origin="structured_activity_filtered_subset",
                source_table="compound_activities",
            )
            register_table_metadata(
                connection,
                table,
                role="derived",
                origin="structure_consolidation",
                source_table=source_table,
            )
    connection.commit()
    connection.close()


def _result(table_name=MODELABILITY_TABLE):
    return ModelabilityIndexUseCaseResult(
        structure_count=2,
        active_count=1,
        inactive_count=1,
        active_concordance=0.0,
        inactive_concordance=0.0,
        modelability_index=0.0,
        diagnostics=(
            {
                "smiles": "CCC",
                "outcome": "Inactive",
                "nearest_neighbor_smiles": "CCO",
                "nearest_neighbor_outcome": "Active",
                "tanimoto_similarity": 0.5,
                "concordant": False,
            },
            {
                "smiles": "CCO",
                "outcome": "Active",
                "nearest_neighbor_smiles": "CCC",
                "nearest_neighbor_outcome": "Inactive",
                "tanimoto_similarity": 0.5,
                "concordant": False,
            },
        ),
        provenance={
            "source_table": table_name,
            "similarity_metric": "tanimoto",
            "neighbor_rule": "single_nearest_neighbor",
        },
    )


def test_modelability_job_completes_with_json_result_and_no_result_table(
    tmp_path,
    monkeypatch,
):
    _create_database(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(
        modelability_jobs,
        "calculate_table_modelability_index",
        lambda *args: calls.append(args) or _result(),
    )

    created = create_scientific_job(
        "test_db",
        JobType.MODELABILITY_INDEX,
        {"table_name": MODELABILITY_TABLE},
    )
    completed = execute_scientific_job(
        "test_db",
        JobType.MODELABILITY_INDEX,
        created.job_id,
    )
    queried = get_scientific_job_status("test_db", created.job_id)

    assert created.status == JobStatus.PENDING
    assert created.stage == "queued"
    assert created.cancellable is False
    assert completed.status == JobStatus.COMPLETED
    assert queried == completed
    assert calls == [("test_db", MODELABILITY_TABLE)]
    assert completed.result["modelability_index"] == 0.0
    assert len(completed.result["diagnostics"]) == 2
    assert completed.result["provenance"]["similarity_metric"] == "tanimoto"
    assert "fingerprints" not in completed.result

    connection = get_connection("test_db")
    try:
        assert get_tables_from_connection(connection) == [
            "activity_subset_IC50",
            MODELABILITY_TABLE,
        ]
        record = JobStore(connection).get_job(created.job_id)
    finally:
        connection.close()
    assert record.metadata["table_name"] == MODELABILITY_TABLE
    assert record.metadata["cancellation_supported"] is False
    assert record.metadata["result"] == completed.result
    assert "fingerprints" not in record.metadata["result"]


def test_duplicate_active_creation_returns_existing_job(tmp_path, monkeypatch):
    _create_database(tmp_path, monkeypatch)

    first = create_modelability_job("test_db", MODELABILITY_TABLE)
    duplicate = create_modelability_job("test_db", MODELABILITY_TABLE)

    assert duplicate == first
    connection = get_connection("test_db")
    try:
        count = connection.execute(
            "SELECT COUNT(*) FROM _chemvault_jobs "
            "WHERE job_type = 'modelability_index'"
        ).fetchone()[0]
    finally:
        connection.close()
    assert count == 1


def test_creation_rejects_existing_non_consolidated_table(
    tmp_path,
    monkeypatch,
):
    _create_database(
        tmp_path,
        monkeypatch,
        register_consolidated=False,
    )

    with pytest.raises(
        InvalidModelabilitySourceError,
        match="requires an Activity Labels consolidated table",
    ):
        create_modelability_job("test_db", MODELABILITY_TABLE)


def test_creation_rejects_unrelated_structure_consolidation_output(
    tmp_path,
    monkeypatch,
):
    _create_database(
        tmp_path,
        monkeypatch,
        tables=("other_structure_consolidated",),
        register_consolidated=False,
    )
    connection = get_connection("test_db")
    try:
        register_table_metadata(
            connection,
            "other_structure_consolidated",
            role="derived",
            origin="structure_consolidation",
            source_table="unrelated_source",
        )
    finally:
        connection.close()

    with pytest.raises(
        InvalidModelabilitySourceError,
        match="requires an Activity Labels consolidated table",
    ):
        create_modelability_job("test_db", "other_structure_consolidated")


def test_creation_rejects_forged_activity_subset_lineage(tmp_path, monkeypatch):
    _create_database(tmp_path, monkeypatch)
    connection = get_connection("test_db")
    try:
        register_table_metadata(
            connection,
            "activity_subset_IC50",
            role="derived",
            origin="refine",
            source_table="compound_activities",
        )
    finally:
        connection.close()

    with pytest.raises(
        InvalidModelabilitySourceError,
        match="requires an Activity Labels consolidated table",
    ):
        create_modelability_job("test_db", MODELABILITY_TABLE)


def test_modelability_execution_failure_is_persisted(tmp_path, monkeypatch):
    _create_database(tmp_path, monkeypatch)
    monkeypatch.setattr(
        modelability_jobs,
        "calculate_table_modelability_index",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("calculation failed")),
    )

    created = create_modelability_job("test_db", MODELABILITY_TABLE)
    failed = execute_modelability_job("test_db", created.job_id)

    assert failed.status == JobStatus.FAILED
    assert failed.error == "calculation failed"
    assert failed.result is None
    assert failed.cancellable is False


def test_dead_orphan_is_failed_and_fresh_job_can_be_created(
    tmp_path,
    monkeypatch,
):
    _create_database(tmp_path, monkeypatch)
    created = create_modelability_job("test_db", MODELABILITY_TABLE)
    connection = get_connection("test_db")
    store = JobStore(connection)
    store.claim_pending_scientific_job(created.job_id, 424242)
    store.start_job(created.job_id)
    connection.close()

    failed = fail_orphaned_modelability_jobs(
        "test_db",
        executor_is_alive=lambda *_args: False,
        process_is_alive=lambda _pid: False,
        current_pid=os.getpid(),
    )

    assert len(failed) == 1
    assert failed[0].status == JobStatus.FAILED
    assert failed[0].error == MODELABILITY_INTERRUPTED_MESSAGE

    replacement = create_modelability_job("test_db", MODELABILITY_TABLE)
    assert replacement.job_id != created.job_id
    assert replacement.status == JobStatus.PENDING


def test_orphan_cleanup_preserves_current_executor_and_live_foreign_pid(
    tmp_path,
    monkeypatch,
):
    _create_database(
        tmp_path,
        monkeypatch,
        tables=(
            "activity_subset_current_structure_consolidated",
            "activity_subset_foreign_structure_consolidated",
        ),
    )
    current = create_modelability_job(
        "test_db",
        "activity_subset_current_structure_consolidated",
    )
    foreign = create_modelability_job(
        "test_db",
        "activity_subset_foreign_structure_consolidated",
    )
    connection = get_connection("test_db")
    store = JobStore(connection)
    store.claim_pending_scientific_job(current.job_id, os.getpid())
    store.start_job(current.job_id)
    store.claim_pending_scientific_job(foreign.job_id, 777777)
    store.start_job(foreign.job_id)
    connection.close()

    failed = fail_orphaned_modelability_jobs(
        "test_db",
        executor_is_alive=lambda _database_id, job_id: job_id == current.job_id,
        process_is_alive=lambda pid: pid == 777777,
        current_pid=os.getpid(),
    )

    assert failed == ()
    connection = get_connection("test_db")
    try:
        assert JobStore(connection).get_job(current.job_id).status == "running"
        assert JobStore(connection).get_job(foreign.job_id).status == "running"
    finally:
        connection.close()
