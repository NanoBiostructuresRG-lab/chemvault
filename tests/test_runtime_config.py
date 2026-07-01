# SPDX-License-Identifier: LGPL-3.0-or-later
import importlib

from services import runtime_config


def test_pubchem_worker_mode_reads_environment_with_safe_default(monkeypatch):
    monkeypatch.delenv("CHEMVAULT_PUBCHEM_WORKER_MODE", raising=False)
    assert importlib.reload(runtime_config).USE_PUBCHEM_WORKER_MODE is False

    monkeypatch.setenv("CHEMVAULT_PUBCHEM_WORKER_MODE", "1")
    assert importlib.reload(runtime_config).USE_PUBCHEM_WORKER_MODE is True

    monkeypatch.setenv("CHEMVAULT_PUBCHEM_WORKER_MODE", "0")
    assert importlib.reload(runtime_config).USE_PUBCHEM_WORKER_MODE is False
