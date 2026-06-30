# SPDX-License-Identifier: LGPL-3.0-or-later
"""Compatibility wrapper for the PubChem protein search service."""
from services import pubchem_protein_search as _service
from services.pubchem_protein_search import (
    fetch_pubchem_assay_activity,
    obtener_CIDs_Pubchem,
    run_pubchem_protein_search,
    run_pubchem_protein_search_job,
)

__all__ = [
    "obtener_CIDs_Pubchem",
    "run_pubchem_protein_search",
    "run_pubchem_protein_search_job",
    "fetch_pubchem_assay_activity",
]


def __getattr__(name):
    return getattr(_service, name)
