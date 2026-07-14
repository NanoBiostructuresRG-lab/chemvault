# SPDX-License-Identifier: LGPL-3.0-or-later
import state_keys


def test_all_session_keys_are_unique():
    assert len(state_keys.ALL_SESSION_KEYS) == len(set(state_keys.ALL_SESSION_KEYS))


def test_existing_core_session_key_strings_are_preserved():
    assert state_keys.DATABASE_ID == "database_id"
    assert state_keys.CURRENT_TABLE == "current_table"
    assert state_keys.HEADERS == "headers"
    assert state_keys.SELECTED_HEADERS == "selected_headers"
    assert state_keys.SELECTED_PROTEINS == "selected_proteins"
    assert state_keys.ALL_TABLES == "all_tables"
    assert state_keys.CUSTOM_QUERY == "custom_query"
    assert (
        state_keys.SCIENTIFIC_RECOVERY_NOTICE
        == "scientific_recovery_notice"
    )


def test_existing_widget_session_key_strings_are_preserved():
    assert state_keys.INPUT_DATABASE_ID == "input_database_id"
    assert state_keys.EXISTING_DB_SELECT == "existing_db_select"
    assert state_keys.NEW_TABLE_NAME == "new_table_name"
    assert state_keys.TYPE_OF_FILTER == "type_of_filter"
    assert state_keys.SELECTED_IDENTIFIER == "selected_identifier"
    assert state_keys.SELECTED_SMILES_FOR_EXPORT == "selected_smiles_for_export"
    assert state_keys.COL_TO_CHANGE_SELECT == "col_to_change_select"
