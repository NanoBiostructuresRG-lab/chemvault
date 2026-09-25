# SPDX-License-Identifier: LGPL-3.0-or-later
import sqlite3

import pytest

from services import pubchem_protein_search as pubchem_search
from services.job_store import JobStore
from services.pubchem_aid_completeness import certify_aid_completeness
from services.pubchem_protein_search import _JobTrackingProgress


def _source(status="success", aids=None):
    return [
        {
            "protein": "P12345",
            "status": status,
            "aids": list(aids or []),
        }
    ]


def _evidence(
    *,
    aid="101",
    cid_status="success",
    cid_count=1,
    activity_status="success",
    attribution="assay_level_fallback",
    scoped_cid_count=1,
):
    return [
        {
            "protein": "P12345",
            "aid": aid,
            "cid_collection_status": cid_status,
            "cid_count": cid_count,
            "activity_retrieval_status": activity_status,
            "target_attribution": attribution,
            "scoped_cid_count": scoped_cid_count,
        }
    ]


def test_target_to_aid_failure_prevents_certification():
    result = certify_aid_completeness(
        source_enumeration=_source(
            status="failed",
            aids=[],
        ),
        requested_proteins=["P12345"],
        aid_evidence=[],
        persisted_pairs=set(),
    )

    assert result["source_enumeration_succeeded"] is False
    assert result["certified_complete"] is False
    assert result["reason"] == "source_enumeration_failed"
    assert result["counts"]["source_observed"] is None


def test_aid_to_cid_failure_is_unresolved_and_not_certified():
    result = certify_aid_completeness(
        source_enumeration=_source(aids=["101"]),
        requested_proteins=["P12345"],
        aid_evidence=_evidence(
            cid_status="failed",
            cid_count=0,
            activity_status="not_attempted",
            attribution="not_evaluated",
            scoped_cid_count=0,
        ),
        persisted_pairs=set(),
    )

    assert result["certified_complete"] is False
    assert result["counts"]["source_observed"] == 1
    assert result["counts"]["unresolved"] == 1
    assert result["unresolved"] == [
        {"protein": "P12345", "aid": "101"}
    ]


def test_activity_failure_is_unresolved_and_not_certified():
    result = certify_aid_completeness(
        source_enumeration=_source(aids=["101"]),
        requested_proteins=["P12345"],
        aid_evidence=_evidence(
            cid_status="success",
            cid_count=1,
            activity_status="failed",
            attribution="not_evaluated",
            scoped_cid_count=0,
        ),
        persisted_pairs=set(),
    )

    assert result["certified_complete"] is False
    assert result["counts"]["unresolved"] == 1
    assert result["terminal"] == []
    assert result["excluded_b1"] == []


def test_row_level_zero_matches_is_exactly_b1_exclusion_and_can_certify():
    result = certify_aid_completeness(
        source_enumeration=_source(aids=["101"]),
        requested_proteins=["P12345"],
        aid_evidence=_evidence(
            cid_status="success",
            cid_count=3,
            activity_status="success",
            attribution="row_level_zero_matches",
            scoped_cid_count=0,
        ),
        persisted_pairs=set(),
    )

    assert result["certified_complete"] is True
    assert result["terminal"] == []
    assert result["excluded_b1"] == [
        {"protein": "P12345", "aid": "101"}
    ]
    assert result["unresolved"] == []
    assert result["counts"]["excluded_b1"] == 1


def test_assay_level_fallback_is_terminal_and_not_b1_exclusion():
    result = certify_aid_completeness(
        source_enumeration=_source(aids=["101"]),
        requested_proteins=["P12345"],
        aid_evidence=_evidence(
            cid_status="success",
            cid_count=2,
            activity_status="success",
            attribution="assay_level_fallback",
            scoped_cid_count=2,
        ),
        persisted_pairs={("P12345", "101")},
    )

    assert result["certified_complete"] is True
    assert result["terminal"] == [
        {"protein": "P12345", "aid": "101"}
    ]
    assert result["excluded_b1"] == []
    assert result["unresolved"] == []


