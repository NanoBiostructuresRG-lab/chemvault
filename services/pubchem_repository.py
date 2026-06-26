# SPDX-License-Identifier: LGPL-3.0-or-later

COMPOUND_ASSAYS_TABLE = "compound_assays"
MAIN_TABLE = "main"
SQLITE_WRITE_CHUNK_SIZE = 5000


def _ensure_column(cursor, table, column, column_type="TEXT"):
    columns = [row[1] for row in cursor.execute(f"PRAGMA table_info({table})").fetchall()]
    if column not in columns:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")


def _ensure_compound_assays_table(cursor):
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS {COMPOUND_ASSAYS_TABLE} (
            CID TEXT NOT NULL,
            AID TEXT NOT NULL,
            Protein TEXT NOT NULL,
            UNIQUE(CID, AID, Protein)
        )
    """)


def ensure_pubchem_search_schema(connection, table=MAIN_TABLE):
    cursor = connection.cursor()
    _ensure_column(cursor, table, "CID")
    _ensure_column(cursor, table, "AIDs")
    _ensure_column(cursor, table, "Proteins")
    _ensure_column(cursor, table, "Compound_Name")
    _ensure_column(cursor, table, "Activity_Enrichment_Status")
    _ensure_compound_assays_table(cursor)
    cursor.execute(f"""
    CREATE UNIQUE INDEX IF NOT EXISTS idx_cid_unique
    ON {table}(CID)
    """)
    connection.commit()


def _join_values(values):
    clean_values = [str(value).strip() for value in values if str(value).strip()]
    return ", ".join(sorted(set(clean_values)))


def _batched(values, size):
    values = list(values)
    for index in range(0, len(values), size):
        yield values[index:index + size]


def iter_main_record_chunks(records, chunk_size=SQLITE_WRITE_CHUNK_SIZE):
    yield from _batched(records.items(), chunk_size)


def upsert_main_records_chunk(connection, records_chunk, table=MAIN_TABLE):
    main_upsert_sql = f"""
    INSERT INTO {table}
    (CID, AIDs, Proteins, Compound_Name, Activity_Enrichment_Status)
    VALUES (?, ?, ?, ?, ?)
    ON CONFLICT(CID) DO UPDATE SET
        AIDs = excluded.AIDs,
        Proteins = excluded.Proteins,
        Compound_Name = COALESCE(NULLIF({table}.Compound_Name, ''), excluded.Compound_Name),
        Activity_Enrichment_Status = excluded.Activity_Enrichment_Status
    """
    main_rows = [
        (
            cid,
            _join_values(record["aids"]),
            _join_values(record["proteins"]),
            record["compound_name"],
            record["activity_status"],
        )
        for cid, record in records_chunk
    ]
    connection.cursor().executemany(main_upsert_sql, main_rows)
    return len(main_rows)


def count_compound_assay_rows(records):
    return sum(len(record["assays"]) for record in records.values())


def iter_compound_assay_chunks(records, chunk_size=SQLITE_WRITE_CHUNK_SIZE):
    assay_buffer = []
    for record in records.values():
        assay_buffer.extend(record["assays"])

        if len(assay_buffer) >= chunk_size:
            yield assay_buffer
            assay_buffer = []

    if assay_buffer:
        yield assay_buffer


def insert_compound_assays_chunk(connection, assay_rows):
    compound_assays_insert_sql = f"""
    INSERT OR IGNORE INTO {COMPOUND_ASSAYS_TABLE}
    (CID, AID, Protein)
    VALUES (?, ?, ?)
    """
    connection.cursor().executemany(compound_assays_insert_sql, assay_rows)
    return len(assay_rows)
