# SPDX-License-Identifier: LGPL-3.0-or-later
import sqlite3

import pandas as pd

from application.database_use_cases import DatabaseMetrics
from clients.backend_gateway import BackendGatewayError
from services.database import DatabaseState
from ui import main_page
from ui.main_page import (
    ACTIVITY_SUMMARY_COLUMNS,
    STRUCTURED_ACTIVITY_SUBSET_SUCCESS,
    STRUCTURED_ACTIVITY_SUBSET_TABLE_TO_SELECT,
    _apply_pending_structured_activity_subset_selection,
    _created_filtered_activity_table,
    _filter_visible_column_options,
    _get_activity_enrichment_job_summary,
    _get_protein_traceability_summary,
    _has_explicit_activity_filter,
    _refresh_database_state,
    _structured_activity_filter_signature,
    load_database_metrics,
    load_selected_columns_preview,
    load_table_schema,
)


def test_main_column_options_hide_only_legacy_activity_summary_columns():
    headers = [
        "primary_id",
        "CID",
        "AIDs",
        "Proteins",
        "Compound_Name",
        "Activity_Type",
        "Activity_Value",
        "Activity_Enrichment_Status",
        "Activity_Value_Raw",
    ]
    selected_headers = ["CID", "Activity_Type", "Activity_Value", "Activity_Value_Raw"]

    options, selected = _filter_visible_column_options(
        headers,
        selected_headers,
        "main",
    )

    assert options == [
        "primary_id",
        "CID",
        "AIDs",
        "Proteins",
        "Compound_Name",
        "Activity_Value_Raw",
    ]
    assert selected == ["CID", "Activity_Value_Raw"]


def test_non_main_column_options_preserve_real_activity_columns():
    headers = ["CID", "AID", "Activity_Type", "Activity_Value", "Unit"]

    options, selected = _filter_visible_column_options(
        headers,
        ["CID", "Activity_Type", "Activity_Value"],
        "user_created_activity_results",
    )

    assert options == headers
    assert selected == ["CID", "Activity_Type", "Activity_Value"]


def test_activity_summary_columns_are_exact_legacy_main_columns():
    assert ACTIVITY_SUMMARY_COLUMNS == {
        "Activity_Type",
        "Activity_Value",
        "Activity_Enrichment_Status",
    }


def test_activity_subset_requires_an_explicit_structured_activity_filter():
    assert _has_explicit_activity_filter(
        activity_types=[],
        units=[],
        outcomes=[],
        aids=[],
        value_range=None,
    ) is False
    assert _has_explicit_activity_filter(
        activity_types=["EC50"],
        units=[],
        outcomes=[],
        aids=[],
        value_range=None,
    ) is True
    assert _has_explicit_activity_filter(
        activity_types=[],
        units=[],
        outcomes=[],
        aids=["123"],
        value_range=None,
    ) is True
    assert _has_explicit_activity_filter(
        activity_types=[],
        units=[],
        outcomes=[],
        aids=[],
        value_range=(1.0, 2.0),
    ) is True


def test_pending_structured_activity_subset_selection_updates_current_table():
    session_state = {
        "current_table": "main",
        STRUCTURED_ACTIVITY_SUBSET_TABLE_TO_SELECT: "activity_subset_EC50",
    }

    selected_table = _apply_pending_structured_activity_subset_selection(session_state)

    assert selected_table == "activity_subset_EC50"
    assert session_state["current_table"] == "activity_subset_EC50"
    assert STRUCTURED_ACTIVITY_SUBSET_TABLE_TO_SELECT not in session_state


def test_created_filtered_activity_table_matches_only_same_filter_and_database():
    connection = sqlite3.connect(":memory:")
    connection.execute('CREATE TABLE "activity_subset_EC50" (CID TEXT)')
    filter_kwargs = {
        "activity_types": ["EC50"],
        "outcomes": ["Active"],
        "units": ["MICROMOLAR"],
        "aids": ["123"],
        "value_range": (1.0, 2.0),
    }
    signature = _structured_activity_filter_signature("test_db", filter_kwargs)
    session_state = {
        STRUCTURED_ACTIVITY_SUBSET_SUCCESS: {
            "filter_signature": signature,
            "table_name": "activity_subset_EC50",
        }
    }

    assert _created_filtered_activity_table(
        session_state,
        connection,
        signature,
    ) == "activity_subset_EC50"
    assert _created_filtered_activity_table(
        session_state,
        connection,
        _structured_activity_filter_signature(
            "test_db",
            {**filter_kwargs, "outcomes": ["Inactive"]},
        ),
    ) == ""
    assert _created_filtered_activity_table(
        session_state,
        connection,
        _structured_activity_filter_signature("other_db", filter_kwargs),
    ) == ""


