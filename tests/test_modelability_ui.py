# SPDX-License-Identifier: LGPL-3.0-or-later

import inspect
from types import SimpleNamespace

import pytest

from application.job_contracts import JobStatusContract
from services.job_models import JobStatus
from ui import main_page, modelability_card, modelability_result
from ui.modelability_state import (
    diagnostics_csv,
    launch_modelability_job,
    poll_modelability_job,
)


DATABASE_ID = "test_db"
SOURCE_TABLE = "activity_subset_IC50"
TABLE_NAME = f"{SOURCE_TABLE}_structure_consolidated"


def _status(status, *, result=None, error=None, progress=0.0):
    return JobStatusContract(
        job_id="job-1",
        job_type="modelability_index",
        status=status,
        database_id=DATABASE_ID,
        stage=status.value,
        progress=progress,
        message=None,
        created_at="2026-07-17T10:00:00+00:00",
        started_at=None,
        finished_at=None,
        error=error,
        cancellable=False,
        result=result,
    )


def _result():
    return {
        "structure_count": 3,
        "active_count": 2,
        "inactive_count": 1,
        "active_concordance": 0.5,
        "inactive_concordance": 1.0,
        "modelability_index": 0.75,
        "diagnostics": [
            {
                "smiles": "CCO",
                "outcome": "Active",
                "nearest_neighbor_smiles": "CCC",
                "nearest_neighbor_outcome": "Inactive",
                "tanimoto_similarity": 0.5,
                "concordant": False,
            }
        ],
        "provenance": {
            "source_table": TABLE_NAME,
            "fingerprint_profile": {
                "algorithm": "morgan",
                "output_type": "binary-bit-vector",
                "radius": 2,
                "fp_size": 2048,
                "include_chirality": False,
                "include_ring_membership": True,
                "use_bond_types": True,
                "include_redundant_environments": False,
                "invariant_policy": "rdkit-default",
                "profile_schema_version": "1.0",
            },
            "molraptor_profile_hash": "profile-hash",
            "molraptor_ordered_input_hash": "input-hash",
            "chemvault_analysis_hash": "analysis-hash",
            "molraptor_version": "0.2.0",
            "rdkit_version": "2025.03.1",
            "similarity_metric": "tanimoto",
            "neighbor_rule": "single_nearest_neighbor",
            "tie_policy": "lowest_ordered_index",
            "aggregation": "macro_average",
        },
    }


def _metadata(origin, source_table):
    return SimpleNamespace(origin=origin, source_table=source_table)


def test_activity_labels_consolidated_source_is_eligible():
    calls = []

    class Gateway:
        def get_table_metadata(self, database_id, table_name):
            calls.append((database_id, table_name))
            if table_name == TABLE_NAME:
                return _metadata("structure_consolidation", SOURCE_TABLE)
            return _metadata(
                "structured_activity_filtered_subset",
                "compound_activities",
            )

    eligible, error = modelability_card.check_eligibility(
        Gateway(),
        DATABASE_ID,
        TABLE_NAME,
    )

    assert eligible is True
    assert error is None
    assert calls == [(DATABASE_ID, TABLE_NAME), (DATABASE_ID, SOURCE_TABLE)]


@pytest.mark.parametrize(
    ("table_name", "metadata", "source_metadata"),
    [
        (
            "arbitrary",
            _metadata(None, None),
            None,
        ),
        (
            "harmonsmile",
            _metadata("harmonsmile", "main"),
            None,
        ),
        (
            "other_structure_consolidated",
            _metadata("structure_consolidation", "other"),
            _metadata("refine", "main"),
        ),
        (
            TABLE_NAME,
            _metadata("structure_consolidation", SOURCE_TABLE),
            _metadata("refine", "compound_activities"),
        ),
        (
            "2",
            _metadata("structure_consolidation", SOURCE_TABLE),
            _metadata(
                "structured_activity_filtered_subset",
                "compound_activities",
            ),
        ),
    ],
)
def test_unrelated_sources_are_not_eligible(
    table_name,
    metadata,
    source_metadata,
):
    assert modelability_card.source_is_eligible(
        table_name,
        metadata,
        source_metadata,
    ) is False


