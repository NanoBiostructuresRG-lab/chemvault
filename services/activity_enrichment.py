# SPDX-License-Identifier: LGPL-3.0-or-later
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import threading
import time

COMPOUND_ACTIVITIES_TABLE = "compound_activities"
COMPOUND_ASSAYS_TABLE = "compound_assays"
DEFAULT_ACTIVITY_CHUNK_SIZE = 10
ACTIVITY_COLUMNS = [
    "CID",
    "AID",
    "Protein",
    "Activity_Type",
    "Relation",
    "Activity_Value",
    "Activity_Value_Raw",
    "Unit",
    "Outcome",
    "Source_Column",
    "Activity_Status",
    "Result_Tag",
]


def ensure_compound_activities_table(connection):
    cursor = connection.cursor()
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS {COMPOUND_ACTIVITIES_TABLE} (
            CID TEXT NOT NULL,
            AID TEXT NOT NULL,
            Protein TEXT NOT NULL,
            Activity_Type TEXT,
            Relation TEXT,
            Activity_Value REAL,
            Activity_Value_Raw TEXT,
            Unit TEXT,
            Outcome TEXT,
            Source_Column TEXT,
            Activity_Status TEXT,
            Result_Tag TEXT
        )
    """)
    cursor.execute(f"""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_compound_activities_unique_result
        ON {COMPOUND_ACTIVITIES_TABLE} (
            CID,
            AID,
            Protein,
            Result_Tag,
            Activity_Type,
            Source_Column,
            Activity_Value_Raw,
            Unit,
            Relation,
            Outcome
        )
    """)
    connection.commit()


def chunk_aid_jobs(aid_jobs, chunk_size=DEFAULT_ACTIVITY_CHUNK_SIZE):
    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than zero.")
    aid_jobs = list(aid_jobs)
    for index in range(0, len(aid_jobs), chunk_size):
        yield aid_jobs[index:index + chunk_size]


def _build_activity_progress(
    status,
    total_aids,
    total_chunks,
    current_chunk,
    processed_aids,
    successful_aids,
    failed_aids,
    inserted_rows,
    error_message=None,
):
    return {
        "status": status,
        "total_aids": total_aids,
        "total_chunks": total_chunks,
        "current_chunk": current_chunk,
        "processed_aids": len(processed_aids),
        "successful_aids": len(successful_aids),
        "failed_aids": len(failed_aids),
        "inserted_rows": inserted_rows,
        "processed_aid_values": list(processed_aids),
        "successful_aid_values": list(successful_aids),
        "failed_aid_values": list(failed_aids),
        "error_message": error_message,
    }


def _emit_progress(progress_callback, snapshot):
    if progress_callback is not None:
        progress_callback(snapshot)


class _GlobalRateLimiter:
    def __init__(self, rate_limit_per_second):
        self._interval = None
        if rate_limit_per_second is not None:
            if rate_limit_per_second <= 0:
                raise ValueError("rate_limit_per_second must be greater than zero.")
            self._interval = 1.0 / rate_limit_per_second
        self._lock = threading.Lock()
        self._next_start_time = 0.0

    def wait(self):
        if self._interval is None:
            return

        with self._lock:
            now = time.monotonic()
            delay = max(0.0, self._next_start_time - now)
            if delay > 0:
                time.sleep(delay)
                now = time.monotonic()
            self._next_start_time = max(now, self._next_start_time) + self._interval


def _fetch_activity_for_job(aid_job, activity_fetcher, rate_limiter):
    rate_limiter.wait()
    return activity_fetcher(aid_job["aid"])


def _fetch_activity_chunk_concurrently(
    chunk,
    activity_fetcher,
    max_workers,
    rate_limiter,
    stop_on_error=False,
):
    chunk = list(chunk)
    if not chunk:
        return []

    results = []
    next_index = 0

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_job = {}

        def submit_next():
            nonlocal next_index
            if next_index >= len(chunk):
                return
            aid_job = chunk[next_index]
            future = executor.submit(
                _fetch_activity_for_job,
                aid_job,
                activity_fetcher,
                rate_limiter,
            )
            future_to_job[future] = (next_index, aid_job)
            next_index += 1

        for _ in range(min(max_workers, len(chunk))):
            submit_next()

        stop_submitting = False
        while future_to_job:
            done, _ = wait(future_to_job, return_when=FIRST_COMPLETED)
            completed_count = 0
            for future in done:
                index, aid_job = future_to_job.pop(future)
                if future.cancelled():
                    continue
                completed_count += 1
                try:
                    activity_by_cid = future.result()
                except Exception as exc:
                    results.append((index, aid_job, None, exc))
                    if stop_on_error:
                        stop_submitting = True
                else:
                    results.append((index, aid_job, activity_by_cid, None))

            if not stop_submitting:
                for _ in range(completed_count):
                    submit_next()

            if stop_submitting:
                for future in list(future_to_job):
                    future.cancel()

    return [
        (aid_job, activity_by_cid, error)
        for _, aid_job, activity_by_cid, error in sorted(results, key=lambda item: item[0])
    ]


def _empty_activity_result():
    return {
        "status": "success",
        "total_aids": 0,
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


def _compound_assays_exists(connection):
    cursor = connection.cursor()
    cursor.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (COMPOUND_ASSAYS_TABLE,),
    )
    return cursor.fetchone() is not None


def build_activity_jobs_from_compound_assays(connection):
    if not _compound_assays_exists(connection):
        return []

    cursor = connection.cursor()
    cursor.execute(f"""
        SELECT Protein, AID, CID
        FROM {COMPOUND_ASSAYS_TABLE}
        ORDER BY Protein, AID, CID
    """)
    grouped_jobs = {}
    for protein, aid, cid in cursor.fetchall():
        key = (str(protein), str(aid))
        job = grouped_jobs.setdefault(
            key,
            {"protein": str(protein), "aid": str(aid), "cids": []},
        )
        cid = str(cid)
        if cid not in job["cids"]:
            job["cids"].append(cid)
    return list(grouped_jobs.values())


def _activity_rows_from_fetch_result(aid_job, activity_by_cid):
    aid = str(aid_job["aid"])
    protein = str(aid_job["protein"])
    expected_cids = {str(cid) for cid in aid_job.get("cids", [])}
    rows = []

    for cid, activity in activity_by_cid.items():
        cid = str(cid)
        if expected_cids and cid not in expected_cids:
            continue
        for record in activity.get("records", []):
            rows.append([
                str(record["CID"]),
                aid,
                protein,
                record["Activity_Type"],
                record["Relation"],
                record["Activity_Value"],
                record["Activity_Value_Raw"],
                record["Unit"],
                record["Outcome"],
                record["Source_Column"],
                record["Activity_Status"],
                str(record["Result_Tag"]),
            ])
    return rows


def upsert_compound_activity_rows(connection, rows):
    if not rows:
        return 0

    cursor = connection.cursor()
    placeholders = ", ".join(["?"] * len(ACTIVITY_COLUMNS))
    cursor.executemany(
        f"""
        INSERT OR IGNORE INTO {COMPOUND_ACTIVITIES_TABLE}
        ({", ".join(ACTIVITY_COLUMNS)})
        VALUES ({placeholders})
        """,
        rows,
    )
    return cursor.rowcount


def run_pubchem_activity_enrichment(
    connection,
    aid_jobs,
    activity_fetcher,
    chunk_size=DEFAULT_ACTIVITY_CHUNK_SIZE,
    progress_callback=None,
    continue_on_error=True,
    max_workers=1,
    rate_limit_per_second=None,
):
    if max_workers <= 0:
        raise ValueError("max_workers must be greater than zero.")

    ensure_compound_activities_table(connection)
    aid_jobs = [
        {
            "protein": str(job["protein"]),
            "aid": str(job["aid"]),
            "cids": [str(cid) for cid in job.get("cids", [])],
        }
        for job in aid_jobs
    ]
    chunks = list(chunk_aid_jobs(aid_jobs, chunk_size))
    total_aids = len(aid_jobs)
    total_chunks = len(chunks)
    processed_aids = []
    successful_aids = []
    failed_aids = []
    successful_cids = set()
    inserted_rows = 0
    rate_limiter = _GlobalRateLimiter(rate_limit_per_second)

    _emit_progress(
        progress_callback,
        _build_activity_progress(
            "started",
            total_aids,
            total_chunks,
            0,
            processed_aids,
            successful_aids,
            failed_aids,
            inserted_rows,
        ),
    )

    for chunk_index, chunk in enumerate(chunks, start=1):
        _emit_progress(
            progress_callback,
            _build_activity_progress(
                "running",
                total_aids,
                total_chunks,
                chunk_index,
                processed_aids,
                successful_aids,
                failed_aids,
                inserted_rows,
            ),
        )
        if max_workers == 1:
            fetch_results = []
            for aid_job in chunk:
                aid = aid_job["aid"]
                try:
                    activity_by_cid = _fetch_activity_for_job(
                        aid_job,
                        activity_fetcher,
                        rate_limiter,
                    )
                except Exception as exc:
                    fetch_results.append((aid_job, None, exc))
                    if not continue_on_error:
                        break
                else:
                    fetch_results.append((aid_job, activity_by_cid, None))
        else:
            fetch_results = _fetch_activity_chunk_concurrently(
                chunk,
                activity_fetcher,
                max_workers,
                rate_limiter,
                stop_on_error=not continue_on_error,
            )

        failure_error = None
        for aid_job, activity_by_cid, error in fetch_results:
            aid = aid_job["aid"]
            if error is not None:
                processed_aids.append(aid)
                failed_aids.append(aid)
                if failure_error is None:
                    failure_error = error
                if not continue_on_error:
                    continue
            else:
                rows = _activity_rows_from_fetch_result(aid_job, activity_by_cid)
                successful_cids.update(row[0] for row in rows)
                inserted_rows += upsert_compound_activity_rows(connection, rows)
                processed_aids.append(aid)
                successful_aids.append(aid)

        if failure_error is not None and not continue_on_error:
            connection.commit()
            _emit_progress(
                progress_callback,
                _build_activity_progress(
                    "failed",
                    total_aids,
                    total_chunks,
                    chunk_index,
                    processed_aids,
                    successful_aids,
                    failed_aids,
                    inserted_rows,
                    error_message=str(failure_error),
                ),
            )
            return {
                "status": "failed",
                "total_aids": total_aids,
                "processed_aids": len(processed_aids),
                "successful_aids": len(successful_aids),
                "failed_aids": len(failed_aids),
                "processed_aid_values": processed_aids,
                "successful_aid_values": successful_aids,
                "failed_aid_values": failed_aids,
                "successful_cid_values": sorted(successful_cids),
                "inserted_rows": inserted_rows,
                "error_message": str(failure_error),
            }
        connection.commit()
        _emit_progress(
            progress_callback,
            _build_activity_progress(
                "chunk_completed",
                total_aids,
                total_chunks,
                chunk_index,
                processed_aids,
                successful_aids,
                failed_aids,
                inserted_rows,
            ),
        )

    result = {
        "status": "success",
        "total_aids": total_aids,
        "processed_aids": len(processed_aids),
        "successful_aids": len(successful_aids),
        "failed_aids": len(failed_aids),
        "processed_aid_values": processed_aids,
        "successful_aid_values": successful_aids,
        "failed_aid_values": failed_aids,
        "successful_cid_values": sorted(successful_cids),
        "inserted_rows": inserted_rows,
        "error_message": None,
    }
    result["progress"] = _build_activity_progress(
        "success",
        total_aids,
        total_chunks,
        total_chunks,
        processed_aids,
        successful_aids,
        failed_aids,
        inserted_rows,
    )
    _emit_progress(progress_callback, result["progress"])
    return result


def run_activity_enrichment_from_compound_assays(
    connection,
    activity_fetcher,
    chunk_size=DEFAULT_ACTIVITY_CHUNK_SIZE,
    progress_callback=None,
    continue_on_error=True,
):
    aid_jobs = build_activity_jobs_from_compound_assays(connection)
    if not aid_jobs:
        ensure_compound_activities_table(connection)
        result = _empty_activity_result()
        result["progress"] = _build_activity_progress(
            "success",
            0,
            0,
            0,
            [],
            [],
            [],
            0,
        )
        _emit_progress(progress_callback, result["progress"])
        return result
    return run_pubchem_activity_enrichment(
        connection,
        aid_jobs,
        activity_fetcher,
        chunk_size=chunk_size,
        progress_callback=progress_callback,
        continue_on_error=continue_on_error,
    )
