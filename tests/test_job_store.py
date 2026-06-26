# SPDX-License-Identifier: LGPL-3.0-or-later
import sqlite3

from services.job_models import JobStatus, JobType
from services.job_store import JOBS_TABLE, JobStore, create_job, ensure_jobs_table


def test_ensure_jobs_table_creates_internal_table():
    connection = sqlite3.connect(":memory:")

    ensure_jobs_table(connection)

    cursor = connection.cursor()
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (JOBS_TABLE,),
    )

    assert cursor.fetchone()[0] == JOBS_TABLE


def test_create_job_persists_pending_record():
    connection = sqlite3.connect(":memory:")
    store = JobStore(connection)

    job = store.create_job(
        job_type=JobType.PUBCHEM_PROTEIN_SEARCH,
        database_id="RAMIRO",
        metadata={"protein": "P32245"},
        job_id="job-1",
    )

    assert job.job_id == "job-1"
    assert job.job_type == "pubchem_protein_search"
    assert job.status == "pending"
    assert job.database_id == "RAMIRO"
    assert job.progress == 0.0
    assert job.metadata == {"protein": "P32245"}
    assert job.created_at


def test_start_job_updates_status_and_started_timestamp():
    connection = sqlite3.connect(":memory:")
    store = JobStore(connection)
    job = store.create_job(job_id="job-1")

    started = store.start_job(job.job_id)

    assert started.status == JobStatus.RUNNING.value
    assert started.started_at
    assert started.finished_at == ""
    assert started.error_message == ""


def test_update_progress_updates_stage_message_and_metadata():
    connection = sqlite3.connect(":memory:")
    store = JobStore(connection)
    job = store.create_job(job_id="job-1")

    updated = store.update_progress(
        job.job_id,
        stage="compound_names",
        progress=0.6,
        message="Fetching names",
        metadata={"processed": 300},
    )

    assert updated.current_stage == "compound_names"
    assert updated.progress == 0.6
    assert updated.message == "Fetching names"
    assert updated.metadata == {"processed": 300}


def test_complete_job_marks_finished_and_preserves_metadata_update():
    connection = sqlite3.connect(":memory:")
    store = JobStore(connection)
    job = store.create_job(job_id="job-1")
    store.start_job(job.job_id)

    completed = store.complete_job(job.job_id, metadata={"rows": 10})

    assert completed.status == JobStatus.COMPLETED.value
    assert completed.progress == 1.0
    assert completed.finished_at
    assert completed.error_message == ""
    assert completed.metadata == {"rows": 10}


def test_fail_job_marks_finished_with_error():
    connection = sqlite3.connect(":memory:")
    store = JobStore(connection)
    job = store.create_job(job_id="job-1")
    store.start_job(job.job_id)

    failed = store.fail_job(
        job.job_id,
        "PubChem timeout",
        metadata={"aid": "123"},
    )

    assert failed.status == JobStatus.FAILED.value
    assert failed.finished_at
    assert failed.error_message == "PubChem timeout"
    assert failed.metadata == {"aid": "123"}


def test_get_job_returns_none_for_missing_job():
    connection = sqlite3.connect(":memory:")
    store = JobStore(connection)

    assert store.get_job("missing") is None


def test_list_jobs_returns_recent_jobs_with_limit():
    connection = sqlite3.connect(":memory:")
    store = JobStore(connection)
    store.create_job(job_id="job-1")
    store.create_job(job_id="job-2")
    store.create_job(job_id="job-3")

    jobs = store.list_jobs(limit=2)

    assert len(jobs) == 2
    assert {job.job_id for job in jobs}.issubset({"job-1", "job-2", "job-3"})


def test_module_create_job_wrapper_uses_store():
    connection = sqlite3.connect(":memory:")

    job = create_job(connection, job_id="job-1", database_id="test_db")

    assert job.job_id == "job-1"
    assert job.database_id == "test_db"
