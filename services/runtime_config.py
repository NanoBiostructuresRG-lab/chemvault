# SPDX-License-Identifier: LGPL-3.0-or-later
"""Internal runtime feature flags for CHEMVAULT."""
import os


USE_PUBCHEM_WORKER_MODE = (
    os.getenv("CHEMVAULT_PUBCHEM_WORKER_MODE", "0") == "1"
)


def _positive_int_environment(name, default):
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return value if value > 0 else default


JOB_HEARTBEAT_TIMEOUT_SECONDS = _positive_int_environment(
    "CHEMVAULT_JOB_HEARTBEAT_TIMEOUT_SECONDS",
    600,
)
