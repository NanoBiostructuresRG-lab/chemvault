# SPDX-License-Identifier: LGPL-3.0-or-later
from pathlib import Path

import pandas as pd
import pytest

from application.database_use_cases import DatabaseMetrics
from application.structure_consolidation import (
    StructureConsolidationTableResult,
)
from clients import backend_gateway
from clients.api_client import ChemVaultApiError
from application.job_contracts import JobStatusContract, RecoveredJobContract
from services.job_models import JobStatus
from services.database import DatabaseState


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
    )


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


def test_structure_consolidation_uses_local_application_backend(monkeypatch):
    monkeypatch.delenv("CHEMVAULT_API_URL", raising=False)
    expected = _structure_consolidation_result()
    calls = []
    monkeypatch.setattr(
        backend_gateway,
        "consolidate_local_structure_table",
        lambda *args: calls.append(args) or expected,
    )

    result = backend_gateway.get_backend_gateway().consolidate_structure_table(
        "test_db",
        "main",
    )

    assert result is expected
    assert calls == [("test_db", "main")]


def test_structure_consolidation_uses_http_backend(monkeypatch):
    monkeypatch.setenv("CHEMVAULT_API_URL", "http://api.example")
    expected = _structure_consolidation_result()
    calls = []

    class FakeClient:
        def __init__(self, base_url):
            calls.append(("init", base_url))

        def consolidate_structure_table(self, database_id, source_table):
            calls.append(("consolidate", database_id, source_table))
            return expected.__dict__

    monkeypatch.setattr(backend_gateway, "ChemVaultApiClient", FakeClient)

    result = backend_gateway.get_backend_gateway().consolidate_structure_table(
        "test_db",
        "main",
    )

    assert result == expected
    assert calls == [
        ("init", "http://api.example"),
        ("consolidate", "test_db", "main"),
    ]


def test_structure_consolidation_http_error_does_not_fall_back(monkeypatch):
    monkeypatch.setenv("CHEMVAULT_API_URL", "http://api.example")
    local_calls = []
    monkeypatch.setattr(
        backend_gateway,
        "consolidate_local_structure_table",
        lambda *args: local_calls.append(args),
    )

    class FailingClient:
        def __init__(self, base_url):
            pass

        def consolidate_structure_table(self, database_id, source_table):
            raise ChemVaultApiError("validation failed")

    monkeypatch.setattr(backend_gateway, "ChemVaultApiClient", FailingClient)

    with pytest.raises(
        backend_gateway.BackendGatewayError,
        match="validation failed",
    ):
        backend_gateway.get_backend_gateway().consolidate_structure_table(
            "test_db",
            "main",
        )

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


def _completed_job(job_id="job-1", status=JobStatus.COMPLETED):
    return JobStatusContract(
        job_id=job_id,
        job_type="harmonsmile",
        status=status,
        database_id="test_db",
        stage=status.value,
        progress=1.0 if status == JobStatus.COMPLETED else 0.0,
        message="done" if status == JobStatus.COMPLETED else "queued",
        created_at="2026-07-03T10:00:00+00:00",
        started_at="2026-07-03T10:00:00+00:00",
        finished_at=(
            "2026-07-03T10:01:00+00:00"
            if status == JobStatus.COMPLETED
            else None
        ),
        error=None,
        cancellable=status in {JobStatus.PENDING, JobStatus.RUNNING},
        updated_at="2026-07-03T10:01:00+00:00",
        result={"merged_rows": 2} if status == JobStatus.COMPLETED else None,
    )


def test_harmonsmile_command_uses_local_application_backend(monkeypatch):
    monkeypatch.delenv("CHEMVAULT_API_URL", raising=False)
    expected = _completed_job(status=JobStatus.PENDING)
    calls = []
    monkeypatch.setattr(
        backend_gateway,
        "create_scientific_job",
        lambda *args: calls.append(("create", *args)) or expected,
    )
    monkeypatch.setattr(
        backend_gateway,
        "start_scientific_job_executor",
        lambda *args, **kwargs: calls.append(("executor", args, kwargs)),
    )

    result = backend_gateway.get_backend_gateway().launch_harmonsmile_job(
        "test_db", "main", "CID"
    )

    assert result is expected
    assert calls[0] == (
        "create",
        "test_db",
        "harmonsmile",
        {"table_name": "main", "cid_column": "CID"},
    )
    assert calls[1][0] == "executor"


