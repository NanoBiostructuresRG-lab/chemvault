# SPDX-License-Identifier: LGPL-3.0-or-later
from pathlib import Path

import pandas as pd
import pytest

from application.database_use_cases import DatabaseMetrics
from clients import backend_gateway
from clients.api_client import ChemVaultApiError
from application.job_contracts import JobStatusContract
from services.job_models import JobStatus
from services.database import DatabaseState


def test_gateway_selects_local_backend_without_api_url(monkeypatch):
    monkeypatch.delenv("CHEMVAULT_API_URL", raising=False)
    monkeypatch.setattr(
        backend_gateway,
        "refresh_database",
        lambda database_id: DatabaseState(
            database_id=database_id,
            all_tables=("main", "curated"),
        ),
    )

    gateway = backend_gateway.get_backend_gateway()

    assert gateway.mode == "local"
    assert gateway.list_tables("test_db") == ("main", "curated")


def test_gateway_selects_http_backend_with_api_url(monkeypatch):
    monkeypatch.setenv("CHEMVAULT_API_URL", " http://api.example/ ")
    calls = []

    class FakeClient:
        def __init__(self, base_url):
            calls.append(("init", base_url))

        def list_tables(self, database_id):
            calls.append(("tables", database_id))
            return {"tables": ["main"]}

    monkeypatch.setattr(backend_gateway, "ChemVaultApiClient", FakeClient)

    gateway = backend_gateway.get_backend_gateway()

    assert gateway.mode == "http"
    assert gateway.list_tables("test_db") == ("main",)
    assert calls == [
        ("init", "http://api.example/"),
        ("tables", "test_db"),
    ]


def test_http_error_does_not_fall_back_to_local_backend(monkeypatch):
    monkeypatch.setenv("CHEMVAULT_API_URL", "http://api.example")
    local_calls = []
    monkeypatch.setattr(
        backend_gateway,
        "refresh_database",
        lambda database_id: local_calls.append(database_id),
    )

    class FailingClient:
        def __init__(self, base_url):
            pass

        def list_tables(self, database_id):
            raise ChemVaultApiError("request timed out")

    monkeypatch.setattr(backend_gateway, "ChemVaultApiClient", FailingClient)

    with pytest.raises(
        backend_gateway.BackendGatewayError,
        match="request timed out",
    ):
        backend_gateway.get_backend_gateway().list_tables("test_db")

    assert local_calls == []


def test_table_schema_uses_local_application_backend(monkeypatch):
    monkeypatch.delenv("CHEMVAULT_API_URL", raising=False)
    expected = ({"name": "CID", "data_type": "TEXT"},)
    calls = []
    monkeypatch.setattr(
        backend_gateway,
        "get_local_table_schema",
        lambda *args: calls.append(args) or expected,
    )

    result = backend_gateway.get_backend_gateway().get_table_schema(
        "test_db",
        "main",
    )

    assert result is expected
    assert calls == [("test_db", "main")]


def test_operation_history_uses_local_application_backend(monkeypatch):
    monkeypatch.delenv("CHEMVAULT_API_URL", raising=False)
    expected = ({"operation_id": 1, "operation_type": "database_created"},)
    calls = []
    monkeypatch.setattr(
        backend_gateway,
        "get_local_operation_history",
        lambda database_id: calls.append(database_id) or expected,
    )

    result = backend_gateway.get_backend_gateway().get_operation_history(
        "test_db"
    )

    assert result is expected
    assert calls == ["test_db"]


def test_operation_history_uses_http_backend(monkeypatch):
    monkeypatch.setenv("CHEMVAULT_API_URL", "http://api.example")
    calls = []

    class FakeClient:
        def __init__(self, base_url):
            calls.append(("init", base_url))

        def get_operation_history(self, database_id):
            calls.append(("operations", database_id))
            return {"operations": [{"operation_id": 2}]}

    monkeypatch.setattr(backend_gateway, "ChemVaultApiClient", FakeClient)

    result = backend_gateway.get_backend_gateway().get_operation_history(
        "test_db"
    )

    assert result == ({"operation_id": 2},)
    assert calls == [
        ("init", "http://api.example"),
        ("operations", "test_db"),
    ]


