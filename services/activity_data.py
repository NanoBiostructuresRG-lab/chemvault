# SPDX-License-Identifier: LGPL-3.0-or-later
import csv
import io
import re
import sqlite3

from services.sql_utils import quote_identifier, table_exists

COMPOUND_ACTIVITIES_TABLE = "compound_activities"
ACTIVITY_EXPORT_FETCH_SIZE = 5000
ACTIVITY_EXPORT_COLUMNS = [
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
    "Result_Tag",
]


def compound_activities_exists(connection):
    return table_exists(connection, COMPOUND_ACTIVITIES_TABLE)


def _distinct_values(connection, column):
    cursor = connection.cursor()
    cursor.execute(f"""
        SELECT DISTINCT {quote_identifier(column)}
        FROM {quote_identifier(COMPOUND_ACTIVITIES_TABLE)}
        WHERE COALESCE({quote_identifier(column)}, '') != ''
        ORDER BY {quote_identifier(column)}
    """)
    return [row[0] for row in cursor.fetchall()]


def get_activity_summary(connection):
    if not compound_activities_exists(connection):
        return None

    cursor = connection.cursor()
    cursor.execute(f"""
        SELECT
            COUNT(*),
            COUNT(DISTINCT CID),
            COUNT(DISTINCT AID),
            MIN(Activity_Value),
            MAX(Activity_Value)
        FROM {quote_identifier(COMPOUND_ACTIVITIES_TABLE)}
    """)
    total_rows, unique_cids, unique_aids, min_value, max_value = cursor.fetchone()
    return {
        "total_rows": total_rows,
        "unique_cids": unique_cids,
        "unique_aids": unique_aids,
        "min_value": min_value,
        "max_value": max_value,
        "activity_types": _distinct_values(connection, "Activity_Type"),
        "outcomes": _distinct_values(connection, "Outcome"),
        "units": _distinct_values(connection, "Unit"),
        "source_columns": _distinct_values(connection, "Source_Column"),
        "aids": _distinct_values(connection, "AID"),
    }


def _add_in_filter(clauses, params, column, values):
    clean_values = [value for value in values if value not in (None, "")]
    if not clean_values:
        return
    placeholders = ", ".join(["?"] * len(clean_values))
    clauses.append(f"{quote_identifier(column)} IN ({placeholders})")
    params.extend(clean_values)


def _activity_filter_sql(
    activity_types=None,
    outcomes=None,
    units=None,
    aids=None,
    value_range=None,
):
    clauses = []
    params = []
    _add_in_filter(clauses, params, "Activity_Type", activity_types or [])
    _add_in_filter(clauses, params, "Outcome", outcomes or [])
    _add_in_filter(clauses, params, "Unit", units or [])
    _add_in_filter(clauses, params, "AID", aids or [])

    if value_range is not None:
        min_value, max_value = value_range
        if min_value is not None:
            clauses.append("Activity_Value >= ?")
            params.append(min_value)
        if max_value is not None:
            clauses.append("Activity_Value <= ?")
            params.append(max_value)

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return where_sql, params


def get_activity_row_count(
    connection,
    activity_types=None,
    outcomes=None,
    units=None,
    aids=None,
    value_range=None,
):
    if not compound_activities_exists(connection):
        return 0

    where_sql, params = _activity_filter_sql(
        activity_types=activity_types,
        outcomes=outcomes,
        units=units,
        aids=aids,
        value_range=value_range,
    )
    cursor = connection.cursor()
    cursor.execute(f"""
        SELECT COUNT(*)
        FROM {quote_identifier(COMPOUND_ACTIVITIES_TABLE)}
        {where_sql}
    """, params)
    return int(cursor.fetchone()[0])


def get_activity_value_stats(
    connection,
    activity_types=None,
    outcomes=None,
    units=None,
    aids=None,
):
    if not compound_activities_exists(connection):
        return None

    where_sql, params = _activity_filter_sql(
        activity_types=activity_types,
        outcomes=outcomes,
        units=units,
        aids=aids,
    )
    cursor = connection.cursor()
    cursor.execute(f"""
        SELECT
            COUNT(*),
            MIN(Activity_Value),
            MAX(Activity_Value),
            SUM(
                CASE
                    WHEN TRIM(COALESCE(Relation, '')) IN ('>', '<', '>=', '<=')
                    THEN 1
                    ELSE 0
                END
            )
        FROM {quote_identifier(COMPOUND_ACTIVITIES_TABLE)}
        {where_sql}
    """, params)
    total_rows, min_value, max_value, qualified_rows = cursor.fetchone()
    return {
        "total_rows": int(total_rows),
        "min_value": min_value,
        "max_value": max_value,
        "qualified_rows": int(qualified_rows or 0),
    }


