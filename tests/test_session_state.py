# SPDX-License-Identifier: LGPL-3.0-or-later
from ui.session_state import initialize_session_state


def test_initialize_session_state_sets_current_defaults_when_database_is_missing():
    session_state = {}
    calls = []

    initialize_session_state(session_state, lambda: calls.append("verified"))

    assert calls == ["verified"]
    assert session_state["database_id"] == ""
    assert session_state["set_text_input_locked"] is False
    assert session_state["headers"] == []
    assert session_state["selected_headers"] == []
    assert session_state["selected_proteins"] == []
    assert session_state["current_table"] == ""
    assert session_state["all_tables"] == []
    assert session_state["grupo_a_contar"] == ""
    assert session_state["custom_query"] == ""
    assert session_state["selecting_harmonsmile"] == ""
    assert session_state["selecting_chamanp"] == ""


def test_initialize_session_state_preserves_existing_values():
    session_state = {
        "database_id": "existing_db",
        "headers": ["CID"],
        "selected_headers": ["CID"],
        "current_table": "main",
        "selecting_harmonsmile": True,
    }
    calls = []

    initialize_session_state(session_state, lambda: calls.append("verified"))

    assert calls == []
    assert session_state["database_id"] == "existing_db"
    assert session_state["headers"] == ["CID"]
    assert session_state["selected_headers"] == ["CID"]
    assert session_state["current_table"] == "main"
    assert session_state["selecting_harmonsmile"] is True
    assert session_state["selecting_chamanp"] == ""


def test_initialize_session_state_uses_independent_default_lists():
    first_state = {}
    second_state = {}

    initialize_session_state(first_state, lambda: None)
    initialize_session_state(second_state, lambda: None)
    first_state["headers"].append("CID")

    assert second_state["headers"] == []
