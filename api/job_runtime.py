# SPDX-License-Identifier: LGPL-3.0-or-later
"""Minimal in-process background runtime for API-launched jobs."""
from threading import Thread


def start_background_job(target, *args):
    """Start a daemon thread so API shutdown never waits for local job work."""
    thread = Thread(
        target=target,
        args=args,
        daemon=True,
        name="chemvault-harmonsmile",
    )
    thread.start()
    return thread
