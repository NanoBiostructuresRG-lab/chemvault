# SPDX-License-Identifier: LGPL-3.0-or-later
import html
import os

import streamlit as st

from services.builders import build_from_csv
from services.curation import (
    agregar_df_por_pk,
    is_cid_header,
    run_chamanp,
    run_harmonsmile,
)
from services.database import count_rows, get_connection, update_headers
from services.db_audit import register_operation, register_table_metadata
from services.export import export_table, export_table_by_sub_grupo
from services.selection import get_active_selected_headers, get_selected_columns
from services.sql_utils import table_exists
from state_keys import (
    CODIGO_BUSCAR,
    CURRENT_TABLE,
    CUSTOM_QUERY,
    DATABASE_ID,
    DEPURADO_SUCCESS_MESSAGE,
    DEPURADO_SUCCESS_TABLE,
    GROUP_BY_COLUMN,
    HEADERS,
    NEW_TABLE_NAME,
    ORDER_BY_COLUMN,
    ORDER_DIRECTION,
    SELECTED_HEADERS,
    SET_TEXT_INPUT_LOCKED,
    TYPE_OF_FILTER,
    WHERE_COLUMN,
    WHERE_CONDITION,
    SELECTED_COLLECTIONS,
    SELECTED_IDENTIFIER,
    SELECTED_SMILES,
    SELECTED_SMILES_FOR_EXPORT,
    SELECTING_CHAMANP,
    SELECTING_HARMONSMILE,
)


def render_build_card(select_proteins_callback):
    with st.container(border=True):
        st.subheader("Build")
        st.caption("Start from proteins or upload a CSV dataset.")
        if st.button("Search Proteins"):
            select_proteins_callback()
        uploaded_file = st.file_uploader("Upload CSV", type=["csv"])
        if uploaded_file is not None:
            st.session_state[SET_TEXT_INPUT_LOCKED] = True
            db_name = uploaded_file.name.replace(".csv", "")
            st.session_state[DATABASE_ID] = db_name
            st.session_state[CURRENT_TABLE] = "main"
            build_from_csv(uploaded_file)
            update_headers()
            st.rerun()


def render_sidebar(select_proteins_callback, clear_preview_callback, build_query_callback):
    with st.sidebar:
        st.header("Actions")
        if st.session_state[CURRENT_TABLE] == "" or (
            st.session_state[DATABASE_ID] != ""
            and count_rows(get_connection(st.session_state[DATABASE_ID])) == 0
        ):
            render_build_card(select_proteins_callback)
        else:
            render_refine_card(clear_preview_callback, build_query_callback)

        render_curate_card()
        render_export_card()


