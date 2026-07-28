# SPDX-License-Identifier: LGPL-3.0-or-later
"""Application boundary for persisted PubChem protein-search jobs."""
from pathlib import Path

from application.database_use_cases import (
    list_database_tables,
    resolve_database_path,
)
from application.job_contracts import JobStatusContract, job_status_from_record
from application.scientific_jobs import JobNotFoundError
from services.job_models import JobRecord, JobStatus, JobType
from services.pubchem_job_service import (
    cancel_pubchem_job_record,
    create_pubchem_search_job,
    load_pubchem_job_record,
    register_completed_pubchem_job_record,
)


class InvalidPubChemProteinSearchError(ValueError):
    """Raised when the requested protein-accession list is invalid."""


class PubChemJobTypeError(ValueError):
    """Raised when a job is not a PubChem protein-search job."""


class PubChemJobStateError(RuntimeError):
    """Raised when a PubChem job cannot perform the requested transition."""


def _normalize_proteins(proteins) -> tuple[str, ...]:
    if isinstance(proteins, (str, bytes)):
        raise InvalidPubChemProteinSearchError(
            "Proteins must be provided as a non-empty list of strings."
        )
    try:
        values = tuple(proteins)
    except TypeError as error:
        raise InvalidPubChemProteinSearchError(
            "Proteins must be provided as a non-empty list of strings."
        ) from error
    if (
        not values
        or any(not isinstance(value, str) for value in values)
        or any(not value.strip() for value in values)
    ):
        raise InvalidPubChemProteinSearchError(
            "Proteins must be provided as a non-empty list of strings."
        )
    return tuple(value.strip() for value in values)


def _load_pubchem_job(
    database_id: str,
    job_id: str,
) -> tuple[JobRecord, Path]:
    list_database_tables(database_id)
    db_path = resolve_database_path(database_id)
    record = load_pubchem_job_record(db_path, job_id)
    if record is None or record.database_id != database_id:
        raise JobNotFoundError(
            f"Job '{job_id}' was not found in database '{database_id}'."
        )
    if record.job_type != JobType.PUBCHEM_PROTEIN_SEARCH.value:
        raise PubChemJobTypeError(
            f"Job '{job_id}' is not a PubChem protein-search job."
        )
    return record, db_path


def launch_pubchem_protein_search(
    database_id: str,
    proteins,
) -> JobStatusContract:
    """Launch the existing external PubChem worker behind a public contract."""
    normalized = _normalize_proteins(proteins)
    list_database_tables(database_id)
    record, _db_path = create_pubchem_search_job(database_id, normalized)
    return job_status_from_record(record)


def get_pubchem_protein_search_status(
    database_id: str,
    job_id: str,
) -> JobStatusContract:
    """Return one PubChem job snapshot, including stale-worker detection."""
    record, _db_path = _load_pubchem_job(database_id, job_id)
    return job_status_from_record(record)


def cancel_pubchem_protein_search(
    database_id: str,
    job_id: str,
) -> JobStatusContract:
    """Cancel an active PubChem job and tolerate terminal-state retries."""
    record, db_path = _load_pubchem_job(database_id, job_id)
    if record.status in {
        JobStatus.COMPLETED.value,
        JobStatus.FAILED.value,
        JobStatus.CANCELLED.value,
    }:
        return job_status_from_record(record)
    cancelled = cancel_pubchem_job_record(db_path, job_id)
    if cancelled is None:
        record, _db_path = _load_pubchem_job(database_id, job_id)
        return job_status_from_record(record)
    return job_status_from_record(cancelled)


def finalize_pubchem_protein_search(
    database_id: str,
    job_id: str,
) -> JobStatusContract:
    """Register a completed PubChem build exactly once for one job id."""
    record, db_path = _load_pubchem_job(database_id, job_id)
    if record.status != JobStatus.COMPLETED.value:
        raise PubChemJobStateError(
            f"PubChem job '{job_id}' is not completed."
        )
    register_completed_pubchem_job_record(db_path, record)
    return job_status_from_record(record)
