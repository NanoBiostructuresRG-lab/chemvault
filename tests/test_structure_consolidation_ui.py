# SPDX-License-Identifier: LGPL-3.0-or-later
import ast
import inspect
from pathlib import Path
from types import SimpleNamespace

import pytest

from clients.backend_gateway import BackendGatewayError
from ui import sidebar


class _Context:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def _result():
    return SimpleNamespace(
        table_name="main_structure_consolidated",
        source_row_count=10,
        valid_source_row_count=8,
        unique_structure_count=6,
        created_row_count=4,
        active_structure_count=3,
        inactive_structure_count=1,
        conflicting_structure_count=1,
        non_binary_structure_count=1,
        unusable_row_count=2,
        consolidated_duplicate_count=2,
    )


def _eligible_state():
    return {
        "database_id": "test_db",
        "current_table": "main",
        "headers": list(sidebar.STRUCTURE_CONSOLIDATION_REQUIRED_COLUMNS),
        "selected_headers": [],
        "all_tables": ["main"],
    }


def _render(
    monkeypatch,
    state,
    *,
    clicked=False,
    gateway=None,
    refresh=None,
    metadata_origin=None,
):
    output = {
        "buttons": [],
        "captions": [],
        "markdown": [],
        "successes": [],
        "errors": [],
        "spinners": [],
        "metadata_calls": [],
    }

    def button(label, **kwargs):
        output["buttons"].append((label, kwargs))
        return (
            clicked
            and not kwargs.get("disabled", False)
            and kwargs.get("key")
            == "curate_run_structure_consolidation"
        )

    def spinner(message):
        output["spinners"].append(message)
        return _Context()

    class GatewayAdapter:
        def get_table_metadata(self, database_id, table_name):
            output["metadata_calls"].append((database_id, table_name))
            return SimpleNamespace(origin=metadata_origin)

        def consolidate_structure_table(self, database_id, source_table):
            return gateway.consolidate_structure_table(
                database_id,
                source_table,
            )

    monkeypatch.setattr(sidebar.st, "session_state", state)
    monkeypatch.setattr(sidebar.st, "container", lambda **_kwargs: _Context())
    monkeypatch.setattr(
        sidebar.st,
        "markdown",
        lambda value, **_kwargs: output["markdown"].append(value),
    )
    monkeypatch.setattr(sidebar.st, "caption", output["captions"].append)
    monkeypatch.setattr(sidebar.st, "button", button)
    monkeypatch.setattr(sidebar.st, "spinner", spinner)
    monkeypatch.setattr(sidebar.st, "success", output["successes"].append)
    monkeypatch.setattr(sidebar.st, "error", output["errors"].append)
    monkeypatch.setattr(
        sidebar,
        "get_backend_gateway",
        lambda: GatewayAdapter(),
    )
    if refresh is not None:
        monkeypatch.setattr(sidebar, "refresh_database_state", refresh)

    output["result"] = sidebar.render_structure_consolidation_card()
    return output


@pytest.mark.parametrize(
    "state",
    [
        {"database_id": "", "current_table": "", "headers": []},
        {"database_id": "test_db", "current_table": "", "headers": []},
    ],
)
def test_card_is_disabled_without_active_database_and_table(monkeypatch, state):
    output = _render(monkeypatch, state)

    assert output["buttons"] == [
        (
            "Run",
            {
                "key": "curate_run_structure_consolidation",
                "disabled": True,
            },
        )
    ]


def test_card_is_disabled_without_required_harmonsmile_columns(monkeypatch):
    state = _eligible_state()
    state["headers"].remove("SMILES_Harmonization_Status")

    output = _render(monkeypatch, state)

    assert output["buttons"][0][1]["disabled"] is True
    assert output["captions"] == [
        "Select a SMILES HARMONIZED activity table to enable "
        "consolidation."
    ]


@pytest.mark.parametrize(
    "missing_column",
    [
        "Activity_Type",
        "Relation",
        "Activity_Value",
        "Activity_Value_Raw",
        "Unit",
    ],
)
def test_card_is_disabled_without_required_activity_columns(
    monkeypatch,
    missing_column,
):
    state = _eligible_state()
    state["headers"].remove(missing_column)

    output = _render(monkeypatch, state)

    assert output["buttons"][0][1]["disabled"] is True
    assert output["captions"] == [
        "Select a SMILES HARMONIZED activity table to enable "
        "consolidation."
    ]


