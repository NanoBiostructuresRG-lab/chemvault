# SPDX-License-Identifier: LGPL-3.0-or-later
"""Launch persistent CHEMVAULT jobs in a separate local process."""
import os
from pathlib import Path
import subprocess
import sys

from services.job_models import JobType
from services.job_store import JobStore


REPO_ROOT = Path(__file__).resolve().parents[1]


def resolve_database_path(db_path, repo_root=None):
    root = Path(repo_root or REPO_ROOT).resolve()
    path = Path(db_path).expanduser()
    if not path.is_absolute():
        path = root / path
    return path.resolve()


def build_pubchem_worker_command(db_path, job_id, repo_root=None):
    resolved_db_path = resolve_database_path(db_path, repo_root=repo_root)
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


def _worker_environment(repo_root):
    environment = os.environ.copy()
    root = str(repo_root)
    existing_pythonpath = environment.get("PYTHONPATH", "")
    pythonpath_entries = [root]
    if existing_pythonpath:
        pythonpath_entries.append(existing_pythonpath)
    environment["PYTHONPATH"] = os.pathsep.join(pythonpath_entries)
    return environment


def launch_pubchem_worker(db_path, job_id, repo_root=None, popen=None):
    root = Path(repo_root or REPO_ROOT).resolve()
    command = build_pubchem_worker_command(db_path, job_id, repo_root=root)
    popen = popen or subprocess.Popen
    kwargs = {
        "cwd": str(root),
        "env": _worker_environment(root),
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
    launcher=None,
):
    proteins = list(proteins)
    store = JobStore(connection)
    job = store.create_job(
        job_type=JobType.PUBCHEM_PROTEIN_SEARCH,
        database_id=database_id,
        metadata={"proteins": proteins},
    )
    connection.commit()

    launcher = launcher or launch_pubchem_worker
    try:
        launcher(db_path, job.job_id)
    except Exception as error:
        store.fail_job(job.job_id, str(error))
        raise
    return job
