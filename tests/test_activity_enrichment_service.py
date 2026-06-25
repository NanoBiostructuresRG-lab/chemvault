# SPDX-License-Identifier: LGPL-3.0-or-later
import sqlite3
import threading

from services.activity_enrichment import (
    _fetch_with_retry,
    build_activity_jobs_from_compound_assays,
    chunk_aid_jobs,
    ensure_compound_activities_table,
    run_activity_enrichment_from_compound_assays,
    run_pubchem_activity_enrichment,
)


class FakeResponse:
    def __init__(self, status_code):
        self.status_code = status_code


class FakeHTTPError(Exception):
    def __init__(self, status_code, message="HTTP error"):
        super().__init__(message)
        self.response = FakeResponse(status_code)


def activity_payload(aid, cid, value):
    return {
        str(cid): {
            "records": [
                {
                    "CID": str(cid),
                    "AID": str(aid),
                    "Activity_Type": "Ki",
                    "Relation": "",
                    "Activity_Value": float(value),
                    "Activity_Value_Raw": str(value),
                    "Unit": "NANOMOLAR",
                    "Outcome": "Active",
                    "Source_Column": "Ki",
                    "Activity_Status": "enriched",
                    "Result_Tag": "1",
                }
            ]
        }
    }


def aid_jobs():
    return [
        {"protein": "P1", "aid": "11", "cids": ["101"]},
        {"protein": "P1", "aid": "22", "cids": ["202"]},
        {"protein": "P2", "aid": "33", "cids": ["303"]},
    ]


def test_activity_runner_processes_aids_in_chunks_and_emits_progress():
    connection = sqlite3.connect(":memory:")
    snapshots = []
    calls = []

    def fetcher(aid):
        calls.append(aid)
        return activity_payload(aid, {"11": "101", "22": "202", "33": "303"}[aid], aid)

    result = run_pubchem_activity_enrichment(
        connection,
        aid_jobs(),
        fetcher,
        chunk_size=2,
        progress_callback=snapshots.append,
    )

    assert calls == ["11", "22", "33"]
    assert result["status"] == "success"
    assert result["total_aids"] == 3
    assert result["processed_aids"] == 3
    assert result["successful_aids"] == 3
    assert result["failed_aids"] == 0
    assert result["inserted_rows"] == 3
    assert [snapshot["status"] for snapshot in snapshots] == [
        "started",
        "running",
        "chunk_completed",
        "running",
        "chunk_completed",
        "success",
    ]


def test_activity_runner_concurrent_fetch_inserts_rows_and_reports_progress():
    connection = sqlite3.connect(":memory:")
    snapshots = []
    calls = []

    def fetcher(aid):
        calls.append(aid)
        return activity_payload(aid, {"11": "101", "22": "202", "33": "303"}[aid], aid)

    result = run_pubchem_activity_enrichment(
        connection,
        aid_jobs(),
        fetcher,
        chunk_size=3,
        max_workers=3,
        progress_callback=snapshots.append,
    )

    cursor = connection.cursor()
    cursor.execute("SELECT AID, CID FROM compound_activities ORDER BY AID")

    assert set(calls) == {"11", "22", "33"}
    assert result["status"] == "success"
    assert result["processed_aids"] == 3
    assert result["successful_aids"] == 3
    assert result["failed_aids"] == 0
    assert result["inserted_rows"] == 3
    assert cursor.fetchall() == [("11", "101"), ("22", "202"), ("33", "303")]
    assert snapshots[-1]["processed_aids"] == 3
    assert snapshots[-1]["successful_aids"] == 3
    assert snapshots[-1]["failed_aids"] == 0
    assert snapshots[-1]["inserted_rows"] == 3


