# SPDX-License-Identifier: LGPL-3.0-or-later
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
):
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
        for aid_job in chunk:
            aid = aid_job["aid"]
            try:
                activity_by_cid = activity_fetcher(aid)
                rows = _activity_rows_from_fetch_result(aid_job, activity_by_cid)
                successful_cids.update(row[0] for row in rows)
                inserted_rows += upsert_compound_activity_rows(connection, rows)
                processed_aids.append(aid)
                successful_aids.append(aid)
            except Exception as exc:
                processed_aids.append(aid)
                failed_aids.append(aid)
                if not continue_on_error:
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
                            error_message=str(exc),
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
                        "error_message": str(exc),
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
