# SPDX-License-Identifier: LGPL-3.0-or-later
"""Internal runtime feature flags for CHEMVAULT."""
import os


USE_PUBCHEM_WORKER_MODE = (
    os.getenv("CHEMVAULT_PUBCHEM_WORKER_MODE", "0") == "1"
)
