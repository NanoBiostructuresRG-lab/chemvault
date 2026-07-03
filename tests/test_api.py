# SPDX-License-Identifier: LGPL-3.0-or-later
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from api import main as api_main
from application.database_use_cases import (
    DatabaseMetrics,
    DatabaseNotFoundError,
    InvalidColumnError,
    TableNotFoundError,
)
from services.database import DatabaseState


client = TestClient(api_main.app)


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
        "/databases/{database_id}/tables/{table_name}/metadata",
        "/databases/{database_id}/tables/{table_name}/metrics",
        "/databases/{database_id}/tables/{table_name}/preview",
    }.issubset(schema["paths"])


def test_health_endpoint():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


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
        "get_table_metrics",
        lambda *args: calls.append(args) or DatabaseMetrics(100, 0),
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
    }
    assert calls == [("test_db", "main", "")]


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
