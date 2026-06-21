import html
import streamlit as st
import pandas as pd
import numpy as np
import sqlite3
import os
from PIL import Image
from modules.obtener_CIDs_Pubchem import obtener_CIDs_Pubchem
from modules.use_harmonsmile import use_PubchemIngest
from modules.use_chamanp import use_chamanp



def get_connection(db_name):
    return sqlite3.connect(f"SQL/{db_name}.db", check_same_thread=False)


def quote_identifier(identifier):
    """Quote a SQLite identifier such as a table or column name."""
    return '"' + str(identifier).replace('"', '""') + '"'


def is_valid_table_name(table_name):
    if not table_name:
        return False
    return str(table_name).replace("_", "").isalnum() and not str(table_name)[0].isdigit()


def is_cid_header(header):
    normalized = str(header).strip().lower().replace("_", "").replace("-", "").replace(" ", "")
    return normalized in {"cid", "cids", "pubchemcid", "pubchemcids", "compoundcid", "compoundcids"}


def get_active_selected_headers():
    headers = st.session_state.get("headers", [])
    selected = st.session_state.get("selected_headers", [])
    return [col for col in selected if col in headers]


def sync_selected_headers():
    st.session_state["selected_headers"] = get_active_selected_headers()


def table_exists(connection, table_name):
    cursor = connection.cursor()
    cursor.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    )
    return cursor.fetchone() is not None


def get_tables_from_connection(connection):
    cursor = connection.cursor()
    cursor.execute("""
        SELECT name
        FROM sqlite_master
        WHERE type='table'
        AND name NOT LIKE 'sqlite_%'
        ORDER BY name
    """)
    return [row[0] for row in cursor.fetchall()]


