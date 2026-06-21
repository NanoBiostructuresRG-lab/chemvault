import html
import streamlit as st
import pandas as pd
import numpy as np
import os
from PIL import Image
from services.builders import build_from_proteins
from services.database import (
    count_rows,
    count_rows_group_by,
    get_connection,
    load_existing_database,
    set_database_id,
    update_headers,
)
from services.curation import agregar_df_por_pk, is_cid_header, run_chamanp, run_harmonsmile
from services.export import export_table, export_table_by_sub_grupo
from services.selection import (
    build_preview_table,
    get_active_selected_headers,
    get_selected_columns,
    sync_selected_headers,
)
from services.sql_utils import (
    is_valid_table_name,
    quote_identifier,
)
from ui.sidebar import render_build_card, render_refine_card
from ui.session_state import initialize_session_state



@st.dialog("Select Proteins", dismissible=False )
def select_proteins():
    st.write("Search CIDs by BioAssays, using a protein as target.")
    st.text_input(label="Protein", key="input_protein",value="P34971")
    if st.button("Add to selection"):
        st.session_state["selected_proteins"].append(st.session_state["input_protein"])
        st.markdown(f"Selected proteins: {st.session_state['selected_proteins']}.")
    if st.button("Confirm selection"):
        if len(st.session_state["selected_proteins"]) == 0:
            st.toast("Select at least one protein")
            print("Select at least one protein")
        elif st.session_state["database_id"] == "":
            st.toast("First, enter a name for your SQL database")
            print("First, enter a name for your SQL database")

        else:
            progreso = st.progress(0)
            st.toast(f"Building database with proteins: {st.session_state['selected_proteins']}")
            build_from_proteins(progreso)
            update_headers()
        st.rerun()
    if st.button("Cancel"):
        st.session_state["selected_proteins"] = []
        st.rerun()






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


initialize_session_state(st.session_state, verify_directories)

### Decor ###
logo = Image.open("assets/logo.jpeg")

# Configuración de página
st.set_page_config(
    page_title="ChemVault",
    page_icon=logo,
    layout="wide"
)

st.markdown(
    """
    <style>
        :root {
            --cv-bg: #ffffff;
            --cv-panel-bg: #ffffff;
            --cv-sidebar-bg: #f8fafc;
            --cv-muted-bg: #f3f4f6;
            --cv-border: #d6dbe1;
            --cv-border-strong: rgba(71, 85, 105, 0.24);
            --cv-text: #111827;
            --cv-heading: #1f2937;
            --cv-muted: #6b7280;
            --cv-link: #4b5563;
            --cv-control-border: #64748b;
            --cv-accent: #b45309;
            --cv-accent-text: #78350f;
            --cv-accent-bg: #fff7ed;
            --cv-code-bg: #111827;
            --cv-code-text: #f9fafb;
            --cv-shadow-soft: 0 8px 24px rgba(15, 23, 42, 0.04);
            --cv-radius: 0.55rem;
        }

        section[data-testid="stSidebar"] {
            background-color: var(--cv-sidebar-bg);
        }

        section[data-testid="stSidebar"] [data-testid="stVerticalBlock"] {
            gap: 0.8rem;
        }

        section[data-testid="stSidebar"] h1,
        section[data-testid="stSidebar"] h2,
        section[data-testid="stSidebar"] h3 {
            color: var(--cv-heading);
        }

        section[data-testid="stSidebar"] h2,
        section[data-testid="stSidebar"] h3 {
            margin-bottom: 0.15rem;
        }

        section[data-testid="stSidebar"] [data-testid="stCaptionContainer"] {
            color: var(--cv-muted);
            line-height: 1.35;
        }

        section[data-testid="stSidebar"] [data-testid="stVerticalBlockBorderWrapper"] {
            background-color: var(--cv-panel-bg);
            border-color: var(--cv-border-strong);
            box-shadow: var(--cv-shadow-soft);
            border-radius: var(--cv-radius);
        }

        section[data-testid="stSidebar"] [data-testid="stVerticalBlockBorderWrapper"] [data-testid="stVerticalBlock"] {
            gap: 0.55rem;
        }

        section[data-testid="stSidebar"] div[data-testid="stButton"],
        section[data-testid="stSidebar"] div[data-testid="stDownloadButton"] {
            width: 100%;
        }

        section[data-testid="stSidebar"] div[data-testid="stButton"] > button,
        section[data-testid="stSidebar"] div[data-testid="stDownloadButton"] > button {
            width: 100%;
            justify-content: center;
            border-color: var(--cv-control-border);
            color: var(--cv-heading);
            background-color: var(--cv-panel-bg);
            min-height: 2.35rem;
        }

        section[data-testid="stSidebar"] div[data-testid="stButton"] > button:hover,
        section[data-testid="stSidebar"] div[data-testid="stDownloadButton"] > button:hover {
            border-color: var(--cv-accent);
            color: var(--cv-accent-text);
            background-color: var(--cv-accent-bg);
        }
    </style>
    """,
    unsafe_allow_html=True,
)