def test_harmonsmile_command_uses_http_backend(monkeypatch):
    monkeypatch.setenv("CHEMVAULT_API_URL", "http://api.example")
    expected = _completed_job()
    payload = {**expected.__dict__, "status": expected.status.value}
    calls = []

    class FakeClient:
        def __init__(self, base_url):
            calls.append(("init", base_url))

        def launch_scientific_job(self, *args):
            calls.append(("launch", *args))
            return payload

    monkeypatch.setattr(backend_gateway, "ChemVaultApiClient", FakeClient)

    result = backend_gateway.get_backend_gateway().launch_harmonsmile_job(
        "test_db", "main", "CID"
    )

    assert result == expected
    assert calls == [
        ("init", "http://api.example"),
        (
            "launch",
            "test_db",
            "harmonsmile",
            {"table_name": "main", "cid_column": "CID"},
        ),
    ]


def test_harmonsmile_http_failure_never_runs_local_backend(monkeypatch):
    monkeypatch.setenv("CHEMVAULT_API_URL", "http://api.example")
    local_calls = []
    monkeypatch.setattr(
        backend_gateway,
        "create_scientific_job",
        lambda *args: local_calls.append(args),
    )

    class FailingClient:
        def __init__(self, base_url):
            pass

        def launch_scientific_job(self, *args):
            raise ChemVaultApiError("request timed out")

    monkeypatch.setattr(backend_gateway, "ChemVaultApiClient", FailingClient)

    with pytest.raises(backend_gateway.BackendGatewayError):
        backend_gateway.get_backend_gateway().launch_harmonsmile_job(
            "test_db", "main", "CID"
        )
    assert local_calls == []


def test_active_harmonsmile_lookup_uses_local_application_backend(monkeypatch):
    monkeypatch.delenv("CHEMVAULT_API_URL", raising=False)
    expected = _completed_job(status=JobStatus.RUNNING)
    calls = []
    monkeypatch.setattr(
        backend_gateway,
        "find_active_scientific_job",
        lambda *args: calls.append(args) or expected,
    )

    result = backend_gateway.get_backend_gateway().find_active_harmonsmile_job(
        "test_db", "main"
    )

    assert result is expected
    assert calls == [
        ("test_db", backend_gateway.JobType.HARMONSMILE, "main")
    ]


def test_database_activation_uses_local_application_runtime(monkeypatch):
    monkeypatch.delenv("CHEMVAULT_API_URL", raising=False)
    recovered = RecoveredJobContract(
        job=_completed_job(status=JobStatus.PENDING),
        table_name="archived_table",
    )
    calls = []
    monkeypatch.setattr(
        backend_gateway,
        "activate_scientific_runtime",
        lambda database_id: calls.append(database_id) or (recovered,),
    )

    result = backend_gateway.get_backend_gateway().activate_scientific_runtime(
        "test_db"
    )

    assert result == (recovered,)
    assert calls == ["test_db"]


def test_database_activation_uses_http_backend_without_local_fallback(
    monkeypatch,
):
    monkeypatch.setenv("CHEMVAULT_API_URL", "http://api.example")
    local_calls = []
    payload = {
        **_completed_job(status=JobStatus.PENDING).__dict__,
        "status": JobStatus.PENDING.value,
        "table_name": "archived_table",
    }

    class FakeClient:
        def __init__(self, base_url):
            self.base_url = base_url

        def activate_scientific_runtime(self, database_id):
            assert database_id == "test_db"
            return {"database_id": database_id, "recovered_jobs": [payload]}

    monkeypatch.setattr(backend_gateway, "ChemVaultApiClient", FakeClient)
    monkeypatch.setattr(
        backend_gateway,
        "activate_scientific_runtime",
        lambda database_id: local_calls.append(database_id),
    )

    result = backend_gateway.get_backend_gateway().activate_scientific_runtime(
        "test_db"
    )

    assert result[0].job.job_id == "job-1"
    assert result[0].table_name == "archived_table"
    assert local_calls == []


def test_active_harmonsmile_lookup_uses_http_backend(monkeypatch):
    monkeypatch.setenv("CHEMVAULT_API_URL", "http://api.example")
    expected = _completed_job(status=JobStatus.RUNNING)
    payload = {**expected.__dict__, "status": expected.status.value}

    class FakeClient:
        def __init__(self, base_url):
            self.base_url = base_url

        def find_active_harmonsmile_job(self, database_id, table_name):
            assert (database_id, table_name) == ("test_db", "main")
            return payload

    monkeypatch.setattr(backend_gateway, "ChemVaultApiClient", FakeClient)
    result = backend_gateway.get_backend_gateway().find_active_harmonsmile_job(
        "test_db", "main"
    )

    assert result == expected
