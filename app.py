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

def count_rows_group_by(connection):

    cursor = connection.cursor()

    cursor.execute("""
        SELECT COUNT(*)
        FROM (
            SELECT Bioactivity_ID
            FROM main
            GROUP BY Bioactivity_ID
        )
    """)

    total = cursor.fetchone()[0]

    return total
def count_rows(connection): 
    cursor = connection.cursor()
    cursor.execute(f""" SELECT COUNT(*) FROM main """) 
    total = cursor.fetchone()[0] 
    return total

def build_from_proteins(progreso):
    obtener_CIDs_Pubchem(get_connection(st.session_state["database_id"]),st.session_state["selected_proteins"],progreso)

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






### setup SQL ###
def set_database_id():
    st.session_state["database_id"] = st.session_state["input_database_id"]
    st.session_state["set_text_input_locked"] = True
    st.toast(f"SQL Database set to { st.session_state["database_id"]}")

    ### construir o cargar datos ###
    update_headers()

def update_headers():
    if st.session_state["database_id"] != "":
        conn = get_connection(st.session_state["database_id"])
        cursor = conn.cursor()
        table = "main"

        cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS {table} (
            primary_id INTEGER PRIMARY KEY AUTOINCREMENT
        )
        """)
        conn.commit()

        cursor.execute(f"PRAGMA table_info({table})")
        columns_info = cursor.fetchall()

        headers = [col[1] for col in columns_info]
        st.session_state["headers"] = headers
    else: return []

def build_from_csv(uploaded_file):
    if os.path.isfile(f"SQL/{db_name}.db"):
        os.remove(f"SQL/{db_name}.db")
    conn = get_connection(st.session_state["database_id"])
    cursor = conn.cursor()
    table = "main"

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

def export_table():
    if st.session_state["database_id"] == "":
        empty_df = pd.DataFrame()
        return empty_df.to_csv(index=False).encode("utf-8")
    


    conn = get_connection(st.session_state["database_id"])

    table = "main"

    # si no hay selección -> usar todas
    if len(st.session_state["selected_headers"]) == 0:
        query = f"SELECT * FROM {table}"
    else:
        cols = ", ".join(st.session_state["selected_headers"])
        query = f"SELECT {cols} FROM {table}"

    df = pd.read_sql_query(query, conn)

    return df.to_csv(index=False).encode("utf-8")

def export_table_by_sub_grupo(codigo_buscar: str, columna_filtro: str):
    if st.session_state["database_id"] == "":
        empty_df = pd.DataFrame()
        return empty_df.to_csv(index=False).encode("utf-8")

    conn = get_connection(st.session_state["database_id"])

    table = "main"

    # columnas seleccionadas
    if len(st.session_state["selected_headers"]) == 0:
        cols = "*"
    else:
        cols = ", ".join(st.session_state["selected_headers"])

    # query con filtro LIKE
    query = f"""
        SELECT {cols}
        FROM {table}
        WHERE {columna_filtro} LIKE ?
    """

    df = pd.read_sql_query(
        query,
        conn,
        params=[f"%{codigo_buscar}%"]
    )

    return df.to_csv(index=False).encode("utf-8")


def build_preview_table():
    if st.session_state["database_id"] != "":
        conn = get_connection(st.session_state["database_id"])
        table = "main"

        if len(st.session_state["selected_headers"]) == 0:
            return pd.DataFrame()
        else:
            cols = ", ".join(st.session_state["selected_headers"])
            query = f"SELECT {cols} FROM {table} LIMIT 10"
            return pd.read_sql_query(query, conn)
    else:
        return pd.DataFrame()

def get_selected_columns(): #diferencia entre build_preview_table es que esta no tiene limite de 10
    if st.session_state["database_id"] != "":
        conn = get_connection(st.session_state["database_id"])
        table = "main"

        if len(st.session_state["selected_headers"]) == 0:
            return pd.DataFrame()
        else:
            cols = ", ".join(st.session_state["selected_headers"])
            query = f"SELECT {cols} FROM {table}"
            return pd.read_sql_query(query, conn)
    else:
        return pd.DataFrame()

def agregar_df_por_pk(df, pk, fk): # agregar dataframe por primary key
    conn = get_connection(st.session_state["database_id"])
    cursor = conn.cursor()
    table = "main"
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
                os.remove(file_path)
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

def set_curados_false():
    st.session_state["selecting_harmonsmile"] = False 
    st.session_state["selecting_chamanp"] = False 

with st.sidebar:
    st.header("Acciones")
    #if st.session_state["database_id"] == "":
    st.subheader("Construcción")
        ### por proteina ###
    if st.button("Buscar Proteínas") : select_proteins()
        ### por csv ###
    uploaded_file = st.file_uploader("Sube un CSV", type=["csv"])
    if st.session_state["database_id"] == "":
        if uploaded_file != None:
                st.session_state["set_text_input_locked"] = True

                db_name = uploaded_file.name.replace(".csv", "")
                st.session_state["database_id"] = db_name

                build_from_csv(uploaded_file)
                update_headers()
                st.rerun()

    st.subheader("Curado")
    if st.button("HARMONSMILE"): 
        set_curados_false()
        st.session_state["selecting_harmonsmile"] = True 
    if st.button("CHAMANP"): 
        set_curados_false()
        st.session_state["selecting_chamanp"] = True 
    
    #procesos
    if st.session_state["selecting_harmonsmile"]:
        st.text("Seleccione únicamente la columna de CIDs")
        if len(st.session_state["selected_headers"]) == 1:
            if st.button("Run"):
                new_table_df = use_PubchemIngest(get_selected_columns())
                #new_table_df = pd.read_csv("tempFilesHarmonsile/res_pubchem_harmonized.csv")#use_PubchemIngest(get_selected_columns())
                #new_table_df.columns = ( #preparamos los datos para ser procesados por sql
                #    new_table_df.columns
                #    .str.replace(" ", "_", regex=False)
                #    .str.replace(":", "", regex=False)
                #)
                
                
                #NOTA: asumo que la fk de la tabla regresada siempre incluye Pubchem CID
                if agregar_df_por_pk(new_table_df, st.session_state["selected_headers"][0], "PubChem_CID"):
                    st.text("HarmonSmile exitoso")
                else:
                    st.text("Error en HarmonSmile")
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
    st.text("Use sub group")
    header_options = st.session_state['selected_headers']
    if len(st.session_state['selected_headers']) == 0:
        header_options = st.session_state['headers']
    st.selectbox("Selecciona SMILES", header_options, key="selected_smiles_for_export")
    st.text_input("Ingresa código a buscar en la columna seleccionada", key="codigo_buscar")
    if (
        st.session_state["selected_smiles_for_export"] != ""
        and st.session_state["codigo_buscar"].strip() != ""
    ):

        st.download_button(
            label="Download SubGroup CSV",
            data=export_table_by_sub_grupo(
                codigo_buscar=st.session_state["codigo_buscar"],
                columna_filtro=st.session_state["selected_smiles"]
            ),
            file_name="data.csv",
            mime="text/csv",
            icon=":material/download:",
        )
    st.download_button(
        label="Download CSV",
        data=export_table(),
        file_name="data.csv",
        mime="text/csv",
        icon=":material/download:",
    )
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



### Escritura de datos y logica ###
# 1 #
col_logo, col_titulo = container0.columns([0.1, 0.9])

# Colocamos el logo en la primera columna}

with col_logo:
    st.image("assets/logo.jpeg", use_container_width=True)

# Colocamos el título en la segunda columna
with col_titulo:
    st.header("Construcción y Curado de Conjuntos de Datos Moleculares Tabulares")

if st.session_state["database_id"] =="":
    container1.text_input(
        label="SQL Database name",
        value=st.session_state["database_id"],
        key="input_database_id",
        on_change=set_database_id,
        disabled=st.session_state["set_text_input_locked"]
    )
else:
    container1.text(st.session_state["database_id"])
    container1.write("Compounds: " + str(count_rows(get_connection(st.session_state["database_id"]))))

# 2 #

with container2:
    options = st.session_state["headers"]
    st.session_state["selected_headers"] = st.pills("Headers", options, selection_mode="multi")
    

    if len(st.session_state["selected_headers"]) >0:
        st.markdown(f"Your selected headers: {st.session_state["selected_headers"]}.")
         #tabla preview de headers seleccionados
        st.dataframe(build_preview_table(), hide_index=True)
        
    else:
        st.markdown("No headers selected")
    
   
    