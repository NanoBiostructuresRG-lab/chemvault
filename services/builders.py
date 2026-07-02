# SPDX-License-Identifier: LGPL-3.0-or-later
import os

import pandas as pd

from services.pubchem_protein_search import obtener_CIDs_Pubchem
from services.database_core import get_connection
from services.db_audit import register_operation, register_table_metadata
from services.pubchem_job_service import (
    register_protein_search_build,
    start_pubchem_search,
)


def build_from_csv(uploaded_file, database_id, current_table=""):
    if os.path.isfile(f"SQL/{database_id}.db"):
        try:
            os.remove(f"SQL/{database_id}.db")
        except PermissionError:
            pass
    conn = get_connection(database_id)
    cursor = conn.cursor()

    table = current_table or "main"

    df = pd.read_csv(uploaded_file)

    df.columns = [col.strip().replace(" ", "_") for col in df.columns]

    cursor.execute(f"""
        DROP TABLE IF EXISTS {table}
        """)
    conn.commit()

    cursor.execute(f"""
        CREATE TABLE {table} (
            primary_id INTEGER PRIMARY KEY AUTOINCREMENT
        )
    """)

    for col in df.columns:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col} TEXT")

    cols_str = ", ".join([f"'{col}'" for col in df.columns])
    placeholders = ", ".join(["?"] * len(df.columns))
    cursor.executemany(
        f"INSERT INTO {table} ({cols_str}) VALUES ({placeholders})",
        df.astype(str).values.tolist()
    )

    conn.commit()
    register_table_metadata(
        conn,
        table,
        role="base",
        origin="csv_upload",
        created_by="build_from_csv",
        notes=f"Source file: {getattr(uploaded_file, 'name', 'uploaded CSV')}.",
    )
    register_operation(
        conn,
        "csv_loaded",
        target_table=table,
        output_columns=["primary_id", *df.columns.tolist()],
        created_by="build_from_csv",
        details=f"Loaded {len(df)} rows from {getattr(uploaded_file, 'name', 'uploaded CSV')}.",
    )
    return table


def build_from_proteins(database_id, selected_proteins, progreso):
    conn = get_connection(database_id)
    proteins = list(selected_proteins)
    obtener_CIDs_Pubchem(conn, proteins, progreso)
    register_protein_search_build(conn, proteins)
    return "main"


def launch_protein_search_job(database_id, selected_proteins):
    job, db_path = start_pubchem_search(database_id, list(selected_proteins))
    return job, db_path, "main"


def run_protein_search(database_id, selected_proteins, progreso=None):
    return launch_protein_search_job(database_id, selected_proteins)
