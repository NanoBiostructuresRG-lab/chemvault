# SPDX-License-Identifier: LGPL-3.0-or-later
import sqlite3

from services.job_launcher import create_and_launch_pubchem_job
from services.job_store import JobStore


def test_pubchem_launcher_persists_optional_target_identity(tmp_path):
    connection = sqlite3.connect(":memory:")
    launched = []

    class Process:
        pid = 1234

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

    job = create_and_launch_pubchem_job(
        connection,
        tmp_path / "target.db",
        ["P32245"],
        database_id="target_db",
        target_identity=target_identity,
        launcher=lambda db_path, job_id: (
            launched.append((db_path, job_id)) or Process()
        ),
    )

    persisted = JobStore(connection).get_job(job.job_id)
    assert persisted.metadata == {
        "proteins": ["P32245"],
        "target_identity": target_identity,
    }
    assert launched == [(tmp_path / "target.db", job.job_id)]
    assert persisted.worker_pid == 1234


def test_pubchem_launcher_preserves_legacy_metadata_without_identity(tmp_path):
    connection = sqlite3.connect(":memory:")

    job = create_and_launch_pubchem_job(
        connection,
        tmp_path / "legacy.db",
        ["P34971"],
        database_id="legacy_db",
        launcher=lambda *_args: object(),
    )

    assert JobStore(connection).get_job(job.job_id).metadata == {
        "proteins": ["P34971"],
    }