def test_operation_history_http_error_does_not_fall_back(monkeypatch):
    monkeypatch.setenv("CHEMVAULT_API_URL", "http://api.example")
    local_calls = []
    monkeypatch.setattr(
        backend_gateway,
        "get_local_operation_history",
        lambda database_id: local_calls.append(database_id),
    )

    class FailingClient:
        def __init__(self, base_url):
            pass

        def get_operation_history(self, database_id):
            raise ChemVaultApiError("request timed out")

    monkeypatch.setattr(backend_gateway, "ChemVaultApiClient", FailingClient)

    with pytest.raises(
        backend_gateway.BackendGatewayError,
        match="request timed out",
    ):
        backend_gateway.get_backend_gateway().get_operation_history("test_db")

    assert local_calls == []


def test_table_export_uses_local_application_backend(monkeypatch):
    monkeypatch.delenv("CHEMVAULT_API_URL", raising=False)
    calls = []
    monkeypatch.setattr(
        backend_gateway,
        "export_table_csv",
        lambda *args: calls.append(args) or b"CID\n1\n",
    )

    result = backend_gateway.get_backend_gateway().export_table(
        "test_db",
        "main",
        ["CID"],
    )

    assert result == b"CID\n1\n"
    assert calls == [("test_db", "main", ["CID"])]


def test_table_export_uses_http_backend(monkeypatch):
    monkeypatch.setenv("CHEMVAULT_API_URL", "http://api.example")
    calls = []

    class FakeClient:
        def __init__(self, base_url):
            calls.append(("init", base_url))

        def export_table(self, database_id, table_name, columns=None):
            calls.append(("export", database_id, table_name, columns))
            return b"CID\n1\n"

    monkeypatch.setattr(backend_gateway, "ChemVaultApiClient", FakeClient)

    result = backend_gateway.get_backend_gateway().export_table(
        "test_db",
        "main",
        ["CID"],
    )

    assert result == b"CID\n1\n"
    assert calls == [
        ("init", "http://api.example"),
        ("export", "test_db", "main", ["CID"]),
    ]


def test_table_export_http_error_does_not_fall_back(monkeypatch):
    monkeypatch.setenv("CHEMVAULT_API_URL", "http://api.example")
    local_calls = []
    monkeypatch.setattr(
        backend_gateway,
        "export_table_csv",
        lambda *args: local_calls.append(args),
    )

    class FailingClient:
        def __init__(self, base_url):
            pass

        def export_table(self, database_id, table_name, columns=None):
            raise ChemVaultApiError("request timed out")

    monkeypatch.setattr(backend_gateway, "ChemVaultApiClient", FailingClient)

    with pytest.raises(
        backend_gateway.BackendGatewayError,
        match="request timed out",
    ):
        backend_gateway.get_backend_gateway().export_table("test_db", "main")

    assert local_calls == []


def test_table_schema_uses_existing_metadata_endpoint_in_http_mode(monkeypatch):
    monkeypatch.setenv("CHEMVAULT_API_URL", "http://api.example")
    local_calls = []
    calls = []
    monkeypatch.setattr(
        backend_gateway,
        "get_local_table_schema",
        lambda *args: local_calls.append(args),
    )

    class FakeClient:
        def __init__(self, base_url):
            calls.append(("init", base_url))

        def get_table_metadata(self, database_id, table_name):
            calls.append(("metadata", database_id, table_name))
            return {"schema": [{"name": "CID", "data_type": "TEXT"}]}

    monkeypatch.setattr(backend_gateway, "ChemVaultApiClient", FakeClient)

    result = backend_gateway.get_backend_gateway().get_table_schema(
        "test_db",
        "main",
    )

    assert result == ({"name": "CID", "data_type": "TEXT"},)
    assert calls == [
        ("init", "http://api.example"),
        ("metadata", "test_db", "main"),
    ]
    assert local_calls == []


def test_table_schema_http_error_does_not_fall_back(monkeypatch):
    monkeypatch.setenv("CHEMVAULT_API_URL", "http://api.example")
    local_calls = []
    monkeypatch.setattr(
        backend_gateway,
        "get_local_table_schema",
        lambda *args: local_calls.append(args),
    )

    class FailingClient:
        def __init__(self, base_url):
            pass

        def get_table_metadata(self, database_id, table_name):
            raise ChemVaultApiError("request timed out")

    monkeypatch.setattr(backend_gateway, "ChemVaultApiClient", FailingClient)

    with pytest.raises(
        backend_gateway.BackendGatewayError,
        match="request timed out",
    ):
        backend_gateway.get_backend_gateway().get_table_schema(
            "test_db",
            "main",
        )

    assert local_calls == []


