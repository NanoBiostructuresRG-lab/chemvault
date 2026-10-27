# SPDX-License-Identifier: LGPL-3.0-or-later
import inspect
import sqlite3
from pathlib import Path

from application.structure_consolidation import StructureConsolidationSummary
from clients.backend_gateway import TableMetadata
from ui import main_page
from ui.state_keys import CURRENT_TABLE, DATABASE_ID


class _Context:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def _summary():
    return StructureConsolidationSummary(
        source_table="main",
        source_row_count=10,
        valid_source_row_count=8,
        unusable_row_count=2,
        unique_structure_count=6,
        conflicting_structure_count=1,
        non_binary_structure_count=1,
        created_row_count=4,
        active_structure_count=3,
        inactive_structure_count=1,
        active_distinct_aid_count=3,
        active_source_observation_count=4,
        inactive_distinct_aid_count=2,
        inactive_source_observation_count=2,
        represented_source_row_count=6,
        consolidated_duplicate_count=2,
        selected_reference_count=3,
        no_eligible_activity_count=1,
    )


def _render(monkeypatch, metadata):
    output = {
        "subheader": [],
        "markdown": [],
        "markdown_kwargs": [],
        "caption": [],
        "containers": [],
        "info": [],
        "warning": [],
        "write": [],
        "text": [],
        "calls": [],
    }

    class Gateway:
        def get_table_metadata(self, database_id, table_name):
            output["calls"].append((database_id, table_name))
            return metadata

    monkeypatch.setattr(main_page, "get_backend_gateway", lambda: Gateway())

    def markdown(value, **kwargs):
        output["markdown"].append(value)
        output["markdown_kwargs"].append(kwargs)

    def container(**kwargs):
        output["containers"].append(kwargs)
        return _Context()

    monkeypatch.setattr(main_page.st, "markdown", markdown)
    monkeypatch.setattr(main_page.st, "subheader", output["subheader"].append)
    monkeypatch.setattr(main_page.st, "caption", output["caption"].append)
    monkeypatch.setattr(main_page.st, "container", container)
    monkeypatch.setattr(main_page.st, "info", output["info"].append)
    monkeypatch.setattr(main_page.st, "warning", output["warning"].append)
    monkeypatch.setattr(main_page.st, "write", output["write"].append)
    monkeypatch.setattr(main_page.st, "text", output["text"].append)
    main_page.render_structure_consolidation_summary(
        "test_db",
        "main_structure_consolidated",
    )
    return output


def test_table_manager_summary_displays_complete_persisted_metadata(monkeypatch):
    output = _render(
        monkeypatch,
        TableMetadata(
            columns=("Reference_CID",),
            row_count=4,
            origin="structure_consolidation",
            source_table="main",
            structure_consolidation_summary=_summary(),
        ),
    )

    rendered = "\n".join(output["markdown"])
    assert output["subheader"] == [
        ":material/layers: Activity Labels Summary"
    ]
    assert output["calls"] == [
        ("test_db", "main_structure_consolidated")
    ]
    for text in (
        "Source",
        "Source rows",
        "10",
        "Usable rows",
        "8",
        "Rows without usable structure",
        "2",
        "Unique usable structures",
        "6",
        "Exclusions",
        "Label conflicts",
        "Non-binary outcomes",
        "Consolidated result",
        "Final structures",
        "Evidence by outcome",
        "Active",
        "Inactive",
        "Structures",
        "Distinct assays (AIDs)",
        "Source observations",
        "Source rows represented",
        "Additional observations consolidated",
        "Activity references",
        "References selected",
        "No exact activity reference",
    ):
        assert text in rendered
    assert output["caption"] == ["Derived from: main"]
    assert output["containers"] == [{"border": True}]
    assert output["markdown_kwargs"] == [
        {"unsafe_allow_html": True},
        {"unsafe_allow_html": True},
        {"unsafe_allow_html": True},
        {"unsafe_allow_html": True},
        {"unsafe_allow_html": True},
        {"unsafe_allow_html": True},
    ]
    assert "display: grid" in rendered
    assert "grid-template-columns" in rendered
    assert "var(--cv-muted-bg)" in rendered
    assert "\n- **" not in rendered
    assert "####" not in rendered
    html_calls = [
        (value, kwargs)
        for value, kwargs in zip(
            output["markdown"],
            output["markdown_kwargs"],
        )
        if "<div" in value
    ]
    assert len(html_calls) == 6
    assert all(
        kwargs == {"unsafe_allow_html": True}
        for _value, kwargs in html_calls
    )
    assert sum(
        value.count("background: var(--cv-muted-bg)")
        for value, _kwargs in html_calls
    ) == 17
    result_html = output["markdown"][2]
    outcome_evidence_html = output["markdown"][3]
    assert result_html.count("background: var(--cv-muted-bg)") == 3
    assert ">Active</div>" not in result_html
    assert ">Inactive</div>" not in result_html
    assert outcome_evidence_html.count(
        "background: var(--cv-muted-bg)"
    ) == 6
    assert ">Evidence by outcome</div>" in outcome_evidence_html
    assert ">Active</div>" in outcome_evidence_html
    assert ">Inactive</div>" in outcome_evidence_html
    assert outcome_evidence_html.count("Structures") == 2
    assert outcome_evidence_html.count("Distinct assays (AIDs)") == 2
    assert outcome_evidence_html.count("Source observations") == 2
    assert html_calls[-1][0] == '<div style="height: 0.4rem;"></div>'
    assert all(value == value.lstrip() for value, _kwargs in html_calls)
    assert all(
        "<div" not in value
        for value, kwargs in zip(
            output["markdown"],
            output["markdown_kwargs"],
        )
        if kwargs.get("unsafe_allow_html") is not True
    )
    assert output["write"] == []
    assert output["text"] == []
    assert output["info"] == []


