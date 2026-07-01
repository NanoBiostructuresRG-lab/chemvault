# SPDX-License-Identifier: LGPL-3.0-or-later
import os
from pathlib import Path

import pandas as pd
import streamlit as st

from services.pubchem_protein_search import obtener_CIDs_Pubchem
from services.database import get_connection
from services.db_audit import register_operation, register_table_metadata
from services.job_launcher import (
    create_and_launch_pubchem_job,
    resolve_database_path,
)
from state_keys import CURRENT_TABLE, DATABASE_ID, SELECTED_PROTEINS, SET_TEXT_INPUT_LOCKED


def build_from_csv(uploaded_file):
    if os.path.isfile(f"SQL/{st.session_state[DATABASE_ID]}.db"):
        try:
            os.remove(f"SQL/{st.session_state[DATABASE_ID]}.db")
        except PermissionError:
            pass
    conn = get_connection(st.session_state[DATABASE_ID])
    cursor = conn.cursor()

    if st.session_state[CURRENT_TABLE] == "":
        st.session_state[CURRENT_TABLE] = "main"
    table = st.session_state[CURRENT_TABLE]

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


def register_protein_search_build(connection, proteins):
    register_table_metadata(
        connection,
        "main",
        role="base",
        origin="protein_search",
        created_by="build_from_proteins",
        notes="Initial table created from selected proteins.",
    )
    register_operation(
        connection,
        "protein_search_loaded",
        target_table="main",
        output_columns=[
            "CID",
            "AIDs",
            "Proteins",
            "Compound_Name",
            "Activity_Enrichment_Status",
        ],
        created_by="build_from_proteins",
        details=f"Loaded selected proteins: {', '.join(map(str, proteins))}.",
    )


def build_from_proteins(progreso):
    st.session_state[CURRENT_TABLE] = "main"
    conn = get_connection(st.session_state[DATABASE_ID])
    proteins = list(st.session_state[SELECTED_PROTEINS])
    obtener_CIDs_Pubchem(conn, proteins, progreso)
    register_protein_search_build(conn, proteins)


def launch_protein_search_job():
    st.session_state[CURRENT_TABLE] = "main"
    database_id = st.session_state[DATABASE_ID]
    proteins = list(st.session_state[SELECTED_PROTEINS])
    db_path = Path("SQL") / f"{database_id}.db"
    conn = get_connection(database_id)
    try:
        job = create_and_launch_pubchem_job(
            conn,
            db_path,
            proteins,
            database_id=database_id,
        )
    finally:
        conn.close()
    return job, resolve_database_path(db_path)


def run_protein_search(progreso, use_worker_mode=False):
    if use_worker_mode:
        return launch_protein_search_job()
    build_from_proteins(progreso)
    return None
