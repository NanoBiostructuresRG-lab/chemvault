# SPDX-License-Identifier: LGPL-3.0-or-later
"""Minimal in-process background runtime for API-launched jobs."""
from threading import Thread

from application.scientific_runtime import start_scientific_job_executor


def start_background_job(target, *args, name="chemvault-scientific-job"):
    """Start a daemon thread so API shutdown never waits for local job work."""
    thread = Thread(
        target=target,
        args=args,
        daemon=True,
        name=name,
    )
    thread.start()
    return thread


def start_scientific_background_job(
    database_id,
    job_type,
    job_id,
    *,
    name="chemvault-scientific-job",
):
    """Start a claimed scientific-job executor in this API process."""
    return start_scientific_job_executor(
        database_id,
        job_type,
        job_id,
        name=name,
    )
