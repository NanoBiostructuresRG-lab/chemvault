# SPDX-License-Identifier: LGPL-3.0-or-later
"""Application contract for singular gene-to-UniProt resolution."""
from dataclasses import dataclass
import re

from services.uniprot_client import UniProtClient


_GENE_SYMBOL_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class InvalidGeneSymbolError(ValueError):
    """Raised when a gene symbol cannot be used safely and deterministically."""


class InvalidOrganismIdError(ValueError):
    """Raised when an organism identifier is not a positive integer."""


class UnsupportedOrganismError(ValueError):
    """Raised when the architecture supports an organism not yet enabled."""


class ProteinIdentifierNotFoundError(LookupError):
    """Raised when no reviewed primary-gene match exists."""


class AmbiguousProteinIdentifierError(RuntimeError):
    """Raised when several reviewed primary-gene matches remain."""


@dataclass(frozen=True)
class SupportedOrganism:
    organism_id: int
    scientific_name: str
    common_name: str


@dataclass(frozen=True)
class ProteinIdentifierResolution:
    gene_symbol: str
    organism_id: int
    organism_name: str
    common_name: str
    accession: str
    entry_name: str
    protein_name: str
    reviewed: bool


SUPPORTED_ORGANISMS = {
    9606: SupportedOrganism(
        organism_id=9606,
        scientific_name="Homo sapiens",
        common_name="Human",
    ),
}


def list_supported_organisms() -> tuple[SupportedOrganism, ...]:
    """Return the enabled catalog in deterministic taxonomy-id order."""
    return tuple(
        SUPPORTED_ORGANISMS[organism_id]
        for organism_id in sorted(SUPPORTED_ORGANISMS)
    )


def _normalize_gene_symbol(gene_symbol) -> str:
    if not isinstance(gene_symbol, str):
        raise InvalidGeneSymbolError("Gene symbol must be a string.")
    normalized = gene_symbol.strip().upper()
    if not normalized or not _GENE_SYMBOL_PATTERN.fullmatch(normalized):
        raise InvalidGeneSymbolError(
            "Gene symbol must contain only letters, numbers, '.', '_' or '-'."
        )
    return normalized


def _supported_organism(organism_id) -> SupportedOrganism:
    if (
        isinstance(organism_id, bool)
        or not isinstance(organism_id, int)
        or organism_id <= 0
    ):
        raise InvalidOrganismIdError(
            "Organism ID must be a positive NCBI taxonomy integer."
        )
    organism = SUPPORTED_ORGANISMS.get(organism_id)
    if organism is None:
        supported = ", ".join(
            f"{item.scientific_name} ({item.organism_id})"
            for item in list_supported_organisms()
        )
        raise UnsupportedOrganismError(
            f"Organism {organism_id} is not supported by this CHEMVAULT "
            f"version. Supported organisms: {supported}."
        )
    return organism


def resolve_gene_symbol(
    gene_symbol,
    organism_id,
    *,
    client: UniProtClient | None = None,
) -> ProteinIdentifierResolution:
    """Resolve one exact primary gene symbol to one reviewed UniProt entry."""
    normalized = _normalize_gene_symbol(gene_symbol)
    organism = _supported_organism(organism_id)
    entries = (client or UniProtClient()).search_reviewed_gene_entries(
        normalized,
        organism.organism_id,
    )

    matches_by_accession = {}
    for entry in entries:
        if not entry.reviewed or entry.organism_id != organism.organism_id:
            continue
        primary_symbols = {
            symbol.strip().upper()
            for symbol in entry.primary_gene_symbols
            if isinstance(symbol, str) and symbol.strip()
        }
        if normalized in primary_symbols:
            matches_by_accession[entry.accession] = entry

    matches = tuple(
        matches_by_accession[accession]
        for accession in sorted(matches_by_accession)
    )
    if not matches:
        raise ProteinIdentifierNotFoundError(
            "No reviewed UniProt entry with primary gene symbol "
            f"'{normalized}' was found in {organism.scientific_name} "
            f"({organism.organism_id})."
        )
    if len(matches) > 1:
        accessions = ", ".join(entry.accession for entry in matches)
        raise AmbiguousProteinIdentifierError(
            "More than one reviewed UniProt entry has primary gene symbol "
            f"'{normalized}' in {organism.scientific_name} "
            f"({organism.organism_id}): {accessions}."
        )

    match = matches[0]
    return ProteinIdentifierResolution(
        gene_symbol=normalized,
        organism_id=organism.organism_id,
        organism_name=organism.scientific_name,
        common_name=organism.common_name,
        accession=match.accession,
        entry_name=match.entry_name,
        protein_name=match.protein_name,
        reviewed=True,
    )


def supported_organisms_from_payload(payload) -> tuple[SupportedOrganism, ...]:
    if not isinstance(payload, dict) or not isinstance(
        payload.get("organisms"), list
    ):
        raise ValueError("Invalid supported-organisms payload.")
    try:
        return tuple(
            SupportedOrganism(**organism)
            for organism in payload["organisms"]
        )
    except (TypeError, ValueError) as error:
        raise ValueError("Invalid supported-organisms payload.") from error


def protein_identifier_resolution_from_payload(
    payload,
) -> ProteinIdentifierResolution:
    if not isinstance(payload, dict):
        raise ValueError("Invalid UniProt resolution payload.")
    try:
        return ProteinIdentifierResolution(**payload)
    except (TypeError, ValueError) as error:
        raise ValueError("Invalid UniProt resolution payload.") from error
