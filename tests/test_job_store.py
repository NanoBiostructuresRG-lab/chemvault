# SPDX-License-Identifier: LGPL-3.0-or-later
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from services.job_models import (
    JobCancellationNotSupportedError,
    JobStatus,
    JobType,
)
from services.job_store import (
    JOBS_TABLE,
    STALE_JOB_ERROR_MESSAGE,
    JobStore,
    create_job,
    ensure_jobs_table,
)


def test_ensure_jobs_table_creates_internal_table():
    connection = sqlite3.connect(":memory:")

    ensure_jobs_table(connection)

    cursor = connection.cursor()
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (JOBS_TABLE,),
    )

    assert cursor.fetchone()[0] == JOBS_TABLE


def test_ensure_jobs_table_creates_and_migrates_last_heartbeat_column():
    connection = sqlite3.connect(":memory:")
    connection.execute(f"""
        CREATE TABLE {JOBS_TABLE} (
            job_id TEXT PRIMARY KEY,
            job_type TEXT NOT NULL,
            status TEXT NOT NULL,
            database_id TEXT,
            current_stage TEXT,
            progress REAL NOT NULL DEFAULT 0.0,
            message TEXT,
            error_message TEXT,
            created_at TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT,
            metadata_json TEXT
        )
    """)
    created_at = "2026-01-01T00:00:00+00:00"
    connection.execute(
        f"""
        INSERT INTO {JOBS_TABLE} (
            job_id, job_type, status, progress, created_at, metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("legacy-job", "pubchem_protein_search", "pending", 0.0, created_at, "{}"),
    )

    ensure_jobs_table(connection)

    columns = {
        row[1] for row in connection.execute(f"PRAGMA table_info({JOBS_TABLE})")
    }
    assert "last_heartbeat_at" in columns
    assert "cancel_requested_at" in columns
    assert "worker_pid" in columns
    migrated = JobStore(connection).get_job("legacy-job")
    assert migrated.last_heartbeat_at == created_at
    assert migrated.cancel_requested_at == ""
    assert migrated.worker_pid is None


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
    assert job.last_heartbeat_at == job.created_at


def test_scientific_job_scope_returns_active_owner_and_allows_after_terminal():
    connection = sqlite3.connect(":memory:")
    store = JobStore(connection)
    first, created = store.create_job_unless_active(
        job_type=JobType.HARMONSMILE,
        database_id="test_db",
        table_name="main",
        metadata={"table_name": "main", "cid_column": "CID"},
    )
    duplicate, duplicate_created = store.create_job_unless_active(
        job_type=JobType.HARMONSMILE,
        database_id="test_db",
        table_name="main",
        metadata={"table_name": "main", "cid_column": "Other CID"},
    )

    assert created is True
    assert duplicate_created is False
    assert duplicate.job_id == first.job_id
    assert store.find_active_scientific_job(
        "test_db", JobType.HARMONSMILE, "main"
    ).job_id == first.job_id

    store.complete_job(first.job_id)
    replacement, replacement_created = store.create_job_unless_active(
        job_type=JobType.HARMONSMILE,
        database_id="test_db",
        table_name="main",
        metadata={"table_name": "main", "cid_column": "CID"},
    )

    assert replacement_created is True
    assert replacement.job_id != first.job_id


def test_start_job_updates_status_and_started_timestamp():
    connection = sqlite3.connect(":memory:")
    store = JobStore(connection)
    job = store.create_job(job_id="job-1")

    started = store.start_job(job.job_id)

    assert started.status == JobStatus.RUNNING.value
    assert started.started_at
    assert started.finished_at == ""
    assert started.error_message == ""
    assert started.last_heartbeat_at


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


def test_set_worker_pid_persists_process_identifier():
    connection = sqlite3.connect(":memory:")
    store = JobStore(connection)
    job = store.create_job(job_id="job-1")

    updated = store.set_worker_pid(job.job_id, 12345)

    assert updated.worker_pid == 12345
    assert store.get_job(job.job_id).worker_pid == 12345


def test_pending_scientific_job_has_only_one_executor_claim():
    connection = sqlite3.connect(":memory:")
    store = JobStore(connection)
    job = store.create_job(job_type=JobType.HARMONSMILE, job_id="job-1")

    claimed = store.claim_pending_scientific_job(job.job_id, 111)
    duplicate = store.claim_pending_scientific_job(job.job_id, 222)

    assert claimed.worker_pid == 111
    assert duplicate is None
    assert store.get_job(job.job_id).worker_pid == 111


def test_orphan_requeue_requires_matching_worker_and_preserves_job_id():
    connection = sqlite3.connect(":memory:")
    store = JobStore(connection)
    job = store.create_job(job_type=JobType.HARMONSMILE, job_id="job-1")
    store.claim_pending_scientific_job(job.job_id, 111)
    store.start_job(job.job_id)

    assert store.requeue_orphaned_scientific_job(
        job.job_id, JobType.HARMONSMILE, 222
    ) is None
    recovered = store.requeue_orphaned_scientific_job(
        job.job_id, JobType.HARMONSMILE, 111
    )

    assert recovered.job_id == job.job_id
    assert recovered.status == JobStatus.PENDING.value
    assert recovered.current_stage == "recovery_queued"
    assert recovered.worker_pid is None


def test_cancel_job_marks_active_job_cancelled():
    connection = sqlite3.connect(":memory:")
    store = JobStore(connection)
    job = store.create_job(job_id="job-1")
    store.start_job(job.job_id)

    cancelled = store.cancel_job(job.job_id, "User cancelled")

    assert cancelled.status == JobStatus.CANCELLED.value
    assert cancelled.finished_at
    assert cancelled.cancel_requested_at
    assert cancelled.message == "User cancelled"
    assert store.heartbeat_job(job.job_id) is None
    assert store.update_progress(job.job_id, "compound_names", 0.8) is None
    assert store.complete_job(job.job_id) is None


def test_cancel_job_ignores_terminal_jobs():
    connection = sqlite3.connect(":memory:")
    store = JobStore(connection)
    job = store.create_job(job_id="job-1")
    store.start_job(job.job_id)
    store.complete_job(job.job_id)

    assert store.cancel_job(job.job_id) is None
    assert store.get_job(job.job_id).status == JobStatus.COMPLETED.value


def test_cancel_job_rejects_non_interruptible_active_job():
    connection = sqlite3.connect(":memory:")
    store = JobStore(connection)
    job = store.create_job(
        job_type=JobType.MODELABILITY_INDEX,
        metadata={"cancellation_supported": False},
        job_id="job-1",
    )
    store.start_job(job.job_id)

    with pytest.raises(
        JobCancellationNotSupportedError,
        match="does not support cancellation",
    ):
        store.cancel_job(job.job_id)

    unchanged = store.get_job(job.job_id)
    assert unchanged.status == JobStatus.RUNNING.value
    assert unchanged.cancel_requested_at == ""


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


def test_heartbeat_and_progress_only_update_active_jobs():
    connection = sqlite3.connect(":memory:")
    store = JobStore(connection)
    job = store.create_job(job_id="job-1")

    connection.execute(
        f"UPDATE {JOBS_TABLE} SET last_heartbeat_at = ? WHERE job_id = ?",
        ("2000-01-01T00:00:00+00:00", job.job_id),
    )
    connection.commit()
    heartbeat = store.heartbeat_job(job.job_id)
    updated = store.update_progress(job.job_id, "aid_search", 0.1)
    assert heartbeat is not None
    assert heartbeat.last_heartbeat_at != "2000-01-01T00:00:00+00:00"
    assert updated.progress == 0.1

    store.fail_job(job.job_id, "external failure")
    failed_before = store.get_job(job.job_id)

    assert store.heartbeat_job(job.job_id) is None
    assert store.update_progress(job.job_id, "compound_names", 0.8) is None
    assert store.complete_job(job.job_id) is None
    failed_after = store.get_job(job.job_id)
    assert failed_after.status == JobStatus.FAILED.value
    assert failed_after.progress == failed_before.progress
    assert failed_after.current_stage == failed_before.current_stage
    assert failed_after.last_heartbeat_at == failed_before.last_heartbeat_at
    assert store.start_job(job.job_id) is None


def _set_heartbeat(connection, job_id, heartbeat):
    connection.execute(
        f"UPDATE {JOBS_TABLE} SET last_heartbeat_at = ? WHERE job_id = ?",
        (heartbeat.isoformat(), job_id),
    )
    connection.commit()


def test_recent_running_heartbeat_is_not_marked_stale():
    connection = sqlite3.connect(":memory:")
    store = JobStore(connection)
    store.create_job(job_id="job-1")
    store.start_job("job-1")
    now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    _set_heartbeat(connection, "job-1", now - timedelta(seconds=30))

    marked = store.fail_stale_job("job-1", timeout_seconds=60, now=now)

    assert marked is False
    assert store.get_job("job-1").status == JobStatus.RUNNING.value


@pytest.mark.parametrize("status", ["pending", "running"])
def test_old_active_heartbeat_is_atomically_marked_failed(status):
    connection = sqlite3.connect(":memory:")
    store = JobStore(connection)
    store.create_job(job_id="job-1")
    if status == "running":
        store.start_job("job-1")
    now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    _set_heartbeat(connection, "job-1", now - timedelta(seconds=61))

    assert store.fail_stale_job("job-1", timeout_seconds=60, now=now) is True
    assert store.fail_stale_job("job-1", timeout_seconds=60, now=now) is False

    failed = store.get_job("job-1")
    assert failed.status == JobStatus.FAILED.value
    assert failed.error_message == STALE_JOB_ERROR_MESSAGE


def test_stale_job_is_not_returned_as_active():
    connection = sqlite3.connect(":memory:")
    store = JobStore(connection)
    store.create_job(job_id="stale")
    store.create_job(job_id="recent")
    now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    _set_heartbeat(connection, "stale", now - timedelta(seconds=61))
    _set_heartbeat(connection, "recent", now - timedelta(seconds=10))

    assert store.get_active_job("stale", timeout_seconds=60, now=now) is None
    assert store.get_active_job("recent", timeout_seconds=60, now=now).job_id == "recent"
