# SPDX-License-Identifier: LGPL-3.0-or-later

import json
import os
import sqlite3

import pytest

from application import modelability_jobs
from application.job_contracts import job_status_from_record
from application.modelability_index import (
    POPULATION_POLICY,
    ModelabilityIndexUseCaseResult,
    ModelabilityStructuralContext,
    PreparedModelabilityInput,
)
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
from services.modelability_index import NearestNeighborDiagnostics
from services.modelability_fingerprint_artifacts import FINGERPRINT_ARTIFACTS_TABLE
from services.murcko_metrics import MurckoStructuralMetrics
from services.murcko_nn_interface import MurckoNNInterfaceResult
from services.murcko_population import MurckoPopulationResult
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
            "(SMILES_Harmonized TEXT, Outcome TEXT, "
            "Reference_Selection_Status TEXT)"
        )
        connection.executemany(
            f'INSERT INTO "{table}" VALUES (?, ?, ?)',
            [
                ("CCO", "Active", "selected"),
                ("CCC", "Inactive", "selected"),
            ],
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
        structural_context=ModelabilityStructuralContext(
            murcko_population=MurckoPopulationResult(
                total_count=2,
                cyclic_count=0,
                acyclic_count=2,
                murcko_coverage=0.0,
                scaffold_count=0,
                assignments=(None, None),
                scaffold_outcome_counts={},
            ),
            murcko_metrics=MurckoStructuralMetrics(
                shared_scaffold_count=0,
                shared_molecule_count=0,
                shared_scaffold_fraction=None,
                shared_molecular_coverage=None,
                within_shared_balance=None,
                global_balance=None,
                within_balance=None,
                within_ratio=None,
                eta_squared=None,
                null_within_ratio=None,
                epsilon_squared=None,
            ),
            nearest_neighbor_diagnostics=NearestNeighborDiagnostics(
                maximum_neighbor_indices=((1,), (0,)),
                maximum_similarities=(0.5, 0.5),
                tied_neighbor_counts=(1, 1),
                tie_fraction=0.0,
                tie_sensitive_fraction=0.0,
                fingerprint_identical_fraction=0.0,
                fingerprint_identical_label_conflict_fraction=0.0,
                active_concordance_min=0.0,
                active_concordance_max=0.0,
                inactive_concordance_min=0.0,
                inactive_concordance_max=0.0,
                modelability_index_min=0.0,
                modelability_index_max=0.0,
            ),
            murcko_nn_interface=MurckoNNInterfaceResult(
                cc_count=0,
                ca_count=0,
                ac_count=0,
                aa_count=2,
                murcko_nn_coverage=0.0,
                same_scaffold_count=0,
                different_scaffold_count=0,
                same_scaffold_nn_fraction=None,
                same_scaffold_concordance=None,
                different_scaffold_concordance=None,
                reconstructed_active_concordance=0.0,
                reconstructed_inactive_concordance=0.0,
                reconstructed_modelability_index=0.0,
                transition_counts={
                    "CC": 0,
                    "CA": 0,
                    "AC": 0,
                    "AA": 2,
                },
            ),
        ),
    )


