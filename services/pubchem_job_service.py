# SPDX-License-Identifier: LGPL-3.0-or-later
"""Persistent lifecycle operations for PubChem protein-search jobs."""
import sqlite3
from pathlib import Path

from services.database import get_connection
from services.db_audit import register_operation, register_table_metadata
from services.job_launcher import (
    create_and_launch_pubchem_job,
    resolve_database_path,
)
from services.job_store import JobStore


def register_protein_search_build(connection, proteins):
    register_table_metadata(
        connection,
        "main",
        role="base",
        origin="protein_search",
        created_by="build_from_proteins",
        notes="Initial table created from selected proteins.",
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
    )


def start_pubchem_search(database_id, proteins, db_dir="SQL"):
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


def load_pubchem_job(db_path, job_id):
    connection = sqlite3.connect(db_path)
    try:
        store = JobStore(connection)
        store.fail_stale_job(job_id)
        return store.get_job(job_id)
    finally:
        connection.close()


def cancel_pubchem_job(db_path, job_id):
    connection = sqlite3.connect(db_path)
    try:
        return JobStore(connection).cancel_job(job_id, "Cancelled by user")
    finally:
        connection.close()


def register_completed_pubchem_job(db_path, job):
    connection = sqlite3.connect(db_path)
    try:
        register_protein_search_build(
            connection,
            job.metadata.get("proteins", []),
        )
    finally:
        connection.close()
