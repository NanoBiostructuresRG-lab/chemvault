# SPDX-License-Identifier: LGPL-3.0-or-later
import json
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from api import main as api_main
from application.job_contracts import (
    RecoveredJobContract,
    job_status_from_payload,
)
from application.database_use_cases import (
    DatabaseMetrics,
    DatabaseNotFoundError,
    InvalidColumnError,
    TableProvenance,
    TableNotFoundError,
)
from application.structure_consolidation import (
    StructureConsolidationSummary,
    StructureConsolidationTableResult,
)
from services.database import DatabaseState
from services.structure_consolidation import StructureConsolidationError


client = TestClient(api_main.app)


def _completed_harmonsmile_job():
    return {
        "job_id": "job-1",
        "job_type": "harmonsmile",
        "status": "completed",
        "database_id": "test_db",
        "stage": "completed",
        "progress": 1.0,
        "message": "done",
        "created_at": "2026-07-03T10:00:00+00:00",
        "updated_at": "2026-07-03T10:01:00+00:00",
        "started_at": "2026-07-03T10:00:00+00:00",
        "finished_at": "2026-07-03T10:01:00+00:00",
        "error": None,
        "result": {"merged_rows": 2},
        "cancellable": False,
    }


def _pending_harmonsmile_job():
    return {
        **_completed_harmonsmile_job(),
        "status": "pending",
        "stage": "queued",
        "progress": 0.0,
        "message": "HARMONSMILE job queued",
        "updated_at": "2026-07-03T10:00:00+00:00",
        "started_at": None,
        "finished_at": None,
        "result": None,
        "cancellable": True,
    }


def _structure_consolidation_result():
    return StructureConsolidationTableResult(
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
        represented_source_row_count=6,
        selected_reference_count=3,
        no_eligible_activity_count=1,
    )


def test_docs_endpoint_is_available():
    response = client.get("/docs", follow_redirects=False)

    assert response.status_code in {200, 307, 308}
    if response.is_redirect:
        assert response.headers["location"]


def test_openapi_schema_exposes_read_only_contract():
    response = client.get("/openapi.json")

    assert response.status_code == 200
    schema = response.json()
    assert schema["info"]["title"] == "ChemVault API"
    assert {
        "/health",
        "/databases/{database_id}/tables",
        "/databases/{database_id}/operations",
        "/databases/{database_id}/tables/{table_name}/metadata",
        "/databases/{database_id}/tables/{table_name}/metrics",
        "/databases/{database_id}/tables/{table_name}/preview",
        "/databases/{database_id}/tables/{table_name}/export",
        (
            "/databases/{database_id}/tables/{table_name}/"
            "structure-consolidation"
        ),
    }.issubset(schema["paths"])
    assert "/databases/{database_id}/jobs/harmonsmile" in schema["paths"]
    assert "/databases/{database_id}/jobs/{job_id}" in schema["paths"]
    assert (
        "/databases/{database_id}/scientific-runtime/activate"
        in schema["paths"]
    )


def test_harmonsmile_launch_endpoint_uses_application_runtime(monkeypatch):
    expected = job_status_from_payload(_pending_harmonsmile_job())
    calls = []
    monkeypatch.setattr(
        api_main,
        "create_scientific_job",
        lambda *args: calls.append(args) or expected,
    )
    background_calls = []
    monkeypatch.setattr(
        api_main,
        "start_scientific_background_job",
        lambda *args, **kwargs: background_calls.append((args, kwargs)),
    )

    response = client.post(
        "/databases/test_db/jobs/harmonsmile",
        json={"table_name": "main", "cid_column": "CID"},
    )

    assert response.status_code == 201
    assert response.json()["job_id"] == "job-1"
    assert response.json()["status"] == "pending"
    assert response.json()["result"] is None
    assert calls == [
        (
            "test_db",
            api_main.JobType.HARMONSMILE,
            {"table_name": "main", "cid_column": "CID"},
        )
    ]
    assert background_calls == [
        (
            (
                "test_db",
                api_main.JobType.HARMONSMILE,
                "job-1",
            ),
            {"name": "chemvault-harmonsmile"},
        )
    ]


def test_active_harmonsmile_endpoint_uses_application_runtime(monkeypatch):
    expected = job_status_from_payload(_pending_harmonsmile_job())
    calls = []
    monkeypatch.setattr(
        api_main,
        "find_active_scientific_job",
        lambda *args: calls.append(args) or expected,
    )

    response = client.get(
        "/databases/test_db/jobs/harmonsmile/active",
        params={"table_name": "main"},
    )

    assert response.status_code == 200
    assert response.json()["job_id"] == "job-1"
    assert calls == [("test_db", api_main.JobType.HARMONSMILE, "main")]


