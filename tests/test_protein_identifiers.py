# SPDX-License-Identifier: LGPL-3.0-or-later
import pytest

from application import protein_identifiers
from services.uniprot_client import UniProtEntry


def _entry(
    accession="P48357",
    *,
    primary_gene_symbols=("LEPR",),
    organism_id=9606,
    organism_name="Homo sapiens",
    common_name="Human",
    entry_name=None,
    protein_name="Leptin receptor",
    reviewed=True,
):
    return UniProtEntry(
        accession=accession,
        entry_name=(
            entry_name or f"{primary_gene_symbols[0]}_HUMAN"
        ),
        organism_id=organism_id,
        organism_name=organism_name,
        common_name=common_name,
        primary_gene_symbols=primary_gene_symbols,
        protein_name=protein_name,
        reviewed=reviewed,
    )


class StubClient:
    def __init__(self, entries):
        self.entries = tuple(entries)
        self.calls = []

    def search_reviewed_gene_entries(self, gene_symbol, organism_id):
        self.calls.append((gene_symbol, organism_id))
        return self.entries


def test_supported_organism_catalog_is_curated_and_human_first():
    organisms = protein_identifiers.list_supported_organisms()

    assert organisms == (
        protein_identifiers.SupportedOrganism(
            organism_id=9606,
            scientific_name="Homo sapiens",
            common_name="Human",
        ),
        protein_identifiers.SupportedOrganism(
            organism_id=10090,
            scientific_name="Mus musculus",
            common_name="Mouse",
        ),
        protein_identifiers.SupportedOrganism(
            organism_id=10116,
            scientific_name="Rattus norvegicus",
            common_name="Rat",
        ),
        protein_identifiers.SupportedOrganism(
            organism_id=9986,
            scientific_name="Oryctolagus cuniculus",
            common_name="Rabbit",
        ),
        protein_identifiers.SupportedOrganism(
            organism_id=10036,
            scientific_name="Mesocricetus auratus",
            common_name="Golden hamster",
        ),
    )
    assert protein_identifiers.DEFAULT_ORGANISM_ID == 9606
    assert organisms[0].organism_id == protein_identifiers.DEFAULT_ORGANISM_ID
    assert len({organism.organism_id for organism in organisms}) == len(
        organisms
    )


@pytest.mark.parametrize(
    ("organism_id", "scientific_name", "common_name"),
    [
        (9606, "Homo sapiens", "Human"),
        (10090, "Mus musculus", "Mouse"),
        (10116, "Rattus norvegicus", "Rat"),
        (9986, "Oryctolagus cuniculus", "Rabbit"),
        (10036, "Mesocricetus auratus", "Golden hamster"),
    ],
)
def test_resolver_uses_curated_metadata_for_each_supported_organism(
    organism_id,
    scientific_name,
    common_name,
):
    client = StubClient(
        [
            _entry(
                organism_id=organism_id,
                organism_name="Ignored UniProt organism",
                common_name=None,
                entry_name="LEPR_TEST",
            )
        ]
    )

    result = protein_identifiers.resolve_gene_symbol(
        "lepr",
        organism_id,
        client=client,
    )

    assert result.organism_id == organism_id
    assert result.organism_name == scientific_name
    assert result.common_name == common_name
    assert result.entry_name == "LEPR_TEST"
    assert client.calls == [("LEPR", organism_id)]


def test_resolver_selects_exact_primary_gene_and_ignores_synonym_only_match():
    client = StubClient(
        [
            _entry("O15243", primary_gene_symbols=("LEPROT",)),
            _entry("P48357", primary_gene_symbols=("LEPR",)),
        ]
    )

    result = protein_identifiers.resolve_gene_symbol(
        " lepr ",
        9606,
        client=client,
    )

    assert result == protein_identifiers.ProteinIdentifierResolution(
        gene_symbol="LEPR",
        organism_id=9606,
        organism_name="Homo sapiens",
        common_name="Human",
        accession="P48357",
        entry_name="LEPR_HUMAN",
        protein_name="Leptin receptor",
        reviewed=True,
    )
    assert client.calls == [("LEPR", 9606)]


def test_resolver_rejects_unreviewed_or_wrong_organism_entries():
    client = StubClient(
        [
            _entry("A0A000", reviewed=False),
            _entry("P48358", organism_id=10090),
        ]
    )

    with pytest.raises(protein_identifiers.ProteinIdentifierNotFoundError):
        protein_identifiers.resolve_gene_symbol(
            "LEPR",
            9606,
            client=client,
        )


def test_resolver_reports_ambiguous_primary_matches():
    client = StubClient([_entry("P48357"), _entry("Q99999")])

    with pytest.raises(
        protein_identifiers.AmbiguousProteinIdentifierError,
        match="P48357, Q99999",
    ):
        protein_identifiers.resolve_gene_symbol(
            "LEPR",
            9606,
            client=client,
        )


@pytest.mark.parametrize("gene_symbol", ["", "LEPR OR reviewed:true", 123])
def test_resolver_rejects_invalid_gene_symbols_before_network(gene_symbol):
    client = StubClient([_entry()])

    with pytest.raises(protein_identifiers.InvalidGeneSymbolError):
        protein_identifiers.resolve_gene_symbol(
            gene_symbol,
            9606,
            client=client,
        )

    assert client.calls == []


@pytest.mark.parametrize("organism_id", [True, 0, -1, "9606"])
def test_resolver_rejects_invalid_organism_ids_before_network(organism_id):
    client = StubClient([_entry()])

    with pytest.raises(protein_identifiers.InvalidOrganismIdError):
        protein_identifiers.resolve_gene_symbol(
            "LEPR",
            organism_id,
            client=client,
        )

    assert client.calls == []


def test_resolver_rejects_valid_but_unsupported_organism_before_network():
    client = StubClient([_entry(organism_id=9913)])

    with pytest.raises(
        protein_identifiers.UnsupportedOrganismError,
        match="Organism 9913 is not supported",
    ):
        protein_identifiers.resolve_gene_symbol(
            "LEPR",
            9913,
            client=client,
        )

    assert client.calls == []


def test_http_payload_adapters_preserve_application_contracts():
    organisms = protein_identifiers.supported_organisms_from_payload(
        {
            "organisms": [
                {
                    "organism_id": 9606,
                    "scientific_name": "Homo sapiens",
                    "common_name": "Human",
                },
                {
                    "organism_id": 10090,
                    "scientific_name": "Mus musculus",
                    "common_name": "Mouse",
                },
                {
                    "organism_id": 10116,
                    "scientific_name": "Rattus norvegicus",
                    "common_name": "Rat",
                },
                {
                    "organism_id": 9986,
                    "scientific_name": "Oryctolagus cuniculus",
                    "common_name": "Rabbit",
                },
                {
                    "organism_id": 10036,
                    "scientific_name": "Mesocricetus auratus",
                    "common_name": "Golden hamster",
                },
            ]
        }
    )
    resolution = protein_identifiers.protein_identifier_resolution_from_payload(
        {
            "gene_symbol": "LEPR",
            "organism_id": 9606,
            "organism_name": "Homo sapiens",
            "common_name": "Human",
            "accession": "P48357",
            "entry_name": "LEPR_HUMAN",
            "protein_name": "Leptin receptor",
            "reviewed": True,
        }
    )

    assert organisms == protein_identifiers.list_supported_organisms()
    assert resolution.accession == "P48357"
