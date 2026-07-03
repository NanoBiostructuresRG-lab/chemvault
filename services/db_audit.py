# SPDX-License-Identifier: LGPL-3.0-or-later
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from services.sql_utils import quote_identifier, table_exists

METADATA_TABLE = "_chemvault_table_metadata"
OPERATION_LOG_TABLE = "_chemvault_operation_log"
HARMONSMILE_CACHE_TABLE = "_chemvault_harmonsmile_cache"
COMPOUND_ASSAYS_TABLE = "compound_assays"
COMPOUND_ACTIVITIES_TABLE = "compound_activities"
INTERNAL_TABLES = {
    METADATA_TABLE,
    OPERATION_LOG_TABLE,
    HARMONSMILE_CACHE_TABLE,
    COMPOUND_ASSAYS_TABLE,
    COMPOUND_ACTIVITIES_TABLE,
    "_chemvault_jobs",
    "sqlite_sequence",
}


def list_database_files(directory: Path) -> list[Path]:
    """Return SQLite database files in a directory."""
    if not directory.exists():
        raise FileNotFoundError(f"Directory not found: {directory}")
    if not directory.is_dir():
        raise NotADirectoryError(f"Not a directory: {directory}")
    return sorted(path for path in directory.iterdir() if path.suffix == ".db")


def list_tables(db_path: Path) -> list[str]:
    """Return SQLite tables ordered by name."""
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")
    with sqlite3.connect(db_path) as con:
        cur = con.cursor()
        cur.execute("""
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
            ORDER BY name
        """)
        return [row[0] for row in cur.fetchall()]


def count_rows(db_path: Path, table: str) -> int:
    """Return row count for a table."""
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")
    with sqlite3.connect(db_path) as con:
        cur = con.cursor()
        cur.execute(f"SELECT COUNT(*) FROM {quote_identifier(table)}")
        return int(cur.fetchone()[0])


def _metadata_table_exists(connection) -> bool:
    cursor = connection.cursor()
    cursor.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (METADATA_TABLE,),
    )
    return cursor.fetchone() is not None


def _table_exists(connection, table_name: str) -> bool:
    cursor = connection.cursor()
    cursor.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    )
    return cursor.fetchone() is not None


def _encode_optional_columns(value):
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        return json.dumps(list(value))
    return str(value)


def ensure_table_metadata(connection, commit: bool = True) -> None:
    """Create ChemVault table metadata storage when needed."""
    cursor = connection.cursor()
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS {quote_identifier(METADATA_TABLE)} (
            table_name TEXT PRIMARY KEY,
            role TEXT NOT NULL,
            origin TEXT NOT NULL,
            source_table TEXT,
            created_at TEXT NOT NULL,
            created_by TEXT,
            query_used TEXT,
            notes TEXT
        )
    """)
    if commit:
        connection.commit()


def ensure_operation_log(connection, commit: bool = True) -> None:
    """Create ChemVault operation log storage when needed."""
    cursor = connection.cursor()
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS {quote_identifier(OPERATION_LOG_TABLE)} (
            operation_id INTEGER PRIMARY KEY AUTOINCREMENT,
            operation_type TEXT NOT NULL,
            target_table TEXT,
            source_table TEXT,
            source_columns TEXT,
            output_columns TEXT,
            created_at TEXT NOT NULL,
            created_by TEXT,
            status TEXT NOT NULL,
            details TEXT,
            query_used TEXT
        )
    """)
    if commit:
        connection.commit()


