# ============================================================
# python tools\db_audit.py inspect SQL\harmonsmile_test_01.db
# python tools\db_audit.py assert-clean SQL\harmonsmile_test_01.db --allowed main sqlite_sequence --expect-row main=102
# ============================================================
import argparse
import sqlite3
from pathlib import Path


def quote_identifier(name: str) -> str:
    """Safely quote a SQLite identifier."""
    return '"' + name.replace('"', '""') + '"'


def list_tables(db_path: Path) -> list[str]:
    """Return SQLite tables ordered by name."""
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
    with sqlite3.connect(db_path) as con:
        cur = con.cursor()
        cur.execute(f"SELECT COUNT(*) FROM {quote_identifier(table)}")
        return int(cur.fetchone()[0])


def inspect_database(db_path: Path) -> int:
    """Print all tables and row counts."""
    if not db_path.exists():
        print(f"ERROR: database not found: {db_path}")
        return 1

    print(f"Database: {db_path.resolve()}")
    print()
    print("Tables found:")

    tables = list_tables(db_path)

    if not tables:
        print("- No tables found")
        return 0

    for table in tables:
        rows = count_rows(db_path, table)
        print(f"- {table}: {rows} rows")

    return 0


def assert_clean_database(
    db_path: Path,
    allowed_tables: list[str],
    expected_rows: dict[str, int],
) -> int:
    """Validate that a database contains only allowed tables and expected row counts."""
    if not db_path.exists():
        print(f"ERROR: database not found: {db_path}")
        return 1

    tables = set(list_tables(db_path))
    allowed = set(allowed_tables)

    unexpected = sorted(tables - allowed)
    missing = sorted(allowed - tables)

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
        if table not in tables:
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
    parsed = {}

    for value in values:
        if "=" not in value:
            raise ValueError(f"Invalid --expect-row value: {value}. Use table=count.")

        table, count_text = value.split("=", 1)
        parsed[table] = int(count_text)

    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit ChemVault SQLite databases.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser("inspect", help="List tables and row counts.")
    inspect_parser.add_argument("db", type=Path)

    assert_parser = subparsers.add_parser(
        "assert-clean",
        help="Validate expected DB state.",
    )
    assert_parser.add_argument("db", type=Path)
    assert_parser.add_argument("--allowed", nargs="+", required=True)
    assert_parser.add_argument("--expect-row", nargs="*", default=[])

    args = parser.parse_args()

    if args.command == "inspect":
        return inspect_database(args.db)

    if args.command == "assert-clean":
        expected_rows = parse_expected_rows(args.expect_row)
        return assert_clean_database(args.db, args.allowed, expected_rows)

    raise RuntimeError(f"Unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
