# SPDX-License-Identifier: LGPL-3.0-or-later
"""Centralized Streamlit session-state keys for ChemVault.

These constants intentionally preserve the existing string values used by
`st.session_state`. Refactors may import these names, but the underlying keys
must remain stable to avoid changing app behavior.
"""

DATABASE_ID = "database_id"
SET_TEXT_INPUT_LOCKED = "set_text_input_locked"
HEADERS = "headers"
SELECTED_HEADERS = "selected_headers"
SELECTED_PROTEINS = "selected_proteins"
CURRENT_TABLE = "current_table"
PUBCHEM_JOB_ID = "pubchem_job_id"
PUBCHEM_JOB_DB_PATH = "pubchem_job_db_path"
PUBCHEM_JOB_COMPLETION_HANDLED = "pubchem_job_completion_handled"
ALL_TABLES = "all_tables"
GROUP_COUNT_COLUMN = "grupo_a_contar"
CUSTOM_QUERY = "custom_query"

INPUT_PROTEIN = "input_protein"
INPUT_DATABASE_ID = "input_database_id"
EXISTING_DB_SELECT = "existing_db_select"

SELECTING_HARMONSMILE = "selecting_harmonsmile"
SELECTING_CHAMANP = "selecting_chamanp"

NEW_TABLE_NAME = "new_table_name"
TYPE_OF_FILTER = "type_of_filter"
GROUP_BY_COLUMN = "group_by_column"
WHERE_COLUMN = "where_column"
WHERE_CONDITION = "where_condition"
ORDER_BY_COLUMN = "order_by_column"
ORDER_DIRECTION = "order_direction"
DEPURADO_SUCCESS_TABLE = "depurado_success_table"
DEPURADO_SUCCESS_MESSAGE = "depurado_success_message"

SELECTED_IDENTIFIER = "selected_identifier"
SELECTED_SMILES = "selected_smiles"
SELECTED_COLLECTIONS = "selected_collections"

SELECTED_SMILES_FOR_EXPORT = "selected_smiles_for_export"
CODIGO_BUSCAR = "codigo_buscar"

COL_TO_CHANGE_SELECT = "col_to_change_select"
NEW_COL_TYPE_SELECT = "new_col_type_select"

ALL_SESSION_KEYS = (
    DATABASE_ID,
    SET_TEXT_INPUT_LOCKED,
    HEADERS,
    SELECTED_HEADERS,
    SELECTED_PROTEINS,
    CURRENT_TABLE,
    PUBCHEM_JOB_ID,
    PUBCHEM_JOB_DB_PATH,
    PUBCHEM_JOB_COMPLETION_HANDLED,
    ALL_TABLES,
    GROUP_COUNT_COLUMN,
    CUSTOM_QUERY,
    INPUT_PROTEIN,
    INPUT_DATABASE_ID,
    EXISTING_DB_SELECT,
    SELECTING_HARMONSMILE,
    SELECTING_CHAMANP,
    NEW_TABLE_NAME,
    TYPE_OF_FILTER,
    GROUP_BY_COLUMN,
    WHERE_COLUMN,
    WHERE_CONDITION,
    ORDER_BY_COLUMN,
    ORDER_DIRECTION,
    DEPURADO_SUCCESS_TABLE,
    DEPURADO_SUCCESS_MESSAGE,
    SELECTED_IDENTIFIER,
    SELECTED_SMILES,
    SELECTED_COLLECTIONS,
    SELECTED_SMILES_FOR_EXPORT,
    CODIGO_BUSCAR,
    COL_TO_CHANGE_SELECT,
    NEW_COL_TYPE_SELECT,
)
