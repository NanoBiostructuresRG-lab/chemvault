# SPDX-License-Identifier: LGPL-3.0-or-later
import sqlite3

import pytest

from services import pubchem_job_service
from services.job_models import JobRecord, JobStatus
from services.job_store import JOBS_TABLE, STALE_JOB_ERROR_MESSAGE, JobStore


@pytest.mark.parametrize(
    (
        "status",
        "error_message",
        "expected_flags",
    ),
    [
        (
            JobStatus.RUNNING.value,
            "",
            (True, False, False, False, False, False, True),
        ),
        (
            JobStatus.COMPLETED.value,
            "",
            (False, True, True, False, False, False, False),
        ),
        (
            JobStatus.FAILED.value,
            STALE_JOB_ERROR_MESSAGE,
            (False, True, False, True, False, True, False),
        ),
        (
            JobStatus.CANCELLED.value,
            "",
            (False, True, False, False, True, False, False),
        ),
    ],
)
def test_job_record_converter_exposes_safe_fields_and_flags(
    status,
    error_message,
    expected_flags,
):
    record = JobRecord(
        job_id="job-1",
        job_type="pubchem_protein_search",
        status=status,
        current_stage="cid_collection",
        progress=0.5,
        message="Collecting CIDs",
        error_message=error_message,
        metadata={"proteins": ["P34971"]},
    )

    view = pubchem_job_service._to_pubchem_job_view(record)

    assert isinstance(view, pubchem_job_service.PubChemJobView)
    assert (
        view.job_id,
        view.status,
        view.current_stage,
        view.progress,
        view.message,
        view.error_message,
        view.proteins,
    ) == (
        "job-1",
        status,
        "cid_collection",
        0.5,
        "Collecting CIDs",
        error_message,
        ("P34971",),
    )
    assert (
        view.is_active,
        view.is_terminal,
        view.is_completed,
        view.is_failed,
        view.is_cancelled,
        view.is_stale_failure,
        view.can_cancel,
    ) == expected_flags


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

    assert isinstance(failed, pubchem_job_service.PubChemJobView)
    assert failed.status == JobStatus.FAILED.value
    assert failed.error_message == STALE_JOB_ERROR_MESSAGE
    assert failed.is_failed
    assert failed.is_stale_failure


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
    assert cancelled.is_cancelled
    assert not cancelled.can_cancel


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
    job = pubchem_job_service.PubChemJobView(
        job_id="job-1",
        status=JobStatus.COMPLETED.value,
        current_stage="complete",
        progress=1.0,
        message="",
        error_message="",
        proteins=("P34971",),
        is_active=False,
        is_terminal=True,
        is_completed=True,
        is_failed=False,
        is_cancelled=False,
        is_stale_failure=False,
        can_cancel=False,
    )

    pubchem_job_service.register_completed_pubchem_job(db_path, job)

    assert calls == [("P34971",)]


@pytest.mark.parametrize("status", [JobStatus.FAILED.value, JobStatus.CANCELLED.value])
def test_register_completed_pubchem_job_refuses_non_completed_jobs(
    tmp_path,
    monkeypatch,
    status,
):
    db_path = tmp_path / "not-completed.db"
    sqlite3.connect(db_path).close()
    monkeypatch.setattr(
        pubchem_job_service,
        "register_protein_search_build",
        lambda *args: pytest.fail("non-completed job must not be registered"),
    )
    job = pubchem_job_service.PubChemJobView(
        job_id="job-1",
        status=status,
        current_stage="",
        progress=0.5,
        message="",
        error_message="",
        proteins=("P34971",),
        is_active=False,
        is_terminal=True,
        is_completed=False,
        is_failed=status == JobStatus.FAILED.value,
        is_cancelled=status == JobStatus.CANCELLED.value,
        is_stale_failure=False,
        can_cancel=False,
    )

    with pytest.raises(ValueError, match="Only completed PubChem jobs"):
        pubchem_job_service.register_completed_pubchem_job(db_path, job)


def test_start_pubchem_search_launches_job_with_explicit_inputs(tmp_path, monkeypatch):
    calls = {}

    class FakeConnection:
        closed = False

        def close(self):
            self.closed = True

    connection = FakeConnection()
    expected_job = JobRecord(
        job_id="job-1",
        job_type="pubchem_protein_search",
        status=JobStatus.PENDING.value,
        metadata={"proteins": ["P34971"]},
    )

    def fake_get_connection(database_id):
        calls["database_id"] = database_id
        return connection

    monkeypatch.setattr(
        pubchem_job_service,
        "get_connection",
        fake_get_connection,
    )

    def fake_create(connection_arg, db_path, proteins, *, database_id):
        calls["launch"] = (connection_arg, db_path, proteins, database_id)
        return expected_job

    monkeypatch.setattr(
        pubchem_job_service,
        "create_and_launch_pubchem_job",
        fake_create,
    )
    monkeypatch.setattr(
        pubchem_job_service,
        "resolve_database_path",
        lambda db_path: db_path.resolve(),
    )

    result = pubchem_job_service.start_pubchem_search(
        "protein_db",
        ("P34971",),
        db_dir=tmp_path,
    )

    expected_path = tmp_path / "protein_db.db"
    job_view, resolved_path = result
    assert isinstance(job_view, pubchem_job_service.PubChemJobView)
    assert job_view.job_id == expected_job.job_id
    assert job_view.proteins == ("P34971",)
    assert job_view.is_active
    assert resolved_path == expected_path.resolve()
    assert calls["database_id"] == "protein_db"
    assert calls["launch"] == (
        connection,
        expected_path,
        ["P34971"],
        "protein_db",
    )
    assert connection.closed is True