def test_metric_tile_html_has_no_markdown_code_block_indentation():
    tile_html = main_page._structure_consolidation_metric_tile_html(
        "Source rows",
        10,
    )

    assert tile_html.startswith("<div")
    assert tile_html == tile_html.lstrip()


def test_table_manager_summary_shows_compact_message_for_ordinary_table(
    monkeypatch,
):
    output = _render(
        monkeypatch,
        TableMetadata(columns=("CID",), row_count=10),
    )

    assert output["subheader"] == [
        ":material/layers: Activity Labels Summary"
    ]
    assert output["markdown"] == []
    assert output["caption"] == [
        "No structure-consolidation summary is available for this table."
    ]
    assert output["containers"] == [{"border": True}]
    assert output["info"] == []
    assert "var(--cv-muted-bg)" not in "\n".join(output["markdown"])


def test_incomplete_legacy_summary_is_non_fatal(monkeypatch):
    output = _render(
        monkeypatch,
        TableMetadata(
            columns=("Reference_CID",),
            row_count=4,
            origin="structure_consolidation",
            source_table="main",
            structure_consolidation_summary=None,
        ),
    )

    assert output["subheader"] == [
        ":material/layers: Activity Labels Summary"
    ]
    assert output["markdown"] == []
    assert output["caption"] == ["Derived from: main"]
    assert output["containers"] == [{"border": True}]
    assert output["info"] == [
        "This structure-consolidated table has incomplete legacy "
        "summary metadata."
    ]


def test_summary_is_reloaded_from_gateway_without_transient_run_state(
    monkeypatch,
):
    metadata = TableMetadata(
        columns=("Reference_CID",),
        row_count=4,
        origin="structure_consolidation",
        source_table="main",
        structure_consolidation_summary=_summary(),
    )
    output = _render(monkeypatch, metadata)
    second = _render(monkeypatch, metadata)

    assert output["calls"] == second["calls"] == [
        ("test_db", "main_structure_consolidated")
    ]
    source = inspect.getsource(
        main_page.render_structure_consolidation_summary
    )
    assert "session_state" not in source
    assert "get_backend_gateway().get_table_metadata" in source
    assert "sqlite3" not in source


def _render_independent_scientific_cards(monkeypatch, state):
    output = {
        "containers": [],
        "subheader": [],
        "markdown": [],
        "caption": [],
    }

    def container(**kwargs):
        output["containers"].append(kwargs)
        return _Context()

    monkeypatch.setattr(main_page.st, "session_state", state)
    monkeypatch.setattr(main_page.st, "container", container)
    monkeypatch.setattr(main_page.st, "subheader", output["subheader"].append)
    monkeypatch.setattr(main_page.st, "markdown", output["markdown"].append)
    monkeypatch.setattr(main_page.st, "caption", output["caption"].append)

    main_page.render_structured_activity_card(_Context())
    main_page.render_activity_labels_summary_card(_Context())
    main_page.render_modelability_result_section(_Context())
    return output


