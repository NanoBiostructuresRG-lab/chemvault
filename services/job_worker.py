# SPDX-License-Identifier: LGPL-3.0-or-later
"""Command-line worker for persistent CHEMVAULT jobs."""
import argparse
import os
import sqlite3
import sys

from services.job_models import JobNotActiveError, JobStatus, JobType
from services.job_store import JobStore
from services.pubchem_protein_search import run_pubchem_protein_search_job


class JobWorkerError(Exception):
    """Base error for controlled worker failures."""


class JobNotFoundError(JobWorkerError):
    """Raised when the requested persistent job does not exist."""


class InvalidJobError(JobWorkerError):
    """Raised when a job cannot be executed from its persisted payload."""


def _proteins_from_job(job):
    proteins = job.metadata.get("proteins")
    if (
        not isinstance(proteins, list)
        or not proteins
        or any(not isinstance(protein, str) or not protein.strip() for protein in proteins)
    ):
        raise InvalidJobError(
            "Job metadata must contain a non-empty 'proteins' list of strings"
        )
    return proteins


def run_pubchem_protein_search_worker(db_path, job_id):
    """Execute one persisted PubChem protein-search job in this process."""
    if not os.path.isfile(db_path):
        raise JobWorkerError(f"Database file does not exist: {db_path}")

    connection = sqlite3.connect(db_path)
    try:
        store = JobStore(connection)
        job = store.get_job(job_id)
        if job is None:
            raise JobNotFoundError(f"Job not found: {job_id}")

        try:
            if job.job_type != JobType.PUBCHEM_PROTEIN_SEARCH.value:
                raise InvalidJobError(
                    f"Job {job_id} has unsupported type: {job.job_type}"
                )
            proteins = _proteins_from_job(job)
            return run_pubchem_protein_search_job(
                connection,
                proteins,
                job_store=store,
                job_id=job_id,
            )
        except JobNotActiveError:
            raise
        except Exception as error:
            current_job = store.get_job(job_id)
            if current_job is not None and current_job.status != JobStatus.FAILED.value:
                store.fail_job(job_id, str(error))
            raise
    finally:
        connection.close()


def _build_parser():
    parser = argparse.ArgumentParser(description="Run persistent CHEMVAULT jobs")
    commands = parser.add_subparsers(dest="command", required=True)
    pubchem = commands.add_parser(
        "run-pubchem-protein-search",
        help="Run an existing PubChem protein-search job",
    )
    pubchem.add_argument("--db-path", required=True)
    pubchem.add_argument("--job-id", required=True)
    return parser


def main(argv=None):
    args = _build_parser().parse_args(argv)
    try:
        job = run_pubchem_protein_search_worker(args.db_path, args.job_id)
    except Exception as error:
        print(f"Worker failed: {error}", file=sys.stderr)
        return 1

    print(f"Job completed: {job.job_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
