# SPDX-License-Identifier: LGPL-3.0-or-later
import requests

from clients.api_client import ChemVaultApiClient, ChemVaultApiError


class StubResponse:
    def __init__(
        self,
        payload,
        status_code=200,
        text="",
        content=b"",
        headers=None,
    ):
        self.payload = payload
        self.status_code = status_code
        self.text = text
        self.content = content
        self.headers = headers or {}

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(response=self)


def test_client_builds_urls_for_read_only_endpoints(monkeypatch):
    calls = []

    def fake_get(_session, url, **kwargs):
        calls.append((url, kwargs))
        return StubResponse({})

    monkeypatch.setattr(requests.Session, "get", fake_get)
    client = ChemVaultApiClient(base_url="http://api.example/")

    client.health()
    client.list_tables("test_db")
    client.get_operation_history("test_db")
    client.get_table_metadata("test_db", "main")
    client.get_table_metrics("test_db", "main")
    client.preview_table("test_db", "main")
    client.export_table("test_db", "main")

    assert [url for url, _ in calls] == [
        "http://api.example/health",
        "http://api.example/databases/test_db/tables",
        "http://api.example/databases/test_db/operations",
        "http://api.example/databases/test_db/tables/main/metadata",
        "http://api.example/databases/test_db/tables/main/metrics",
        "http://api.example/databases/test_db/tables/main/preview",
        "http://api.example/databases/test_db/tables/main/export",
    ]


def test_health_returns_api_status(monkeypatch):
    monkeypatch.setattr(
        requests.Session,
        "get",
        lambda *_args, **_kwargs: StubResponse({"status": "ok"}),
    )

    assert ChemVaultApiClient().health() == {"status": "ok"}


def test_client_posts_explicit_database_activation(monkeypatch):
    calls = []

    def fake_post(_session, url, **kwargs):
        calls.append((url, kwargs))
        return StubResponse({"database_id": "test db", "recovered_jobs": []})

    monkeypatch.setattr(requests.Session, "post", fake_post)

    result = ChemVaultApiClient(
        "http://api.example/"
    ).activate_scientific_runtime("test db")

    assert result == {"database_id": "test db", "recovered_jobs": []}
    assert calls == [
        (
            "http://api.example/databases/test%20db/"
            "scientific-runtime/activate",
            {"json": None, "timeout": 10.0},
        )
    ]


def test_preview_sends_columns_as_repeated_query_params(monkeypatch):
    calls = []

    def fake_get(_session, url, **kwargs):
        calls.append((url, kwargs))
        return StubResponse({"rows": []})

    monkeypatch.setattr(requests.Session, "get", fake_get)

    ChemVaultApiClient().preview_table(
        "test_db",
        "main",
        columns=["CID", "SMILES"],
    )

    assert calls[0][1]["params"] == [
        ("columns", "CID"),
        ("columns", "SMILES"),
    ]


def test_export_returns_bytes_and_sends_selected_columns(monkeypatch):
    calls = []

    def fake_get(_session, url, **kwargs):
        calls.append((url, kwargs))
        return StubResponse({}, content=b"CID\r\n1\r\n")

    monkeypatch.setattr(requests.Session, "get", fake_get)

    result = ChemVaultApiClient().export_table(
        "test_db",
        "main",
        columns=["CID", "SMILES"],
    )

    assert result == b"CID\r\n1\r\n"
    assert calls[0][1]["params"] == [
        ("columns", "CID"),
        ("columns", "SMILES"),
    ]


def test_modelability_npz_export_forwards_identity_and_backend_filename(
    monkeypatch,
):
    calls = []
    filename = "test_db_IC50_fingerprints_12345678.npz"

    def fake_get(_session, url, **kwargs):
        calls.append((url, kwargs))
        return StubResponse(
            {},
            content=b"npz-bytes",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"'
            },
        )

    monkeypatch.setattr(requests.Session, "get", fake_get)

    result = ChemVaultApiClient(
        "http://api.example"
    ).export_modelability_fingerprints(
        "test db",
        "activity_subset_IC50_structure_consolidated",
        "12345678analysis",
    )

    assert result == (b"npz-bytes", filename)
    assert calls == [
        (
            "http://api.example/databases/test%20db/tables/"
            "activity_subset_IC50_structure_consolidated/"
            "modelability-index/fingerprints/export",
            {
                "params": {"analysis_identity": "12345678analysis"},
                "timeout": 10.0,
            },
        )
    ]


def test_client_posts_structure_consolidation_command(monkeypatch):
    calls = []
    payload = {
        "table_name": "source_structure_consolidated",
        "created_row_count": 4,
    }

    def fake_post(_session, url, **kwargs):
        calls.append((url, kwargs))
        return StubResponse(payload, status_code=201)

    monkeypatch.setattr(requests.Session, "post", fake_post)

    result = ChemVaultApiClient(
        "http://api.example/"
    ).consolidate_structure_table("test db", "source table")

    assert result == payload
    assert calls == [
        (
            "http://api.example/databases/test%20db/tables/"
            "source%20table/structure-consolidation",
            {"json": None, "timeout": 10.0},
        )
    ]


def test_http_error_is_converted_to_client_error(monkeypatch):
    monkeypatch.setattr(
        requests.Session,
        "get",
        lambda *_args, **_kwargs: StubResponse(
            {"detail": "Database was not found."},
            status_code=404,
        ),
    )

    try:
        ChemVaultApiClient().list_tables("missing")
    except ChemVaultApiError as error:
        assert str(error) == (
            "CHEMVAULT API returned HTTP 404: Database was not found."
        )
    else:
        raise AssertionError("ChemVaultApiError was not raised")


def test_request_exception_is_converted_to_client_error(monkeypatch):
    def raise_timeout(*_args, **_kwargs):
        raise requests.Timeout("request timed out")

    monkeypatch.setattr(requests.Session, "get", raise_timeout)

    try:
        ChemVaultApiClient().health()
    except ChemVaultApiError as error:
        assert "request timed out" in str(error)
    else:
        raise AssertionError("ChemVaultApiError was not raised")


def test_client_posts_harmonsmile_command(monkeypatch):
    calls = []

    def fake_post(_session, url, **kwargs):
        calls.append((url, kwargs))
        return StubResponse({"job_id": "job-1"}, status_code=201)

    monkeypatch.setattr(requests.Session, "post", fake_post)

    result = ChemVaultApiClient("http://api.example/").launch_harmonsmile_job(
        "test db", "main", "CID"
    )

    assert result == {"job_id": "job-1"}
    assert calls[0][0] == (
        "http://api.example/databases/test%20db/jobs/harmonsmile"
    )
    assert calls[0][1]["json"] == {
        "table_name": "main",
        "cid_column": "CID",
    }
    assert calls[0][1]["timeout"] == 10.0


def test_client_gets_active_harmonsmile_job(monkeypatch):
    calls = []

    def fake_get(_session, url, **kwargs):
        calls.append((url, kwargs))
        return StubResponse(None)

    monkeypatch.setattr(requests.Session, "get", fake_get)
    result = ChemVaultApiClient(
        "http://api.example/"
    ).find_active_harmonsmile_job("test db", "active table")

    assert result is None
    assert calls == [
        (
            "http://api.example/databases/test%20db/jobs/harmonsmile/active",
            {"params": {"table_name": "active table"}, "timeout": 10.0},
        )
    ]
