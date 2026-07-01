# SPDX-License-Identifier: LGPL-3.0-or-later
"""Persistent lifecycle operations for PubChem protein-search jobs."""
import sqlite3

from services.builders import register_protein_search_build
from services.job_store import JobStore


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