def test_structured_activity_filter_signature_ignores_multiselect_order():
    first = _structured_activity_filter_signature(
        "test_db",
        {
            "activity_types": ["EC50", "IC50"],
            "outcomes": ["Active", "Inactive"],
            "units": [],
            "aids": ["2", "1"],
            "value_range": None,
        },
    )
    second = _structured_activity_filter_signature(
        "test_db",
        {
            "activity_types": ["IC50", "EC50"],
            "outcomes": ["Inactive", "Active"],
            "units": [],
            "aids": ["1", "2"],
            "value_range": None,
        },
    )

    assert first == second


def test_selected_columns_preview_uses_local_path_by_default(
    monkeypatch,
):
    expected = pd.DataFrame([{"CID": "1"}])
    calls = []

    class FakeGateway:
        def preview_table(self, *args, **kwargs):
            calls.append((args, kwargs))
            return expected

    monkeypatch.setattr(
        main_page,
        "get_backend_gateway",
        lambda: FakeGateway(),
    )

    preview, error = load_selected_columns_preview(
        "test_db",
        "main",
        ["CID", "SMILES"],
        ["CID"],
    )

    assert preview is expected
    assert error is None
    assert calls == [
        (("test_db", "main"), {"columns": ["CID"], "limit": 10})
    ]


def test_selected_columns_preview_uses_api_when_configured(monkeypatch):
    calls = []

    class FakeGateway:
        def preview_table(self, database_id, table_name, columns=None, limit=10):
            calls.append(("preview", database_id, table_name, columns, limit))
            return pd.DataFrame([{"CID": "1", "SMILES": "CCO"}])

    monkeypatch.setattr(main_page, "get_backend_gateway", lambda: FakeGateway())

    preview, error = load_selected_columns_preview(
        "test_db",
        "main",
        ["CID", "SMILES", "Name"],
        ["CID", "SMILES"],
    )

    assert error is None
    assert preview.to_dict(orient="records") == [
        {"CID": "1", "SMILES": "CCO"}
    ]
    assert calls == [
        ("preview", "test_db", "main", ["CID", "SMILES"], 10),
    ]


def test_selected_columns_preview_returns_visible_api_error(monkeypatch):
    class FailingGateway:
        def preview_table(self, *args, **kwargs):
            raise BackendGatewayError("request timed out")

    monkeypatch.setattr(
        main_page,
        "get_backend_gateway",
        lambda: FailingGateway(),
    )

    preview, error = load_selected_columns_preview(
        "test_db",
        "main",
        ["CID"],
        ["CID"],
    )

    assert preview is None
    assert error == (
        "Unable to load the selected columns preview from the "
        "CHEMVAULT API: request timed out"
    )


def test_database_metrics_uses_local_path_by_default(monkeypatch):
    connection = object()
    expected = DatabaseMetrics(row_count=10, group_count=2)
    calls = []

    class FakeGateway:
        def get_table_metrics(self, *args, **kwargs):
            calls.append((args, kwargs))
            return expected

    monkeypatch.setattr(
        main_page,
        "get_backend_gateway",
        lambda: FakeGateway(),
    )

    metrics, error = load_database_metrics(
        "test_db",
        "main",
        "category",
        ["CID", "category"],
        connection,
    )

    assert metrics is expected
    assert error is None
    assert calls == [
        (("test_db", "main"), {"group_column": "category"})
    ]


def test_database_metrics_uses_api_when_configured(monkeypatch):
    calls = []

    class FakeGateway:
        def get_table_metrics(
            self,
            database_id,
            table_name,
            group_column="",
        ):
            calls.append(
                ("metrics", database_id, table_name, group_column)
            )
            return DatabaseMetrics(row_count=100, group_count=4)

    monkeypatch.setattr(main_page, "get_backend_gateway", lambda: FakeGateway())

    metrics, error = load_database_metrics(
        "test_db",
        "main",
        "category",
        ["CID", "category"],
        object(),
    )

    assert metrics == DatabaseMetrics(row_count=100, group_count=4)
    assert error is None
    assert calls == [
        ("metrics", "test_db", "main", "category"),
    ]


