# SPDX-License-Identifier: LGPL-3.0-or-later
import requests
import pytest

from services.uniprot_client import (
    REVIEWED_ENTRY_TYPE,
    UNIPROT_SEARCH_URL,
    UniProtClient,
    UniProtClientError,
)


class StubResponse:
    def __init__(self, payload, status_code=200, json_error=None):
        self._payload = payload
        self.status_code = status_code
        self._json_error = json_error

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        if self._json_error is not None:
            raise self._json_error
        return self._payload


class StubSession:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.error is not None:
            raise self.error
        return self.response


def _entry_payload(
    *,
    accession="P48357",
    entry_name="LEPR_HUMAN",
    primary_gene="LEPR",
    synonyms=None,
    organism_id=9606,
    entry_type=REVIEWED_ENTRY_TYPE,
):
    return {
        "entryType": entry_type,
        "primaryAccession": accession,
        "uniProtkbId": entry_name,
        "organism": {
            "scientificName": "Homo sapiens",
            "commonName": "Human",
            "taxonId": organism_id,
        },
        "genes": [
            {
                "geneName": {"value": primary_gene},
                "synonyms": [
                    {"value": synonym}
                    for synonym in (synonyms or [])
                ],
            }
        ],
        "proteinDescription": {
            "recommendedName": {
                "fullName": {"value": "Leptin receptor"}
            }
        },
    }


def test_client_queries_reviewed_gene_entries_and_parses_primary_names():
    session = StubSession(
        StubResponse(
            {
                "results": [
                    _entry_payload(
                        accession="O15243",
                        entry_name="OBRG_HUMAN",
                        primary_gene="LEPROT",
                        synonyms=["LEPR"],
                    ),
                    _entry_payload(),
                ]
            }
        )
    )

    entries = UniProtClient(timeout=7.5, session=session).search_reviewed_gene_entries(
        "LEPR",
        9606,
    )

    assert [entry.accession for entry in entries] == ["O15243", "P48357"]
    assert entries[0].primary_gene_symbols == ("LEPROT",)
    assert entries[1].primary_gene_symbols == ("LEPR",)
    assert entries[1].protein_name == "Leptin receptor"
    assert entries[1].reviewed is True
    assert session.calls == [
        (
            UNIPROT_SEARCH_URL,
            {
                "params": {
                    "query": (
                        "(gene_exact:LEPR) AND (organism_id:9606) "
                        "AND (reviewed:true)"
                    ),
                    "format": "json",
                    "fields": (
                        "accession,id,gene_names,organism_name,"
                        "organism_id,reviewed,protein_name"
                    ),
                    "size": 100,
                },
                "headers": {"Accept": "application/json"},
                "timeout": 7.5,
            },
        )
    ]


def test_client_marks_unreviewed_payload_without_trusting_query_filter():
    session = StubSession(
        StubResponse(
            {
                "results": [
                    _entry_payload(entry_type="UniProtKB unreviewed (TrEMBL)")
                ]
            }
        )
    )

    entries = UniProtClient(session=session).search_reviewed_gene_entries(
        "LEPR",
        9606,
    )

    assert entries[0].reviewed is False


@pytest.mark.parametrize(
    "response",
    [
        StubResponse({}, status_code=503),
        StubResponse(None, json_error=ValueError("invalid json")),
        StubResponse({"unexpected": []}),
    ],
)
def test_client_rejects_http_or_invalid_responses(response):
    with pytest.raises(UniProtClientError):
        UniProtClient(session=StubSession(response)).search_reviewed_gene_entries(
            "LEPR",
            9606,
        )


def test_client_converts_transport_errors():
    session = StubSession(error=requests.Timeout("request timed out"))

    with pytest.raises(UniProtClientError, match="request timed out"):
        UniProtClient(session=session).search_reviewed_gene_entries(
            "LEPR",
            9606,
        )
