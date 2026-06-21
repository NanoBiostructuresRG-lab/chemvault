import os

import pandas as pd
import streamlit as st

from modules.obtener_CIDs_Pubchem import obtener_CIDs_Pubchem
from services.database import get_connection
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

    ### para eliminar errores de duplicados de keys, se hace un drop
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

    # insertar datos
    cols_str = ", ".join([f"'{col}'" for col in df.columns])
    placeholders = ", ".join(["?"] * len(df.columns))
    cursor.executemany(
        f"INSERT INTO {table} ({cols_str}) VALUES ({placeholders})",
        df.astype(str).values.tolist()
    )

    conn.commit()


def build_from_proteins(progreso):
    st.session_state[CURRENT_TABLE] = "main"
    obtener_CIDs_Pubchem(
        get_connection(st.session_state[DATABASE_ID]),
        st.session_state[SELECTED_PROTEINS],
        progreso,
    )