def test_job_status_endpoint_uses_application_runtime(monkeypatch):
    expected = _completed_harmonsmile_job()
    calls = []
    monkeypatch.setattr(
        api_main,
        "get_scientific_job_status",
        lambda *args: calls.append(args) or expected,
    )

    response = client.get("/databases/test_db/jobs/job-1")

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert calls == [("test_db", "job-1")]


@pytest.mark.parametrize(
    ("status", "error"),
    [
        ("running", None),
        ("completed", None),
        ("failed", "HARMONSMILE unavailable"),
    ],
)
def test_job_status_endpoint_reflects_persisted_lifecycle(
    monkeypatch, status, error
):
    payload = {
        **_completed_harmonsmile_job(),
        "status": status,
        "error": error,
    }
    monkeypatch.setattr(
        api_main,
        "get_scientific_job_status",
        lambda *_args: payload,
    )

    response = client.get("/databases/test_db/jobs/job-1")

    assert response.status_code == 200
    assert response.json()["status"] == status
    assert response.json()["error"] == error


def test_health_endpoint():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_api_startup_does_not_activate_or_enumerate_databases(monkeypatch):
    calls = []
    monkeypatch.setattr(
        api_main,
        "activate_scientific_runtime",
        lambda database_id: calls.append(database_id),
    )

    with TestClient(api_main.app) as startup_client:
        assert startup_client.get("/health").status_code == 200

    assert calls == []


def test_database_activation_returns_recovered_job_snapshots(monkeypatch):
    recovered_job = RecoveredJobContract(
        job=job_status_from_payload(_pending_harmonsmile_job()),
        table_name="archived_table",
    )
    calls = []
    monkeypatch.setattr(
        api_main,
        "activate_scientific_runtime",
        lambda database_id: calls.append(database_id) or (recovered_job,),
    )

    response = client.post(
        "/databases/test_db/scientific-runtime/activate"
    )

    assert response.status_code == 200
    assert response.json()["database_id"] == "test_db"
    assert response.json()["recovered_jobs"][0]["job_id"] == "job-1"
    assert response.json()["recovered_jobs"][0]["table_name"] == (
        "archived_table"
    )
    assert response.json()["recovered_jobs"][0]["status"] == "pending"
    assert calls == ["test_db"]


def test_database_tables_endpoint_uses_application_layer(monkeypatch):
    calls = []
    monkeypatch.setattr(
        api_main,
        "list_database_tables",
        lambda database_id: calls.append(database_id) or ["main", "curated"],
    )

    response = client.get("/databases/test_db/tables")

    assert response.status_code == 200
    assert response.json() == {
        "database_id": "test_db",
        "tables": ["main", "curated"],
    }
    assert calls == ["test_db"]


def test_database_tables_endpoint_returns_404_for_missing_database(monkeypatch):
    error = DatabaseNotFoundError("Database 'missing' was not found.")
    monkeypatch.setattr(
        api_main,
        "list_database_tables",
        lambda *args: (_ for _ in ()).throw(error),
    )

    response = client.get("/databases/missing/tables")

    assert response.status_code == 404
    assert response.json() == {"detail": "Database 'missing' was not found."}


def test_database_operations_endpoint_uses_application_layer(monkeypatch):
    operations = (
        {
            "operation_type": "table_created",
            "target_table": "curated",
            "source_table": "main",
            "source_columns": '["CID"]',
            "created_at": "2026-07-03T12:00:00+00:00",
            "status": "success",
            "details": None,
        },
    )
    calls = []
    monkeypatch.setattr(
        api_main,
        "get_operation_history",
        lambda database_id: calls.append(database_id) or operations,
    )

    response = client.get("/databases/test_db/operations")

    assert response.status_code == 200
    assert response.json() == {
        "database_id": "test_db",
        "operations": [operations[0]],
    }
    assert calls == ["test_db"]


def test_database_operations_endpoint_returns_404_for_missing_database(monkeypatch):
    error = DatabaseNotFoundError("Database 'missing' was not found.")
    monkeypatch.setattr(
        api_main,
        "get_operation_history",
        lambda *args: (_ for _ in ()).throw(error),
    )

    response = client.get("/databases/missing/operations")

    assert response.status_code == 404
    assert response.json() == {"detail": "Database 'missing' was not found."}