def render_refine_card(clear_preview_callback, build_query_callback):
    with st.container(border=True):
        st.subheader("Refine")
        st.caption("Create derived tables from the active column selection.")
        st.text_input(
            label="New table name",
            key=NEW_TABLE_NAME,
            value="New_table",
            on_change=clear_preview_callback,
        )
        if st.session_state.get(TYPE_OF_FILTER) == "Ninguno":
            st.session_state[TYPE_OF_FILTER] = "None"
        st.selectbox(
            "Additional filter",
            ["None", "GROUP BY", "WHERE", "ORDER BY"],
            key=TYPE_OF_FILTER,
            on_change=clear_preview_callback,
        )
        match st.session_state[TYPE_OF_FILTER]:
            case "None":
                pass
            case "GROUP BY":
                st.selectbox(
                    "Column to group",
                    st.session_state[SELECTED_HEADERS],
                    key=GROUP_BY_COLUMN,
                    on_change=clear_preview_callback,
                )
            case "WHERE":
                st.selectbox(
                    "Column to filter",
                    st.session_state[HEADERS],
                    key=WHERE_COLUMN,
                    on_change=clear_preview_callback,
                )
                st.text_input(
                    "Condition (example: > 100, = 'HarmonSmile', etc)",
                    key=WHERE_CONDITION,
                    on_change=clear_preview_callback,
                )
            case "ORDER BY":
                st.selectbox(
                    "Column to sort",
                    st.session_state[SELECTED_HEADERS],
                    key=ORDER_BY_COLUMN,
                    on_change=clear_preview_callback,
                )
                st.selectbox(
                    "Sort direction",
                    ["ASC", "DESC"],
                    key=ORDER_DIRECTION,
                    on_change=clear_preview_callback,
                )
        if st.button("Preview SQL"):
            try:
                st.session_state[CUSTOM_QUERY] = build_query_callback()
            except ValueError as e:
                st.session_state[CUSTOM_QUERY] = ""
                st.error(str(e))
        if st.session_state.get(CUSTOM_QUERY, "") != "":
            compact_query = html.escape(" ".join(st.session_state[CUSTOM_QUERY].split()))
            st.markdown("**SQL preview**")
            st.markdown(
                f'''
                <div style="background-color:var(--cv-code-bg); color:var(--cv-code-text); padding:0.85rem 1rem;
                            border-radius:var(--cv-radius); font-family:monospace; font-size:0.9rem;
                            line-height:1.5; overflow-x:auto; margin-bottom:0.85rem;">
                    {compact_query}
                </div>
                ''',
                unsafe_allow_html=True,
            )

        if st.button("Create table from current selection"):
            conn = get_connection(st.session_state[DATABASE_ID])
            cursor = conn.cursor()
            try:
                query_to_run = build_query_callback()
                new_table_name = st.session_state[NEW_TABLE_NAME].strip()
                source_table = st.session_state[CURRENT_TABLE]
                source_columns = get_active_selected_headers()
                if table_exists(conn, new_table_name):
                    raise ValueError(
                        f"Table '{new_table_name}' already exists. Use another name or delete it first."
                    )
                cursor.execute(query_to_run)
                register_table_metadata(
                    conn,
                    new_table_name,
                    role="derived",
                    origin="refine",
                    source_table=source_table,
                    created_by="render_refine_card",
                    query_used=query_to_run,
                    commit=False,
                )
                register_operation(
                    conn,
                    "refine_table_created",
                    target_table=new_table_name,
                    source_table=source_table,
                    source_columns=source_columns,
                    output_columns=source_columns,
                    created_by="render_refine_card",
                    details="Created a derived table from the active column selection.",
                    query_used=query_to_run,
                    commit=False,
                )
                conn.commit()
                st.session_state[CURRENT_TABLE] = new_table_name
                st.session_state[SELECTED_HEADERS] = []
                st.session_state[CUSTOM_QUERY] = query_to_run
                update_headers()
                st.session_state[DEPURADO_SUCCESS_TABLE] = new_table_name
                st.session_state[DEPURADO_SUCCESS_MESSAGE] = (
                    f"Table '{new_table_name}' was created successfully."
                )
                st.rerun()
            except Exception as e:
                conn.rollback()
                st.error(f"Could not create the table: {e}")

        created_table = st.session_state.get(DEPURADO_SUCCESS_TABLE, "")
        if created_table and created_table == st.session_state.get(CURRENT_TABLE, ""):
            st.success(
                st.session_state.get(
                    DEPURADO_SUCCESS_MESSAGE,
                    f"Table '{created_table}' was created successfully.",
                )
            )


def _set_curados_false():
    st.session_state[SELECTING_HARMONSMILE] = False
    st.session_state[SELECTING_CHAMANP] = False


def _safe_register_curate_operation(
    operation_type,
    target_table,
    source_columns,
    output_columns=None,
    status="success",
    details=None,
):
    try:
        register_operation(
            get_connection(st.session_state[DATABASE_ID]),
            operation_type,
            target_table=target_table,
            source_columns=source_columns,
            output_columns=output_columns,
            created_by="render_curate_card",
            status=status,
            details=details,
        )
    except Exception:
        pass


