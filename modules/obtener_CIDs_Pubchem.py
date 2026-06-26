# SPDX-License-Identifier: LGPL-3.0-or-later
"""
Compatibility wrapper for the PubChem protein search service.

This module is a shim that redirects all imports to
services/pubchem_protein_search.py, where the actual logic lives.

Any code that imports from this module continues to work unchanged:
    from modules.obtener_CIDs_Pubchem import fetch_pubchem_assay_activity
    from modules.obtener_CIDs_Pubchem import BASE_URL
"""
import sys

from services import pubchem_protein_search as _pubchem_protein_search

# Redirect this module to the real implementation.
sys.modules[__name__] = _pubchem_protein_search
