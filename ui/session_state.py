# SPDX-License-Identifier: LGPL-3.0-or-later
from state_keys import (
    ALL_TABLES,
    CUSTOM_QUERY,
    CURRENT_TABLE,
    DATABASE_ID,
    GROUP_COUNT_COLUMN,
    HEADERS,
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