### SIDE BAR MENU ###
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
        raise ValueError("Enter a valid table name: use letters, numbers, and underscores; do not start with a number.")
    if current_table == "":
        raise ValueError("Select a source table before creating a new table.")
    if len(selected_headers) == 0:
        raise ValueError("Select at least one column before creating a new table.")

    cols = ", ".join(quote_identifier(col) for col in selected_headers)
    base_query = f"""
    CREATE TABLE {quote_identifier(new_table_name)} AS
    SELECT {cols} FROM {quote_identifier(current_table)}
    """
    filter_clause = ""
    match st.session_state.get("type_of_filter", "None"):
        case "None":
            pass
        case "GROUP BY":
            group_col = st.session_state.get("group_by_column", "")
            if group_col not in selected_headers:
                raise ValueError("The GROUP BY column must be one of the selected columns.")
            filter_clause = f"GROUP BY {quote_identifier(group_col)}"
        case "WHERE":
            where_col = st.session_state.get("where_column", "")
            condition = st.session_state.get("where_condition", "").strip()
            if where_col not in st.session_state.get("headers", []):
                raise ValueError("Select a valid column for WHERE.")
            if condition == "":
                raise ValueError("Enter a WHERE condition.")
            filter_clause = f"WHERE {quote_identifier(where_col)} {condition}"
        case "ORDER BY":
            order_col = st.session_state.get("order_by_column", "")
            direction = st.session_state.get("order_direction", "ASC")
            if order_col not in selected_headers:
                raise ValueError("The ORDER BY column must be one of the selected columns.")
            filter_clause = f"ORDER BY {quote_identifier(order_col)} {direction}"
    return base_query + filter_clause

with st.sidebar:
    st.header("Actions")
    #Construccion
    if st.session_state["current_table"] == "" or (st.session_state["database_id"] != "" and count_rows(get_connection(st.session_state["database_id"])) == 0):
        render_build_card(select_proteins)
    else:#Depurado
        render_refine_card(clear_depurado_preview, construir_linea_query)

#falta agregar order by
#hacer un text box que muestre el query

    with st.container(border=True):
        st.subheader("Curate")
        st.caption("Run chemistry workflows on selected columns.")
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
                        new_table_df = run_harmonsmile(get_selected_columns())
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
            st.text("Select the columns to process")
            st.text(f"Selected columns: {st.session_state['selected_headers']}")
            st.selectbox("Select identifier", st.session_state['selected_headers'], key="selected_identifier")
            st.selectbox("Select canonical_smiles", st.session_state['selected_headers'], key="selected_smiles")
            st.selectbox("Select collections", st.session_state['selected_headers'], key="selected_collections")

            if st.button("Run"):
                run_chamanp(get_selected_columns(), st.session_state["selected_identifier"], st.session_state["selected_smiles"], st.session_state["selected_collections"])
                st.text("Chamanp completed successfully")
                st.text("Downloading files")
            folder_path = "artifacts"
            files = os.listdir(folder_path)

         #manejar la descraga de los archivos, en caso de que se corra de nuevo, en use chamanp se eliminan los archivos
            for file_name in files:
                file_path = os.path.join(folder_path, file_name)
                if(file_name != "notes.txt"):
                    with open(file_path, "rb") as f:
                        downloaded = st.download_button(
                            label=f"Download {file_name}",
                            data=f,
                            file_name=file_name,
                            mime="application/octet-stream",
                            key=file_name
                        )
                    if downloaded:
                        os.remove(file_path)
                        st.success(f"{file_name} removed from the server")

    with st.container(border=True):
        st.subheader("Export")
        st.caption("Download the current table or a filtered subset.")
        if st.session_state.get("database_id", "") == "" or st.session_state.get("current_table", "") == "":
            st.info("Load or select a database before exporting.")
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
container0 = st.container(horizontal=True, horizontal_alignment="distribute", gap="large", border=True)
st.html("""
    <div style="
        height: 3.25rem;
    "></div>
    """)
