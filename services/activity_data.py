# SPDX-License-Identifier: LGPL-3.0-or-later
import sqlite3

from services.sql_utils import quote_identifier, table_exists

COMPOUND_ACTIVITIES_TABLE = "compound_activities"
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


def get_activity_rows(
    connection,
    activity_types=None,
    outcomes=None,
    units=None,
    aids=None,
    value_range=None,
):
    if not compound_activities_exists(connection):
        return []

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
    columns_sql = ", ".join(quote_identifier(column) for column in ACTIVITY_EXPORT_COLUMNS)
    cursor = connection.cursor()
    cursor.execute(f"""
        SELECT {columns_sql}
        FROM {quote_identifier(COMPOUND_ACTIVITIES_TABLE)}
        {where_sql}
        ORDER BY CAST(AID AS INTEGER), CID, Result_Tag
    """, params)
    rows = cursor.fetchall()
    return [dict(zip(ACTIVITY_EXPORT_COLUMNS, row, strict=True)) for row in rows]