def render_curate_card():
    with st.container(border=True):
        st.subheader("Curate")
        st.caption("Run chemistry workflows on selected columns.")
        if st.button("HARMONSMILE"):
            _set_curados_false()
            st.session_state[SELECTING_HARMONSMILE] = True
        if st.button("CHAMANP"):
            _set_curados_false()
            st.session_state[SELECTING_CHAMANP] = True

        if st.session_state[SELECTING_HARMONSMILE]:
            selected_headers = get_active_selected_headers()
            if len(selected_headers) == 0:
                st.warning("Select the CID column before running HARMONSMILE.")
            elif len(selected_headers) > 1:
                st.warning("HARMONSMILE requires exactly one column: CID.")
            elif not is_cid_header(selected_headers[0]):
                st.warning(
                    f"Selected column is '{selected_headers[0]}'. HARMONSMILE requires a valid CID column."
                )
            else:
                if st.button("Run"):
                    target_table = st.session_state[CURRENT_TABLE]
                    try:
                        new_table_df = run_harmonsmile(get_selected_columns())
                    except ValueError as e:
                        st.toast(str(e))
                        st.error(str(e))
                        _safe_register_curate_operation(
                            "harmonsmile_run",
                            target_table,
                            selected_headers,
                            status="failed",
                            details=str(e),
                        )
                        new_table_df = None
                    if new_table_df is not None:
                        output_columns = [col for col in new_table_df.columns if col != "PubChem_CID"]
                        if agregar_df_por_pk(new_table_df, selected_headers[0], "PubChem_CID"):
                            st.toast("HarmonSmile completed successfully")
                            _safe_register_curate_operation(
                                "harmonsmile_run",
                                target_table,
                                selected_headers,
                                output_columns=output_columns,
                                details="Enriched the active table with HARMONSMILE columns.",
                            )
                        else:
                            st.toast("HarmonSmile failed")
                            _safe_register_curate_operation(
                                "harmonsmile_run",
                                target_table,
                                selected_headers,
                                output_columns=output_columns,
                                status="failed",
                                details="HARMONSMILE returned data, but ChemVault could not merge it into the active table.",
                            )
                        update_headers()
                        st.rerun()

        if st.session_state[SELECTING_CHAMANP]:
            st.text("Select the columns to process")
            st.text(f"Selected columns: {st.session_state[SELECTED_HEADERS]}")
            st.selectbox("Select identifier", st.session_state[SELECTED_HEADERS], key=SELECTED_IDENTIFIER)
            st.selectbox("Select canonical_smiles", st.session_state[SELECTED_HEADERS], key=SELECTED_SMILES)
            st.selectbox("Select collections", st.session_state[SELECTED_HEADERS], key=SELECTED_COLLECTIONS)

            if st.button("Run"):
                source_columns = [
                    st.session_state[SELECTED_IDENTIFIER],
                    st.session_state[SELECTED_SMILES],
                    st.session_state[SELECTED_COLLECTIONS],
                ]
                run_chamanp(
                    get_selected_columns(),
                    st.session_state[SELECTED_IDENTIFIER],
                    st.session_state[SELECTED_SMILES],
                    st.session_state[SELECTED_COLLECTIONS],
                )
                _safe_register_curate_operation(
                    "chamanp_run",
                    st.session_state[CURRENT_TABLE],
                    source_columns,
                    details="Ran CHAMANP and generated downloadable artifacts.",
                )
                st.text("Chamanp completed successfully")
                st.text("Downloading files")
            folder_path = "artifacts"
            files = os.listdir(folder_path)

            for file_name in files:
                file_path = os.path.join(folder_path, file_name)
                if file_name != "notes.txt":
                    with open(file_path, "rb") as f:
                        downloaded = st.download_button(
                            label=f"Download {file_name}",
                            data=f,
                            file_name=file_name,
                            mime="application/octet-stream",
                            key=file_name,
                        )
                    if downloaded:
                        os.remove(file_path)
                        st.success(f"{file_name} removed from the server")


def render_export_card():
    with st.container(border=True):
        st.subheader("Export")
        st.caption("Download the current table or a filtered subset.")
        if st.session_state.get(DATABASE_ID, "") == "" or st.session_state.get(CURRENT_TABLE, "") == "":
            st.info("Load or select a database before exporting.")
        else:
            selected_headers = get_active_selected_headers()
            header_options = (
                selected_headers if len(selected_headers) > 0 else st.session_state.get(HEADERS, [])
            )

            st.download_button(
                label="Download CSV",
                data=export_table(),
                file_name=f"{st.session_state[CURRENT_TABLE]}_export.csv",
                mime="text/csv",
                icon=":material/download:",
            )

            with st.expander("Optional: export a filtered subgroup", expanded=False):
                st.caption("Use this only when you want to filter rows before exporting a subgroup.")
                if len(header_options) > 0:
                    if st.session_state.get(SELECTED_SMILES_FOR_EXPORT, "") not in header_options:
                        st.session_state[SELECTED_SMILES_FOR_EXPORT] = header_options[0]
                    st.selectbox("Column to filter", header_options, key=SELECTED_SMILES_FOR_EXPORT)
                    st.text_input("Value to search in selected column", key=CODIGO_BUSCAR)
                    if (
                        st.session_state.get(SELECTED_SMILES_FOR_EXPORT, "") != ""
                        and st.session_state.get(CODIGO_BUSCAR, "").strip() != ""
                    ):

                        st.download_button(
                            label="Download subgroup CSV",
                            data=export_table_by_sub_grupo(
                                codigo_buscar=st.session_state[CODIGO_BUSCAR],
                                columna_filtro=st.session_state[SELECTED_SMILES_FOR_EXPORT],
                            ),
                            file_name=f"{st.session_state[CURRENT_TABLE]}_subgroup.csv",
                            mime="text/csv",
                            icon=":material/download:",
                        )
                else:
                    st.info("No columns are available for subgroup filtering.")
