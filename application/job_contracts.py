# SPDX-License-Identifier: LGPL-3.0-or-later
"""Typed public contract for backend job status."""
from dataclasses import dataclass
from typing import Any

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
    updated_at: str = ""
    result: dict[str, Any] | None = None


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
        updated_at=(
            record.finished_at
            or record.last_heartbeat_at
            or record.started_at
            or record.created_at
        ),
        started_at=record.started_at or None,
        finished_at=record.finished_at or None,
        error=record.error_message or None,
        result=record.metadata.get("result"),
        cancellable=status in CANCELLABLE_STATUSES,
    )


def job_status_from_payload(payload: dict[str, Any]) -> JobStatusContract:
    """Build the typed contract returned by the HTTP backend."""
    return JobStatusContract(
        job_id=payload["job_id"],
        job_type=payload["job_type"],
        status=JobStatus(payload["status"]),
        database_id=payload["database_id"],
        stage=payload.get("stage", ""),
        progress=float(payload.get("progress", 0.0)),
        message=payload.get("message"),
        created_at=payload["created_at"],
        updated_at=payload["updated_at"],
        started_at=payload.get("started_at"),
        finished_at=payload.get("finished_at"),
        error=payload.get("error"),
        result=payload.get("result"),
        cancellable=bool(payload.get("cancellable", False)),
    )
