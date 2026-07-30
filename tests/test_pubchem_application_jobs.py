# SPDX-License-Identifier: LGPL-3.0-or-later
from pathlib import Path

import pytest

from application import pubchem_jobs
from application.scientific_jobs import JobNotFoundError
from services.job_models import JobRecord, JobStatus, JobType


def _record(
    *,
    status=JobStatus.PENDING.value,
    job_type=JobType.PUBCHEM_PROTEIN_SEARCH.value,
    database_id="protein_db",
    metadata=None,
):
    return JobRecord(
        job_id="job-1",
        job_type=job_type,
        status=status,
        database_id=database_id,
        current_stage="queued",
        progress=0.0,
        message="queued",
        created_at="2026-07-27T10:00:00+00:00",
        last_heartbeat_at="2026-07-27T10:00:00+00:00",
        metadata=metadata or {"proteins": ["P34971"]},
    )


def test_launch_validates_database_and_delegates_to_existing_launcher(monkeypatch):
    calls = []
    expected = _record()
    monkeypatch.setattr(
        pubchem_jobs,
        "list_database_tables",
        lambda database_id: calls.append(("tables", database_id)) or ["main"],
    )
    monkeypatch.setattr(
        pubchem_jobs,
        "create_pubchem_search_job",
        lambda database_id, proteins, *, target_identity=None: (
            calls.append(
                ("launch", database_id, proteins, target_identity)
            )
            or (expected, Path("SQL/protein_db.db"))
        ),
    )

    result = pubchem_jobs.launch_pubchem_protein_search(
        "protein_db",
        [" P34971 "],
    )

    assert result.job_id == "job-1"
    assert result.job_type == JobType.PUBCHEM_PROTEIN_SEARCH.value
    assert result.status == JobStatus.PENDING
    assert calls == [
        ("tables", "protein_db"),
        ("launch", "protein_db", ("P34971",), None),
    ]


def test_launch_persists_valid_gene_target_identity(monkeypatch):
    calls = []
    expected = _record()
    target_identity = {
        "input_mode": "gene_symbol",
        "gene_symbol": "MC4R",
        "organism_id": 9606,
        "organism_name": "Homo sapiens",
        "common_name": "Human",
        "uniprot_accession": "P32245",
        "uniprot_entry_name": "MC4R_HUMAN",
        "protein_name": "Melanocortin receptor 4",
        "reviewed": True,
    }
    monkeypatch.setattr(
        pubchem_jobs,
        "list_database_tables",
        lambda database_id: ["main"],
    )
    monkeypatch.setattr(
        pubchem_jobs,
        "create_pubchem_search_job",
        lambda database_id, proteins, *, target_identity=None: (
            calls.append((database_id, proteins, target_identity))
            or (expected, Path("SQL/protein_db.db"))
        ),
    )

    pubchem_jobs.launch_pubchem_protein_search(
        "protein_db",
        ["P32245"],
        target_identity,
    )

    assert calls == [
        ("protein_db", ("P32245",), target_identity),
    ]


@pytest.mark.parametrize(
    ("proteins", "target_identity"),
    [
        (
            ["P32245"],
            {
                "input_mode": "uniprot_accession",
                "uniprot_accession": "P48357",
            },
        ),
        (
            ["P32245", "P48357"],
            {
                "input_mode": "uniprot_accession",
                "uniprot_accession": "P32245",
            },
        ),
    ],
)
def test_launch_rejects_inconsistent_target_identity_before_database_access(
    monkeypatch,
    proteins,
    target_identity,
):
    monkeypatch.setattr(
        pubchem_jobs,
        "list_database_tables",
        lambda *_args: pytest.fail("invalid input must not inspect database"),
    )

    with pytest.raises(pubchem_jobs.InvalidPubChemProteinSearchError):
        pubchem_jobs.launch_pubchem_protein_search(
            "protein_db",
            proteins,
            target_identity,
        )


@pytest.mark.parametrize("proteins", [[], [""], "P34971", [123]])
def test_launch_rejects_invalid_protein_lists(monkeypatch, proteins):
    monkeypatch.setattr(
        pubchem_jobs,
        "list_database_tables",
        lambda _database_id: pytest.fail(
            "invalid input must not inspect the database"
        ),
    )
    monkeypatch.setattr(
        pubchem_jobs,
        "create_pubchem_search_job",
        lambda *_args: pytest.fail("invalid input must not launch a worker"),
    )

    with pytest.raises(pubchem_jobs.InvalidPubChemProteinSearchError):
        pubchem_jobs.launch_pubchem_protein_search("protein_db", proteins)


def test_status_resolves_database_path_and_projects_record(monkeypatch):
    expected = _record(status=JobStatus.RUNNING.value)
    calls = []
    monkeypatch.setattr(
        pubchem_jobs,
        "list_database_tables",
        lambda database_id: calls.append(("tables", database_id)) or ["main"],
    )
    monkeypatch.setattr(
        pubchem_jobs,
        "resolve_database_path",
        lambda database_id: Path(f"SQL/{database_id}.db"),
    )
    monkeypatch.setattr(
        pubchem_jobs,
        "load_pubchem_job_record",
        lambda db_path, job_id: (
            calls.append(("load", db_path, job_id)) or expected
        ),
    )

    result = pubchem_jobs.get_pubchem_protein_search_status(
        "protein_db",
        "job-1",
    )

    assert result.status == JobStatus.RUNNING
    assert calls == [
        ("tables", "protein_db"),
        ("load", Path("SQL/protein_db.db"), "job-1"),
    ]