def test_async_job_state_is_scoped_to_database_and_table():
    state = {}
    calls = []

    class Gateway:
        def launch_scientific_job(self, *args):
            calls.append(("launch", args))
            return _status(JobStatus.PENDING)

        def get_job_status(self, *args):
            calls.append(("status", args))
            return _status(JobStatus.RUNNING, progress=0.4)

    gateway = Gateway()
    launch_modelability_job(state, gateway, DATABASE_ID, TABLE_NAME)

    assert state["modelability_job_id"] == "job-1"
    assert state["modelability_job_database_id"] == DATABASE_ID
    assert state["modelability_job_table_name"] == TABLE_NAME
    assert state["modelability_running"] is True
    assert poll_modelability_job(
        state,
        gateway,
        DATABASE_ID,
        "different_table",
    ) is None
    assert [call[0] for call in calls] == ["launch"]

    status = poll_modelability_job(state, gateway, DATABASE_ID, TABLE_NAME)
    assert status.status == JobStatus.RUNNING
    assert calls[-1] == ("status", (DATABASE_ID, "job-1"))


def test_immediate_completed_job_restores_persisted_result():
    state = {}

    class Gateway:
        def launch_scientific_job(self, *_args):
            return _status(JobStatus.COMPLETED, result=_result(), progress=1.0)

    status = launch_modelability_job(
        state,
        Gateway(),
        DATABASE_ID,
        TABLE_NAME,
    )

    assert status.status == JobStatus.COMPLETED
    assert state["modelability_running"] is False
    assert state["modelability_result"] == _result()
    assert state["modelability_feedback_kind"] == "success"
    assert state["modelability_feedback_message"] == (
        "Result restored from persisted analysis."
    )


def test_completed_and_failed_jobs_update_scoped_result_state():
    completed_state = {
        "modelability_job_id": "job-1",
        "modelability_job_database_id": DATABASE_ID,
        "modelability_job_table_name": TABLE_NAME,
        "modelability_running": True,
    }

    class CompletedGateway:
        def get_job_status(self, *_args):
            return _status(JobStatus.COMPLETED, result=_result(), progress=1.0)

    poll_modelability_job(
        completed_state,
        CompletedGateway(),
        DATABASE_ID,
        TABLE_NAME,
    )
    assert completed_state["modelability_running"] is False
    assert completed_state["modelability_result"] == _result()
    assert completed_state["modelability_feedback_kind"] == "success"
    assert completed_state["modelability_feedback_message"] == (
        "Modelability Index calculation completed."
    )

    failed_state = {
        "modelability_job_id": "job-2",
        "modelability_job_database_id": DATABASE_ID,
        "modelability_job_table_name": TABLE_NAME,
        "modelability_running": True,
    }

    class FailedGateway:
        def get_job_status(self, *_args):
            return _status(JobStatus.FAILED, error="invalid population")

    poll_modelability_job(
        failed_state,
        FailedGateway(),
        DATABASE_ID,
        TABLE_NAME,
    )
    assert failed_state["modelability_running"] is False
    assert failed_state["modelability_result"] is None
    assert failed_state["modelability_feedback_kind"] == "error"
    assert failed_state["modelability_feedback_message"] == "invalid population"


def test_diagnostics_csv_is_generated_in_memory():
    csv_text = diagnostics_csv(_result())

    assert csv_text.splitlines() == [
        "smiles,outcome,nearest_neighbor_smiles,nearest_neighbor_outcome,"
        "tanimoto_similarity,concordant",
        "CCO,Active,CCC,Inactive,0.5,False",
    ]


def test_sidebar_execution_card_does_not_render_scientific_result():
    source = inspect.getsource(modelability_card.render_modelability_card)

    assert 'st.subheader("MODELABILITY INDEX")' in source
    assert "st.caption(message)" in source
    assert "st.success(message)" not in source
    assert "MODELABILITY_RESULT" not in source
    assert "render_result" not in source
    assert "st.metric" not in source
    assert "st.dataframe" not in source
    assert "st.download_button" not in source
    assert "st.json" not in source