def test_database_metrics_returns_visible_api_error(monkeypatch):
    class FailingGateway:
        def get_table_metrics(self, *args, **kwargs):
            raise BackendGatewayError("request timed out")

    monkeypatch.setattr(
        main_page,
        "get_backend_gateway",
        lambda: FailingGateway(),
    )

    metrics, error = load_database_metrics(
        "test_db",
        "main",
        "category",
        ["CID", "category"],
        object(),
    )

    assert metrics is None
    assert error == (
        "Unable to load the database metrics from the "
        "CHEMVAULT API: request timed out"
    )


def test_table_schema_delegates_to_backend_gateway(monkeypatch):
    expected = ({"name": "CID", "data_type": "TEXT"},)
    calls = []

    class FakeGateway:
        def get_table_schema(self, database_id, table_name):
            calls.append((database_id, table_name))
            return expected

    monkeypatch.setattr(
        main_page,
        "get_backend_gateway",
        lambda: FakeGateway(),
    )

    schema, error = load_table_schema("test_db", "main")

    assert schema is expected
    assert error is None
    assert calls == [("test_db", "main")]


def test_table_schema_returns_visible_http_error(monkeypatch):
    class FailingGateway:
        def get_table_schema(self, *args, **kwargs):
            raise BackendGatewayError("request timed out")

    monkeypatch.setattr(
        main_page,
        "get_backend_gateway",
        lambda: FailingGateway(),
    )

    schema, error = load_table_schema("test_db", "main")

    assert schema is None
    assert error == (
        "Unable to load the active table schema from the "
        "CHEMVAULT API: request timed out"
    )


def test_refresh_database_state_displays_metadata_error(monkeypatch):
    error_state = DatabaseState(
        message="Unable to load table metadata from the CHEMVAULT API",
        success=False,
    )
    errors = []
    monkeypatch.setattr(
        main_page,
        "refresh_database_state",
        lambda session_state: error_state,
    )
    monkeypatch.setattr(main_page.st, "error", errors.append)

    result = _refresh_database_state()

    assert result is error_state
    assert errors == [
        "Unable to load table metadata from the CHEMVAULT API"
    ]


def test_activity_enrichment_job_summary_handles_missing_compound_assays():
    connection = sqlite3.connect(":memory:")

    assert _get_activity_enrichment_job_summary(connection) is None


def test_activity_enrichment_job_summary_handles_empty_compound_assays():
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE compound_assays (CID TEXT, AID TEXT, Protein TEXT)")

    assert _get_activity_enrichment_job_summary(connection) is None


def test_activity_enrichment_job_summary_counts_distinct_protein_aid_pairs():
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE compound_assays (CID TEXT, AID TEXT, Protein TEXT)")
    connection.executemany(
        "INSERT INTO compound_assays (CID, AID, Protein) VALUES (?, ?, ?)",
        [
            ("101", "11", "P1"),
            ("101", "11", "P1"),
            ("102", "11", "P1"),
            ("103", "11", "P2"),
            ("104", "12", "P1"),
        ],
    )

    summary = _get_activity_enrichment_job_summary(connection)

    assert summary == {
        "total_aids": 3,
        "cid_aid_links": 5,
        "proteins": ["P1", "P2"],
    }


def test_protein_traceability_summary_exposes_skipped_activity_status_count():
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE compound_assays (CID TEXT, AID TEXT, Protein TEXT)")
    connection.execute(
        """
        CREATE TABLE main (
            CID TEXT,
            Activity_Enrichment_Status TEXT
        )
        """
    )
    connection.executemany(
        "INSERT INTO compound_assays (CID, AID, Protein) VALUES (?, ?, ?)",
        [("1", "11", "P34971"), ("2", "12", "P34971")],
    )
    connection.executemany(
        "INSERT INTO main (CID, Activity_Enrichment_Status) VALUES (?, ?)",
        [("1", "skipped_aid_limit"), ("2", "skipped_aid_limit")],
    )

    summary = _get_protein_traceability_summary(connection)

    assert summary["activity_status"] == "skipped_aid_limit: 2"
    assert summary["activity_status_counts"] == {"skipped_aid_limit": 2}