def test_source_enumeration_is_preserved_exactly_across_later_metadata_updates():
    connection = sqlite3.connect(":memory:")
    store = JobStore(connection)
    job = store.create_job(
        job_id="aid-source-preservation",
        metadata={"source": "test"},
    )
    store.start_job(job.job_id)

    progress = _JobTrackingProgress(
        None,
        store,
        job.job_id,
    )
    progress.set_stage("aid_search")

    source_enumeration = [
        {
            "protein": "P12345",
            "status": "success",
            "aids": ["101", "202"],
        }
    ]

    progress.persist_source_enumeration(source_enumeration)

    before = store.get_job(job.job_id).metadata[
        "aid_completeness"
    ]["source_enumeration"]

    progress.merge_aid_completeness(
        {
            "aids": [
                {
                    "protein": "P12345",
                    "aid": "101",
                    "cid_collection_status": "success",
                }
            ]
        }
    )

    after = store.get_job(job.job_id).metadata[
        "aid_completeness"
    ]["source_enumeration"]

    assert before == source_enumeration
    assert after == source_enumeration
    assert {
        (item["protein"], aid)
        for item in before
        for aid in item["aids"]
    } == {
        (item["protein"], aid)
        for item in after
        for aid in item["aids"]
    }

    with pytest.raises(
        ValueError,
        match="source_enumeration",
    ):
        progress.merge_aid_completeness(
            {"source_enumeration": []}
        )


@pytest.mark.parametrize(
    "source_enumeration",
    [
        None,
        [{"protein": "P12345", "status": "success"}],
    ],
)
def test_missing_or_corrupt_source_never_reconstructs_denominator(
    source_enumeration,
):
    result = certify_aid_completeness(
        source_enumeration=source_enumeration,
        requested_proteins=["P12345"],
        aid_evidence=_evidence(),
        persisted_pairs={("P12345", "101")},
    )

    assert result["source_enumeration_succeeded"] is False
    assert result["certified_complete"] is False
    assert result["counts"]["source_observed"] is None
    assert result["terminal"] == []
    assert result["excluded_b1"] == []
    assert result["unresolved"] == []


def test_valid_empty_source_can_certify_but_absent_source_cannot():
    empty_result = certify_aid_completeness(
        source_enumeration=_source(aids=[]),
        requested_proteins=["P12345"],
        aid_evidence=[],
        persisted_pairs=set(),
    )

    absent_result = certify_aid_completeness(
        source_enumeration=None,
        requested_proteins=["P12345"],
        aid_evidence=[],
        persisted_pairs=set(),
    )

    assert empty_result["source_enumeration_succeeded"] is True
    assert empty_result["certified_complete"] is True
    assert empty_result["counts"]["source_observed"] == 0
    assert empty_result["counts"]["terminal"] == 0
    assert empty_result["counts"]["excluded_b1"] == 0
    assert empty_result["counts"]["unresolved"] == 0

    assert absent_result["source_enumeration_succeeded"] is False
    assert absent_result["certified_complete"] is False
    assert absent_result["counts"]["source_observed"] is None

def _workflow_connection():
    connection = sqlite3.connect(":memory:")
    connection.execute(
        "CREATE TABLE main (primary_id INTEGER PRIMARY KEY AUTOINCREMENT)"
    )
    return connection


def _patch_basic_pubchem_acquisition(monkeypatch):
    monkeypatch.setattr(
        pubchem_search,
        "_fetch_aids_for_protein",
        lambda protein: [101],
    )
    monkeypatch.setattr(
        pubchem_search,
        "fetch_cids_for_aid_batch",
        lambda aids: {
            "InformationList": {
                "Information": [
                    {
                        "AID": 101,
                        "CID": [202],
                    }
                ]
            }
        },
    )
    monkeypatch.setattr(
        pubchem_search,
        "fetch_compound_titles_for_cid_batch",
        lambda cids: {
            "PropertyTable": {
                "Properties": [
                    {
                        "CID": 202,
                        "Title": "Completeness test compound",
                    }
                ]
            }
        },
    )


