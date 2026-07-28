# SPDX-License-Identifier: LGPL-3.0-or-later
"""Persistent lifecycle operations for PubChem protein-search jobs."""
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from services.database_core import get_connection
from services.db_audit import (
    operation_exists,
    register_operation,
    register_table_metadata,
)
from services.job_launcher import (
    create_and_launch_pubchem_job,
    resolve_database_path,
)
from services.job_models import JobRecord, JobStatus, JobType
from services.job_store import ACTIVE_JOB_STATUSES, STALE_JOB_ERROR_MESSAGE, JobStore


@dataclass(frozen=True)
class PubChemJobView:
    job_id: str
    status: str
    current_stage: str
    progress: float
    message: str
    error_message: str
    proteins: tuple[str, ...]
    is_active: bool
    is_terminal: bool
    is_completed: bool
    is_failed: bool
    is_cancelled: bool
    is_stale_failure: bool
    can_cancel: bool


def _to_pubchem_job_view(job: JobRecord) -> PubChemJobView:
    is_active = job.status in ACTIVE_JOB_STATUSES
    is_completed = job.status == JobStatus.COMPLETED.value
    is_failed = job.status == JobStatus.FAILED.value
    is_cancelled = job.status == JobStatus.CANCELLED.value
    return PubChemJobView(
        job_id=job.job_id,
        status=job.status,
        current_stage=job.current_stage,
        progress=job.progress,
        message=job.message,
        error_message=job.error_message,
        proteins=tuple(job.metadata.get("proteins", [])),
        is_active=is_active,
        is_terminal=is_completed or is_failed or is_cancelled,
        is_completed=is_completed,
        is_failed=is_failed,
        is_cancelled=is_cancelled,
        is_stale_failure=(
            is_failed and job.error_message == STALE_JOB_ERROR_MESSAGE
        ),
        can_cancel=is_active,
    )


def register_protein_search_build(connection, proteins, *, job_id=None):
    query_used = f"pubchem_job:{job_id}" if job_id else None
    try:
        if query_used:
            connection.execute("BEGIN IMMEDIATE")
            if operation_exists(
                connection, "protein_search_loaded", query_used
            ):
                connection.commit()
                return False
        register_table_metadata(
            connection,
            "main",
            role="base",
            origin="protein_search",
            created_by="build_from_proteins",
            notes="Initial table created from selected proteins.",
            commit=False,
        )
        register_operation(
            connection,
            "protein_search_loaded",
            target_table="main",
            output_columns=[
                "CID",
                "AIDs",
                "Proteins",
                "Compound_Name",
                "Activity_Enrichment_Status",
            ],
            created_by="build_from_proteins",
            details=f"Loaded selected proteins: {', '.join(map(str, proteins))}.",
            query_used=query_used,
            commit=False,
        )
        connection.commit()
        return True
    except Exception:
        connection.rollback()
        raise


def create_pubchem_search_job(
    database_id,
    proteins,
    db_dir="SQL",
) -> tuple[JobRecord, Path]:
    db_path = Path(db_dir) / f"{database_id}.db"
    connection = get_connection(database_id)
    try:
        job = create_and_launch_pubchem_job(
            connection,
            db_path,
            list(proteins),
            database_id=database_id,
        )
    finally:
        connection.close()
    return job, resolve_database_path(db_path)


def start_pubchem_search(
    database_id,
    proteins,
    db_dir="SQL",
) -> tuple[PubChemJobView, Path]:
    job, db_path = create_pubchem_search_job(
        database_id,
        proteins,
        db_dir=db_dir,
    )
    return _to_pubchem_job_view(job), db_path


def load_pubchem_job_record(db_path, job_id) -> JobRecord | None:
    connection = sqlite3.connect(db_path)
    try:
        store = JobStore(connection)
        job = store.get_job(job_id)
        if (
            job is not None
            and job.job_type == JobType.PUBCHEM_PROTEIN_SEARCH.value
        ):
            store.fail_stale_job(job_id)
            job = store.get_job(job_id)
        return job
    finally:
        connection.close()


def load_pubchem_job(db_path, job_id) -> PubChemJobView | None:
    job = load_pubchem_job_record(db_path, job_id)
    return _to_pubchem_job_view(job) if job is not None else None


def cancel_pubchem_job_record(db_path, job_id) -> JobRecord | None:
    connection = sqlite3.connect(db_path)
    try:
        return JobStore(connection).cancel_job(job_id, "Cancelled by user")
    finally:
        connection.close()


def cancel_pubchem_job(db_path, job_id) -> PubChemJobView | None:
    job = cancel_pubchem_job_record(db_path, job_id)
    return _to_pubchem_job_view(job) if job is not None else None


def register_completed_pubchem_job(db_path, job_view: PubChemJobView):
    if not job_view.is_completed:
        raise ValueError("Only completed PubChem jobs can be registered.")

    connection = sqlite3.connect(db_path)
    try:
        register_protein_search_build(
            connection,
            job_view.proteins,
        )
    finally:
        connection.close()


def register_completed_pubchem_job_record(
    db_path,
    job: JobRecord,
) -> bool:
    if job.job_type != JobType.PUBCHEM_PROTEIN_SEARCH.value:
        raise ValueError("Only PubChem protein-search jobs can be registered.")
    if job.status != JobStatus.COMPLETED.value:
        raise ValueError("Only completed PubChem jobs can be registered.")
    connection = sqlite3.connect(db_path)
    try:
        return register_protein_search_build(
            connection,
            tuple(job.metadata.get("proteins", [])),
            job_id=job.job_id,
        )
    finally:
        connection.close()
