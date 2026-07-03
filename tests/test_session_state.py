# SPDX-License-Identifier: LGPL-3.0-or-later
from services.database import DatabaseState
from clients.backend_gateway import BackendGatewayError, TableMetadata
from ui import session_state as session_state_module
from ui.session_state import (
    apply_database_state,
    initialize_session_state,
    load_database_metadata,
    load_database_tables,
)


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


def test_apply_database_state_updates_streamlit_owned_state():
    session_state = {
        "database_id": "old_db",
        "current_table": "old_table",
        "headers": ["old_column"],
        "all_tables": ["old_table"],
        "selected_headers": ["old_column"],
        "set_text_input_locked": False,
    }
    database_state = DatabaseState(
        database_id="new_db",
        current_table="main",
        headers=("CID", "SMILES"),
        all_tables=("main",),
        selected_headers=("CID",),
        input_locked=True,
    )

    applied = apply_database_state(session_state, database_state)

    assert applied is True
    assert session_state == {
        "database_id": "new_db",
        "current_table": "main",
        "headers": ["CID", "SMILES"],
        "all_tables": ["main"],
        "selected_headers": ["CID"],
        "set_text_input_locked": True,
    }


def test_database_tables_uses_local_path_by_default(monkeypatch):
    expected = DatabaseState(
        database_id="test_db",
        current_table="main",
        all_tables=("main", "curated"),
    )
    calls = []

    class FakeGateway:
        def list_tables(self, database_id):
            calls.append(database_id)
            return ("main", "curated")

    monkeypatch.setattr(
        session_state_module,
        "get_backend_gateway",
        lambda: FakeGateway(),
    )

    state, error = load_database_tables(
        "test_db",
        "main",
        ["CID"],
    )

    assert state == expected
    assert error is None
    assert calls == ["test_db"]


def test_database_tables_uses_api_when_configured(monkeypatch):
    calls = []

    class FakeGateway:
        def list_tables(self, database_id):
            calls.append(("tables", database_id))
            return ("main", "curated")

    monkeypatch.setattr(
        session_state_module,
        "get_backend_gateway",
        lambda: FakeGateway(),
    )

    state, error = load_database_tables(
        "test_db",
        "missing",
        ["CID"],
    )

    assert error is None
    assert state == DatabaseState(
        database_id="test_db",
        current_table="main",
        all_tables=("main", "curated"),
    )
    assert calls == [
        ("tables", "test_db"),
    ]


def test_database_tables_returns_visible_api_error(monkeypatch):
    class FailingGateway:
        def list_tables(self, *args, **kwargs):
            raise BackendGatewayError("request timed out")

    monkeypatch.setattr(
        session_state_module,
        "get_backend_gateway",
        lambda: FailingGateway(),
    )

    state, error = load_database_tables(
        "test_db",
        "main",
        ["CID"],
    )

    assert state is None
    assert error == (
        "Unable to load database tables from the "
        "CHEMVAULT API: request timed out"
    )


def test_database_metadata_uses_local_path_by_default(monkeypatch):
    calls = []

    class FakeGateway:
        def get_table_metadata(self, database_id, table_name):
            calls.append((database_id, table_name))
            return TableMetadata(
                columns=("CID", "SMILES"),
                row_count=1,
            )

    monkeypatch.setattr(
        session_state_module,
        "get_backend_gateway",
        lambda: FakeGateway(),
    )

    state, error = load_database_metadata(
        "test_db",
        "main",
        ["CID"],
        ["main"],
    )

    assert state == DatabaseState(
        database_id="test_db",
        current_table="main",
        headers=("CID", "SMILES"),
        all_tables=("main",),
        selected_headers=("CID",),
    )
    assert error is None
    assert calls == [("test_db", "main")]


def test_database_metadata_uses_api_when_configured(monkeypatch):
    calls = []

    class FakeGateway:
        def get_table_metadata(self, database_id, table_name):
            calls.append(("metadata", database_id, table_name))
            return TableMetadata(
                columns=("CID", "SMILES"),
                row_count=1,
            )

    monkeypatch.setattr(
        session_state_module,
        "get_backend_gateway",
        lambda: FakeGateway(),
    )

    state, error = load_database_metadata(
        "test_db",
        "main",
        ["CID", "stale"],
        ["main", "curated"],
    )

    assert error is None
    assert state == DatabaseState(
        database_id="test_db",
        current_table="main",
        headers=("CID", "SMILES"),
        all_tables=("main", "curated"),
        selected_headers=("CID",),
    )
    assert calls == [
        ("metadata", "test_db", "main"),
    ]


def test_database_metadata_returns_visible_api_error(monkeypatch):
    class FailingGateway:
        def get_table_metadata(self, *args, **kwargs):
            raise BackendGatewayError("request timed out")

    monkeypatch.setattr(
        session_state_module,
        "get_backend_gateway",
        lambda: FailingGateway(),
    )

    state, error = load_database_metadata(
        "test_db",
        "main",
        ["CID"],
        ["main"],
    )

    assert state is None
    assert error == (
        "Unable to load table metadata from the "
        "CHEMVAULT API: request timed out"
    )
