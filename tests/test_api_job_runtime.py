# SPDX-License-Identifier: LGPL-3.0-or-later
from threading import Event
from time import monotonic

from api.job_runtime import start_background_job


def test_background_job_launch_returns_without_waiting_for_work():
    started = Event()
    release = Event()

    def work():
        started.set()
        release.wait(timeout=2)

    before = monotonic()
    thread = start_background_job(work)
    elapsed = monotonic() - before

    assert started.wait(timeout=1)
    assert elapsed < 0.5
    assert thread.is_alive()
    assert thread.daemon is True
    release.set()
    thread.join(timeout=1)
