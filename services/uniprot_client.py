# SPDX-License-Identifier: LGPL-3.0-or-later
"""Small UniProt REST client for reviewed gene-target resolution."""
from dataclasses import dataclass

import requests


UNIPROT_SEARCH_URL = "https://rest.uniprot.org/uniprotkb/search"
REVIEWED_ENTRY_TYPE = "UniProtKB reviewed (Swiss-Prot)"
DEFAULT_TIMEOUT_SECONDS = 20.0
SEARCH_FIELDS = (
    "accession,id,gene_names,organism_name,organism_id,reviewed,protein_name"
)


class UniProtClientError(RuntimeError):
    """Raised when UniProt cannot return a valid search response."""


@dataclass(frozen=True)
class UniProtEntry:
    accession: str
    entry_name: str
    organism_id: int
    organism_name: str
    common_name: str | None
    primary_gene_symbols: tuple[str, ...]
    protein_name: str
    reviewed: bool


def _text(value, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise UniProtClientError(
            f"UniProt response is missing required field '{field_name}'."
        )
    return value.strip()


def _protein_name(payload: dict, entry_name: str) -> str:
    description = payload.get("proteinDescription")
    if isinstance(description, dict):
        recommended = description.get("recommendedName")
        if isinstance(recommended, dict):
            full_name = recommended.get("fullName")
            if isinstance(full_name, dict):
                value = full_name.get("value")
                if isinstance(value, str) and value.strip():
                    return value.strip()
        submissions = description.get("submissionNames")
        if isinstance(submissions, list):
            for submission in submissions:
                if not isinstance(submission, dict):
                    continue
                full_name = submission.get("fullName")
                if not isinstance(full_name, dict):
                    continue
                value = full_name.get("value")
                if isinstance(value, str) and value.strip():
                    return value.strip()
    return entry_name


def _parse_entry(payload) -> UniProtEntry:
    if not isinstance(payload, dict):
        raise UniProtClientError("UniProt returned an invalid entry payload.")

    organism = payload.get("organism")
    if not isinstance(organism, dict):
        raise UniProtClientError(
            "UniProt response is missing required field 'organism'."
        )
    organism_id = organism.get("taxonId")
    if isinstance(organism_id, bool) or not isinstance(organism_id, int):
        raise UniProtClientError(
            "UniProt response is missing required field 'organism.taxonId'."
        )

    primary_gene_symbols = []
    genes = payload.get("genes", [])
    if not isinstance(genes, list):
        raise UniProtClientError("UniProt returned an invalid genes payload.")
    for gene in genes:
        if not isinstance(gene, dict):
            continue
        gene_name = gene.get("geneName")
        if not isinstance(gene_name, dict):
            continue
        value = gene_name.get("value")
        if isinstance(value, str) and value.strip():
            primary_gene_symbols.append(value.strip())

    entry_name = _text(payload.get("uniProtkbId"), "uniProtkbId")
    entry_type = _text(payload.get("entryType"), "entryType")
    return UniProtEntry(
        accession=_text(
            payload.get("primaryAccession"),
            "primaryAccession",
        ),
        entry_name=entry_name,
        organism_id=organism_id,
        organism_name=_text(
            organism.get("scientificName"),
            "organism.scientificName",
        ),
        common_name=(
            organism.get("commonName").strip()
            if isinstance(organism.get("commonName"), str)
            and organism.get("commonName").strip()
            else None
        ),
        primary_gene_symbols=tuple(primary_gene_symbols),
        protein_name=_protein_name(payload, entry_name),
        reviewed=entry_type == REVIEWED_ENTRY_TYPE,
    )


class UniProtClient:
    def __init__(
        self,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        session: requests.Session | None = None,
    ):
        self.timeout = timeout
        self.session = session or requests.Session()

    def search_reviewed_gene_entries(
        self,
        gene_symbol: str,
        organism_id: int,
    ) -> tuple[UniProtEntry, ...]:
        query = (
            f"(gene_exact:{gene_symbol}) AND "
            f"(organism_id:{organism_id}) AND (reviewed:true)"
        )
        try:
            response = self.session.get(
                UNIPROT_SEARCH_URL,
                params={
                    "query": query,
                    "format": "json",
                    "fields": SEARCH_FIELDS,
                    "size": 100,
                },
                headers={"Accept": "application/json"},
                timeout=self.timeout,
            )
        except requests.RequestException as error:
            raise UniProtClientError(
                f"UniProt request failed: {error}"
            ) from error

        try:
            response.raise_for_status()
        except requests.HTTPError as error:
            raise UniProtClientError(
                "UniProt request returned HTTP "
                f"{response.status_code}."
            ) from error

        try:
            payload = response.json()
        except ValueError as error:
            raise UniProtClientError(
                "UniProt returned an invalid JSON response."
            ) from error
        if not isinstance(payload, dict) or not isinstance(
            payload.get("results"), list
        ):
            raise UniProtClientError(
                "UniProt returned an invalid search response."
            )
        return tuple(_parse_entry(entry) for entry in payload["results"])
