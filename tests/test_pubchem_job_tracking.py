# SPDX-License-Identifier: LGPL-3.0-or-later
import sqlite3

import pytest

from services import pubchem_protein_search as pubchem_search
from services.job_models import JobStatus
from services.job_store import JobStore


class FakeProgress:
    def __init__(self):
        self.values = []

    def progress(self, value):
        self.values.append(value)


class RecordingJobStore(JobStore):
    def __init__(self, connection):
        super().__init__(connection)
        self.stages = []
        self.heartbeats = []

    def update_progress(self, job_id, stage, progress, message=None, metadata=None):
        self.stages.append((stage, progress, message))
        job = super().update_progress(
            job_id,
            stage,
            progress,
            message=message,
            metadata=metadata,
        )
        self.heartbeats.append((stage, job.last_heartbeat_at if job else ""))
        return job


def _connection():
    connection = sqlite3.connect(":memory:")
    connection.execute(
        "CREATE TABLE main (primary_id INTEGER PRIMARY KEY AUTOINCREMENT)"
    )
    return connection


def test_run_pubchem_protein_search_job_tracks_all_stages_without_http(monkeypatch):
    connection = _connection()
    store = RecordingJobStore(connection)
    progress = FakeProgress()

    monkeypatch.setattr(pubchem_search, "_fetch_aids_for_protein", lambda protein: [101])
    monkeypatch.setattr(
        pubchem_search,
        "fetch_cids_for_aid_batch",
        lambda aids: {
            "InformationList": {
                "Information": [{"AID": 101, "CID": [202]}],
            },
        },
    )
    monkeypatch.setattr(
        pubchem_search,
        "fetch_compound_titles_for_cid_batch",
        lambda cids: {
            "PropertyTable": {
                "Properties": [{"CID": 202, "Title": "Tracked compound"}],
            },
        },
    )

    def fake_activity_enrichment(
        connection,
        aid_jobs,
        activity_fetcher,
        progress_callback=None,
        **kwargs,
    ):
        progress_callback({"total_aids": 1, "processed_aids": 1})
        return {"successful_cid_values": ["202"]}

    monkeypatch.setattr(
        pubchem_search,
        "run_pubchem_activity_enrichment",
        fake_activity_enrichment,
    )

    completed = pubchem_search.run_pubchem_protein_search_job(
        connection,
        ["P12345"],
        progress,
        job_store=store,
        job_id="pubchem-job-1",
        database_id="test-db",
        metadata={"source": "test"},
    )

    expected_stages = [
        "aid_search",
        "cid_collection",
        "compound_names",
        "activity_enrichment",
        "sqlite_main_upsert",
        "compound_assays_insert",
        "completed",
    ]
    observed_stages = []
    for stage, _, _ in store.stages:
        if not observed_stages or observed_stages[-1] != stage:
            observed_stages.append(stage)

    assert observed_stages == expected_stages
    assert completed.job_id == "pubchem-job-1"
    assert completed.status == JobStatus.COMPLETED.value
    assert completed.current_stage == "completed"
    assert completed.progress == 1.0
    assert completed.started_at
    assert completed.finished_at
    assert completed.database_id == "test-db"
    assert completed.metadata == {"source": "test"}
    assert progress.values[-1] == 1.0
    assert sum(stage == "activity_enrichment" for stage, _, _ in store.stages) >= 2
    activity_heartbeats = [
        heartbeat
        for stage, heartbeat in store.heartbeats
        if stage == "activity_enrichment"
    ]
    assert len(activity_heartbeats) >= 2
    assert all(activity_heartbeats)


def test_run_pubchem_protein_search_job_marks_failure_and_reraises(monkeypatch):
    connection = _connection()
    store = JobStore(connection)

    def fail_search(*args, **kwargs):
        raise RuntimeError("unhandled PubChem failure")

    monkeypatch.setattr(pubchem_search, "_run_pubchem_protein_search", fail_search)

    with pytest.raises(RuntimeError, match="unhandled PubChem failure"):
        pubchem_search.run_pubchem_protein_search_job(
            connection,
            ["P12345"],
            job_store=store,
            job_id="pubchem-job-failed",
        )

    failed = store.get_job("pubchem-job-failed")
    assert failed.status == JobStatus.FAILED.value
    assert failed.started_at
    assert failed.finished_at
    assert failed.error_message == "unhandled PubChem failure"