def register_operation(
    connection,
    operation_type: str,
    target_table: str | None = None,
    source_table: str | None = None,
    source_columns=None,
    output_columns=None,
    created_by: str | None = None,
    status: str = "success",
    details: str | None = None,
    query_used: str | None = None,
    commit: bool = True,
) -> int:
    """Register a ChemVault database operation and return its log id."""
    if operation_type.strip() == "":
        raise ValueError("operation_type is required.")
    if status.strip() == "":
        raise ValueError("status is required.")

    ensure_operation_log(connection, commit=False)
    created_at = datetime.now(timezone.utc).isoformat()
    cursor = connection.cursor()
    cursor.execute(
        f"""
        INSERT INTO {quote_identifier(OPERATION_LOG_TABLE)}
            (
                operation_type,
                target_table,
                source_table,
                source_columns,
                output_columns,
                created_at,
                created_by,
                status,
                details,
                query_used
            )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            operation_type,
            target_table,
            source_table,
            _encode_optional_columns(source_columns),
            _encode_optional_columns(output_columns),
            created_at,
            created_by,
            status,
            details,
            query_used,
        ),
    )
    operation_id = int(cursor.lastrowid)
    if commit:
        connection.commit()
    return operation_id


def get_operation_log(db_path: Path) -> list[dict[str, object]]:
    """Return registered ChemVault operations, newest first."""
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    with sqlite3.connect(db_path) as con:
        if not _table_exists(con, OPERATION_LOG_TABLE):
            return []
        con.row_factory = sqlite3.Row
        cur = con.cursor()
        cur.execute(f"""
            SELECT
                operation_id,
                operation_type,
                target_table,
                source_table,
                source_columns,
                output_columns,
                created_at,
                created_by,
                status,
                details,
                query_used
            FROM {quote_identifier(OPERATION_LOG_TABLE)}
            ORDER BY operation_id DESC
        """)
        return [dict(row) for row in cur.fetchall()]


def register_table_metadata(
    connection,
    table_name: str,
    role: str,
    origin: str,
    source_table: str | None = None,
    created_by: str | None = None,
    query_used: str | None = None,
    notes: str | None = None,
    commit: bool = True,
) -> None:
    """Register a ChemVault table role and provenance."""
    ensure_table_metadata(connection, commit=False)
    created_at = datetime.now(timezone.utc).isoformat()
    cursor = connection.cursor()
    cursor.execute(
        f"""
        INSERT INTO {quote_identifier(METADATA_TABLE)}
            (table_name, role, origin, source_table, created_at, created_by, query_used, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(table_name) DO UPDATE SET
            role = excluded.role,
            origin = excluded.origin,
            source_table = excluded.source_table,
            created_by = excluded.created_by,
            query_used = excluded.query_used,
            notes = excluded.notes
        """,
        (
            table_name,
            role,
            origin,
            source_table,
            created_at,
            created_by,
            query_used,
            notes,
        ),
    )
    if commit:
        connection.commit()


def get_table_metadata(db_path: Path) -> dict[str, dict[str, object]]:
    """Return registered ChemVault table metadata keyed by table name."""
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    with sqlite3.connect(db_path) as con:
        if not _metadata_table_exists(con):
            return {}
        con.row_factory = sqlite3.Row
        cur = con.cursor()
        cur.execute(f"""
            SELECT table_name, role, origin, source_table, created_at, created_by, query_used, notes
            FROM {quote_identifier(METADATA_TABLE)}
            ORDER BY table_name
        """)
        return {row["table_name"]: dict(row) for row in cur.fetchall()}


def delete_user_table(connection, table_name: str, commit: bool = True) -> None:
    """Delete a user-facing table and its ChemVault metadata."""
    if table_name == "main":
        raise ValueError("The main table cannot be deleted.")
    if table_name in INTERNAL_TABLES or table_name.startswith("sqlite_"):
        raise ValueError("Internal SQLite or ChemVault tables cannot be deleted.")
    if not table_exists(connection, table_name):
        raise ValueError(f"Table not found: {table_name}")

    cursor = connection.cursor()
    cursor.execute(f"DROP TABLE {quote_identifier(table_name)}")
    if _metadata_table_exists(connection):
        cursor.execute(
            f"DELETE FROM {quote_identifier(METADATA_TABLE)} WHERE table_name = ?",
            (table_name,),
        )
    register_operation(
        connection,
        "table_deleted",
        target_table=table_name,
        created_by="delete_user_table",
        details="Deleted a user-facing table and its ChemVault metadata.",
        commit=False,
    )
    if commit:
        connection.commit()


def get_table_row_counts(db_path: Path) -> list[dict[str, int | str]]:
    """Return table names and row counts for a database."""
    return [
        {"table": table, "rows": count_rows(db_path, table)}
        for table in list_tables(db_path)
    ]


def get_database_schema(db_path: Path) -> list[dict[str, object]]:
    """Return tables with SQLite column metadata."""
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    schema = []
    with sqlite3.connect(db_path) as con:
        cur = con.cursor()
        for table in list_tables(db_path):
            cur.execute(f"PRAGMA table_info({quote_identifier(table)})")
            columns = []
            for column in cur.fetchall():
                cid, name, data_type, not_null, default_value, primary_key = column
                columns.append(
                    {
                        "cid": cid,
                        "name": name,
                        "data_type": data_type or "UNKNOWN",
                        "not_null": bool(not_null),
                        "default_value": default_value,
                        "primary_key": bool(primary_key),
                    }
                )
            schema.append({"table": table, "columns": columns})
    return schema


def get_table_schema(db_path: Path, table: str) -> dict[str, object]:
    """Return SQLite column metadata for one existing table."""
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    with sqlite3.connect(db_path) as con:
        if not _table_exists(con, table):
            raise ValueError(f"Table not found: {table}")
        cur = con.cursor()
        cur.execute(f"PRAGMA table_info({quote_identifier(table)})")
        columns = []
        for column in cur.fetchall():
            cid, name, data_type, not_null, default_value, primary_key = column
            columns.append(
                {
                    "cid": cid,
                    "name": name,
                    "data_type": data_type or "UNKNOWN",
                    "not_null": bool(not_null),
                    "default_value": default_value,
                    "primary_key": bool(primary_key),
                }
            )
    return {"table": table, "columns": columns}


def _classify_table_origin(table: str) -> str:
    normalized = table.lower()
    if normalized == "main":
        return "base"
    if "harmon" in normalized or "harmonsmile" in normalized:
        return "possible_harmonsmile"
    return "derived_inferred"


def _classify_table_status(
    table: str,
    rows: int,
    column_names: list[str],
    duplicate_candidates: set[str],
) -> list[str]:
    normalized = table.lower()
    normalized_columns = {column.lower().replace("_", "").replace(" ", "") for column in column_names}
    statuses = []

    if rows == 0 and len(column_names) == 0:
        statuses.append("empty")
    elif rows == 0:
        statuses.append("structure_only")
    else:
        statuses.append("ok")

    if 0 < len(column_names) <= 3:
        statuses.append("few_columns")
    if normalized.startswith("_temp") or "temp" in normalized or "stale" in normalized:
        statuses.append("possible_temporary")
    if "test" in normalized:
        statuses.append("possible_test_table")
    if {"cid", "smiles"}.issubset(normalized_columns) and len(column_names) <= 4:
        statuses.append("possible_harmonsmile_output")
    if table in duplicate_candidates:
        statuses.append("possible_duplicate")

    return statuses


def recommend_table_action(profile: dict[str, object]) -> str:
    """Return a conservative user-facing table action recommendation."""
    table = profile.get("table")
    statuses = set(profile.get("status", []))
    metadata_status = profile.get("metadata_status")

    if table == "main":
        return "Keep as base"
    if "empty" in statuses or "structure_only" in statuses:
        return "Review or delete"
    if "possible_temporary" in statuses or "possible_test_table" in statuses:
        return "Review cleanup"
    if "possible_duplicate" in statuses:
        return "Compare before use"
    if metadata_status == "inferred":
        return "Review provenance"
    return "Available"


def get_table_profiles(db_path: Path) -> list[dict[str, object]]:
    """Return inferred table profiles for database overview and management."""
    table_counts = {item["table"]: item["rows"] for item in get_table_row_counts(db_path)}
    schema = get_database_schema(db_path)
    table_metadata = get_table_metadata(db_path)
    signatures = {}

    for table_schema in schema:
        column_names = tuple(column["name"] for column in table_schema["columns"])
        signature = (table_counts[table_schema["table"]], column_names)
        signatures.setdefault(signature, []).append(table_schema["table"])

    duplicate_candidates = {
        table
        for tables in signatures.values()
        if len(tables) > 1
        for table in tables
    }

    profiles = []
    for table_schema in schema:
        table = table_schema["table"]
        columns = table_schema["columns"]
        column_names = [column["name"] for column in columns]
        rows = table_counts[table]
        metadata = table_metadata.get(table, {})
        origin = metadata.get("origin", _classify_table_origin(table))
        role = metadata.get("role", "base" if table == "main" else "derived")
        metadata_status = "registered" if metadata else "inferred"
        profiles.append(
            {
                "table": table,
                "rows": rows,
                "columns": len(columns),
                "column_names": column_names,
                "role": role,
                "origin": origin,
                "source_table": metadata.get("source_table"),
                "created_at": metadata.get("created_at"),
                "created_by": metadata.get("created_by"),
                "query_used": metadata.get("query_used"),
                "notes": metadata.get("notes"),
                "metadata_status": metadata_status,
                "status": _classify_table_status(
                    table,
                    rows,
                    column_names,
                    duplicate_candidates,
                ),
            }
        )
        profiles[-1]["recommended_action"] = recommend_table_action(profiles[-1])
    return profiles


def get_user_table_profiles(db_path: Path) -> list[dict[str, object]]:
    """Return profiles for user-facing ChemVault data tables only."""
    return [
        profile
        for profile in get_table_profiles(db_path)
        if profile["table"] not in INTERNAL_TABLES
    ]


def get_database_summary(db_path: Path) -> dict[str, object]:
    """Return structured database tables, row counts, and schema."""
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")
    return {
        "path": db_path,
        "tables": get_table_row_counts(db_path),
        "schema": get_database_schema(db_path),
        "profiles": get_table_profiles(db_path),
    }
