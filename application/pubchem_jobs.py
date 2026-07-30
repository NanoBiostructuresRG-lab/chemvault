# SPDX-License-Identifier: LGPL-3.0-or-later
"""Application boundary for persisted PubChem protein-search jobs."""
from pathlib import Path

from application.database_use_cases import (
    list_database_tables,
    resolve_database_path,
)
from application.job_contracts import JobStatusContract, job_status_from_record
from application.scientific_jobs import JobNotFoundError
from application.target_identity import (
    InvalidTargetIdentityError,
    target_identity_from_payload,
    target_identity_notes,
)
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


def _target_identity_from_job(record: JobRecord):
    payload = record.metadata.get("target_identity")
    if payload is None:
        return None
    proteins = record.metadata.get("proteins")
    if (
        not isinstance(proteins, list)
        or len(proteins) != 1
        or not isinstance(proteins[0], str)
        or not proteins[0].strip()
    ):
        raise InvalidTargetIdentityError(
            "Persisted target identity requires exactly one protein accession."
        )
    return target_identity_from_payload(
        payload,
        expected_accession=proteins[0],
    )


def launch_pubchem_protein_search(
    database_id: str,
    proteins,
    target_identity=None,
) -> JobStatusContract:
    """Launch the existing external PubChem worker behind a public contract."""
    normalized = _normalize_proteins(proteins)
    if target_identity is not None and len(normalized) != 1:
        raise InvalidPubChemProteinSearchError(
            "Target identity requires exactly one protein accession."
        )
    try:
        identity = target_identity_from_payload(
            target_identity,
            expected_accession=normalized[0] if len(normalized) == 1 else None,
        )
    except InvalidTargetIdentityError as error:
        raise InvalidPubChemProteinSearchError(str(error)) from error
    list_database_tables(database_id)
    record, _db_path = create_pubchem_search_job(
        database_id,
        normalized,
        target_identity=(
            identity.to_payload() if identity is not None else None
        ),
    )
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
    try:
        identity = _target_identity_from_job(record)
    except InvalidTargetIdentityError as error:
        raise PubChemJobStateError(
            f"PubChem job '{job_id}' has invalid target identity metadata: "
            f"{error}"
        ) from error
    register_completed_pubchem_job_record(
        db_path,
        record,
        metadata_notes=(
            target_identity_notes(identity)
            if identity is not None
            else None
        ),
    )
    return job_status_from_record(record)
