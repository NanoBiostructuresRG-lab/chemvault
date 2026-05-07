import streamlit as st
import pandas as pd
import numpy as np
import sqlite3
from modules.obtener_CIDs_Pubchem import obtener_CIDs_Pubchem


@st.cache_resource #esto se usa para manejar la persistencia de la conexion
def get_connection(db_name):
    return sqlite3.connect(f"SQL/{db_name}", check_same_thread=False)


def count_rows(connection):
    cursor = connection.cursor()

    cursor.execute(f"""
    SELECT COUNT(*)
    FROM main
    """)

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

def build_preview_table():
    if st.session_state["database_id"] != "":
        conn = get_connection(st.session_state["database_id"])
        table = "main"

        if len(st.session_state["selected_headers"]) == 0:
            query = f"SELECT * FROM {table}"
            return pd.DataFrame()
        else:
            cols = ", ".join(st.session_state["selected_headers"])
            query = f"SELECT {cols} FROM {table} LIMIT 10"
            return pd.read_sql_query(query, conn)
    else:
        return pd.DataFrame()



### Definicion session state vars
if "database_id" not in st.session_state:
    st.session_state["database_id"] = ""

if "set_text_input_locked" not in st.session_state:
    st.session_state["set_text_input_locked"] = False

if "headers" not in st.session_state: 
    st.session_state["headers"] = []

if "selected_headers" not in st.session_state: 
    st.session_state["selected_headers"] = []

if "selected_proteins" not in st.session_state: 
    st.session_state["selected_proteins"] = []


### SIDE BAR MENU ###
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
    st.subheader("Export")
    st.download_button(
        label="Download CSV",
        data=export_table(),
        file_name="data.csv",
        mime="text/csv",
        icon=":material/download:",
    )
### MAIN PAGE ###

## Session --- Current Progress
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
    
   
    