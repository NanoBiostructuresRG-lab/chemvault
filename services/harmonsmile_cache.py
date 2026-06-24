# SPDX-License-Identifier: LGPL-3.0-or-later
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

import pandas as pd

from services.sql_utils import quote_identifier

CACHE_TABLE = "_chemvault_harmonsmile_cache"
DEFAULT_CHUNK_SIZE = 500
SQLITE_MAX_INT = 9223372036854775807
BASE_COLUMNS = {
    "PubChem_CID",
    "status",
    "fetched_at",
    "error_message",
}
MERGE_EXCLUDED_COLUMNS = {
    "PubChem_CID",
    "status",
    "fetched_at",
    "error_message",
    "created_at",
    "updated_at",
}


def normalize_cid(value):
    """Return a canonical PubChem CID string or None when the value is invalid."""
    if value is None:
        return None

    text = str(value).strip()
    if text == "":
        return None

    try:
        number = Decimal(text)
    except InvalidOperation:
        return None

    if number != number.to_integral_value():
        return None

    cid = int(number)
    if cid <= 0 or cid > SQLITE_MAX_INT:
        return None
    return str(cid)


def normalize_cids(values):
    """Normalize and deduplicate PubChem CIDs while preserving first-seen order."""
    normalized = []
    invalid = []
    seen = set()

    for value in values:
        cid = normalize_cid(value)
        if cid is None:
            invalid.append(value)
            continue
        if cid not in seen:
            normalized.append(cid)
            seen.add(cid)

    return normalized, invalid


def chunk_cids(cids, chunk_size=DEFAULT_CHUNK_SIZE):
    """Yield CID chunks using the accepted future runner chunk size."""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than zero.")

    for index in range(0, len(cids), chunk_size):
        yield cids[index:index + chunk_size]


def normalize_harmonsmile_column_name(column):
    return (
        str(column)
        .strip()
        .replace(" ", "_")
        .replace(":", "")
    )


def normalize_harmonsmile_result(result_df):
    """Return a copy with stable column names and canonical PubChem_CID values."""
    normalized_df = result_df.copy()
    normalized_df.columns = [
        normalize_harmonsmile_column_name(column)
        for column in normalized_df.columns
    ]

    if "PubChem_CID" not in normalized_df.columns:
        raise ValueError("HARMONSMILE result must include a PubChem_CID column.")

    normalized_df["PubChem_CID"] = normalized_df["PubChem_CID"].map(normalize_cid)
    normalized_df = normalized_df.dropna(subset=["PubChem_CID"])
    normalized_df = normalized_df.drop_duplicates(subset=["PubChem_CID"], keep="last")
    return normalized_df


def get_harmonsmile_output_columns(result_df):
    normalized_df = normalize_harmonsmile_result(result_df)
    return [
        column
        for column in normalized_df.columns
        if column != "PubChem_CID"
    ]


