# SPDX-License-Identifier: LGPL-3.0-or-later
import pytest

from application.job_contracts import (
    JobStatusContract,
    job_status_from_record,
)
from services.job_models import JobRecord, JobStatus


def test_job_status_contract_projects_generic_persisted_fields():
    record = JobRecord(
        job_id="job-1",
        job_type="pubchem_protein_search",
        status=JobStatus.RUNNING.value,
        database_id="test_db",
        current_stage="compound_names",
        progress=0.6,
        message="Fetching names",
        error_message="",
        created_at="2026-07-03T10:00:00+00:00",
        started_at="2026-07-03T10:00:01+00:00",
        metadata={"proteins": ["P32245"]},
        worker_pid=12345,
    )

    status = job_status_from_record(record)

    assert status == JobStatusContract(
        job_id="job-1",
        job_type="pubchem_protein_search",
        status=JobStatus.RUNNING,
        database_id="test_db",
        stage="compound_names",
        progress=0.6,
        message="Fetching names",
        created_at="2026-07-03T10:00:00+00:00",
        started_at="2026-07-03T10:00:01+00:00",
        finished_at=None,
        error=None,
        cancellable=True,
        updated_at="2026-07-03T10:00:01+00:00",
        result=None,
    )
    assert not hasattr(status, "metadata")
    assert not hasattr(status, "worker_pid")


@pytest.mark.parametrize(
    ("persisted_status", "cancellable"),
    [
        (JobStatus.PENDING, True),
        (JobStatus.RUNNING, True),
        (JobStatus.COMPLETED, False),
        (JobStatus.FAILED, False),
        (JobStatus.CANCELLED, False),
    ],
)
def test_job_status_contract_derives_cancellable_from_lifecycle(
    persisted_status,
    cancellable,
):
    record = JobRecord(
        job_id="job-1",
        job_type="pubchem_protein_search",
        status=persisted_status.value,
    )

    assert job_status_from_record(record).cancellable is cancellable


def test_job_status_contract_maps_terminal_error_and_timestamps():
    record = JobRecord(
        job_id="job-1",
        job_type="pubchem_protein_search",
        status=JobStatus.FAILED.value,
        message="Stopped",
        error_message="Request timed out",
        created_at="2026-07-03T10:00:00+00:00",
        started_at="2026-07-03T10:00:01+00:00",
        finished_at="2026-07-03T10:01:00+00:00",
    )

    status = job_status_from_record(record)

    assert status.message == "Stopped"
    assert status.error == "Request timed out"
    assert status.finished_at == "2026-07-03T10:01:00+00:00"
    assert status.cancellable is False


def test_job_status_contract_rejects_unknown_persisted_status():
    record = JobRecord(
        job_id="job-1",
        job_type="future_job",
        status="unknown",
    )

    with pytest.raises(ValueError, match="unknown"):
        job_status_from_record(record)