def test_workflow_certifies_assay_level_fallback(monkeypatch):
    connection = _workflow_connection()
    store = JobStore(connection)
    _patch_basic_pubchem_acquisition(monkeypatch)

    def fake_activity_enrichment(
        connection,
        aid_jobs,
        activity_fetcher,
        progress_callback=None,
        **kwargs,
    ):
        assert aid_jobs == [
            {
                "protein": "P12345",
                "aid": "101",
                "cids": ["202"],
            }
        ]

        if progress_callback is not None:
            progress_callback(
                {
                    "total_aids": 1,
                    "processed_aids": 1,
                }
            )

        return {
            "successful_cid_values": ["202"],
            "failed_job_diagnostics": [],
            "target_scoped_jobs": [
                {
                    "protein": "P12345",
                    "aid": "101",
                    "cids": ["202"],
                    "target_column_present": False,
                }
            ],
        }

    monkeypatch.setattr(
        pubchem_search,
        "run_pubchem_activity_enrichment",
        fake_activity_enrichment,
    )

    completed = pubchem_search.run_pubchem_protein_search_job(
        connection,
        ["P12345"],
        job_store=store,
        job_id="fallback-certification",
    )

    completeness = completed.metadata["aid_completeness"]

    assert completeness["source_enumeration"] == [
        {
            "protein": "P12345",
            "status": "success",
            "aids": ["101"],
        }
    ]
    assert completeness["source_enumeration_succeeded"] is True
    assert completeness["certified_complete"] is True
    assert completeness["counts"] == {
        "source_observed": 1,
        "terminal": 1,
        "excluded_b1": 0,
        "unresolved": 0,
        "unexpected_persisted": 0,
        "missing_materialization": 0,
    }
    assert completeness["terminal"] == [
        {
            "protein": "P12345",
            "aid": "101",
        }
    ]
    assert completeness["excluded_b1"] == []
    assert completeness["unresolved"] == []

    persisted = connection.execute(
        """
        SELECT DISTINCT Protein, AID
        FROM compound_assays
        """
    ).fetchall()

    assert persisted == [("P12345", "101")]


def test_workflow_certifies_row_level_zero_matches(monkeypatch):
    connection = _workflow_connection()
    store = JobStore(connection)
    _patch_basic_pubchem_acquisition(monkeypatch)

    def fake_activity_enrichment(
        connection,
        aid_jobs,
        activity_fetcher,
        progress_callback=None,
        **kwargs,
    ):
        assert aid_jobs == [
            {
                "protein": "P12345",
                "aid": "101",
                "cids": ["202"],
            }
        ]

        if progress_callback is not None:
            progress_callback(
                {
                    "total_aids": 1,
                    "processed_aids": 1,
                }
            )

        return {
            "successful_cid_values": [],
            "failed_job_diagnostics": [],
            "target_scoped_jobs": [
                {
                    "protein": "P12345",
                    "aid": "101",
                    "cids": [],
                    "target_column_present": True,
                }
            ],
        }

    monkeypatch.setattr(
        pubchem_search,
        "run_pubchem_activity_enrichment",
        fake_activity_enrichment,
    )

    completed = pubchem_search.run_pubchem_protein_search_job(
        connection,
        ["P12345"],
        job_store=store,
        job_id="b1-exclusion-certification",
    )

    completeness = completed.metadata["aid_completeness"]

    assert completeness["source_enumeration_succeeded"] is True
    assert completeness["certified_complete"] is True
    assert completeness["counts"] == {
        "source_observed": 1,
        "terminal": 0,
        "excluded_b1": 1,
        "unresolved": 0,
        "unexpected_persisted": 0,
        "missing_materialization": 0,
    }
    assert completeness["terminal"] == []
    assert completeness["excluded_b1"] == [
        {
            "protein": "P12345",
            "aid": "101",
        }
    ]
    assert completeness["unresolved"] == []
    assert completeness["excluded_b1_persisted"] == []

    persisted = connection.execute(
        """
        SELECT DISTINCT Protein, AID
        FROM compound_assays
        """
    ).fetchall()

    assert persisted == []

def test_workflow_does_not_attempt_activity_after_invalid_aid_to_cid(
    monkeypatch,
):
    connection = _workflow_connection()
    store = JobStore(connection)

    monkeypatch.setattr(
        pubchem_search,
        "_fetch_aids_for_protein",
        lambda protein: [101],
    )

    # PubChem explicitly returns the AID but supplies no CID field.
    # This is structurally incomplete evidence for this AID.
    monkeypatch.setattr(
        pubchem_search,
        "fetch_cids_for_aid_batch",
        lambda aids: {
            "InformationList": {
                "Information": [
                    {
                        "AID": 101,
                    }
                ]
            }
        },
    )

    activity_calls = []

    def fake_activity_enrichment(
        connection,
        aid_jobs,
        activity_fetcher,
        progress_callback=None,
        **kwargs,
    ):
        activity_calls.append(list(aid_jobs))
        assert aid_jobs == []

        return {
            "successful_cid_values": [],
            "failed_job_diagnostics": [],
            "target_scoped_jobs": [],
        }

    monkeypatch.setattr(
        pubchem_search,
        "run_pubchem_activity_enrichment",
        fake_activity_enrichment,
    )

    completed = pubchem_search.run_pubchem_protein_search_job(
        connection,
        ["P12345"],
        job_store=store,
        job_id="invalid-cid-no-activity",
    )

    completeness = completed.metadata["aid_completeness"]

    assert activity_calls == [[]]
    assert completeness["certified_complete"] is False
    assert completeness["counts"]["source_observed"] == 1
    assert completeness["counts"]["terminal"] == 0
    assert completeness["counts"]["excluded_b1"] == 0
    assert completeness["counts"]["unresolved"] == 1

    assert completeness["aids"] == [
        {
            "protein": "P12345",
            "aid": "101",
            "cid_collection_status": "invalid_response",
            "cid_count": 0,
            "activity_retrieval_status": "not_attempted",
            "target_attribution": "not_evaluated",
            "scoped_cid_count": 0,
            "classification": "unresolved",
        }
    ]

    assert completeness["unresolved"] == [
        {
            "protein": "P12345",
            "aid": "101",
        }
    ]

    persisted = connection.execute(
        """
        SELECT COUNT(*)
        FROM compound_assays
        """
    ).fetchone()[0]

    assert persisted == 0