def ensure_harmonsmile_cache(connection):
    cursor = connection.cursor()
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS {quote_identifier(CACHE_TABLE)} (
            PubChem_CID TEXT PRIMARY KEY,
            status TEXT NOT NULL DEFAULT 'success',
            fetched_at TEXT NOT NULL,
            error_message TEXT
        )
    """)
    connection.commit()


def _cache_columns(connection):
    cursor = connection.cursor()
    cursor.execute(f"PRAGMA table_info({quote_identifier(CACHE_TABLE)})")
    return [row[1] for row in cursor.fetchall()]


def _table_columns(connection, table):
    cursor = connection.cursor()
    cursor.execute(f"PRAGMA table_info({quote_identifier(table)})")
    return [row[1] for row in cursor.fetchall()]


def _ensure_cache_result_columns(connection, columns):
    ensure_harmonsmile_cache(connection)
    existing_columns = set(_cache_columns(connection))
    cursor = connection.cursor()
    for column in columns:
        if column in BASE_COLUMNS or column in existing_columns:
            continue
        cursor.execute(
            f"ALTER TABLE {quote_identifier(CACHE_TABLE)} "
            f"ADD COLUMN {quote_identifier(column)} TEXT"
        )
    connection.commit()


def _harmonsmile_merge_columns(connection):
    ensure_harmonsmile_cache(connection)
    return [
        column
        for column in _cache_columns(connection)
        if column not in MERGE_EXCLUDED_COLUMNS
    ]


def _ensure_table_columns(connection, table, columns):
    existing_columns = set(_table_columns(connection, table))
    cursor = connection.cursor()
    for column in columns:
        if column in existing_columns:
            continue
        cursor.execute(
            f"ALTER TABLE {quote_identifier(table)} "
            f"ADD COLUMN {quote_identifier(column)} TEXT"
        )
    connection.commit()


def get_cached_harmonsmile_cids(connection, cids, status="success"):
    ensure_harmonsmile_cache(connection)
    normalized_cids, _ = normalize_cids(cids)
    if not normalized_cids:
        return set()

    cached = set()
    cursor = connection.cursor()
    batch_size = 500
    for index in range(0, len(normalized_cids), batch_size):
        batch = normalized_cids[index:index + batch_size]
        placeholders = ", ".join("?" for _ in batch)
        params = [*batch]
        status_clause = ""
        if status is not None:
            status_clause = "AND status = ?"
            params.append(status)

        cursor.execute(
            f"""
            SELECT PubChem_CID
            FROM {quote_identifier(CACHE_TABLE)}
            WHERE PubChem_CID IN ({placeholders})
            {status_clause}
            """,
            params,
        )
        cached.update(row[0] for row in cursor.fetchall())

    return cached


def _read_success_cache_rows(connection, cids=None):
    merge_columns = _harmonsmile_merge_columns(connection)
    if not merge_columns:
        return merge_columns, []

    selected_columns = ["PubChem_CID", *merge_columns]
    query = f"""
        SELECT {", ".join(quote_identifier(column) for column in selected_columns)}
        FROM {quote_identifier(CACHE_TABLE)}
        WHERE status = ?
    """
    params = ["success"]

    if cids is not None:
        normalized_cids, _ = normalize_cids(cids)
        if not normalized_cids:
            return merge_columns, []
        placeholders = ", ".join("?" for _ in normalized_cids)
        query += f" AND PubChem_CID IN ({placeholders})"
        params.extend(normalized_cids)

    cursor = connection.cursor()
    cursor.execute(query, params)
    return merge_columns, cursor.fetchall()


def merge_harmonsmile_cache_to_table(connection, table, cid_column, cids=None):
    """Merge successful cached HARMONSMILE values into an active data table."""
    merge_columns, rows = _read_success_cache_rows(connection, cids)
    if not merge_columns or not rows:
        connection.commit()
        return 0

    _ensure_table_columns(connection, table, merge_columns)
    set_clause = ", ".join(
        f"{quote_identifier(column)} = ?"
        for column in merge_columns
    )
    cursor = connection.cursor()
    update_sql = f"""
        UPDATE {quote_identifier(table)}
        SET {set_clause}
        WHERE {quote_identifier(cid_column)} = ?
    """
    update_params = []

    for row in rows:
        pubchem_cid = row[0]
        values = list(row[1:])
        update_params.append([*values, pubchem_cid])

    cursor.executemany(update_sql, update_params)
    updated_rows = cursor.rowcount
    connection.commit()
    return updated_rows


def read_cids_from_table(connection, table, cid_column):
    """Read raw CID values from a SQLite table column."""
    cursor = connection.cursor()
    cursor.execute(
        f"""
        SELECT {quote_identifier(cid_column)}
        FROM {quote_identifier(table)}
        """
    )
    return [row[0] for row in cursor.fetchall()]


def prepare_harmonsmile_job(connection, table, cid_column):
    """Split selected table CIDs into cached, pending, and invalid groups."""
    raw_cids = read_cids_from_table(connection, table, cid_column)
    valid_cids, invalid_cids = normalize_cids(raw_cids)
    cached_set = get_cached_harmonsmile_cids(connection, valid_cids)
    cached_cids = [cid for cid in valid_cids if cid in cached_set]
    pending_cids = [cid for cid in valid_cids if cid not in cached_set]

    return {
        "source_table": table,
        "cid_column": cid_column,
        "total_cids": len(valid_cids),
        "valid_cids": valid_cids,
        "cached_cids": cached_cids,
        "pending_cids": pending_cids,
        "invalid_cids": invalid_cids,
    }


def upsert_harmonsmile_cache(connection, result_df, status="success", error_message=None):
    normalized_df = normalize_harmonsmile_result(result_df)
    result_columns = get_harmonsmile_output_columns(normalized_df)
    _ensure_cache_result_columns(connection, result_columns)

    if normalized_df.empty:
        return 0

    fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rows = []
    insert_columns = [
        "PubChem_CID",
        "status",
        "fetched_at",
        "error_message",
        *result_columns,
    ]

    for _, row in normalized_df.iterrows():
        rows.append([
            row.get("PubChem_CID"),
            status,
            fetched_at,
            error_message,
            *[None if pd.isna(row.get(column)) else str(row.get(column)) for column in result_columns],
        ])

    quoted_columns = ", ".join(quote_identifier(column) for column in insert_columns)
    placeholders = ", ".join("?" for _ in insert_columns)
    update_columns = [
        column
        for column in insert_columns
        if column != "PubChem_CID"
    ]
    update_clause = ", ".join(
        f"{quote_identifier(column)} = excluded.{quote_identifier(column)}"
        for column in update_columns
    )

    cursor = connection.cursor()
    cursor.executemany(
        f"""
        INSERT INTO {quote_identifier(CACHE_TABLE)}
        ({quoted_columns})
        VALUES ({placeholders})
        ON CONFLICT(PubChem_CID) DO UPDATE SET
            {update_clause}
        """,
        rows,
    )
    connection.commit()
    return len(rows)


def mark_harmonsmile_cache_failed(connection, cids, error_message):
    normalized_cids, _ = normalize_cids(cids)
    if not normalized_cids:
        return 0

    ensure_harmonsmile_cache(connection)
    fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rows = [
        (cid, "failed", fetched_at, str(error_message))
        for cid in normalized_cids
    ]

    cursor = connection.cursor()
    cursor.executemany(
        f"""
        INSERT INTO {quote_identifier(CACHE_TABLE)}
        (PubChem_CID, status, fetched_at, error_message)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(PubChem_CID) DO UPDATE SET
            status = excluded.status,
            fetched_at = excluded.fetched_at,
            error_message = excluded.error_message
        """,
        rows,
    )
    connection.commit()
    return len(rows)


def _build_harmonsmile_progress(
    status,
    total_cids,
    total_chunks,
    current_chunk,
    processed_cids,
    successful_cids,
    failed_cids,
    missing_cids=None,
    stopped_by_exception=False,
    error_message=None,
):
    return {
        "status": status,
        "total_cids": total_cids,
        "total_chunks": total_chunks,
        "current_chunk": current_chunk,
        "processed_cids": len(processed_cids),
        "successful_cids": len(successful_cids),
        "failed_cids": len(failed_cids),
        "missing_cids": len(missing_cids or []),
        "processed_cid_values": list(processed_cids),
        "successful_cid_values": list(successful_cids),
        "failed_cid_values": list(failed_cids),
        "missing_cid_values": list(missing_cids or []),
        "stopped_by_exception": stopped_by_exception,
        "error_message": error_message,
    }


def _emit_progress(progress_callback, snapshot):
    if progress_callback is not None:
        progress_callback(snapshot)


def run_harmonsmile_chunks(
    connection,
    pending_cids,
    harmonsmile_runner,
    chunk_size=DEFAULT_CHUNK_SIZE,
    progress_callback=None,
):
    """Run HARMONSMILE for pending CIDs and persist each chunk into cache."""
    normalized_cids, invalid_cids = normalize_cids(pending_cids)
    chunks = list(chunk_cids(normalized_cids, chunk_size))
    processed_cids = []
    successful_cids = []
    failed_cids = []
    missing_result_cids = []
    total_cids = len(normalized_cids)
    total_chunks = len(chunks)

    _emit_progress(
        progress_callback,
        _build_harmonsmile_progress(
            "started",
            total_cids,
            total_chunks,
            0,
            processed_cids,
            successful_cids,
            failed_cids,
        ),
    )

    for chunk_index, chunk in enumerate(chunks, start=1):
        _emit_progress(
            progress_callback,
            _build_harmonsmile_progress(
                "running",
                total_cids,
                total_chunks,
                chunk_index,
                processed_cids,
                successful_cids,
                failed_cids,
            ),
        )
        chunk_df = pd.DataFrame({"CID": chunk})
        try:
            result_df = harmonsmile_runner(chunk_df)
            normalized_result = normalize_harmonsmile_result(result_df)
            upsert_harmonsmile_cache(connection, normalized_result)
            returned_cids = normalized_result["PubChem_CID"].tolist()
            returned_set = set(returned_cids)
            missing_cids = [cid for cid in chunk if cid not in returned_set]
            if missing_cids:
                mark_harmonsmile_cache_failed(
                    connection,
                    missing_cids,
                    "Missing HARMONSMILE result for CID in processed chunk",
                )
            processed_cids.extend(returned_cids)
            successful_cids.extend(returned_cids)
            failed_cids.extend(missing_cids)
            missing_result_cids.extend(missing_cids)
            _emit_progress(
                progress_callback,
                _build_harmonsmile_progress(
                    "chunk_completed",
                    total_cids,
                    total_chunks,
                    chunk_index,
                    processed_cids,
                    successful_cids,
                    failed_cids,
                    missing_cids=missing_cids,
                ),
            )
        except Exception as exc:
            mark_harmonsmile_cache_failed(connection, chunk, str(exc))
            failed_cids.extend(chunk)
            _emit_progress(
                progress_callback,
                _build_harmonsmile_progress(
                    "failed",
                    total_cids,
                    total_chunks,
                    chunk_index,
                    processed_cids,
                    successful_cids,
                    failed_cids,
                    stopped_by_exception=True,
                    error_message=str(exc),
                ),
            )
            return {
                "status": "failed",
                "chunk_index": chunk_index,
                "total_chunks": len(chunks),
                "processed_cids": processed_cids,
                "failed_cids": chunk,
                "missing_cids": missing_result_cids,
                "invalid_cids": invalid_cids,
                "error_message": str(exc),
            }

    result = {
        "status": "success",
        "chunk_index": len(chunks),
        "total_chunks": len(chunks),
        "processed_cids": processed_cids,
        "failed_cids": failed_cids,
        "missing_cids": missing_result_cids,
        "invalid_cids": invalid_cids,
        "error_message": None,
    }
    result["progress"] = _build_harmonsmile_progress(
        "success",
        total_cids,
        total_chunks,
        len(chunks),
        processed_cids,
        successful_cids,
        failed_cids,
    )
    _emit_progress(progress_callback, result["progress"])
    return result
