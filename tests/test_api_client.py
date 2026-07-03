# SPDX-License-Identifier: LGPL-3.0-or-later
import requests

from clients.api_client import ChemVaultApiClient, ChemVaultApiError


class StubResponse:
    def __init__(self, payload, status_code=200, text=""):
        self.payload = payload
        self.status_code = status_code
        self.text = text

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
    client.get_table_metadata("test_db", "main")
    client.get_table_metrics("test_db", "main")
    client.preview_table("test_db", "main")

    assert [url for url, _ in calls] == [
        "http://api.example/health",
        "http://api.example/databases/test_db/tables",
        "http://api.example/databases/test_db/tables/main/metadata",
        "http://api.example/databases/test_db/tables/main/metrics",
        "http://api.example/databases/test_db/tables/main/preview",
    ]


def test_health_returns_api_status(monkeypatch):
    monkeypatch.setattr(
        requests.Session,
        "get",
        lambda *_args, **_kwargs: StubResponse({"status": "ok"}),
    )

    assert ChemVaultApiClient().health() == {"status": "ok"}


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