def test_card_is_enabled_for_eligible_active_table(monkeypatch):
    output = _render(monkeypatch, _eligible_state())

    assert output["markdown"] == ["**ACTIVITY LABELS**"]
    assert output["captions"] == []
    assert output["buttons"][0][1]["disabled"] is False
    assert output["metadata_calls"] == [("test_db", "main")]


def test_card_is_disabled_for_already_consolidated_table(monkeypatch):
    state = _eligible_state()
    state["current_table"] = "main_structure_consolidated"

    output = _render(
        monkeypatch,
        state,
        clicked=True,
        metadata_origin="structure_consolidation",
    )

    assert output["buttons"][0][1]["disabled"] is True
    assert output["result"] is None
    assert output["captions"] == [
        "This table already contains consolidated activity labels."
    ]


def test_card_invokes_gateway_and_selects_refreshed_derived_table(monkeypatch):
    state = _eligible_state()
    state["selected_headers"] = ["CID"]
    calls = []
    expected = _result()

    class Gateway:
        def consolidate_structure_table(self, database_id, source_table):
            calls.append(("gateway", database_id, source_table))
            return expected

    def refresh(current_state):
        calls.append(("refresh", current_state["current_table"]))
        current_state["all_tables"] = ["main", expected.table_name]
        return SimpleNamespace(success=True, message="")

    output = _render(
        monkeypatch,
        state,
        clicked=True,
        gateway=Gateway(),
        refresh=refresh,
    )

    assert output["result"] is expected
    assert calls == [
        ("gateway", "test_db", "main"),
        ("refresh", expected.table_name),
    ]
    assert state["current_table"] == expected.table_name
    assert state["selected_headers"] == []
    assert state["all_tables"] == ["main", expected.table_name]


def test_card_displays_concise_success_feedback(monkeypatch):
    expected = _result()

    class Gateway:
        def consolidate_structure_table(self, *_args):
            return expected

    output = _render(
        monkeypatch,
        _eligible_state(),
        clicked=True,
        gateway=Gateway(),
        refresh=lambda _state: SimpleNamespace(success=True, message=""),
    )

    assert len(output["successes"]) == 1
    message = output["successes"][0]
    assert message == (
        "Created table 'main_structure_consolidated'. "
        "Created structures: 4."
    )
    assert "Source rows" not in message
    assert "conflicts excluded" not in message


def test_card_displays_gateway_error_without_changing_active_table(monkeypatch):
    state = _eligible_state()

    class Gateway:
        def consolidate_structure_table(self, *_args):
            raise BackendGatewayError("request timed out")

    output = _render(
        monkeypatch,
        state,
        clicked=True,
        gateway=Gateway(),
    )

    assert output["result"] is None
    assert output["successes"] == []
    assert output["errors"] == [
        "Structure consolidation could not be completed: request timed out"
    ]
    assert state["current_table"] == "main"


def test_card_uses_only_gateway_for_consolidation_and_is_ordered_in_curate():
    function_source = inspect.getsource(
        sidebar.render_structure_consolidation_card
    )
    assert (
        "gateway.consolidate_structure_table"
        in function_source
    )
    assert "get_connection" not in function_source
    assert "sqlite3" not in function_source
    assert "read_sql" not in function_source

    module_path = Path(sidebar.__file__)
    module_tree = ast.parse(module_path.read_text(encoding="utf-8"))
    imported_modules = {
        node.module
        for node in ast.walk(module_tree)
        if isinstance(node, ast.ImportFrom)
    }
    assert "application.structure_consolidation" not in imported_modules
    assert "services.structure_consolidation" not in imported_modules

    curate_source = inspect.getsource(sidebar.render_curate_card)
    consolidation_position = curate_source.index(
        "render_structure_consolidation_card()"
    )
    assert curate_source.index("**SMILES HARMONIZED**") < consolidation_position
    assert (
        "Load or select a database to enable SMILES calculations."
        in curate_source
    )
    assert (
        "Select one CID column to enable SMILES calculations."
        in curate_source
    )
    assert consolidation_position < curate_source.index("**CHAMANP**")
