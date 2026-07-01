# SPDX-License-Identifier: LGPL-3.0-or-later
import importlib

from services import runtime_config


def test_job_heartbeat_timeout_reads_positive_environment_value(monkeypatch):
    monkeypatch.delenv("CHEMVAULT_JOB_HEARTBEAT_TIMEOUT_SECONDS", raising=False)
    assert importlib.reload(runtime_config).JOB_HEARTBEAT_TIMEOUT_SECONDS == 600

    monkeypatch.setenv("CHEMVAULT_JOB_HEARTBEAT_TIMEOUT_SECONDS", "45")
    assert importlib.reload(runtime_config).JOB_HEARTBEAT_TIMEOUT_SECONDS == 45

    monkeypatch.setenv("CHEMVAULT_JOB_HEARTBEAT_TIMEOUT_SECONDS", "invalid")
    assert importlib.reload(runtime_config).JOB_HEARTBEAT_TIMEOUT_SECONDS == 600