container1 = st.container(horizontal=False, horizontal_alignment="left", border=True)
st.html("""
    <hr style="
        border: none;
        height: 2px;
        background-color: var(--cv-border);
        margin: 32px 0 24px 0;
    ">
    """)


## Encabezados
container2 = st.container(horizontal=False, horizontal_alignment="left", border=True)
st.html("""
    <hr style="
        border: none;
        height: 2px;
        background-color: var(--cv-border);
        margin: 32px 0 24px 0;
    ">
    """)
container3 = st.container(horizontal=False, horizontal_alignment="left", border=True)



### Escritura de datos y logica ###
# 1 #
col_logo, col_titulo = container0.columns([0.12, 0.88], vertical_alignment="center")

# Colocamos el logo en la primera columna}

with col_logo:
    st.image("assets/logo.jpeg", use_container_width=True)

# Colocamos el título en la segunda columna
with col_titulo:
    st.markdown(
        """
        <div style="padding: 0.15rem 0;">
            <div style="font-size: 2.45rem; line-height: 1.05; font-weight: 700; color: var(--cv-heading);">
                ChemVault
            </div>
            <div style="margin-top: 0.25rem; font-size: 0.98rem; color: var(--cv-muted);">
                Molecular dataset construction, curation, and export workspace.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    #st.header("Construcción y Curado de Conjuntos de Datos Moleculares Tabulares")

if st.session_state["database_id"] =="":
    container1.subheader("Database")
    container1.caption("Create or select the active molecular database.")
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
    container1.selectbox("Or select an existing SQL database", dbs, key="existing_db_select", on_change=load_existing_database)
else:
    update_headers()
    container1.subheader("Database")
    container1.caption("Active table and row summary.")
    table_options = st.session_state.get("all_tables", [])
    if len(table_options) > 0:
        if st.session_state.get("current_table", "") not in table_options:
            st.session_state["current_table"] = table_options[0]
        row_count = count_rows(get_connection(st.session_state["database_id"]))
        if len(st.session_state.get("headers", [])) > 0:
            if st.session_state.get("grupo_a_contar", "") not in st.session_state["headers"]:
                st.session_state["grupo_a_contar"] = st.session_state["headers"][0]
        group_count = count_rows_group_by(get_connection(st.session_state["database_id"]))
        container1.markdown(
            f"""
            <div style="
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
                gap: 0.35rem 1.5rem;
                margin: 0.7rem 0 1rem 0;
                padding: 0.85rem 0;
                border-top: 1px solid var(--cv-border);
                border-bottom: 1px solid var(--cv-border);
            ">
                <div>
                    <div style="font-size: 0.76rem; color: var(--cv-muted);">Database</div>
                    <div style="font-size: 0.95rem; color: var(--cv-text); overflow-wrap: anywhere;">{html.escape(st.session_state["database_id"])}</div>
                </div>
                <div>
                    <div style="font-size: 0.76rem; color: var(--cv-muted);">Table</div>
                    <div style="font-size: 0.95rem; color: var(--cv-text);">{html.escape(st.session_state["current_table"])}</div>
                </div>
                <div>
                    <div style="font-size: 0.76rem; color: var(--cv-muted);">Rows</div>
                    <div style="font-size: 0.95rem; color: var(--cv-text);">{row_count}</div>
                </div>
                <div>
                    <div style="font-size: 0.76rem; color: var(--cv-muted);">Unique groups</div>
                    <div style="font-size: 0.95rem; color: var(--cv-text);">{group_count}</div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        container1.markdown("#### Table controls")
        container1.selectbox("Select table", table_options, key="current_table", on_change=update_headers)
        if len(st.session_state.get("headers", [])) > 0:
            container1.selectbox("Count unique groups by", st.session_state['headers'], key="grupo_a_contar")
    else:
        container1.warning("The database does not contain tables.")

# 2 #

with container2:
    st.subheader("Columns")
    st.caption("Select columns to preview, refine, curate, or export.")
    options = st.session_state["headers"]
    if len(options) > 0:
        st.pills(
            "Headers",
            options,
            selection_mode="multi",
            key="selected_headers",
            label_visibility="collapsed",
        )

        selected_count = len(st.session_state["selected_headers"])
        if selected_count > 0:
            selected_columns = ", ".join(st.session_state["selected_headers"])
            st.markdown(f"**{selected_count} column{'s' if selected_count != 1 else ''} selected:** {selected_columns}")
             #tabla preview de headers seleccionados
            st.markdown("#### Selected columns preview")
            st.dataframe(build_preview_table(), hide_index=True)

        else:
            st.info("Select one or more columns to preview data and enable downstream actions.")
    else:
        st.info("No columns are available in the current table.")


with container3:
    st.subheader("Table information")
    st.caption("Column types and maintenance tools for the active table.")
    if st.session_state["database_id"] != "" and len(st.session_state["headers"]) > 0:
        conn = get_connection(st.session_state["database_id"])
        cursor = conn.cursor()
        cursor.execute(f"PRAGMA table_info({quote_identifier(st.session_state['current_table'])})")
        columns_info = cursor.fetchall()
        if columns_info:
            headers_types_df = pd.DataFrame(
                [(col[1], col[2]) for col in columns_info],
                columns=["Column", "Data type"]
            )
            st.markdown("Current schema for the active table.")
            st.dataframe(headers_types_df, hide_index=True)

            with st.expander("Advanced: change column type", expanded=False):
                st.caption("This updates the SQLite column type for the selected column.")
                st.warning("Use this only when you are sure the selected values can be converted safely.")
                col_to_change = st.selectbox("Select column", [col[1] for col in columns_info], key="col_to_change_select")
                new_type = st.selectbox("New type", ["TEXT", "INTEGER", "REAL", "BLOB"], key="new_col_type_select")

                if st.button("Apply column type change"):
                    try:
                        cursor.execute(f"ALTER TABLE {st.session_state['current_table']} ADD COLUMN {col_to_change}_new {new_type}")
                        cursor.execute(f"UPDATE {st.session_state['current_table']} SET {col_to_change}_new = CAST({col_to_change} AS {new_type})")
                        cursor.execute(f"ALTER TABLE {st.session_state['current_table']} DROP COLUMN {col_to_change}")
                        cursor.execute(f"ALTER TABLE {st.session_state['current_table']} RENAME COLUMN {col_to_change}_new TO {col_to_change}")
                        conn.commit()
                        st.success(f"Column '{col_to_change}' changed to {new_type}")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error changing type: {e}")
        else:
            st.markdown("No column type information was found.")
    else:
        st.info("Select a database with columns to view additional information.")

st.markdown(
    """
    <footer style="
        margin-top: 3rem;
        padding-top: 1rem;
        border-top: 1px solid var(--cv-border);
        text-align: center;
        color: var(--cv-muted);
        font-size: 0.85rem;
        line-height: 1.6;
    ">
        <div>D.R. © ChemVault 2026</div>
        <div>
            Developed by the
            <a href="https://nanobiostructuresrg.github.io/" style="color: var(--cv-link);">
                Nano]°[Biostructures RG
            </a>
            at Tecnológico de Monterrey.
        </div>
    </footer>
    """,
    unsafe_allow_html=True,
)
