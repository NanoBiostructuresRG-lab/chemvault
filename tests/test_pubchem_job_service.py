# SPDX-License-Identifier: LGPL-3.0-or-later
import sqlite3
from types import SimpleNamespace

from services import pubchem_job_service
from services.job_models import JobStatus
from services.job_store import JOBS_TABLE, STALE_JOB_ERROR_MESSAGE, JobStore


def test_load_pubchem_job_marks_stale_job_failed(tmp_path):
    db_path = tmp_path / "stale.db"
    connection = sqlite3.connect(db_path)
    store = JobStore(connection)
    store.create_job(job_id="job-1")
    store.start_job("job-1")
    connection.execute(
        f"UPDATE {JOBS_TABLE} SET last_heartbeat_at = ? WHERE job_id = ?",
        ("2000-01-01T00:00:00+00:00", "job-1"),
    )
    connection.commit()
    connection.close()

    failed = pubchem_job_service.load_pubchem_job(db_path, "job-1")

    assert failed.status == JobStatus.FAILED.value
    assert failed.error_message == STALE_JOB_ERROR_MESSAGE


def test_cancel_pubchem_job_marks_active_job_cancelled(tmp_path):
    db_path = tmp_path / "cancel.db"
    connection = sqlite3.connect(db_path)
    store = JobStore(connection)
    store.create_job(job_id="job-1")
    store.start_job("job-1")
    connection.close()

    cancelled = pubchem_job_service.cancel_pubchem_job(db_path, "job-1")

    assert cancelled.status == JobStatus.CANCELLED.value
    assert cancelled.message == "Cancelled by user"


def test_register_completed_pubchem_job_uses_existing_build_registration(
    tmp_path,
    monkeypatch,
):
    db_path = tmp_path / "completed.db"
    sqlite3.connect(db_path).close()
    calls = []

    def fake_register(connection, proteins):
        connection.execute("SELECT 1")
        calls.append(proteins)

    monkeypatch.setattr(
        pubchem_job_service,
        "register_protein_search_build",
        fake_register,
    )
    job = SimpleNamespace(metadata={"proteins": ["P34971"]})

    pubchem_job_service.register_completed_pubchem_job(db_path, job)

    assert calls == [["P34971"]]
