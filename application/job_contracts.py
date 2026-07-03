# SPDX-License-Identifier: LGPL-3.0-or-later
"""Typed read-only contract for a future backend job-status boundary."""
from dataclasses import dataclass

from services.job_models import JobRecord, JobStatus


CANCELLABLE_STATUSES = frozenset({
    JobStatus.PENDING,
    JobStatus.RUNNING,
})


@dataclass(frozen=True)
class JobStatusContract:
    """Public status fields independent of execution-specific metadata."""

    job_id: str
    job_type: str
    status: JobStatus
    database_id: str
    stage: str
    progress: float
    message: str | None
    created_at: str
    started_at: str | None
    finished_at: str | None
    error: str | None
    cancellable: bool


def job_status_from_record(record: JobRecord) -> JobStatusContract:
    """Project an internal persisted record onto the future public contract."""
    status = JobStatus(record.status)
    return JobStatusContract(
        job_id=record.job_id,
        job_type=record.job_type,
        status=status,
        database_id=record.database_id,
        stage=record.current_stage,
        progress=record.progress,
        message=record.message or None,
        created_at=record.created_at,
        started_at=record.started_at or None,
        finished_at=record.finished_at or None,
        error=record.error_message or None,
        cancellable=status in CANCELLABLE_STATUSES,
    )