def _activity_rows_query(where_sql, limit=None):
    columns_sql = ", ".join(quote_identifier(column) for column in ACTIVITY_EXPORT_COLUMNS)
    limit_sql = "LIMIT ?" if limit is not None else ""
    return f"""
        SELECT {columns_sql}
        FROM {quote_identifier(COMPOUND_ACTIVITIES_TABLE)}
        {where_sql}
        ORDER BY CAST(AID AS INTEGER), CID, Result_Tag
        {limit_sql}
    """


def get_activity_rows(
    connection,
    activity_types=None,
    outcomes=None,
    units=None,
    aids=None,
    value_range=None,
    limit=None,
):
    if not compound_activities_exists(connection):
        return []

    where_sql, params = _activity_filter_sql(
        activity_types=activity_types,
        outcomes=outcomes,
        units=units,
        aids=aids,
        value_range=value_range,
    )
    if limit is not None:
        params = [*params, int(limit)]
    cursor = connection.cursor()
    cursor.execute(_activity_rows_query(where_sql, limit), params)
    rows = cursor.fetchall()
    return [dict(zip(ACTIVITY_EXPORT_COLUMNS, row, strict=True)) for row in rows]


def get_activity_cids(
    connection,
    activity_types=None,
    outcomes=None,
    units=None,
    aids=None,
    value_range=None,
):
    if not compound_activities_exists(connection):
        return []

    where_sql, params = _activity_filter_sql(
        activity_types=activity_types,
        outcomes=outcomes,
        units=units,
        aids=aids,
        value_range=value_range,
    )
    cid_clause = "COALESCE(CID, '') != ''"
    where_sql = (
        f"{where_sql} AND {cid_clause}"
        if where_sql
        else f"WHERE {cid_clause}"
    )
    cursor = connection.cursor()
    cursor.execute(f"""
        SELECT DISTINCT CID
        FROM {quote_identifier(COMPOUND_ACTIVITIES_TABLE)}
        {where_sql}
        ORDER BY CID
    """, params)
    return [str(row[0]) for row in cursor.fetchall()]


def get_activity_csv_bytes(
    connection,
    activity_types=None,
    outcomes=None,
    units=None,
    aids=None,
    value_range=None,
    fetch_size=ACTIVITY_EXPORT_FETCH_SIZE,
):
    if not compound_activities_exists(connection):
        return b"\n"

    where_sql, params = _activity_filter_sql(
        activity_types=activity_types,
        outcomes=outcomes,
        units=units,
        aids=aids,
        value_range=value_range,
    )
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow(ACTIVITY_EXPORT_COLUMNS)

    cursor = connection.cursor()
    cursor.execute(_activity_rows_query(where_sql), params)
    while True:
        rows = cursor.fetchmany(fetch_size)
        if not rows:
            break
        writer.writerows(rows)

    return buffer.getvalue().encode("utf-8")


def _sanitize_table_name_part(value):
    clean = re.sub(r"[^0-9A-Za-z]+", "_", str(value).strip()).strip("_")
    return clean or "filtered"


def build_harmonsmile_subset_base_name(activity_types=None, units=None):
    clean_activity_types = [
        value for value in activity_types or [] if value not in (None, "")
    ]
    clean_units = [
        value for value in units or [] if value not in (None, "")
    ]

    parts = ["harmonsmile", "subset"]
    if len(clean_activity_types) == 1:
        parts.append(_sanitize_table_name_part(clean_activity_types[0]))
        if len(clean_units) == 1:
            parts.append(_sanitize_table_name_part(clean_units[0]))
    else:
        parts.append("filtered_activity")
    return "_".join(parts)


def unique_harmonsmile_subset_table_name(
    connection,
    activity_types=None,
    units=None,
):
    base_name = build_harmonsmile_subset_base_name(
        activity_types=activity_types,
        units=units,
    )
    candidate = base_name
    suffix = 2
    while table_exists(connection, candidate):
        candidate = f"{base_name}_{suffix}"
        suffix += 1
    return candidate


def create_harmonsmile_subset_table(connection, table_name, cids):
    clean_cids = []
    seen = set()
    for cid in cids:
        text = str(cid).strip()
        if text == "" or text in seen:
            continue
        clean_cids.append(text)
        seen.add(text)

    if not clean_cids:
        raise ValueError("At least one CID is required to create a HARMONSMILE subset.")
    if table_exists(connection, table_name):
        raise ValueError(f"Table already exists: {table_name}")

    cursor = connection.cursor()
    cursor.execute(f"""
        CREATE TABLE {quote_identifier(table_name)} (
            CID TEXT NOT NULL
        )
    """)
    cursor.executemany(
        f"INSERT INTO {quote_identifier(table_name)} (CID) VALUES (?)",
        [(cid,) for cid in clean_cids],
    )
    connection.commit()
    return len(clean_cids)
