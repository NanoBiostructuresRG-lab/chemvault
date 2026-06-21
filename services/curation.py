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


def agregar_df_por_pk(df, pk, fk): # agregar dataframe por primary key
    conn = get_connection(st.session_state[DATABASE_ID])
    cursor = conn.cursor()
    table = st.session_state[CURRENT_TABLE]
    print(df)
    # agregar las columnas que vamos a agregar (excluyendo la llave foreign key)
    columnas_a_actualizar = [col for col in df.columns if col != fk]
    print(columnas_a_actualizar)
    if not columnas_a_actualizar:
        return False # No hay columnas nuevas que actualizar

    try:
        #Paso 1: Asegurarnos de que las columnas nuevas existan en la tabla 'main'
        # Buscamos qué columnas ya existen en 'main' para no duplicar errores
        cursor.execute(f"PRAGMA table_info({table})")
        columnas_existentes = [row[1] for row in cursor.fetchall()]

        for col in columnas_a_actualizar:
            if col not in columnas_existentes:
                cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col} TEXT")
        print("Columnas agregadas")

        #Paso 2: Subir el DataFrame actual a una tabla temporal
        temp_table_name = "_temp_updates"
        df.to_sql(temp_table_name, conn, if_exists="replace", index=False)

        # 4. Paso 3: Ejecutar el UPDATE masivo mediante un JOIN con la tabla temporal
        set_clause = ", ".join([f"{col} = (SELECT {col} FROM {temp_table_name} WHERE {temp_table_name}.{fk} = {table}.{pk})" for col in columnas_a_actualizar])

        # Solo actualizamos las filas donde realmente coincidan las llaves para no borrar datos existentes con NULLs
        update_query = f"""
            UPDATE {table}
            SET {set_clause}
            WHERE {pk} IN (SELECT {fk} FROM {temp_table_name})
        """
        print("Query construido")
        cursor.execute(update_query)
        print("query ejecutado")
        # 5. Paso 4: Limpieza de la tabla temporal y guardar cambios
        cursor.execute(f"DROP TABLE IF EXISTS {temp_table_name}")
        print("tabla eliminada")

        conn.commit()
        print("after commit")

        return True

    except Exception as e:
        conn.rollback()
        st.error(f"Error updating the database: {e}")
        return False
