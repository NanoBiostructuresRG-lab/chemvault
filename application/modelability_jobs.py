# SPDX-License-Identifier: LGPL-3.0-or-later
"""Asynchronous scientific-job lifecycle for Modelability Index analysis."""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Callable
from dataclasses import asdict

from application.database_use_cases import (
    get_table_provenance,
    resolve_database_path,
)
from application.job_contracts import JobStatusContract, job_status_from_record
from application.modelability_index import calculate_table_modelability_index
from application.scientific_jobs import JobNotFoundError, register_scientific_job
from services.database_core import get_connection
from services.job_models import JobStatus, JobType
from services.job_store import JobStore


MODELABILITY_INTERRUPTED_MESSAGE = (
    "Modelability Index calculation was interrupted by a backend restart. "
    "Run it again."
)


class InvalidModelabilitySourceError(ValueError):
    """Raised when Modelability input is not structure-consolidated."""


def fail_orphaned_modelability_jobs(
    database_id: str,
    *,
    db_dir="SQL",
    executor_is_alive: Callable,
    process_is_alive: Callable,
    current_pid: int,
) -> tuple[JobStatusContract, ...]:
    """Fail active Modelability jobs that no live executor still owns."""
    db_path = resolve_database_path(database_id, db_dir=db_dir)
    connection = sqlite3.connect(db_path, check_same_thread=False)
    failed = []
    try:
        has_jobs_table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            ("_chemvault_jobs",),
        ).fetchone()
        if has_jobs_table is None:
            return ()

        store = JobStore(connection)
        for job in store.list_active_scientific_jobs(
            JobType.MODELABILITY_INDEX
        ):
            if job.database_id and job.database_id != database_id:
                continue
            if executor_is_alive(database_id, job.job_id):
                continue
            if (
                job.worker_pid is not None
                and job.worker_pid != current_pid
                and process_is_alive(job.worker_pid)
            ):
                continue

            creator_pid = job.metadata.get("creator_pid")
            if job.status == JobStatus.PENDING.value and job.worker_pid is None:
                if creator_pid == current_pid:
                    continue
                if creator_pid is not None and process_is_alive(creator_pid):
                    continue

            interrupted = store.fail_job(
                job.job_id,
                MODELABILITY_INTERRUPTED_MESSAGE,
            )
            if interrupted is not None:
                failed.append(job_status_from_record(interrupted))
    finally:
        connection.close()
    return tuple(failed)


def _fail_orphans_before_creation(database_id: str) -> None:
    # Imported lazily because scientific_runtime imports this module's cleanup.
    from application.scientific_runtime import (
        process_is_alive,
        scientific_job_executor_is_alive,
    )

    fail_orphaned_modelability_jobs(
        database_id,
        executor_is_alive=scientific_job_executor_is_alive,
        process_is_alive=process_is_alive,
        current_pid=os.getpid(),
    )


def create_modelability_job(
    database_id: str,
    table_name: str,
) -> JobStatusContract:
    """Validate and persist one queued Modelability Index job."""
    provenance = get_table_provenance(database_id, table_name)
    if provenance.origin != "structure_consolidation":
        raise InvalidModelabilitySourceError(
            "Modelability Index requires a table produced by structure "
            "consolidation / Activity Labels."
        )
    _fail_orphans_before_creation(database_id)
    request_metadata = {
        "table_name": table_name,
        "cancellation_supported": False,
        "creator_pid": os.getpid(),
    }
    connection = get_connection(database_id)
    try:
        store = JobStore(connection)
        record, created = store.create_job_unless_active(
            job_type=JobType.MODELABILITY_INDEX,
            database_id=database_id,
            table_name=table_name,
            metadata=request_metadata,
        )
        if not created:
            return job_status_from_record(record)
        queued = store.update_progress(
            record.job_id,
            "queued",
            0.0,
            "Modelability Index job queued",
            request_metadata,
        )
        return job_status_from_record(queued)
    finally:
        connection.close()


def execute_modelability_job(
    database_id: str,
    job_id: str,
) -> JobStatusContract:
    """Execute a previously queued Modelability Index job."""
    connection = get_connection(database_id)
    store = JobStore(connection)
    record = store.get_job(job_id)
    if record is None or record.database_id != database_id:
        connection.close()
        raise JobNotFoundError(
            f"Job '{job_id}' was not found in database '{database_id}'."
        )

    request_metadata = dict(record.metadata)
    started = store.start_job(job_id)
    if started is None:
        current = store.get_job(job_id)
        connection.close()
        return job_status_from_record(current)

    try:
        table_name = str(request_metadata["table_name"])
        store.update_progress(
            job_id,
            "calculating",
            0.1,
            "Calculating Modelability Index",
            request_metadata,
        )
        result = calculate_table_modelability_index(database_id, table_name)
        store.update_progress(
            job_id,
            "completed",
            0.95,
            "Modelability Index calculated",
        )
        final = store.complete_job(
            job_id,
            {**request_metadata, "result": asdict(result)},
        )
    except Exception as error:
        final = store.fail_job(job_id, str(error), request_metadata)
    finally:
        connection.close()
    return job_status_from_record(final)


register_scientific_job(
    JobType.MODELABILITY_INDEX,
    create=create_modelability_job,
    execute=execute_modelability_job,
)