def test_completed_result_renders_summary_diagnostics_and_analysis_details(
    monkeypatch,
):
    active_columns = []

    class Context:
        def __init__(self, column=None):
            self.column = column

        def __enter__(self):
            if self.column is not None:
                active_columns.append(self.column)
            return self

        def __exit__(self, *_args):
            if self.column is not None:
                active_columns.pop()
            return False

    rendered = {
        "markdown": [],
        "markdown_kwargs": [],
        "captions": [],
        "frames": [],
        "downloads": [],
        "download_columns": [],
        "column_calls": [],
        "expanders": [],
    }
    monkeypatch.setattr(
        modelability_result.st,
        "container",
        lambda **_kwargs: Context(),
    )
    monkeypatch.setattr(
        modelability_result.st,
        "columns",
        lambda spec: (
            rendered["column_calls"].append(spec)
            or (Context(0), Context(1))
        ),
    )

    def markdown(value, **kwargs):
        rendered["markdown"].append(value)
        rendered["markdown_kwargs"].append(kwargs)

    monkeypatch.setattr(modelability_result.st, "markdown", markdown)
    monkeypatch.setattr(
        modelability_result.st,
        "caption",
        rendered["captions"].append,
    )
    monkeypatch.setattr(
        modelability_result.st,
        "dataframe",
        lambda data, **_kwargs: rendered["frames"].append(data),
    )
    monkeypatch.setattr(
        modelability_result.st,
        "download_button",
        lambda *args, **kwargs: (
            rendered["download_columns"].append(active_columns[-1])
            or rendered["downloads"].append((args, kwargs))
        ),
    )
    monkeypatch.setattr(
        modelability_result.st,
        "expander",
        lambda label, **kwargs: (
            rendered["expanders"].append((label, kwargs)) or Context()
        ),
    )
    gateway_calls = []

    class Gateway:
        def export_modelability_fingerprints(
            self,
            database_id,
            table_name,
            analysis_identity,
        ):
            gateway_calls.append(
                (database_id, table_name, analysis_identity)
            )
            return (
                b"npz-bytes",
                "test_db_IC50_fingerprints_analysis.npz",
            )

    monkeypatch.setattr(
        modelability_result,
        "get_backend_gateway",
        lambda: Gateway(),
    )

    result = _result()
    result["provenance"]["fingerprint_source"] = "restored"
    result["diagnostics"] = [
        {**result["diagnostics"][0], "smiles": f"structure-{index}"}
        for index in range(12)
    ]
    state = {
        "modelability_job_database_id": DATABASE_ID,
        "modelability_job_table_name": TABLE_NAME,
        "modelability_result": result,
    }
    rendered_result = modelability_result.render_modelability_result_card(
        state,
        DATABASE_ID,
        TABLE_NAME,
    )

    assert rendered_result is True
    rendered_html = "\n".join(rendered["markdown"])
    for text in (
        "**Modelability Index result**",
        "Modelability",
        "Modelability Index",
        "0.750",
        "Active Concordance",
        "0.500",
        "Inactive Concordance",
        "1.000",
        "<strong>Nearest-neighbor diagnostics</strong>",
    ):
        assert text in rendered_html
    for removed_text in (
        "Structures",
        "Total structures",
        "Active structures",
        "Inactive structures",
    ):
        assert removed_text not in rendered_html
    assert rendered_html.count("background: var(--cv-muted-bg)") == 3
    assert "display: grid" in rendered_html
    assert rendered_html.count(
        "data-cv-modelability-diagnostics-heading"
    ) == 1
    assert 'style="margin-top: 1.5rem;"' in rendered_html
    assert "st.metric" not in inspect.getsource(
        modelability_result._render_metrics
    )
    assert rendered["captions"] == [
        f"Calculated from: {TABLE_NAME}",
        "Preview of nearest-neighbor comparisons used in the "
        "Modelability Index calculation.",
    ]
    assert len(rendered["frames"][0]) == 10
    assert rendered["frames"][0] == result["diagnostics"][:10]

    analysis_frame = rendered["frames"][1]
    assert {row["Field"] for row in analysis_frame} == {
        "Algorithm",
        "Output type",
        "Fingerprint size",
        "Radius",
        "Chirality",
        "Ring membership",
        "Bond types",
        "Similarity metric",
        "Neighbor rule",
        "Tie policy",
        "Aggregation method",
        "MOLRAPTOR version",
        "RDKit version",
    }
    assert next(
        row["Value"]
        for row in analysis_frame
        if row["Field"] == "Algorithm"
    ) == "Morgan"
    assert next(
        row["Value"]
        for row in analysis_frame
        if row["Field"] == "Output type"
    ) == "Binary bit vector"
    assert next(
        row["Value"]
        for row in analysis_frame
        if row["Field"] == "Fingerprint size"
    ) == "2048 bits"
    assert {
        row["Field"]: row["Value"]
        for row in analysis_frame
        if row["Group"] == "Fingerprint"
    } == {
        "Algorithm": "Morgan",
        "Output type": "Binary bit vector",
        "Fingerprint size": "2048 bits",
        "Radius": 2,
        "Chirality": "Not included",
        "Ring membership": "Included",
        "Bond types": "Used",
    }
    visible_details = str(analysis_frame)
    for hidden_value in (
        "Fingerprint profile (JSON)",
        "include_redundant_environments",
        "invariant_policy",
        "profile_schema_version",
        "profile-hash",
        "input-hash",
        "analysis-hash",
    ):
        assert hidden_value not in visible_details
    assert rendered["downloads"][0][0] == (
        "Download nearest-neighbor report",
    )
    assert rendered["downloads"][0][1]["data"] == diagnostics_csv(result)
    assert rendered["downloads"][1] == (
        ("Download fingerprints (.npz)",),
        {
            "data": b"npz-bytes",
            "file_name": "test_db_IC50_fingerprints_analysis.npz",
            "mime": "application/octet-stream",
            "key": f"download_modelability_fingerprints_{TABLE_NAME}",
        },
    )
    assert rendered["column_calls"] == [2]
    assert rendered["download_columns"] == [0, 1]
    assert gateway_calls == [
        (DATABASE_ID, TABLE_NAME, "analysis-hash")
    ]
    assert len(diagnostics_csv(result).splitlines()) == 13
    assert rendered["expanders"] == [
        ("Analysis details", {"expanded": False}),
    ]
    assert result["provenance"]["fingerprint_profile"][
        "include_redundant_environments"
    ] is False
    assert result["provenance"]["fingerprint_profile"][
        "invariant_policy"
    ] == "rdkit-default"
    assert result["provenance"]["fingerprint_profile"][
        "profile_schema_version"
    ] == "1.0"
    assert result["provenance"]["molraptor_profile_hash"] == "profile-hash"
    assert result["provenance"]["molraptor_ordered_input_hash"] == "input-hash"
    assert result["provenance"]["chemvault_analysis_hash"] == "analysis-hash"


