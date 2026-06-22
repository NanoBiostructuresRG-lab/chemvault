# SPDX-License-Identifier: LGPL-3.0-or-later
import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.db_audit import (
    INTERNAL_TABLES,
    count_rows,
    get_database_schema,
    get_table_row_counts,
    list_database_files,
    list_tables,
)


def list_databases(directory: Path) -> int:
    """Print SQLite database files in a directory."""
    try:
        db_files = list_database_files(directory)
    except (FileNotFoundError, NotADirectoryError) as e:
        print(f"ERROR: {e}")
        return 1

    print(f"Directory: {directory.resolve()}")
    print()
    print("Databases found:")

    if not db_files:
        print("- No .db files found")
        return 0

    for db_file in db_files:
        print(f"- {db_file.name}")

    return 0


def inspect_database(db_path: Path) -> int:
    """Print all tables and row counts."""
    try:
        table_counts = get_table_row_counts(db_path)
    except FileNotFoundError as e:
        print(f"ERROR: {e}")
        return 1

    print(f"Database: {db_path.resolve()}")
    print()
    print("Tables found:")

    if not table_counts:
        print("- No tables found")
        return 0

    for table in table_counts:
        print(f"- {table['table']}: {table['rows']} rows")

    return 0


def inspect_schema(db_path: Path) -> int:
    """Print tables with column names and SQLite data types."""
    try:
        schema = get_database_schema(db_path)
    except FileNotFoundError as e:
        print(f"ERROR: {e}")
        return 1

    print(f"Database: {db_path.resolve()}")
    print()
    print("Schema:")

    if not schema:
        print("- No tables found")
        return 0

    for table in schema:
        print(f"- {table['table']}")
        if not table["columns"]:
            print("  - No columns found")
            continue
        for column in table["columns"]:
            parts = [column["name"], column["data_type"]]
            if column["primary_key"]:
                parts.append("PRIMARY KEY")
            if column["not_null"]:
                parts.append("NOT NULL")
            if column["default_value"] is not None:
                parts.append(f"DEFAULT {column['default_value']}")
            print(f"  - {' | '.join(parts)}")

    return 0


def assert_clean_database(
    db_path: Path,
    allowed_tables: list[str],
    expected_rows: dict[str, int],
) -> int:
    """Validate that a database contains only allowed tables and expected row counts."""
    try:
        tables = set(list_tables(db_path))
    except FileNotFoundError as e:
        print(f"ERROR: {e}")
        return 1

    allowed = set(allowed_tables) - INTERNAL_TABLES
    user_tables = tables - INTERNAL_TABLES

    unexpected = sorted(user_tables - allowed)
    missing = sorted(allowed - user_tables)

    ok = True

    print(f"Database: {db_path.resolve()}")
    print()

    if unexpected:
        ok = False
        print("Unexpected tables:")
        for table in unexpected:
            print(f"- {table}")

    if missing:
        ok = False
        print("Missing expected tables:")
        for table in missing:
            print(f"- {table}")

    for table, expected in expected_rows.items():
        if table not in user_tables:
            ok = False
            print(f"Cannot check rows for missing table: {table}")
            continue

        observed = count_rows(db_path, table)
        if observed != expected:
            ok = False
            print(
                f"Unexpected row count for {table}: "
                f"expected {expected}, observed {observed}"
            )
        else:
            print(f"Row count OK for {table}: {observed}")

    if ok:
        print()
        print("Database state OK.")
        return 0

    print()
    print("Database state FAILED.")
    return 1


def parse_expected_rows(values: list[str]) -> dict[str, int]:
    """Parse table=row_count arguments."""
    flattened = [
        item
        for value in values
        for item in (value if isinstance(value, list) else [value])
    ]
    parsed = {}

    for value in flattened:
        if "=" not in value:
            raise ValueError(f"Invalid --expect-row value: {value}. Use table=count.")

        table, count_text = value.split("=", 1)
        parsed[table] = int(count_text)

    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit ChemVault SQLite databases.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="List .db files in a directory.")
    list_parser.add_argument("directory", type=Path)

    inspect_parser = subparsers.add_parser("inspect", help="List tables and row counts.")
    inspect_parser.add_argument("db", type=Path)

    schema_parser = subparsers.add_parser("schema", help="List tables, columns, and data types.")
    schema_parser.add_argument("db", type=Path)

    assert_parser = subparsers.add_parser(
        "assert-clean",
        help="Validate expected DB state.",
    )
    assert_parser.add_argument("db", type=Path)
    assert_parser.add_argument("--allowed", nargs="+", required=True)
    assert_parser.add_argument("--expect-row", action="append", nargs="+", default=[])

    args = parser.parse_args()

    if args.command == "list":
        return list_databases(args.directory)

    if args.command == "inspect":
        return inspect_database(args.db)

    if args.command == "schema":
        return inspect_schema(args.db)

    if args.command == "assert-clean":
        expected_rows = parse_expected_rows(args.expect_row)
        return assert_clean_database(args.db, args.allowed, expected_rows)

    raise RuntimeError(f"Unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
