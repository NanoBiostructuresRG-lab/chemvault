# SPDX-License-Identifier: LGPL-3.0-or-later
"""Internal runtime settings for CHEMVAULT."""
import os


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
