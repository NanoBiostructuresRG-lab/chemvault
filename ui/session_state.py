# SPDX-License-Identifier: LGPL-3.0-or-later
import os

from application.database_use_cases import (
    create_database,
    open_database,
    refresh_database,
)
from clients.api_client import ChemVaultApiClient, ChemVaultApiError
from services.database import DatabaseState
from state_keys import (
    ALL_TABLES,
    CUSTOM_QUERY,
    CURRENT_TABLE,
    DATABASE_ID,
    EXISTING_DB_SELECT,
    GROUP_COUNT_COLUMN,
    HEADERS,
    INPUT_DATABASE_ID,
    PUBCHEM_JOB_COMPLETION_HANDLED,
    PUBCHEM_JOB_DB_PATH,
    PUBCHEM_JOB_ID,
    SELECTED_HEADERS,
    SELECTED_PROTEINS,
    SELECTING_CHAMANP,
    SELECTING_HARMONSMILE,
    SET_TEXT_INPUT_LOCKED,
)


def initialize_session_state(session_state, verify_directories_callback):
    """Initialize ChemVault session-state defaults without changing key names."""
    if DATABASE_ID not in session_state:
        verify_directories_callback()
        session_state[DATABASE_ID] = ""

    defaults = {
        SET_TEXT_INPUT_LOCKED: False,
        HEADERS: [],
        SELECTED_HEADERS: [],
        SELECTED_PROTEINS: [],
        CURRENT_TABLE: "",
        PUBCHEM_JOB_ID: "",
        PUBCHEM_JOB_DB_PATH: "",
        PUBCHEM_JOB_COMPLETION_HANDLED: False,
        ALL_TABLES: [],
        GROUP_COUNT_COLUMN: "",
        CUSTOM_QUERY: "",
        SELECTING_HARMONSMILE: "",
        SELECTING_CHAMANP: "",
    }

    for key, value in defaults.items():
        if key not in session_state:
            session_state[key] = value.copy() if isinstance(value, list) else value


def apply_database_state(session_state, database_state):
    if not database_state.success:
        return False

    session_state[DATABASE_ID] = database_state.database_id
    session_state[CURRENT_TABLE] = database_state.current_table
    session_state[HEADERS] = list(database_state.headers)
    session_state[ALL_TABLES] = list(database_state.all_tables)
    session_state[SELECTED_HEADERS] = list(database_state.selected_headers)
    if database_state.input_locked is not None:
        session_state[SET_TEXT_INPUT_LOCKED] = database_state.input_locked
    return True


def load_database_metadata(
    database_id,
    current_table,
    selected_headers,
    all_tables,
):
    api_url = os.getenv("CHEMVAULT_API_URL", "").strip()
    if not api_url:
        return (
            refresh_database(
                database_id,
                current_table,
                selected_headers,
            ),
            None,
        )

    try:
        response = ChemVaultApiClient(base_url=api_url).get_table_metadata(
            database_id,
            current_table,
        )
    except ChemVaultApiError as error:
        return None, (
            "Unable to load table metadata from the "
            f"CHEMVAULT API: {error}"
        )

    headers = tuple(response.get("columns", []))
    return DatabaseState(
        database_id=database_id,
        current_table=current_table,
        headers=headers,
        all_tables=tuple(all_tables),
        selected_headers=tuple(
            header for header in selected_headers if header in headers
        ),
    ), None


def refresh_database_state(session_state):
    database_state, error = load_database_metadata(
        session_state.get(DATABASE_ID, ""),
        session_state.get(CURRENT_TABLE, ""),
        session_state.get(SELECTED_HEADERS, []),
        session_state.get(ALL_TABLES, []),
    )
    if error:
        return DatabaseState(
            database_id=session_state.get(DATABASE_ID, ""),
            current_table=session_state.get(CURRENT_TABLE, ""),
            headers=tuple(session_state.get(HEADERS, [])),
            all_tables=tuple(session_state.get(ALL_TABLES, [])),
            selected_headers=tuple(
                session_state.get(SELECTED_HEADERS, [])
            ),
            message=error,
            success=False,
        )
    apply_database_state(session_state, database_state)
    return database_state


def set_database_from_input(session_state):
    database_state = create_database(
        session_state.get(INPUT_DATABASE_ID, ""),
    )
    apply_database_state(session_state, database_state)
    return database_state


def load_database_from_selection(session_state):
    database_state = open_database(
        session_state.get(EXISTING_DB_SELECT, ""),
    )
    apply_database_state(session_state, database_state)
    return database_state
