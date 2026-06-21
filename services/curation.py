import streamlit as st

from modules.use_chamanp import use_chamanp
from modules.use_harmonsmile import use_PubchemIngest
from services.database import get_connection
from state_keys import CURRENT_TABLE, DATABASE_ID


def is_cid_header(header):
    normalized = str(header).strip().lower().replace("_", "").replace("-", "").replace(" ", "")
    return normalized in {"cid", "cids", "pubchemcid", "pubchemcids", "compoundcid", "compoundcids"}


def run_harmonsmile(selected_columns_df):
    return use_PubchemIngest(selected_columns_df)


def run_chamanp(selected_columns_df, identifier_col, smiles_col, collections_col):
    return use_chamanp(selected_columns_df, identifier_col, smiles_col, collections_col)


def agregar_df_por_pk(df, pk, fk):
    conn = get_connection(st.session_state[DATABASE_ID])
    cursor = conn.cursor()
    table = st.session_state[CURRENT_TABLE]
    print(df)
    columnas_a_actualizar = [col for col in df.columns if col != fk]
    print(columnas_a_actualizar)
    if not columnas_a_actualizar:
        return False

    try:
        # Ensure update columns exist before writing values into the active table.
        cursor.execute(f"PRAGMA table_info({table})")
        columnas_existentes = [row[1] for row in cursor.fetchall()]

        for col in columnas_a_actualizar:
            if col not in columnas_existentes:
                cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col} TEXT")
        print("Columnas agregadas")

        temp_table_name = "_temp_updates"
        df.to_sql(temp_table_name, conn, if_exists="replace", index=False)

        set_clause = ", ".join([
            f"{col} = (SELECT {col} FROM {temp_table_name} "
            f"WHERE {temp_table_name}.{fk} = {table}.{pk})"
            for col in columnas_a_actualizar
        ])

        # Only update rows with matching keys to avoid replacing existing values with NULL.
        update_query = f"""
            UPDATE {table}
            SET {set_clause}
            WHERE {pk} IN (SELECT {fk} FROM {temp_table_name})
        """
        print("Query construido")
        cursor.execute(update_query)
        print("query ejecutado")
        cursor.execute(f"DROP TABLE IF EXISTS {temp_table_name}")
        print("tabla eliminada")

        conn.commit()
        print("after commit")

        return True

    except Exception as e:
        conn.rollback()
        st.error(f"Error updating the database: {e}")
        return False
