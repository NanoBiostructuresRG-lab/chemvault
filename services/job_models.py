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
    metadata: dict = field(default_factory=dict)
