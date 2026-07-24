# SPDX-License-Identifier: LGPL-3.0-or-later
import inspect
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


def test_database_summary_uses_active_table_semantic_labels(monkeypatch):
    markdown_calls = []
    connection = sqlite3.connect(":memory:")

    class Container:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(
        main_page.st,
        "markdown",
        lambda value, **kwargs: markdown_calls.append((value, kwargs)),
    )

    main_page.render_database_summary(
        Container(),
        "test_db",
        "activity_subset_IC50",
        10,
        2,
        "Outcome",
        connection,
    )

    assert len(markdown_calls) == 1
    rendered, kwargs = markdown_calls[0]
    assert kwargs == {"unsafe_allow_html": True}
    for text in (
        "Database",
        "Active table",
        "Rows in active table",
        "Distinct values",
        "Column: Outcome",
        "test_db",
        "activity_subset_IC50",
    ):
        assert text in rendered
    assert ">Table</div>" not in rendered
    assert ">Rows</div>" not in rendered
    assert "Unique groups" not in rendered
    assert rendered.count("data-cv-summary-section=") == 1
    assert rendered.count("data-cv-summary-metric") == 4
    assert "Active table and row summary." not in inspect.getsource(
        main_page.render_database_card
    )


def test_database_summary_groups_pubchem_provenance_and_activity_status(
    monkeypatch,
):
    connection = sqlite3.connect(":memory:")
    connection.execute(
        "CREATE TABLE compound_assays (CID TEXT, AID TEXT, Protein TEXT)"
    )
    connection.executemany(
        "INSERT INTO compound_assays (CID, AID, Protein) VALUES (?, ?, ?)",
        [
            ("1", "11", "P1"),
            ("1", "12", "P1"),
            ("2", "11", "P2"),
        ],
    )
    connection.execute(
        "CREATE TABLE main (CID TEXT, Activity_Enrichment_Status TEXT)"
    )
    connection.executemany(
        "INSERT INTO main (CID, Activity_Enrichment_Status) VALUES (?, ?)",
        [
            ("1", "enriched"),
            ("2", "enriched"),
            ("3", "partial_or_failed"),
        ],
    )
    markdown_calls = []
    warnings = []

    class Container:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def warning(self, value):
            warnings.append(value)

    monkeypatch.setattr(
        main_page.st,
        "markdown",
        lambda value, **kwargs: markdown_calls.append((value, kwargs)),
    )

    main_page.render_database_summary(
        Container(),
        "test_db",
        "main",
        3,
        2,
        "Outcome",
        connection,
    )

    assert len(markdown_calls) == 1
    rendered, kwargs = markdown_calls[0]
    assert kwargs == {"unsafe_allow_html": True}
    assert rendered.startswith("<div")
    assert rendered == rendered.strip()
    for text in (
        "PubChem assay coverage",
        "Compounds linked to assays",
        "Proteins represented",
        "PubChem assays",
        "Compound–assay links",
        "Activity data availability",
        "Compounds with activity data",
        "Compounds with incomplete activity data",
    ):
        assert text in rendered
    section_titles = (
        "Active table",
        "PubChem assay coverage",
        "Activity data availability",
    )
    section_fragments = []
    for index, title in enumerate(section_titles):
        marker = f'data-cv-summary-section="{title}"'
        start = rendered.index(marker)
        if index + 1 < len(section_titles):
            next_marker = (
                f'data-cv-summary-section="{section_titles[index + 1]}"'
            )
            end = rendered.index(next_marker)
        else:
            end = len(rendered)
        section_fragments.append(rendered[start:end])
    assert [
        fragment.count("data-cv-summary-metric")
        for fragment in section_fragments
    ] == [4, 4, 2]
    assert rendered.count("border-top: 1px solid var(--cv-border)") == 3
    assert rendered.count("padding: 0.75rem 0") == 3
    assert rendered.count("margin-bottom: 0.45rem") == 3
    assert rendered.count("data-cv-summary-grid") == 3
    assert rendered.count("auto-fit") == 3
    assert rendered.count("minmax(min(100%, 145px), 1fr)") == 3
    assert "Compounds with activity data: 2" not in rendered
    assert "Compounds with incomplete activity data: 1" not in rendered
    activity_data_position = rendered.index("Compounds with activity data")
    incomplete_position = rendered.index(
        "Compounds with incomplete activity data"
    )
    assert activity_data_position < incomplete_position
    first_metric_lines = {
        line.strip()
        for line in rendered[
            activity_data_position:incomplete_position
        ].splitlines()
    }
    second_metric_lines = {
        line.strip()
        for line in rendered[incomplete_position:].splitlines()
    }
    assert any(line.endswith(">2</div>") for line in first_metric_lines)
    assert any(line.endswith(">1</div>") for line in second_metric_lines)
    assert "Unique CIDs" not in rendered
    assert "Seed proteins" not in rendered
    assert "Individual AIDs" not in rendered
    assert "CID-AID links" not in rendered
    assert "Latest activity retrieval status" not in rendered
    assert "partial_or_failed" not in rendered
    assert warnings == []


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


def test_activity_repair_uses_collapsed_advanced_maintenance_presentation(
    monkeypatch,
):
    connection = sqlite3.connect(":memory:")
    connection.execute(
        "CREATE TABLE compound_assays (CID TEXT, AID TEXT, Protein TEXT)"
    )
    connection.executemany(
        "INSERT INTO compound_assays (CID, AID, Protein) VALUES (?, ?, ?)",
        [
            ("101", "11", "P1"),
            ("102", "11", "P1"),
            ("103", "12", "P2"),
        ],
    )
    output = {
        "expanders": [],
        "markdown": [],
        "captions": [],
        "buttons": [],
    }

    class Context:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def expander(label, **kwargs):
        output["expanders"].append((label, kwargs))
        return Context()

    def button(label, **kwargs):
        output["buttons"].append((label, kwargs))
        return False

    monkeypatch.setattr(main_page.st, "expander", expander)
    monkeypatch.setattr(main_page.st, "markdown", output["markdown"].append)
    monkeypatch.setattr(main_page.st, "caption", output["captions"].append)
    monkeypatch.setattr(main_page.st, "button", button)

    main_page.render_activity_enrichment_action(connection)

    assert output["expanders"] == [
        ("Repair activity records", {"expanded": False})
    ]
    assert output["markdown"] == ["**Repair missing activity records**"]
    assert output["captions"] == [
        "Retry PubChem activity retrieval for persisted assay links. "
        "Existing activity records are preserved.",
        "Reconstructible AIDs: 2; CID-AID links: 3; Proteins: P1, P2",
    ]
    assert output["buttons"] == [
        (
            "Run activity repair",
            {"key": "enrich_structured_activity_from_assay_links"},
        )
    ]


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
