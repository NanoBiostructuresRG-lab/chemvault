# SPDX-License-Identifier: LGPL-3.0-or-later
import json

import pytest

from application.target_identity import (
    GENE_SYMBOL_INPUT_MODE,
    TARGET_IDENTITY_ARTIFACT_CONTRACT,
    TARGET_IDENTITY_ARTIFACT_VERSION,
    UNIPROT_ACCESSION_INPUT_MODE,
    InvalidTargetIdentityError,
    target_identity_from_notes,
    target_identity_from_payload,
    target_identity_notes,
)


GENE_TARGET = {
    "input_mode": "gene_symbol",
    "gene_symbol": " mc4r ",
    "organism_id": 9606,
    "organism_name": "Homo sapiens",
    "common_name": "Human",
    "uniprot_accession": " p32245 ",
    "uniprot_entry_name": "MC4R_HUMAN",
    "protein_name": "Melanocortin receptor 4",
    "reviewed": True,
}


def test_gene_target_identity_is_normalized_and_round_trips_through_notes():
    identity = target_identity_from_payload(
        GENE_TARGET,
        expected_accession="P32245",
    )

    assert identity.input_mode == GENE_SYMBOL_INPUT_MODE
    assert identity.gene_symbol == "MC4R"
    assert identity.uniprot_accession == "P32245"
    assert identity.organism_id == 9606
    assert identity.reviewed is True

    notes = target_identity_notes(identity)
    persisted = json.loads(notes)
    assert persisted["artifact_contract"] == TARGET_IDENTITY_ARTIFACT_CONTRACT
    assert persisted["version"] == TARGET_IDENTITY_ARTIFACT_VERSION
    assert target_identity_from_notes(notes) == identity


def test_direct_accession_identity_does_not_infer_gene_or_organism():
    identity = target_identity_from_payload(
        {
            "input_mode": "uniprot_accession",
            "uniprot_accession": "p32245",
        },
        expected_accession="P32245",
    )

    assert identity.input_mode == UNIPROT_ACCESSION_INPUT_MODE
    assert identity.uniprot_accession == "P32245"
    assert identity.gene_symbol is None
    assert identity.organism_id is None
    assert identity.protein_name is None


@pytest.mark.parametrize(
    "payload",
    [
        {
            **GENE_TARGET,
            "uniprot_accession": "P48357",
        },
        {
            "input_mode": "uniprot_accession",
            "uniprot_accession": "P32245",
            "gene_symbol": "MC4R",
        },
        {
            **GENE_TARGET,
            "organism_id": 0,
        },
        {
            **GENE_TARGET,
            "reviewed": "yes",
        },
        {
            **GENE_TARGET,
            "unexpected": "value",
        },
    ],
)
def test_invalid_target_identity_is_rejected(payload):
    with pytest.raises(InvalidTargetIdentityError):
        target_identity_from_payload(
            payload,
            expected_accession="P32245",
        )


@pytest.mark.parametrize(
    "notes",
    [
        None,
        "",
        "Initial table created from selected proteins.",
        "{}",
        '{"artifact_contract":"other","version":1}',
        (
            '{"artifact_contract":"protein_search_target_identity",'
            '"version":99,"target_identity":{}}'
        ),
    ],
)
def test_legacy_or_unrelated_notes_do_not_create_identity(notes):
    assert target_identity_from_notes(notes) is None
