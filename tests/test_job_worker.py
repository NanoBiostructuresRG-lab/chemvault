# SPDX-License-Identifier: LGPL-3.0-or-later
import sqlite3

import pytest

from services import job_worker
from services.job_models import JobStatus
from services.job_store import JobStore


def _create_database_with_job(db_path, *, job_id="job-1", metadata=None):
    connection = sqlite3.connect(db_path)
    connection.execute(
        "CREATE TABLE main (primary_id INTEGER PRIMARY KEY AUTOINCREMENT)"
    )
    JobStore(connection).create_job(
        job_id=job_id,
        metadata=metadata,
    )
    connection.close()


def _load_job(db_path, job_id="job-1"):
    connection = sqlite3.connect(db_path)
    try:
        return JobStore(connection).get_job(job_id)
    finally:
        connection.close()


def test_worker_runs_existing_job_with_proteins_from_metadata(tmp_path, monkeypatch):
    db_path = tmp_path / "worker-success.db"
    _create_database_with_job(
        db_path,
        metadata={"proteins": ["P32245", "P12345"]},
    )
    captured = {}

    def fake_run(connection, proteins, *, job_store, job_id):
        captured["proteins"] = proteins
        captured["job_id"] = job_id
        job_store.start_job(job_id)
        return job_store.complete_job(job_id)

    monkeypatch.setattr(job_worker, "run_pubchem_protein_search_job", fake_run)

    result = job_worker.run_pubchem_protein_search_worker(db_path, "job-1")

    assert captured == {
        "proteins": ["P32245", "P12345"],
        "job_id": "job-1",
    }
    assert result.status == JobStatus.COMPLETED.value
    persisted = _load_job(db_path)
    assert persisted.status == JobStatus.COMPLETED.value
    assert persisted.metadata == {"proteins": ["P32245", "P12345"]}


def test_worker_marks_job_failed_and_propagates_execution_error(tmp_path, monkeypatch):
    db_path = tmp_path / "worker-failure.db"
    _create_database_with_job(db_path, metadata={"proteins": ["P32245"]})

    def fake_run(*args, **kwargs):
        raise RuntimeError("PubChem execution failed")

    monkeypatch.setattr(job_worker, "run_pubchem_protein_search_job", fake_run)

    with pytest.raises(RuntimeError, match="PubChem execution failed"):
        job_worker.run_pubchem_protein_search_worker(db_path, "job-1")

    failed = _load_job(db_path)
    assert failed.status == JobStatus.FAILED.value
    assert failed.error_message == "PubChem execution failed"
    assert failed.finished_at


def test_worker_rejects_missing_job(tmp_path, monkeypatch):
    db_path = tmp_path / "worker-missing.db"
    _create_database_with_job(
        db_path,
        job_id="different-job",
        metadata={"proteins": ["P32245"]},
    )
    called = False

    def fake_run(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(job_worker, "run_pubchem_protein_search_job", fake_run)

    with pytest.raises(job_worker.JobNotFoundError, match="Job not found: missing"):
        job_worker.run_pubchem_protein_search_worker(db_path, "missing")

    assert called is False


@pytest.mark.parametrize(
    "metadata",
    [
        {},
        {"proteins": []},
        {"proteins": "P32245"},
        {"proteins": [""]},
    ],
)
def test_worker_rejects_invalid_protein_metadata(tmp_path, monkeypatch, metadata):
    db_path = tmp_path / "worker-invalid.db"
    _create_database_with_job(db_path, metadata=metadata)
    called = False

    def fake_run(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(job_worker, "run_pubchem_protein_search_job", fake_run)

    with pytest.raises(job_worker.InvalidJobError, match="non-empty 'proteins' list"):
        job_worker.run_pubchem_protein_search_worker(db_path, "job-1")

    assert called is False
    failed = _load_job(db_path)
    assert failed.status == JobStatus.FAILED.value
    assert "non-empty 'proteins' list" in failed.error_message


def test_worker_cli_returns_controlled_error_for_missing_job(tmp_path, capsys):
    db_path = tmp_path / "worker-cli.db"
    _create_database_with_job(
        db_path,
        job_id="different-job",
        metadata={"proteins": ["P32245"]},
    )

    exit_code = job_worker.main(
        [
            "run-pubchem-protein-search",
            "--db-path",
            str(db_path),
            "--job-id",
            "missing",
        ]
    )

    assert exit_code == 1
    assert "Worker failed: Job not found: missing" in capsys.readouterr().err