def test_cid_collection_explicit_empty_cid_list_is_success(
    monkeypatch,
):
    monkeypatch.setattr(
        pubchem_search,
        "fetch_cids_for_aid_batch",
        lambda aids: {
            "InformationList": {
                "Information": [
                    {
                        "AID": 101,
                        "CID": [],
                    }
                ]
            }
        },
    )

    cids, results = (
        pubchem_search._fetch_cids_for_aids_with_provenance(
            ["101"]
        )
    )

    assert cids == {"101": []}
    assert results == {
        "101": {
            "status": "success",
            "cid_count": 0,
        }
    }


def test_cid_collection_omitted_aid_is_missing_in_response(
    monkeypatch,
):
    monkeypatch.setattr(
        pubchem_search,
        "fetch_cids_for_aid_batch",
        lambda aids: {
            "InformationList": {
                "Information": [
                    {
                        "AID": 101,
                        "CID": [1001],
                    }
                ]
            }
        },
    )

    cids, results = (
        pubchem_search._fetch_cids_for_aids_with_provenance(
            ["101", "202"]
        )
    )

    assert cids == {"101": ["1001"]}
    assert results["101"] == {
        "status": "success",
        "cid_count": 1,
    }
    assert results["202"] == {
        "status": "missing_in_response",
        "cid_count": 0,
    }


def test_cid_collection_batch_exception_is_failed(
    monkeypatch,
):
    def fail_fetch(aids):
        raise RuntimeError("network failure")

    monkeypatch.setattr(
        pubchem_search,
        "fetch_cids_for_aid_batch",
        fail_fetch,
    )

    cids, results = (
        pubchem_search._fetch_cids_for_aids_with_provenance(
            ["101"]
        )
    )

    assert cids == {}
    assert results["101"]["status"] == "failed"
    assert results["101"]["cid_count"] == 0
    assert results["101"]["error"] == "network failure"


def test_cid_collection_explicit_aid_without_cid_is_invalid_response(
    monkeypatch,
):
    monkeypatch.setattr(
        pubchem_search,
        "fetch_cids_for_aid_batch",
        lambda aids: {
            "InformationList": {
                "Information": [
                    {
                        "AID": 101,
                    }
                ]
            }
        },
    )

    cids, results = (
        pubchem_search._fetch_cids_for_aids_with_provenance(
            ["101"]
        )
    )

    assert cids == {}
    assert results == {
        "101": {
            "status": "invalid_response",
            "cid_count": 0,
        }
    }


def test_unexpected_persisted_identity_prevents_certification():
    result = certify_aid_completeness(
        source_enumeration=_source(aids=["101"]),
        requested_proteins=["P12345"],
        aid_evidence=_evidence(),
        persisted_pairs={
            ("P12345", "101"),
            ("P12345", "999"),
        },
    )

    assert result["certified_complete"] is False
    assert result["terminal"] == [
        {"protein": "P12345", "aid": "101"}
    ]
    assert result["unexpected_persisted"] == [
        {"protein": "P12345", "aid": "999"}
    ]
    assert result["counts"]["unexpected_persisted"] == 1


def test_missing_terminal_materialization_prevents_certification():
    result = certify_aid_completeness(
        source_enumeration=_source(aids=["101"]),
        requested_proteins=["P12345"],
        aid_evidence=_evidence(),
        persisted_pairs=set(),
    )

    assert result["certified_complete"] is False
    assert result["terminal"] == []
    assert result["missing_materialization"] == [
        {"protein": "P12345", "aid": "101"}
    ]
    assert result["unresolved"] == [
        {"protein": "P12345", "aid": "101"}
    ]
    assert result["counts"]["missing_materialization"] == 1