def test_modelability_job_completes_with_json_result_and_no_result_table(
    tmp_path,
    monkeypatch,
):
    _create_database(tmp_path, monkeypatch)
    prepared = PreparedModelabilityInput(
        smiles=("CCC", "CCO"),
        outcomes=("Inactive", "Active"),
        analysis_identity="analysis-v1",
    )
    preparation_calls = []
    calculation_calls = []

    def prepare(
        connection,
        table_name,
        *,
        database_id=None,
        fingerprint_type="morgan",
    ):
        preparation_calls.append(
            (connection, table_name, database_id, fingerprint_type)
        )
        return prepared

    def calculate(connection, prepared_input, *, source_table):
        calculation_calls.append((connection, prepared_input, source_table))
        return _result()

    monkeypatch.setattr(
        modelability_jobs,
        "prepare_table_modelability_input",
        prepare,
    )
    monkeypatch.setattr(
        modelability_jobs,
        "calculate_persisted_prepared_modelability_index",
        calculate,
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
    restored = create_modelability_job("test_db", MODELABILITY_TABLE)

    assert created.status == JobStatus.PENDING
    assert created.stage == "queued"
    assert created.cancellable is False
    assert completed.status == JobStatus.COMPLETED
    assert queried == completed
    assert restored == completed
    assert len(preparation_calls) == 3
    assert all(
        (table_name, database_id, fingerprint_type)
        == (MODELABILITY_TABLE, "test_db", "morgan")
        for (
            _connection,
            table_name,
            database_id,
            fingerprint_type,
        ) in preparation_calls
    )

    assert len(calculation_calls) == 1
    calculation_connection, calculation_input, calculation_table = (
        calculation_calls[0]
    )
    assert isinstance(calculation_connection, sqlite3.Connection)
    assert calculation_input is prepared
    assert calculation_table == MODELABILITY_TABLE

    assert completed.result["modelability_index"] == 0.0
    assert len(completed.result["diagnostics"]) == 2
    assert completed.result["provenance"]["similarity_metric"] == "tanimoto"
    assert (
        completed.result["structural_context"]["murcko_population"]["acyclic_count"]
        == 2
    )
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
    assert record.metadata["fingerprint_type"] == "morgan"
    assert record.metadata["cancellation_supported"] is False
    assert record.metadata["analysis_identity"] == "analysis-v1"
    assert record.metadata["analysis_contract"] == POPULATION_POLICY
    assert record.metadata["result"] == completed.result
    assert "fingerprints" not in record.metadata["result"]


def test_maccs_job_persists_and_executes_canonical_fingerprint_type(
    tmp_path,
    monkeypatch,
):
    _create_database(tmp_path, monkeypatch)

    created = create_modelability_job(
        "test_db",
        MODELABILITY_TABLE,
        fingerprint_type="maccs",
    )
    connection = get_connection("test_db")
    try:
        queued_record = JobStore(connection).get_job(created.job_id)
    finally:
        connection.close()

    completed = execute_modelability_job("test_db", created.job_id)

    assert queued_record.metadata["fingerprint_type"] == "maccs"
    assert completed.status == JobStatus.COMPLETED
    assert completed.result["provenance"]["fingerprint_type"] == "maccs"
    assert completed.result["provenance"]["fingerprint_profile"]["fp_size"] == 167

    connection = get_connection("test_db")
    try:
        artifact_width = connection.execute(
            f"SELECT fp_size FROM {FINGERPRINT_ARTIFACTS_TABLE}"
        ).fetchone()[0]
        completed_record = JobStore(connection).get_job(created.job_id)
    finally:
        connection.close()

    assert artifact_width == 167
    assert completed_record.metadata["fingerprint_type"] == "maccs"


def test_omitted_fingerprint_type_remains_morgan_through_restoration(
    tmp_path,
    monkeypatch,
):
    _create_database(tmp_path, monkeypatch)

    created = create_modelability_job("test_db", MODELABILITY_TABLE)
    completed = execute_modelability_job("test_db", created.job_id)
    restored = create_modelability_job("test_db", MODELABILITY_TABLE)

    assert completed.status == JobStatus.COMPLETED
    assert completed.result["provenance"]["fingerprint_type"] == "morgan"
    assert restored == completed
    connection = get_connection("test_db")
    try:
        record = JobStore(connection).get_job(created.job_id)
    finally:
        connection.close()
    assert record.metadata["fingerprint_type"] == "morgan"


def test_old_job_metadata_without_fingerprint_type_executes_as_morgan(
    tmp_path,
    monkeypatch,
):
    _create_database(tmp_path, monkeypatch)
    created = create_modelability_job("test_db", MODELABILITY_TABLE)

    connection = get_connection("test_db")
    try:
        store = JobStore(connection)
        record = store.get_job(created.job_id)
        legacy_metadata = dict(record.metadata)
        legacy_metadata.pop("fingerprint_type")
        store.update_progress(
            created.job_id,
            record.current_stage,
            record.progress,
            metadata=legacy_metadata,
        )
    finally:
        connection.close()

    completed = execute_modelability_job("test_db", created.job_id)

    assert completed.status == JobStatus.COMPLETED
    assert completed.result["provenance"]["fingerprint_type"] == "morgan"
    connection = get_connection("test_db")
    try:
        completed_record = JobStore(connection).get_job(created.job_id)
    finally:
        connection.close()
    assert completed_record.metadata["fingerprint_type"] == "morgan"


def test_same_table_with_morgan_and_maccs_creates_distinct_jobs(
    tmp_path,
    monkeypatch,
):
    _create_database(tmp_path, monkeypatch)

    morgan = create_modelability_job(
        "test_db",
        MODELABILITY_TABLE,
        fingerprint_type="morgan",
    )
    maccs = create_modelability_job(
        "test_db",
        MODELABILITY_TABLE,
        fingerprint_type="maccs",
    )

    assert morgan.job_id != maccs.job_id
    connection = get_connection("test_db")
    try:
        records = [
            JobStore(connection).get_job(job_id)
            for job_id in (morgan.job_id, maccs.job_id)
        ]
    finally:
        connection.close()
    assert {record.metadata["fingerprint_type"] for record in records} == {
        "morgan",
        "maccs",
    }
    assert len(
        {record.metadata["analysis_identity"] for record in records}
    ) == 2


def test_restoring_completed_job_backfills_missing_fingerprint_artifact(
    tmp_path,
    monkeypatch,
):
    _create_database(tmp_path, monkeypatch)
    monkeypatch.setattr(
        modelability_jobs,
        "calculate_persisted_prepared_modelability_index",
        lambda *_args, **_kwargs: _result(),
    )

    created = create_modelability_job("test_db", MODELABILITY_TABLE)
    completed = execute_modelability_job("test_db", created.job_id)

    connection = get_connection("test_db")
    try:
        artifact_table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (FINGERPRINT_ARTIFACTS_TABLE,),
        ).fetchone()
        completed_record = JobStore(connection).get_job(created.job_id)
    finally:
        connection.close()

    assert artifact_table is None
    persisted_result = completed_record.metadata["result"]
    persisted_provenance = persisted_result["provenance"]

    restored = create_modelability_job("test_db", MODELABILITY_TABLE)

    assert restored == completed
    assert restored.result == persisted_result
    assert restored.result["provenance"] == persisted_provenance

    connection = get_connection("test_db")
    try:
        artifact_rows = connection.execute(
            f"SELECT source_table FROM {FINGERPRINT_ARTIFACTS_TABLE}"
        ).fetchall()
        restored_record = JobStore(connection).get_job(created.job_id)
    finally:
        connection.close()

    assert artifact_rows == [(MODELABILITY_TABLE,)]
    assert restored_record.metadata["result"] == persisted_result
    assert restored_record.metadata["result"]["provenance"] == persisted_provenance


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
        "calculate_persisted_prepared_modelability_index",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("calculation failed")
        ),
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


def test_completed_job_without_murcko_context_contract_is_not_reused(
    tmp_path,
    monkeypatch,
):
    _create_database(tmp_path, monkeypatch)

    monkeypatch.setattr(
        modelability_jobs,
        "calculate_persisted_prepared_modelability_index",
        lambda *_args, **_kwargs: _result(),
    )

    created = create_modelability_job(
        "test_db",
        MODELABILITY_TABLE,
    )
    completed = execute_modelability_job(
        "test_db",
        created.job_id,
    )

    connection = get_connection("test_db")
    try:
        store = JobStore(connection)
        record = store.get_job(completed.job_id)

        legacy_metadata = dict(record.metadata)
        legacy_metadata.pop(
            "murcko_context_contract_version",
            None,
        )

        connection.execute(
            """
            UPDATE _chemvault_jobs
            SET metadata_json = ?
            WHERE job_id = ?
            """,
            (
                json.dumps(legacy_metadata),
                completed.job_id,
            ),
        )
        connection.commit()
    finally:
        connection.close()

    replacement = create_modelability_job(
        "test_db",
        MODELABILITY_TABLE,
    )

    assert replacement.job_id != completed.job_id
    assert replacement.status == JobStatus.PENDING