def test_local_backend_preserves_read_only_contract(monkeypatch):
    monkeypatch.delenv("CHEMVAULT_API_URL", raising=False)
    state = DatabaseState(
        database_id="test_db",
        current_table="main",
        headers=("CID", "SMILES"),
        all_tables=("main",),
    )
    expected_metrics = DatabaseMetrics(row_count=2, group_count=0)
    expected_preview = pd.DataFrame(
        [{"CID": "1"}, {"CID": "2"}],
    )
    monkeypatch.setattr(backend_gateway, "get_table_state", lambda *args: state)
    monkeypatch.setattr(
        backend_gateway,
        "get_local_table_metrics",
        lambda *args: expected_metrics,
    )
    monkeypatch.setattr(
        backend_gateway,
        "preview_selected_columns",
        lambda *args: expected_preview,
    )
    gateway = backend_gateway.get_backend_gateway()

    metadata = gateway.get_table_metadata("test_db", "main")
    metrics = gateway.get_table_metrics("test_db", "main")
    preview = gateway.preview_table(
        "test_db",
        "main",
        ["CID"],
        limit=1,
    )

    assert metadata == backend_gateway.TableMetadata(
        columns=("CID", "SMILES"),
        row_count=2,
    )
    assert metrics is expected_metrics
    assert preview.to_dict(orient="records") == [{"CID": "1"}]


def test_streamlit_read_only_routes_do_not_branch_on_api_url():
    repository_root = Path(__file__).resolve().parents[1]

    for relative_path in (
        "ui/session_state.py",
        "ui/main_page.py",
        "ui/sidebar.py",
    ):
        source = (repository_root / relative_path).read_text(encoding="utf-8")
        assert "CHEMVAULT_API_URL" not in source
        assert "ChemVaultApiClient" not in source


def _completed_job(job_id="job-1"):
    return JobStatusContract(
        job_id=job_id,
        job_type="harmonsmile",
        status=JobStatus.COMPLETED,
        database_id="test_db",
        stage="completed",
        progress=1.0,
        message="done",
        created_at="2026-07-03T10:00:00+00:00",
        started_at="2026-07-03T10:00:00+00:00",
        finished_at="2026-07-03T10:01:00+00:00",
        error=None,
        cancellable=False,
        updated_at="2026-07-03T10:01:00+00:00",
        result={"merged_rows": 2},
    )


def test_harmonsmile_command_uses_local_application_backend(monkeypatch):
    monkeypatch.delenv("CHEMVAULT_API_URL", raising=False)
    expected = _completed_job()
    calls = []
    monkeypatch.setattr(
        backend_gateway,
        "launch_local_harmonsmile_job",
        lambda *args: calls.append(args) or expected,
    )

    result = backend_gateway.get_backend_gateway().launch_harmonsmile_job(
        "test_db", "main", "CID"
    )

    assert result is expected
    assert calls == [("test_db", "main", "CID")]


def test_harmonsmile_command_uses_http_backend(monkeypatch):
    monkeypatch.setenv("CHEMVAULT_API_URL", "http://api.example")
    expected = _completed_job()
    payload = {**expected.__dict__, "status": expected.status.value}
    calls = []

    class FakeClient:
        def __init__(self, base_url):
            calls.append(("init", base_url))

        def launch_harmonsmile_job(self, *args):
            calls.append(("launch", *args))
            return payload

    monkeypatch.setattr(backend_gateway, "ChemVaultApiClient", FakeClient)

    result = backend_gateway.get_backend_gateway().launch_harmonsmile_job(
        "test_db", "main", "CID"
    )

    assert result == expected
    assert calls == [
        ("init", "http://api.example"),
        ("launch", "test_db", "main", "CID"),
    ]


def test_harmonsmile_http_failure_never_runs_local_backend(monkeypatch):
    monkeypatch.setenv("CHEMVAULT_API_URL", "http://api.example")
    local_calls = []
    monkeypatch.setattr(
        backend_gateway,
        "launch_local_harmonsmile_job",
        lambda *args: local_calls.append(args),
    )

    class FailingClient:
        def __init__(self, base_url):
            pass

        def launch_harmonsmile_job(self, *args):
            raise ChemVaultApiError("request timed out")

    monkeypatch.setattr(backend_gateway, "ChemVaultApiClient", FailingClient)

    with pytest.raises(backend_gateway.BackendGatewayError):
        backend_gateway.get_backend_gateway().launch_harmonsmile_job(
            "test_db", "main", "CID"
        )
    assert local_calls == []
