# SPDX-License-Identifier: LGPL-3.0-or-later
"""Generic application boundary for scientific backend jobs."""
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from application.job_contracts import JobStatusContract, job_status_from_record
from application.database_use_cases import list_database_tables
from services.database_core import get_connection
from services.job_models import JobType
from services.job_store import JobStore


class JobNotFoundError(LookupError):
    """Raised when a job does not exist in the requested database."""


class UnsupportedJobTypeError(ValueError):
    """Raised when a scientific job type is not registered."""


@dataclass(frozen=True)
class ScientificJobDefinition:
    """Workflow-specific hooks behind the generic job launch contract."""

    create: Callable[..., JobStatusContract]
    execute: Callable[[str, str], JobStatusContract]


_JOB_DEFINITIONS: dict[str, ScientificJobDefinition] = {}


def _job_type_value(job_type: str | JobType) -> str:
    return job_type.value if hasattr(job_type, "value") else str(job_type)


def register_scientific_job(
    job_type: str | JobType,
    *,
    create: Callable[..., JobStatusContract],
    execute: Callable[[str, str], JobStatusContract],
) -> None:
    """Register a workflow implementation behind the shared job contract."""
    _JOB_DEFINITIONS[_job_type_value(job_type)] = ScientificJobDefinition(
        create=create,
        execute=execute,
    )


def get_scientific_job_definition(
    job_type: str | JobType,
) -> ScientificJobDefinition:
    try:
        return _JOB_DEFINITIONS[_job_type_value(job_type)]
    except KeyError as error:
        raise UnsupportedJobTypeError(
            f"Unsupported scientific job type: {_job_type_value(job_type)}"
        ) from error


def create_scientific_job(
    database_id: str,
    job_type: str | JobType,
    request: dict[str, Any],
) -> JobStatusContract:
    """Create a queued scientific job using a registered workflow hook."""
    definition = get_scientific_job_definition(job_type)
    return definition.create(database_id, **request)


def execute_scientific_job(
    database_id: str,
    job_type: str | JobType,
    job_id: str,
) -> JobStatusContract:
    """Execute a queued scientific job using a registered workflow hook."""
    definition = get_scientific_job_definition(job_type)
    return definition.execute(database_id, job_id)


def get_scientific_job_status(
    database_id: str,
    job_id: str,
) -> JobStatusContract:
    """Return persisted job status without depending on a workflow module."""
    list_database_tables(database_id)
    connection = get_connection(database_id)
    try:
        record = JobStore(connection).get_job(job_id)
    finally:
        connection.close()
    if record is None or record.database_id != database_id:
        raise JobNotFoundError(
            f"Job '{job_id}' was not found in database '{database_id}'."
        )
    return job_status_from_record(record)
