# SPDX-License-Identifier: LGPL-3.0-or-later
from application.database_use_cases import (
    create_database,
    open_database,
)
from clients.backend_gateway import BackendGatewayError, get_backend_gateway
from services.database import DatabaseState
from state_keys import (
    ALL_TABLES,
    CUSTOM_QUERY,
    CURRENT_TABLE,
    DATABASE_ID,
    EXISTING_DB_SELECT,
    GROUP_COUNT_COLUMN,
    HEADERS,
    HARMONSMILE_FEEDBACK_KIND,
    HARMONSMILE_FEEDBACK_MESSAGE,
    HARMONSMILE_JOB_ID,
    HARMONSMILE_RUNNING,
    INPUT_DATABASE_ID,
    PUBCHEM_JOB_COMPLETION_HANDLED,
    PUBCHEM_JOB_DB_PATH,
    PUBCHEM_JOB_ID,
    SELECTED_HEADERS,
    SELECTED_PROTEINS,
    SELECTING_CHAMANP,
    SELECTING_HARMONSMILE,
    SET_TEXT_INPUT_LOCKED,
    SCIENTIFIC_RECOVERY_NOTICE,
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
        HARMONSMILE_RUNNING: False,
        HARMONSMILE_JOB_ID: "",
        HARMONSMILE_FEEDBACK_KIND: "",
        HARMONSMILE_FEEDBACK_MESSAGE: "",
        SCIENTIFIC_RECOVERY_NOTICE: "",
    }

    for key, value in defaults.items():
        if key not in session_state:
            session_state[key] = value.copy() if isinstance(value, list) else value


def apply_database_state(session_state, database_state):
    if not database_state.success:
        return False

    previous_database_id = session_state.get(DATABASE_ID, "")
    if (
        previous_database_id != database_state.database_id
        and SCIENTIFIC_RECOVERY_NOTICE in session_state
    ):
        session_state[SCIENTIFIC_RECOVERY_NOTICE] = ""
    session_state[DATABASE_ID] = database_state.database_id
    session_state[CURRENT_TABLE] = database_state.current_table
    session_state[HEADERS] = list(database_state.headers)
    session_state[ALL_TABLES] = list(database_state.all_tables)
    session_state[SELECTED_HEADERS] = list(database_state.selected_headers)
    if database_state.input_locked is not None:
        session_state[SET_TEXT_INPUT_LOCKED] = database_state.input_locked
    return True


def load_database_tables(
    database_id,
    current_table,
    selected_headers,
):
    try:
        tables = get_backend_gateway().list_tables(database_id)
    except BackendGatewayError as error:
        return None, (
            "Unable to load database tables from the "
            f"CHEMVAULT API: {error}"
        )

    if current_table not in tables:
        current_table = (
            "main" if "main" in tables else next(iter(tables), "")
        )
    return DatabaseState(
        database_id=database_id,
        current_table=current_table,
        all_tables=tables,
    ), None


def load_database_metadata(
    database_id,
    current_table,
    selected_headers,
    all_tables,
):
    try:
        metadata = get_backend_gateway().get_table_metadata(
            database_id,
            current_table,
        )
    except BackendGatewayError as error:
        return None, (
            "Unable to load table metadata from the "
            f"CHEMVAULT API: {error}"
        )

    headers = metadata.columns
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
    database_id = session_state.get(DATABASE_ID, "")
    if database_id:
        try:
            recovered_jobs = get_backend_gateway().activate_scientific_runtime(
                database_id
            )
        except BackendGatewayError as error:
            return DatabaseState(
                database_id=database_id,
                current_table=session_state.get(CURRENT_TABLE, ""),
                headers=tuple(session_state.get(HEADERS, [])),
                all_tables=tuple(session_state.get(ALL_TABLES, [])),
                selected_headers=tuple(
                    session_state.get(SELECTED_HEADERS, [])
                ),
                message=(
                    "Unable to activate scientific recovery for the selected "
                    f"database: {error}"
                ),
                success=False,
            )
        if recovered_jobs:
            notices = [
                (
                    "Recovered interrupted HARMONSMILE job "
                    f"{recovered.job.job_id} for table "
                    f"'{recovered.table_name}' "
                    f"(status: {recovered.job.status.value})."
                )
                for recovered in recovered_jobs
            ]
            session_state[SCIENTIFIC_RECOVERY_NOTICE] = " ".join(notices)

    database_state, error = load_database_tables(
        database_id,
        session_state.get(CURRENT_TABLE, ""),
        session_state.get(SELECTED_HEADERS, []),
    )
    if not error and database_state.current_table:
        database_state, error = load_database_metadata(
            database_state.database_id,
            database_state.current_table,
            session_state.get(SELECTED_HEADERS, []),
            database_state.all_tables,
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
