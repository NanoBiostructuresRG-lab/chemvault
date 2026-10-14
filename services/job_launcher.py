# SPDX-License-Identifier: LGPL-3.0-or-later
"""Launch persistent CHEMVAULT jobs in a separate local process."""
import subprocess
import sys
from pathlib import Path

from services.job_models import JobType
from services.job_store import JobStore


def resolve_database_path(db_path):
    path = Path(db_path).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return path.resolve()


def build_pubchem_worker_command(db_path, job_id):
    resolved_db_path = resolve_database_path(db_path)
    return [
        sys.executable,
        "-m",
        "services.job_worker",
        "run-pubchem-protein-search",
        "--db-path",
        str(resolved_db_path),
        "--job-id",
        str(job_id),
    ]


def launch_pubchem_worker(db_path, job_id, popen=None):
    command = build_pubchem_worker_command(db_path, job_id)
    popen = popen or subprocess.Popen
    kwargs = {
        "shell": False,
    }
    create_no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if create_no_window:
        kwargs["creationflags"] = create_no_window
    return popen(command, **kwargs)


def create_and_launch_pubchem_job(
    connection,
    db_path,
    proteins,
    *,
    database_id="",
    target_identity=None,
    launcher=None,
):
    proteins = list(proteins)
    metadata = {"proteins": proteins}
    if target_identity is not None:
        metadata["target_identity"] = dict(target_identity)
    store = JobStore(connection)
    job = store.create_job(
        job_type=JobType.PUBCHEM_PROTEIN_SEARCH,
        database_id=database_id,
        metadata=metadata,
    )
    connection.commit()

    launcher = launcher or launch_pubchem_worker
    try:
        process = launcher(db_path, job.job_id)
        worker_pid = getattr(process, "pid", None)
        if worker_pid is not None:
            updated = store.set_worker_pid(job.job_id, worker_pid)
            if updated is not None:
                job = updated
    except Exception as error:
        store.fail_job(job.job_id, str(error))
        raise
    return job