def test_structure_consolidation_endpoint_returns_complete_result(monkeypatch):
    expected = _structure_consolidation_result()
    calls = []
    monkeypatch.setattr(
        api_main,
        "consolidate_structure_table",
        lambda *args: calls.append(args) or expected,
    )

    response = client.post(
        "/databases/test_db/tables/main/structure-consolidation"
    )

    assert response.status_code == 201
    assert response.json() == expected.__dict__
    assert calls == [("test_db", "main")]


@pytest.mark.parametrize(
    ("error", "status_code"),
    [
        (DatabaseNotFoundError("Database was not found."), 404),
        (TableNotFoundError("Table was not found."), 404),
        (
            StructureConsolidationError("Missing HARMONSMILE columns."),
            422,
        ),
    ],
)
def test_structure_consolidation_endpoint_maps_application_errors(
    monkeypatch,
    error,
    status_code,
):
    monkeypatch.setattr(
        api_main,
        "consolidate_structure_table",
        lambda *_args: (_ for _ in ()).throw(error),
    )

    response = client.post(
        "/databases/test_db/tables/main/structure-consolidation"
    )

    assert response.status_code == status_code
    assert response.json() == {"detail": str(error)}


def test_table_metrics_endpoint_uses_application_layer(monkeypatch):
    calls = []
    monkeypatch.setattr(
        api_main,
        "get_table_metrics",
        lambda *args: calls.append(args) or DatabaseMetrics(3, 2),
    )

    response = client.get(
        "/databases/test_db/tables/main/metrics",
        params={"group_column": "category"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "database_id": "test_db",
        "table": "main",
        "row_count": 3,
        "group_count": 2,
    }
    assert calls == [("test_db", "main", "category")]


def test_table_metrics_rejects_unknown_group_column(monkeypatch):
    error = InvalidColumnError("Unknown column: missing")
    monkeypatch.setattr(
        api_main,
        "get_table_metrics",
        lambda *args: (_ for _ in ()).throw(error),
    )

    response = client.get(
        "/databases/test_db/tables/main/metrics",
        params={"group_column": "missing"},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Unknown column: missing"}


def test_table_metadata_endpoint_uses_application_layer(monkeypatch):
    state = DatabaseState(
        database_id="test_db",
        current_table="main",
        headers=("CID", "SMILES"),
    )
    calls = []
    monkeypatch.setattr(api_main, "get_table_state", lambda *args: state)
    monkeypatch.setattr(
        api_main,
        "get_table_provenance",
        lambda *args: TableProvenance(),
    )
    monkeypatch.setattr(
        api_main,
        "get_table_metrics",
        lambda *args: calls.append(args) or DatabaseMetrics(100, 0),
    )
    monkeypatch.setattr(
        api_main,
        "get_table_schema",
        lambda *args: calls.append(args) or (
            {
                "cid": 0,
                "name": "CID",
                "data_type": "TEXT",
                "not_null": False,
                "default_value": None,
                "primary_key": False,
            },
        ),
    )

    response = client.get("/databases/test_db/tables/main/metadata")

    assert response.status_code == 200
    assert response.json() == {
        "database_id": "test_db",
        "table": "main",
        "columns": ["CID", "SMILES"],
        "row_count": 100,
        "preview_limit": 10,
        "read_only": True,
        "origin": None,
        "source_table": None,
        "structure_consolidation_summary": None,
        "schema": [
            {
                "cid": 0,
                "name": "CID",
                "data_type": "TEXT",
                "not_null": False,
                "default_value": None,
                "primary_key": False,
            }
        ],
    }
    assert calls == [
        ("test_db", "main", ""),
        ("test_db", "main"),
    ]


def test_table_metadata_endpoint_returns_persisted_consolidation_summary(
    monkeypatch,
):
    state = DatabaseState(
        database_id="test_db",
        current_table="main_structure_consolidated",
        headers=("Reference_CID",),
    )
    summary = StructureConsolidationSummary(
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
    notes = json.dumps(
        {
            "source_rows": 10,
            "usable_source_rows": 8,
            "unusable_rows": 2,
            "unique_harmonized_structures": 6,
            "conflicting_structures": 1,
            "non_binary_structures": 1,
            "created_rows": 4,
            "active_structures": 3,
            "inactive_structures": 1,
            "active_distinct_aids": 3,
            "active_source_observations": 4,
            "inactive_distinct_aids": 2,
            "inactive_source_observations": 2,
            "represented_source_row_count": 6,
            "consolidated_duplicates": 2,
            "selected_reference_count": 3,
            "no_eligible_activity_count": 1,
        }
    )
    monkeypatch.setattr(api_main, "get_table_state", lambda *args: state)
    monkeypatch.setattr(
        api_main,
        "get_table_metrics",
        lambda *args: DatabaseMetrics(4, 0),
    )
    monkeypatch.setattr(api_main, "get_table_schema", lambda *args: ())
    monkeypatch.setattr(
        api_main,
        "get_table_provenance",
        lambda *args: TableProvenance(
            origin="structure_consolidation",
            source_table="main",
            notes=notes,
        ),
    )

    response = client.get(
        "/databases/test_db/tables/main_structure_consolidated/metadata"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["origin"] == "structure_consolidation"
    assert payload["source_table"] == "main"
    assert payload["structure_consolidation_summary"] == summary.__dict__


@pytest.mark.parametrize(
    "error",
    [
        DatabaseNotFoundError("Database 'missing' was not found."),
        TableNotFoundError("Table 'missing' was not found."),
    ],
)
def test_table_metadata_endpoint_returns_404_when_missing(monkeypatch, error):
    monkeypatch.setattr(
        api_main,
        "get_table_state",
        lambda *args: (_ for _ in ()).throw(error),
    )

    response = client.get("/databases/missing/tables/missing/metadata")

    assert response.status_code == 404
    assert response.json() == {"detail": str(error)}


def test_table_preview_endpoint_uses_selected_columns(monkeypatch):
    state = DatabaseState(
        database_id="test_db",
        current_table="main",
        headers=("CID", "SMILES"),
    )
    calls = []
    monkeypatch.setattr(api_main, "get_table_state", lambda *args: state)
    monkeypatch.setattr(
        api_main,
        "preview_selected_columns",
        lambda *args: calls.append(args) or pd.DataFrame([{"CID": "1"}]),
    )

    response = client.get(
        "/databases/test_db/tables/main/preview",
        params={"columns": "CID"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "database_id": "test_db",
        "table": "main",
        "columns": ["CID"],
        "rows": [{"CID": "1"}],
        "limit": 10,
    }
    assert calls == [
        ("test_db", "main", ("CID", "SMILES"), ["CID"])
    ]


def test_read_endpoints_return_404_for_missing_database(monkeypatch):
    error = DatabaseNotFoundError("Database 'missing' was not found.")
    monkeypatch.setattr(
        api_main,
        "get_table_metrics",
        lambda *args: (_ for _ in ()).throw(error),
    )
    monkeypatch.setattr(
        api_main,
        "get_table_state",
        lambda *args: (_ for _ in ()).throw(error),
    )

    metrics_response = client.get(
        "/databases/missing/tables/main/metrics"
    )
    preview_response = client.get(
        "/databases/missing/tables/main/preview"
    )

    assert metrics_response.status_code == 404
    assert preview_response.status_code == 404


def test_table_preview_rejects_unknown_columns(monkeypatch):
    state = DatabaseState(
        database_id="test_db",
        current_table="main",
        headers=("CID",),
    )
    monkeypatch.setattr(api_main, "get_table_state", lambda *args: state)
    monkeypatch.setattr(
        api_main,
        "preview_selected_columns",
        lambda *args: pytest.fail("invalid columns must not be queried"),
    )

    response = client.get(
        "/databases/test_db/tables/main/preview",
        params={"columns": "missing"},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Unknown columns: missing"}


def test_table_export_returns_selected_columns_as_csv(monkeypatch):
    calls = []
    monkeypatch.setattr(
        api_main,
        "export_table_csv",
        lambda *args: calls.append(args) or b"CID\r\n1\r\n",
    )

    response = client.get(
        "/databases/test_db/tables/main/export",
        params=[("columns", "CID")],
    )

    assert response.status_code == 200
    assert response.content == b"CID\r\n1\r\n"
    assert response.headers["content-type"].startswith("text/csv")
    assert response.headers["content-disposition"] == (
        'attachment; filename="chemvault_table_export.csv"'
    )
    assert calls == [("test_db", "main", ["CID"])]


@pytest.mark.parametrize(
    ("error", "status_code"),
    [
        (DatabaseNotFoundError("Database was not found."), 404),
        (TableNotFoundError("Table was not found."), 404),
        (InvalidColumnError("Unknown columns: missing"), 422),
    ],
)
def test_table_export_reports_validation_errors(monkeypatch, error, status_code):
    monkeypatch.setattr(
        api_main,
        "export_table_csv",
        lambda *args: (_ for _ in ()).throw(error),
    )

    response = client.get("/databases/test_db/tables/main/export")

    assert response.status_code == status_code
    assert response.json() == {"detail": str(error)}