def ensure_main_table(connection):
    cursor = connection.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS "main" (
            primary_id INTEGER PRIMARY KEY AUTOINCREMENT
        )
    ''')
    connection.commit()


def count_rows_group_by(connection):
    group_col = st.session_state.get("grupo_a_contar", "")
    table = st.session_state.get("current_table", "")
    if group_col == "" or table == "":
        return 0
    if group_col not in st.session_state.get("headers", []):
        return 0
    cursor = connection.cursor()
    cursor.execute(f"""
        SELECT COUNT(*)
        FROM (
            SELECT {quote_identifier(group_col)}
            FROM {quote_identifier(table)}
            GROUP BY {quote_identifier(group_col)}
        )
    """)
    return cursor.fetchone()[0]


def count_rows(connection):
    table = st.session_state.get("current_table", "")
    if table == "" or not table_exists(connection, table):
        return 0
    cursor = connection.cursor()
    cursor.execute(f"SELECT COUNT(*) FROM {quote_identifier(table)}")
    return cursor.fetchone()[0]

@st.dialog("Seleccionar Proteínas", dismissible=False )
def select_proteins():
    st.write("Buscar CIDs por BioAssayss, usando proteína como target")
    st.text_input(label="Protein", key="input_protein",value="P34971")
    if st.button("Agregar a selección"):
        st.session_state["selected_proteins"].append(st.session_state["input_protein"])
        st.markdown(f"Tus proteinas: {st.session_state["selected_proteins"]}.")
    if st.button("Confirmar selección"):
        if len(st.session_state["selected_proteins"]) == 0:
            st.toast("Selecciona al menos una proteína")
            print("Selecciona al menos una proteína")
        elif st.session_state["database_id"] == "":
            st.toast("Primero, ingresa un nombre para tu SQL Database")
            print("Primero, ingresa un nombre para tu SQL Database")

        else:
            progreso = st.progress(0)
            st.toast(f"Construyendo base de datos con proteínas: {st.session_state["selected_proteins"]}")
            build_from_proteins(progreso)
            update_headers()
        st.rerun()
    if st.button("Cancelar"):
        st.session_state["selected_proteins"] = []
        st.rerun()  






### setup SQL ###
def set_database_id():
    db_name = st.session_state.get("input_database_id", "").strip()
    if db_name == "":
        st.toast("Ingresa un nombre para tu SQL Database")
        return
    st.session_state["database_id"] = db_name
    st.session_state["set_text_input_locked"] = True
    st.session_state["current_table"] = "main"
    st.session_state["selected_headers"] = []
    conn = get_connection(st.session_state["database_id"])
    ensure_main_table(conn)
    update_headers()
    st.toast(f"SQL Database set to {st.session_state['database_id']}")


def load_existing_database():
    db_name = st.session_state.get("existing_db_select", "")
    if db_name == "":
        return
    st.session_state["database_id"] = db_name
    st.session_state["set_text_input_locked"] = True
    st.session_state["selected_headers"] = []
    conn = get_connection(db_name)
    tables = get_tables_from_connection(conn)
    if not tables:
        ensure_main_table(conn)
        tables = get_tables_from_connection(conn)
    st.session_state["current_table"] = "main" if "main" in tables else tables[0]
    update_headers()


def get_tables():
    if st.session_state.get("database_id", "") == "":
        st.session_state["all_tables"] = []
        return []
    db_path = f"SQL/{st.session_state['database_id']}.db"
    if not os.path.isfile(db_path):
        st.session_state["all_tables"] = []
        return []
    conn = get_connection(st.session_state["database_id"])
    tables = get_tables_from_connection(conn)
    st.session_state["all_tables"] = tables
    return tables


def update_headers():
    if st.session_state.get("database_id", "") == "":
        st.session_state["headers"] = []
        st.session_state["all_tables"] = []
        st.session_state["current_table"] = ""
        st.session_state["selected_headers"] = []
        return []

    conn = get_connection(st.session_state["database_id"])
    tables = get_tables_from_connection(conn)
    st.session_state["all_tables"] = tables

    if not tables:
        st.session_state["headers"] = []
        st.session_state["current_table"] = ""
        st.session_state["selected_headers"] = []
        return []

    if st.session_state.get("current_table", "") not in tables:
        st.session_state["current_table"] = "main" if "main" in tables else tables[0]

    table = st.session_state["current_table"]
    cursor = conn.cursor()
    cursor.execute(f"PRAGMA table_info({quote_identifier(table)})")
    columns_info = cursor.fetchall()
    headers = [col[1] for col in columns_info]
    st.session_state["headers"] = headers
    sync_selected_headers()
    return headers
#st.session_state['all_tables']
def build_from_csv(uploaded_file):
    if os.path.isfile(f"SQL/{st.session_state['database_id']}.db"):
        try:
            os.remove(f"SQL/{st.session_state['database_id']}.db")
        except PermissionError:
            pass
    conn = get_connection(st.session_state["database_id"])
    cursor = conn.cursor()

    if st.session_state["current_table"] == "":
        st.session_state["current_table"] = "main"
    table = st.session_state["current_table"]

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
    st.session_state["current_table"] = "main"
    obtener_CIDs_Pubchem(get_connection(st.session_state["database_id"]),st.session_state["selected_proteins"],progreso)

def export_table():
    if st.session_state.get("database_id", "") == "" or st.session_state.get("current_table", "") == "":
        return pd.DataFrame().to_csv(index=False).encode("utf-8")

    conn = get_connection(st.session_state["database_id"])
    table = st.session_state["current_table"]
    selected_headers = get_active_selected_headers()

    if len(selected_headers) == 0:
        query = f"SELECT * FROM {quote_identifier(table)}"
    else:
        cols = ", ".join(quote_identifier(col) for col in selected_headers)
        query = f"SELECT {cols} FROM {quote_identifier(table)}"

    df = pd.read_sql_query(query, conn)
    return df.to_csv(index=False).encode("utf-8")


def export_table_by_sub_grupo(codigo_buscar: str, columna_filtro: str):
    if st.session_state.get("database_id", "") == "" or st.session_state.get("current_table", "") == "":
        return pd.DataFrame().to_csv(index=False).encode("utf-8")
    if columna_filtro not in st.session_state.get("headers", []):
        return pd.DataFrame().to_csv(index=False).encode("utf-8")

    conn = get_connection(st.session_state["database_id"])
    table = st.session_state["current_table"]
    selected_headers = get_active_selected_headers()

    if len(selected_headers) == 0:
        cols = "*"
    else:
        cols = ", ".join(quote_identifier(col) for col in selected_headers)

    query = f"""
        SELECT {cols}
        FROM {quote_identifier(table)}
        WHERE {quote_identifier(columna_filtro)} LIKE ?
    """

    df = pd.read_sql_query(query, conn, params=[f"%{codigo_buscar}%"])
    return df.to_csv(index=False).encode("utf-8")


def build_preview_table():
    if st.session_state.get("database_id", "") == "" or st.session_state.get("current_table", "") == "":
        return pd.DataFrame()

    selected_headers = get_active_selected_headers()
    if len(selected_headers) == 0:
        return pd.DataFrame()

    conn = get_connection(st.session_state["database_id"])
    table = st.session_state["current_table"]
    cols = ", ".join(quote_identifier(col) for col in selected_headers)
    query = f"SELECT {cols} FROM {quote_identifier(table)} LIMIT 10"
    return pd.read_sql_query(query, conn)


def get_selected_columns(): #diferencia entre build_preview_table es que esta no tiene limite de 10
    if st.session_state.get("database_id", "") == "" or st.session_state.get("current_table", "") == "":
        return pd.DataFrame()

    selected_headers = get_active_selected_headers()
    if len(selected_headers) == 0:
        return pd.DataFrame()

    conn = get_connection(st.session_state["database_id"])
    table = st.session_state["current_table"]
    cols = ", ".join(quote_identifier(col) for col in selected_headers)
    query = f"SELECT {cols} FROM {quote_identifier(table)}"
    return pd.read_sql_query(query, conn)

def agregar_df_por_pk(df, pk, fk): # agregar dataframe por primary key
    conn = get_connection(st.session_state["database_id"])
    cursor = conn.cursor()
    table = st.session_state["current_table"]
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
        st.error(f"Error al actualizar la base de datos: {e}")
        return False

### Definicion session state vars
def verify_directories():
    if not os.path.exists("SQL"):
        os.makedirs("SQL")
    if not os.path.exists("artifacts"):
        os.makedirs("artifacts")
    else:
        files = os.listdir("artifacts")  
        for file_name in files:
            file_path = os.path.join("artifacts", file_name)
            if os.path.isfile(file_path):
                try:
                    os.remove(file_path)
                except PermissionError:
                    pass
    if not os.path.exists("tempFilesChamanp"):
        os.makedirs("tempFilesChamanp")
    if not os.path.exists("tempFilesHarmonsile"):
        os.makedirs("tempFilesHarmonsile")


if "database_id" not in st.session_state: ##aqui tambien verifico y creo las carpetas para sql, harmonsmile y chamanp
    verify_directories()
    st.session_state["database_id"] = ""

if "set_text_input_locked" not in st.session_state:
    st.session_state["set_text_input_locked"] = False

if "headers" not in st.session_state: 
    st.session_state["headers"] = []

if "selected_headers" not in st.session_state: 
    st.session_state["selected_headers"] = []

if "selected_proteins" not in st.session_state: 
    st.session_state["selected_proteins"] = []

if "current_table" not in st.session_state: 
    st.session_state["current_table"] = ""

if "all_tables" not in st.session_state: 
    st.session_state["all_tables"] =[]

if "grupo_a_contar" not in st.session_state: 
    st.session_state["grupo_a_contar"] =""

if "custom_query" not in st.session_state:
    st.session_state["custom_query"] = ""

### Decor ###
logo = Image.open("assets/logo.jpeg")

# Configuración de página
st.set_page_config(
    page_title="Curador",
    page_icon=logo,
    layout="wide"
)

### SIDE BAR MENU ###
#variables de estado

if "selecting_harmonsmile" not in st.session_state:
    st.session_state["selecting_harmonsmile"] = ""
if "selecting_chamanp" not in st.session_state:
    st.session_state["selecting_chamanp"] = ""

# Mantiene database_id/current_table/headers sincronizados antes de construir la sidebar.
# Esto evita que Export/Curado/Depurado lean un estado previo y luego el cuerpo principal
# muestre una tabla distinta ya corregida por update_headers().
if st.session_state.get("database_id", "") != "":
    update_headers()
else:
    sync_selected_headers()

def set_curados_false():
    st.session_state["selecting_harmonsmile"] = False 
    st.session_state["selecting_chamanp"] = False 


def clear_depurado_preview():
    st.session_state["custom_query"] = ""

def construir_linea_query():
    new_table_name = st.session_state.get("new_table_name", "").strip()
    selected_headers = get_active_selected_headers()
    current_table = st.session_state.get("current_table", "")

    if not is_valid_table_name(new_table_name):
        raise ValueError("Ingresa un nombre de tabla válido: usa letras, números y guiones bajos; no empieces con número.")
    if current_table == "":
        raise ValueError("Selecciona una tabla fuente antes de crear una nueva tabla.")
    if len(selected_headers) == 0:
        raise ValueError("Selecciona al menos una columna para crear una nueva tabla.")

    cols = ", ".join(quote_identifier(col) for col in selected_headers)
    base_query = f"""
    CREATE TABLE {quote_identifier(new_table_name)} AS
    SELECT {cols} FROM {quote_identifier(current_table)}
    """
    filter_clause = ""
    match st.session_state.get("type_of_filter", "Ninguno"):
        case "Ninguno":
            pass
        case "GROUP BY":
            group_col = st.session_state.get("group_by_column", "")
            if group_col not in selected_headers:
                raise ValueError("La columna de GROUP BY debe estar dentro de las columnas seleccionadas.")
            filter_clause = f"GROUP BY {quote_identifier(group_col)}"
        case "WHERE":
            where_col = st.session_state.get("where_column", "")
            condition = st.session_state.get("where_condition", "").strip()
            if where_col not in st.session_state.get("headers", []):
                raise ValueError("Selecciona una columna válida para WHERE.")
            if condition == "":
                raise ValueError("Escribe una condición WHERE.")
            filter_clause = f"WHERE {quote_identifier(where_col)} {condition}"
        case "ORDER BY":
            order_col = st.session_state.get("order_by_column", "")
            direction = st.session_state.get("order_direction", "ASC")
            if order_col not in selected_headers:
                raise ValueError("La columna de ORDER BY debe estar dentro de las columnas seleccionadas.")
            filter_clause = f"ORDER BY {quote_identifier(order_col)} {direction}"
    return base_query + filter_clause

with st.sidebar:
    st.header("Acciones")
    #Construccion
    if st.session_state["current_table"] == "" or (st.session_state["database_id"] != "" and count_rows(get_connection(st.session_state["database_id"])) == 0):
        st.subheader("Construcción")
            ### por proteina ###
        if st.button("Buscar Proteínas") : select_proteins()
            ### por csv ###
        uploaded_file = st.file_uploader("Sube un CSV", type=["csv"])
        if uploaded_file != None:
                st.session_state["set_text_input_locked"] = True
                db_name = uploaded_file.name.replace(".csv", "")
                st.session_state["database_id"] = db_name
                st.session_state["current_table"] = "main"
                build_from_csv(uploaded_file)
                update_headers()
                st.rerun()
    else:#Depurado
        st.subheader("Depurado")
        st.text_input(label="Nombre", key="new_table_name", value="Nueva_tabla", on_change=clear_depurado_preview)
        st.selectbox("Filtrado Adicional", ["Ninguno", "GROUP BY", "WHERE", "ORDER BY"], key="type_of_filter", on_change=clear_depurado_preview)
        match st.session_state["type_of_filter"]:
            case "Ninguno":
                pass
            case "GROUP BY":
                st.selectbox("Columna a agrupar", st.session_state["selected_headers"], key="group_by_column", on_change=clear_depurado_preview)
            case "WHERE":
                st.selectbox("Columna a condicionar", st.session_state["headers"], key="where_column", on_change=clear_depurado_preview)
                st.text_input("Condición (ejemplo: > 100, = 'HarmonSmile', etc)", key="where_condition", on_change=clear_depurado_preview)
            case "ORDER BY":
                st.selectbox("Columna a ordenar", st.session_state["selected_headers"], key="order_by_column", on_change=clear_depurado_preview)
                st.selectbox("Ascendente o Descendente", ["ASC", "DESC"], key="order_direction", on_change=clear_depurado_preview)
        if st.button("Preview SQL"):
            try:
                st.session_state["custom_query"] = construir_linea_query()
            except ValueError as e:
                st.session_state["custom_query"] = ""
                st.error(str(e))
        if st.session_state.get("custom_query", "") != "":
            compact_query = html.escape(" ".join(st.session_state["custom_query"].split()))
            st.markdown("**SQL preview**")
            st.markdown(
                f'''
                <div style="background-color:#111827; color:#f9fafb; padding:0.85rem 1rem;
                            border-radius:0.55rem; font-family:monospace; font-size:0.9rem;
                            line-height:1.5; overflow-x:auto; margin-bottom:0.85rem;">
                    {compact_query}
                </div>
                ''',
                unsafe_allow_html=True,
            )

        if st.button("Crear Nueva Tabla con selección actual"):
            conn = get_connection(st.session_state["database_id"])
            cursor = conn.cursor()
            try:
                query_to_run = construir_linea_query()
                new_table_name = st.session_state["new_table_name"].strip()
                if table_exists(conn, new_table_name):
                    raise ValueError(f"La tabla '{new_table_name}' ya existe. Usa otro nombre o elimínala primero.")
                cursor.execute(query_to_run)
                conn.commit()
                st.session_state["current_table"] = new_table_name
                st.session_state["selected_headers"] = []
                st.session_state["custom_query"] = query_to_run
                update_headers()
                st.session_state["depurado_success_table"] = new_table_name
                st.session_state["depurado_success_message"] = f"Table '{new_table_name}' was created successfully."
                st.rerun()
            except Exception as e:
                conn.rollback()
                st.error(f"No se pudo crear la tabla: {e}")
        
        created_table = st.session_state.get("depurado_success_table", "")
        if created_table and created_table == st.session_state.get("current_table", ""):
            st.success(st.session_state.get("depurado_success_message", f"Table '{created_table}' was created successfully."))

#falta agregar order by
#hacer un text box que muestre el query
        
    st.subheader("Curado")
    if st.button("HARMONSMILE"): 
        set_curados_false()
        st.session_state["selecting_harmonsmile"] = True 
    if st.button("CHAMANP"): 
        set_curados_false()
        st.session_state["selecting_chamanp"] = True 
    
    #procesos
    if st.session_state["selecting_harmonsmile"]:
        selected_headers = get_active_selected_headers()
        if len(selected_headers) == 0:
            st.warning("Select the CID column before running HARMONSMILE.")
        elif len(selected_headers) > 1:
            st.warning("HARMONSMILE requires exactly one column: CID.")
        elif not is_cid_header(selected_headers[0]):
            st.warning(f"Selected column is '{selected_headers[0]}'. HARMONSMILE requires a valid CID column.")
        else:
            if st.button("Run"):
                try:
                    new_table_df = use_PubchemIngest(get_selected_columns())
                except ValueError as e:
                    st.toast(str(e))
                    st.error(str(e))
                    new_table_df = None
                #new_table_df = pd.read_csv("tempFilesHarmonsile/res_pubchem_harmonized.csv")#use_PubchemIngest(get_selected_columns())
                #new_table_df.columns = ( #preparamos los datos para ser procesados por sql
                #    new_table_df.columns
                #    .str.replace(" ", "_", regex=False)
                #    .str.replace(":", "", regex=False)
                #)
                
                #NOTA: asumo que la fk de la tabla regresada siempre incluye Pubchem CID
                if new_table_df is not None:
                    if agregar_df_por_pk(new_table_df, selected_headers[0], "PubChem_CID"):
                        st.toast("HarmonSmile completed successfully")
                    else:
                        st.toast("HarmonSmile failed")
                    update_headers()
                    st.rerun()

    if st.session_state["selecting_chamanp"]:
        st.text("Selecciona las columnas a procesar")
        st.text(f"Columnas Seleccionadas : {st.session_state['selected_headers']}")
        st.selectbox("Selecciona identifier", st.session_state['selected_headers'], key="selected_identifier")
        st.selectbox("Selecciona canonical_smiles", st.session_state['selected_headers'], key="selected_smiles")
        st.selectbox("Selecciona collections", st.session_state['selected_headers'], key="selected_collections")

        if st.button("Run"):
            use_chamanp(get_selected_columns(), st.session_state["selected_identifier"], st.session_state["selected_smiles"], st.session_state["selected_collections"])
            st.text("Chamanp exitoso")
            st.text("Descargando archivos")
        folder_path = "artifacts"
        files = os.listdir(folder_path)

         #manejar la descraga de los archivos, en caso de que se corra de nuevo, en use chamanp se eliminan los archivos    
        for file_name in files:
            file_path = os.path.join(folder_path, file_name)
            if(file_name != "notes.txt"):
                with open(file_path, "rb") as f:
                    downloaded = st.download_button(
                        label=f"Descargar {file_name}",
                        data=f,
                        file_name=file_name,
                        mime="application/octet-stream",
                        key=file_name
                    )
                if downloaded:
                    os.remove(file_path)
                    st.success(f"{file_name} eliminado del servidor")
                    
    st.subheader("Export")
    if st.session_state.get("database_id", "") == "" or st.session_state.get("current_table", "") == "":
        st.info("Carga o selecciona una base de datos antes de exportar.")
    else:
        selected_headers = get_active_selected_headers()
        header_options = selected_headers if len(selected_headers) > 0 else st.session_state.get("headers", [])

        st.download_button(
            label="Download CSV",
            data=export_table(),
            file_name=f"{st.session_state['current_table']}_export.csv",
            mime="text/csv",
            icon=":material/download:",
        )

        with st.expander("Optional: export a filtered subgroup", expanded=False):
            st.caption("Use this only when you want to filter rows before exporting a subgroup.")
            if len(header_options) > 0:
                if st.session_state.get("selected_smiles_for_export", "") not in header_options:
                    st.session_state["selected_smiles_for_export"] = header_options[0]
                st.selectbox("Column to filter", header_options, key="selected_smiles_for_export")
                st.text_input("Value to search in selected column", key="codigo_buscar")
                if (
                    st.session_state.get("selected_smiles_for_export", "") != ""
                    and st.session_state.get("codigo_buscar", "").strip() != ""
                ):

                    st.download_button(
                        label="Download subgroup CSV",
                        data=export_table_by_sub_grupo(
                            codigo_buscar=st.session_state["codigo_buscar"],
                            columna_filtro=st.session_state["selected_smiles_for_export"]
                        ),
                        file_name=f"{st.session_state['current_table']}_subgroup.csv",
                        mime="text/csv",
                        icon=":material/download:",
                    )
            else:
                st.info("No columns are available for subgroup filtering.")
### MAIN PAGE ###

## Session --- Current Progress
container0 = st.container(horizontal=True, horizontal_alignment="distribute", gap="large")
container1 = st.container(horizontal=True, horizontal_alignment="distribute", gap="large")
st.html("""
    <hr style="
        border: none;
        height: 2px;
        background-color: #ccc;
        margin: 20px 0;
    ">
    """)


## Encabezados
container2 = st.container(horizontal=False, horizontal_alignment="left")
st.html("""
    <hr style="
        border: none;
        height: 2px;
        background-color: #ccc;
        margin: 20px 0;
    ">
    """)
container3 = st.container(horizontal=False, horizontal_alignment="left")



### Escritura de datos y logica ###
# 1 #
col_logo, col_titulo = container0.columns([0.1, 0.9], vertical_alignment="center")

# Colocamos el logo en la primera columna}

with col_logo:
    st.image("assets/logo.jpeg", use_container_width=True)

# Colocamos el título en la segunda columna
with col_titulo:
    st.title("ChemVault")
    st.caption("A molecular dataset builder and curator")
    #st.header("Construcción y Curado de Conjuntos de Datos Moleculares Tabulares")

if st.session_state["database_id"] =="":
    container1.text_input(
        label="SQL Database name",
        value=st.session_state["database_id"],
        key="input_database_id",
        on_change=set_database_id,
        disabled=st.session_state["set_text_input_locked"]
    )
    files = os.listdir("SQL")  
    dbs = []
    for file_name in files:
        dbs.append(file_name.replace(".db", ""))
    container1.selectbox("O selecciona una SQL Database existente", dbs, key="existing_db_select", on_change=load_existing_database)
else:
    update_headers()
    container1.text("Data Base: " + st.session_state["database_id"])
    table_options = st.session_state.get("all_tables", [])
    if len(table_options) > 0:
        if st.session_state.get("current_table", "") not in table_options:
            st.session_state["current_table"] = table_options[0]
        container1.selectbox("Selecciona Table", table_options, key="current_table", on_change=update_headers)
        container1.write("Rows: " + str(count_rows(get_connection(st.session_state["database_id"]))))
        if len(st.session_state.get("headers", [])) > 0:
            if st.session_state.get("grupo_a_contar", "") not in st.session_state["headers"]:
                st.session_state["grupo_a_contar"] = st.session_state["headers"][0]
            container1.selectbox("Contar por grupos", st.session_state['headers'], key="grupo_a_contar")
            container1.write("Rows by group: " + str(count_rows_group_by(get_connection(st.session_state["database_id"]))))
    else:
        container1.warning("La base de datos no contiene tablas.")

# 2 #

with container2:
    options = st.session_state["headers"]
    st.pills(
        "Headers",
        options,
        selection_mode="multi",
        key="selected_headers",
    )
    

    if len(st.session_state["selected_headers"]) > 0:
        st.markdown(f"Your selected headers: {st.session_state['selected_headers']}.")
         #tabla preview de headers seleccionados
        st.dataframe(build_preview_table(), hide_index=True)
        
    else:
        st.markdown("No headers selected")
    
   
with container3:
    if st.session_state["database_id"] != "" and len(st.session_state["headers"]) > 0:
        st.subheader("Información Adicional")
        conn = get_connection(st.session_state["database_id"])
        cursor = conn.cursor()
        cursor.execute(f"PRAGMA table_info({quote_identifier(st.session_state['current_table'])})")
        columns_info = cursor.fetchall()
        if columns_info:
            headers_types_df = pd.DataFrame(
                [(col[1], col[2]) for col in columns_info],
                columns=["Header", "Type"]
            )
            st.dataframe(headers_types_df, hide_index=True)
            
            st.subheader("Cambiar tipo de columna")
            col_to_change = st.selectbox("Selecciona columna", [col[1] for col in columns_info], key="col_to_change_select")
            new_type = st.selectbox("Nuevo tipo", ["TEXT", "INTEGER", "REAL", "BLOB"], key="new_col_type_select")
            
            if st.button("Aplicar cambio de tipo"):
                try:
                    cursor.execute(f"ALTER TABLE {st.session_state['current_table']} ADD COLUMN {col_to_change}_new {new_type}")
                    cursor.execute(f"UPDATE {st.session_state['current_table']} SET {col_to_change}_new = CAST({col_to_change} AS {new_type})")
                    cursor.execute(f"ALTER TABLE {st.session_state['current_table']} DROP COLUMN {col_to_change}")
                    cursor.execute(f"ALTER TABLE {st.session_state['current_table']} RENAME COLUMN {col_to_change}_new TO {col_to_change}")
                    conn.commit()
                    st.success(f"Tipo de '{col_to_change}' cambiado a {new_type}")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error al cambiar el tipo: {e}")
        else:
            st.markdown("No se encontró información de tipos de datos.")
