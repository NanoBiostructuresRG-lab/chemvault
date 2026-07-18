# SPDX-License-Identifier: LGPL-3.0-or-later
from dataclasses import dataclass, field
from enum import Enum


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobType(str, Enum):
    PUBCHEM_PROTEIN_SEARCH = "pubchem_protein_search"
    HARMONSMILE = "harmonsmile"
    MODELABILITY_INDEX = "modelability_index"


class JobNotActiveError(RuntimeError):
    """Raised when a worker no longer owns an active job."""


@dataclass(frozen=True)
class JobRecord:
    job_id: str
    job_type: str
    status: str
    database_id: str = ""
    current_stage: str = ""
    progress: float = 0.0
    message: str = ""
    error_message: str = ""
    created_at: str = ""
    started_at: str = ""
    finished_at: str = ""
    last_heartbeat_at: str = ""
    cancel_requested_at: str = ""
    worker_pid: int | None = None
    metadata: dict = field(default_factory=dict)


class JobCancellationNotSupportedError(RuntimeError):
    """Raised when cancellation is requested for non-interruptible work."""


def job_supports_cancellation(job: JobRecord) -> bool:
    """Return the persisted cancellation capability, defaulting to enabled."""
    return job.metadata.get("cancellation_supported", True) is not False