def test_independent_scientific_cards_remain_visible_without_database(monkeypatch):
    output = _render_independent_scientific_cards(
        monkeypatch,
        {DATABASE_ID: "", CURRENT_TABLE: ""},
    )

    assert output["containers"] == [{"border": True}] * 3
    assert output["subheader"] == [
        ":material/science: Structured Quantitative Activity",
        ":material/layers: Activity Labels Summary",
        ":material/scatter_plot: Modelability Index Result",
    ]
    assert output["markdown"] == []
    assert len(output["caption"]) == 3
    assert all("Select or create a database" in text for text in output["caption"])


def test_independent_scientific_cards_show_empty_database_and_table_states(
    monkeypatch,
    tmp_path,
):
    database_dir = tmp_path / "SQL"
    database_dir.mkdir()
    with sqlite3.connect(database_dir / "empty.db"):
        pass
    monkeypatch.chdir(tmp_path)

    class Gateway:
        def get_table_metadata(self, database_id, table_name):
            assert (database_id, table_name) == ("empty", "main")
            return TableMetadata(columns=("CID",), row_count=1)

    monkeypatch.setattr(main_page, "get_backend_gateway", lambda: Gateway())
    output = _render_independent_scientific_cards(
        monkeypatch,
        {DATABASE_ID: "empty", CURRENT_TABLE: "main"},
    )

    assert output["containers"] == [{"border": True}] * 3
    assert output["subheader"] == [
        ":material/science: Structured Quantitative Activity",
        ":material/layers: Activity Labels Summary",
        ":material/scatter_plot: Modelability Index Result",
    ]
    assert output["markdown"] == []
    assert output["caption"] == [
        "No structured quantitative activity data is available for this database.",
        "No structure-consolidation summary is available for this table.",
        "No Modelability Index result is available for this table.",
    ]


def test_main_layout_separates_and_orders_scientific_sections():
    activity_source = inspect.getsource(
        main_page.render_structured_activity_section
    )
    manager_source = inspect.getsource(main_page.render_table_manager_card)
    summary_source = inspect.getsource(
        main_page.render_structure_consolidation_summary
    )
    modelability_source = inspect.getsource(
        main_page.render_modelability_result_card
    )
    app_source = (Path(__file__).resolve().parents[1] / "app.py").read_text(
        encoding="utf-8"
    )

    assert activity_source.index('_nested_card_heading_html("Filter")') < (
        activity_source.index('"Create filtered activity table"')
    )
    container_position = manager_source.index("with st.container(")
    maintenance_heading_position = manager_source.index(
        '_nested_card_heading_html("Database Maintenance")'
    )
    manage_position = manager_source.index(
        "render_table_manager_actions(database_id, profiles)"
    )
    maintenance_position = manager_source.index(
        "render_activity_enrichment_action(activity_conn)"
    )
    assert (
        container_position
        < maintenance_heading_position
        < manage_position
        < maintenance_position
    )
    assert "render_structured_activity_section(" not in manager_source
    assert "render_structure_consolidation_summary(" not in manager_source
    assert "render_modelability_result_card(" not in manager_source

    assert 'st.subheader(":material/table_view: Table Manager")' in manager_source
    assert (
        'st.subheader(":material/science: Structured Quantitative Activity")'
        in activity_source
    )
    assert 'st.subheader(":material/layers: Activity Labels Summary")' in summary_source
    assert (
        'st.subheader(":material/scatter_plot: Modelability Index Result")'
        in modelability_source
    )

    ordered_calls = (
        "render_database_card(container1)",
        "render_columns_card(container2)",
        "render_table_manager_card(container3)",
        "render_structured_activity_card(container4)",
        "render_activity_labels_summary_card(container5)",
        "render_modelability_result_section(container6)",
        "render_table_maintenance_card(container7)",
        "render_operation_history_card(container8)",
    )
    positions = [app_source.index(call) for call in ordered_calls]
    assert positions == sorted(positions)

    layout_source = inspect.getsource(main_page.create_main_layout)
    assert 'details[data-testid="stExpander"]' in layout_source
    assert "background-color: var(--cv-panel-bg);" in layout_source
    assert "border: 1px solid var(--cv-border-strong);" in layout_source
    compact_scientific_block = layout_source[
        layout_source.index("container3 =") : layout_source.index("container6 =")
    ]
    assert compact_scientific_block.count("<hr") == 3
    assert compact_scientific_block.count("margin: 12px 0;") == 3
    assert "margin: 32px 0 24px 0;" not in compact_scientific_block