def test_status_rejects_jobs_from_another_type(monkeypatch):
    monkeypatch.setattr(
        pubchem_jobs,
        "list_database_tables",
        lambda _database_id: ["main"],
    )
    monkeypatch.setattr(
        pubchem_jobs,
        "resolve_database_path",
        lambda _database_id: Path("SQL/protein_db.db"),
    )
    monkeypatch.setattr(
        pubchem_jobs,
        "load_pubchem_job_record",
        lambda *_args: _record(job_type=JobType.HARMONSMILE.value),
    )

    with pytest.raises(pubchem_jobs.PubChemJobTypeError):
        pubchem_jobs.get_pubchem_protein_search_status(
            "protein_db",
            "job-1",
        )


def test_status_rejects_jobs_from_another_database(monkeypatch):
    monkeypatch.setattr(
        pubchem_jobs,
        "list_database_tables",
        lambda _database_id: ["main"],
    )
    monkeypatch.setattr(
        pubchem_jobs,
        "resolve_database_path",
        lambda _database_id: Path("SQL/protein_db.db"),
    )
    monkeypatch.setattr(
        pubchem_jobs,
        "load_pubchem_job_record",
        lambda *_args: _record(database_id="other_db"),
    )

    with pytest.raises(JobNotFoundError):
        pubchem_jobs.get_pubchem_protein_search_status(
            "protein_db",
            "job-1",
        )


def test_cancel_is_idempotent_for_terminal_jobs(monkeypatch):
    completed = _record(status=JobStatus.COMPLETED.value)
    monkeypatch.setattr(
        pubchem_jobs,
        "_load_pubchem_job",
        lambda *_args: (completed, Path("SQL/protein_db.db")),
    )
    monkeypatch.setattr(
        pubchem_jobs,
        "cancel_pubchem_job_record",
        lambda *_args: pytest.fail("terminal job must not be cancelled again"),
    )

    result = pubchem_jobs.cancel_pubchem_protein_search(
        "protein_db",
        "job-1",
    )

    assert result.status == JobStatus.COMPLETED


def test_finalize_requires_completed_job(monkeypatch):
    running = _record(status=JobStatus.RUNNING.value)
    monkeypatch.setattr(
        pubchem_jobs,
        "_load_pubchem_job",
        lambda *_args: (running, Path("SQL/protein_db.db")),
    )

    with pytest.raises(pubchem_jobs.PubChemJobStateError):
        pubchem_jobs.finalize_pubchem_protein_search(
            "protein_db",
            "job-1",
        )


def test_finalize_delegates_completed_record(monkeypatch):
    completed = _record(status=JobStatus.COMPLETED.value)
    calls = []
    path = Path("SQL/protein_db.db")
    monkeypatch.setattr(
        pubchem_jobs,
        "_load_pubchem_job",
        lambda *_args: (completed, path),
    )
    monkeypatch.setattr(
        pubchem_jobs,
        "register_completed_pubchem_job_record",
        lambda db_path, record, *, metadata_notes=None: calls.append(
            (db_path, record, metadata_notes)
        ),
    )

    result = pubchem_jobs.finalize_pubchem_protein_search(
        "protein_db",
        "job-1",
    )

    assert result.status == JobStatus.COMPLETED
    assert calls == [(path, completed, None)]


def test_finalize_rejects_target_identity_with_multiple_proteins(
    monkeypatch,
):
    completed = _record(
        status=JobStatus.COMPLETED.value,
        metadata={
            "proteins": ["P32245", "P48357"],
            "target_identity": {
                "input_mode": "uniprot_accession",
                "uniprot_accession": "P32245",
            },
        },
    )
    monkeypatch.setattr(
        pubchem_jobs,
        "_load_pubchem_job",
        lambda *_args: (completed, Path("SQL/protein_db.db")),
    )

    with pytest.raises(
        pubchem_jobs.PubChemJobStateError,
        match="requires exactly one protein accession",
    ):
        pubchem_jobs.finalize_pubchem_protein_search(
            "protein_db",
            "job-1",
        )


def test_finalize_serializes_gene_identity_into_table_metadata(monkeypatch):
    completed = _record(
        status=JobStatus.COMPLETED.value,
        metadata={
            "proteins": ["P32245"],
            "target_identity": {
                "input_mode": "gene_symbol",
                "gene_symbol": "MC4R",
                "organism_id": 9606,
                "organism_name": "Homo sapiens",
                "common_name": "Human",
                "uniprot_accession": "P32245",
                "uniprot_entry_name": "MC4R_HUMAN",
                "protein_name": "Melanocortin receptor 4",
                "reviewed": True,
            },
        },
    )
    calls = []
    path = Path("SQL/protein_db.db")
    monkeypatch.setattr(
        pubchem_jobs,
        "_load_pubchem_job",
        lambda *_args: (completed, path),
    )
    monkeypatch.setattr(
        pubchem_jobs,
        "register_completed_pubchem_job_record",
        lambda db_path, record, *, metadata_notes=None: calls.append(
            (db_path, record, metadata_notes)
        ),
    )

    pubchem_jobs.finalize_pubchem_protein_search(
        "protein_db",
        "job-1",
    )

    assert calls[0][0:2] == (path, completed)
    assert '"artifact_contract":"protein_search_target_identity"' in calls[0][2]
    assert '"gene_symbol":"MC4R"' in calls[0][2]
    assert '"organism_id":9606' in calls[0][2]