def test_activity_runner_inserts_rows_into_compound_activities():
    connection = sqlite3.connect(":memory:")

    run_pubchem_activity_enrichment(
        connection,
        [aid_jobs()[0]],
        lambda aid: activity_payload(aid, "101", "10"),
    )

    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT CID, AID, Protein, Activity_Type, Activity_Value, Unit, Outcome
        FROM compound_activities
        """
    )

    assert cursor.fetchall() == [
        ("101", "11", "P1", "Ki", 10.0, "NANOMOLAR", "Active")
    ]


def test_activity_runner_does_not_duplicate_rows_when_rerun():
    connection = sqlite3.connect(":memory:")
    jobs = [aid_jobs()[0]]
    fetcher = lambda aid: activity_payload(aid, "101", "10")

    first = run_pubchem_activity_enrichment(connection, jobs, fetcher)
    second = run_pubchem_activity_enrichment(connection, jobs, fetcher)

    cursor = connection.cursor()
    cursor.execute("SELECT COUNT(*) FROM compound_activities")

    assert first["inserted_rows"] == 1
    assert second["inserted_rows"] == 0
    assert cursor.fetchone() == (1,)


def test_activity_runner_continues_after_failed_aid_when_enabled():
    connection = sqlite3.connect(":memory:")

    def fetcher(aid):
        if aid == "22":
            raise RuntimeError("PubChem failed")
        return activity_payload(aid, {"11": "101", "33": "303"}[aid], aid)

    result = run_pubchem_activity_enrichment(
        connection,
        aid_jobs(),
        fetcher,
        chunk_size=1,
        continue_on_error=True,
    )

    cursor = connection.cursor()
    cursor.execute("SELECT AID, CID FROM compound_activities ORDER BY AID")

    assert result["status"] == "success"
    assert result["processed_aids"] == 3
    assert result["successful_aids"] == 2
    assert result["failed_aids"] == 1
    assert result["failed_aid_values"] == ["22"]
    assert cursor.fetchall() == [("11", "101"), ("33", "303")]


def test_activity_runner_concurrent_fetch_continues_after_failed_aid_when_enabled():
    connection = sqlite3.connect(":memory:")

    def fetcher(aid):
        if aid == "22":
            raise RuntimeError("PubChem failed")
        return activity_payload(aid, {"11": "101", "33": "303"}[aid], aid)

    result = run_pubchem_activity_enrichment(
        connection,
        aid_jobs(),
        fetcher,
        chunk_size=3,
        max_workers=3,
        continue_on_error=True,
    )

    cursor = connection.cursor()
    cursor.execute("SELECT AID, CID FROM compound_activities ORDER BY AID")

    assert result["status"] == "success"
    assert result["processed_aids"] == 3
    assert result["successful_aids"] == 2
    assert result["failed_aids"] == 1
    assert result["failed_aid_values"] == ["22"]
    assert cursor.fetchall() == [("11", "101"), ("33", "303")]


def test_activity_runner_stops_on_failed_aid_when_disabled():
    connection = sqlite3.connect(":memory:")
    snapshots = []

    def fetcher(aid):
        if aid == "22":
            raise RuntimeError("PubChem failed")
        return activity_payload(aid, "101", "10")

    result = run_pubchem_activity_enrichment(
        connection,
        aid_jobs()[:2],
        fetcher,
        chunk_size=2,
        progress_callback=snapshots.append,
        continue_on_error=False,
    )

    cursor = connection.cursor()
    cursor.execute("SELECT AID, CID FROM compound_activities")

    assert result["status"] == "failed"
    assert result["processed_aids"] == 2
    assert result["successful_aids"] == 1
    assert result["failed_aids"] == 1
    assert result["error_message"] == "PubChem failed"
    assert cursor.fetchall() == [("11", "101")]
    assert snapshots[-1]["status"] == "failed"


def test_activity_runner_concurrent_fetch_stops_submitting_after_failure_when_disabled():
    connection = sqlite3.connect(":memory:")
    calls = []
    calls_lock = threading.Lock()
    release_second_aid = threading.Event()
    jobs = [
        {"protein": "P1", "aid": "11", "cids": ["101"]},
        {"protein": "P1", "aid": "22", "cids": ["202"]},
        {"protein": "P1", "aid": "33", "cids": ["303"]},
        {"protein": "P1", "aid": "44", "cids": ["404"]},
    ]

    def fetcher(aid):
        with calls_lock:
            calls.append(aid)
        if aid == "11":
            raise RuntimeError("PubChem failed")
        if aid == "22":
            release_second_aid.wait(timeout=0.1)
        return activity_payload(aid, {"22": "202", "33": "303", "44": "404"}[aid], aid)

    result = run_pubchem_activity_enrichment(
        connection,
        jobs,
        fetcher,
        chunk_size=4,
        max_workers=2,
        continue_on_error=False,
    )
    release_second_aid.set()

    cursor = connection.cursor()
    cursor.execute("SELECT AID, CID FROM compound_activities ORDER BY AID")

    assert result["status"] == "failed"
    assert result["failed_aid_values"] == ["11"]
    assert "33" not in calls
    assert "44" not in calls
    assert cursor.fetchall() in ([], [("22", "202")])


def test_activity_runner_rate_limiter_uses_global_start_spacing(monkeypatch):
    connection = sqlite3.connect(":memory:")
    monotonic_value = {"value": 0.0}
    sleep_calls = []

    def fake_monotonic():
        return monotonic_value["value"]

    def fake_sleep(delay):
        sleep_calls.append(delay)
        monotonic_value["value"] += delay

    activity_time = run_pubchem_activity_enrichment.__globals__["time"]
    monkeypatch.setattr(activity_time, "monotonic", fake_monotonic)
    monkeypatch.setattr(activity_time, "sleep", fake_sleep)

    run_pubchem_activity_enrichment(
        connection,
        aid_jobs()[:2],
        lambda aid: activity_payload(aid, {"11": "101", "22": "202"}[aid], aid),
        chunk_size=2,
        max_workers=2,
        rate_limit_per_second=2,
    )

    assert sleep_calls == [0.5]


def test_fetch_with_retry_retries_http_503_once_then_succeeds():
    calls = []
    sleeps = []

    def fetcher(aid):
        calls.append(aid)
        if len(calls) == 1:
            raise FakeHTTPError(503, "ServerBusy")
        return activity_payload(aid, "101", "10")

    result = _fetch_with_retry(
        "11",
        fetcher,
        max_retries=3,
        initial_delay=1.0,
        backoff_multiplier=2.0,
        max_delay=8.0,
        sleep_func=sleeps.append,
    )

    assert result == activity_payload("11", "101", "10")
    assert calls == ["11", "11"]
    assert sleeps == [1.0]


def test_fetch_with_retry_reraises_http_503_after_retries_are_exhausted():
    calls = []
    sleeps = []

    def fetcher(aid):
        calls.append(aid)
        raise FakeHTTPError(503, "ServerBusy")

    try:
        _fetch_with_retry(
            "11",
            fetcher,
            max_retries=2,
            initial_delay=1.0,
            backoff_multiplier=2.0,
            max_delay=8.0,
            sleep_func=sleeps.append,
        )
    except FakeHTTPError as exc:
        assert exc.response.status_code == 503
    else:
        raise AssertionError("Expected FakeHTTPError")

    assert calls == ["11", "11", "11"]
    assert sleeps == [1.0, 2.0]


def test_fetch_with_retry_does_not_retry_http_400():
    calls = []
    sleeps = []

    def fetcher(aid):
        calls.append(aid)
        raise FakeHTTPError(400, "Too many SIDs")

    try:
        _fetch_with_retry(
            "11",
            fetcher,
            max_retries=3,
            sleep_func=sleeps.append,
        )
    except FakeHTTPError as exc:
        assert exc.response.status_code == 400
    else:
        raise AssertionError("Expected FakeHTTPError")

    assert calls == ["11"]
    assert sleeps == []


def test_activity_runner_concurrent_fetch_retries_transient_503_without_blocking_successes():
    connection = sqlite3.connect(":memory:")
    calls = []

    def fetcher(aid):
        calls.append(aid)
        if aid == "22" and calls.count("22") == 1:
            raise FakeHTTPError(503, "ServerBusy")
        return activity_payload(aid, {"11": "101", "22": "202", "33": "303"}[aid], aid)

    result = run_pubchem_activity_enrichment(
        connection,
        aid_jobs(),
        fetcher,
        chunk_size=3,
        max_workers=3,
        max_retries=1,
        retry_initial_delay=0.0,
        retry_backoff_multiplier=2.0,
        retry_max_delay=0.0,
    )

    cursor = connection.cursor()
    cursor.execute("SELECT AID, CID FROM compound_activities ORDER BY AID")

    assert result["status"] == "success"
    assert result["processed_aids"] == 3
    assert result["successful_aids"] == 3
    assert result["failed_aids"] == 0
    assert cursor.fetchall() == [("11", "101"), ("22", "202"), ("33", "303")]
    assert calls.count("22") == 2


def test_ensure_compound_activities_table_is_idempotent():
    connection = sqlite3.connect(":memory:")

    ensure_compound_activities_table(connection)
    ensure_compound_activities_table(connection)

    cursor = connection.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")

    assert cursor.fetchall() == [("compound_activities",)]


def test_chunk_aid_jobs_rejects_non_positive_chunk_size():
    for chunk_size in (0, -1):
        try:
            list(chunk_aid_jobs(aid_jobs(), chunk_size=chunk_size))
        except ValueError as exc:
            assert str(exc) == "chunk_size must be greater than zero."
        else:
            raise AssertionError("Expected ValueError")


def test_build_activity_jobs_from_compound_assays_groups_by_protein_and_aid():
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE compound_assays (CID TEXT, AID TEXT, Protein TEXT)")
    connection.executemany(
        "INSERT INTO compound_assays (CID, AID, Protein) VALUES (?, ?, ?)",
        [
            ("101", "11", "P1"),
            ("102", "11", "P1"),
            ("101", "11", "P1"),
            ("201", "11", "P2"),
            ("301", "22", "P1"),
        ],
    )

    jobs = build_activity_jobs_from_compound_assays(connection)

    assert jobs == [
        {"protein": "P1", "aid": "11", "cids": ["101", "102"]},
        {"protein": "P1", "aid": "22", "cids": ["301"]},
        {"protein": "P2", "aid": "11", "cids": ["201"]},
    ]


def test_run_activity_enrichment_from_compound_assays_fills_compound_activities():
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE compound_assays (CID TEXT, AID TEXT, Protein TEXT)")
    connection.executemany(
        "INSERT INTO compound_assays (CID, AID, Protein) VALUES (?, ?, ?)",
        [("101", "11", "P1"), ("202", "22", "P1")],
    )

    result = run_activity_enrichment_from_compound_assays(
        connection,
        lambda aid: activity_payload(aid, {"11": "101", "22": "202"}[aid], aid),
        chunk_size=1,
    )

    cursor = connection.cursor()
    cursor.execute("SELECT AID, Protein, CID FROM compound_activities ORDER BY AID")

    assert result["total_aids"] == 2
    assert result["inserted_rows"] == 2
    assert cursor.fetchall() == [("11", "P1", "101"), ("22", "P1", "202")]


def test_run_activity_enrichment_from_compound_assays_keeps_sequential_defaults(monkeypatch):
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE compound_assays (CID TEXT, AID TEXT, Protein TEXT)")
    connection.execute(
        "INSERT INTO compound_assays (CID, AID, Protein) VALUES ('101', '11', 'P1')"
    )
    captured = {}

    def fake_runner(connection, aid_jobs, activity_fetcher, **kwargs):
        captured["aid_jobs"] = aid_jobs
        captured["kwargs"] = kwargs
        return {
            "status": "success",
            "total_aids": len(aid_jobs),
            "processed_aids": 0,
            "successful_aids": 0,
            "failed_aids": 0,
            "processed_aid_values": [],
            "successful_aid_values": [],
            "failed_aid_values": [],
            "successful_cid_values": [],
            "inserted_rows": 0,
            "error_message": None,
        }

    monkeypatch.setitem(
        run_activity_enrichment_from_compound_assays.__globals__,
        "run_pubchem_activity_enrichment",
        fake_runner,
    )

    run_activity_enrichment_from_compound_assays(
        connection,
        lambda aid: activity_payload(aid, "101", "10"),
    )

    assert captured["aid_jobs"] == [{"protein": "P1", "aid": "11", "cids": ["101"]}]
    assert captured["kwargs"]["max_workers"] == 1
    assert captured["kwargs"]["rate_limit_per_second"] is None
    assert captured["kwargs"]["max_retries"] == 0
    assert captured["kwargs"]["retry_initial_delay"] == 1.0
    assert captured["kwargs"]["retry_backoff_multiplier"] == 2.0
    assert captured["kwargs"]["retry_max_delay"] == 8.0


def test_run_activity_enrichment_from_compound_assays_passes_concurrency_options(monkeypatch):
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE compound_assays (CID TEXT, AID TEXT, Protein TEXT)")
    connection.execute(
        "INSERT INTO compound_assays (CID, AID, Protein) VALUES ('101', '11', 'P1')"
    )
    captured = {}

    def fake_runner(connection, aid_jobs, activity_fetcher, **kwargs):
        captured["kwargs"] = kwargs
        return {
            "status": "success",
            "total_aids": len(aid_jobs),
            "processed_aids": 0,
            "successful_aids": 0,
            "failed_aids": 0,
            "processed_aid_values": [],
            "successful_aid_values": [],
            "failed_aid_values": [],
            "successful_cid_values": [],
            "inserted_rows": 0,
            "error_message": None,
        }

    monkeypatch.setitem(
        run_activity_enrichment_from_compound_assays.__globals__,
        "run_pubchem_activity_enrichment",
        fake_runner,
    )

    run_activity_enrichment_from_compound_assays(
        connection,
        lambda aid: activity_payload(aid, "101", "10"),
        max_workers=4,
        rate_limit_per_second=4,
        max_retries=3,
        retry_initial_delay=1.0,
        retry_backoff_multiplier=2.0,
        retry_max_delay=8.0,
    )

    assert captured["kwargs"]["max_workers"] == 4
    assert captured["kwargs"]["rate_limit_per_second"] == 4
    assert captured["kwargs"]["max_retries"] == 3
    assert captured["kwargs"]["retry_initial_delay"] == 1.0
    assert captured["kwargs"]["retry_backoff_multiplier"] == 2.0
    assert captured["kwargs"]["retry_max_delay"] == 8.0


def test_run_activity_enrichment_from_compound_assays_handles_missing_or_empty_source_table():
    missing_connection = sqlite3.connect(":memory:")

    missing_result = run_activity_enrichment_from_compound_assays(
        missing_connection,
        lambda aid: activity_payload(aid, "101", "10"),
    )

    empty_connection = sqlite3.connect(":memory:")
    empty_connection.execute("CREATE TABLE compound_assays (CID TEXT, AID TEXT, Protein TEXT)")
    empty_result = run_activity_enrichment_from_compound_assays(
        empty_connection,
        lambda aid: activity_payload(aid, "101", "10"),
    )

    assert missing_result["total_aids"] == 0
    assert missing_result["inserted_rows"] == 0
    assert empty_result["total_aids"] == 0
    assert empty_result["inserted_rows"] == 0


def test_run_activity_enrichment_from_compound_assays_is_idempotent():
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE compound_assays (CID TEXT, AID TEXT, Protein TEXT)")
    connection.execute(
        "INSERT INTO compound_assays (CID, AID, Protein) VALUES ('101', '11', 'P1')"
    )
    fetcher = lambda aid: activity_payload(aid, "101", "10")

    first = run_activity_enrichment_from_compound_assays(connection, fetcher)
    second = run_activity_enrichment_from_compound_assays(connection, fetcher)

    cursor = connection.cursor()
    cursor.execute("SELECT COUNT(*) FROM compound_activities")

    assert first["inserted_rows"] == 1
    assert second["inserted_rows"] == 0
    assert cursor.fetchone() == (1,)