def test_modelability_npz_export_failure_is_visible(monkeypatch):
    class Context:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    class FailingGateway:
        def export_modelability_fingerprints(self, *_args):
            raise modelability_result.BackendGatewayError(
                "persisted fingerprint artifact is unavailable"
            )

    errors = []
    monkeypatch.setattr(
        modelability_result,
        "get_backend_gateway",
        lambda: FailingGateway(),
    )
    monkeypatch.setattr(
        modelability_result.st,
        "container",
        lambda **_kwargs: Context(),
    )
    monkeypatch.setattr(
        modelability_result.st,
        "columns",
        lambda _spec: (Context(), Context()),
    )
    monkeypatch.setattr(
        modelability_result.st,
        "expander",
        lambda *_args, **_kwargs: Context(),
    )
    monkeypatch.setattr(modelability_result.st, "markdown", lambda *_a, **_k: None)
    monkeypatch.setattr(modelability_result.st, "caption", lambda *_a, **_k: None)
    monkeypatch.setattr(modelability_result.st, "dataframe", lambda *_a, **_k: None)
    monkeypatch.setattr(
        modelability_result.st,
        "download_button",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(modelability_result.st, "error", errors.append)
    state = {
        "modelability_job_database_id": DATABASE_ID,
        "modelability_job_table_name": TABLE_NAME,
        "modelability_result": _result(),
    }

    assert modelability_result.render_modelability_result_card(
        state,
        DATABASE_ID,
        TABLE_NAME,
    ) is True
    assert errors == [
        "Modelability fingerprint download could not be prepared: "
        "persisted fingerprint artifact is unavailable"
    ]


def test_scope_mismatch_does_not_render_stale_result(monkeypatch):
    monkeypatch.setattr(
        modelability_result.st,
        "container",
        lambda **_kwargs: pytest.fail("stale result must not render"),
    )
    state = {
        "modelability_job_database_id": DATABASE_ID,
        "modelability_job_table_name": TABLE_NAME,
        "modelability_result": _result(),
    }

    assert modelability_result.render_modelability_result_card(
        state,
        DATABASE_ID,
        "different_table",
    ) is False


def test_table_manager_places_modelability_after_advanced_maintenance():
    source = inspect.getsource(main_page.render_table_manager_card)

    maintenance = source.index("render_activity_enrichment_action(activity_conn)")
    result = source.index("render_modelability_result_card(")
    assert maintenance < result
