# SPDX-License-Identifier: LGPL-3.0-or-later

import pytest

from services import pubchem_client


class FakeResponse:
    def __init__(self, *, json_data=None, text="", status_code=200):
        self._json_data = json_data
        self.text = text
        self.status_code = status_code
        self.raise_calls = 0

    def raise_for_status(self):
        self.raise_calls += 1

    def json(self):
        return self._json_data


def test_fetch_assay_sid_listkey_returns_normalized_metadata(monkeypatch):
    calls = []

    def fake_get(url, params, timeout):
        calls.append((url, params, timeout))
        return FakeResponse(
            json_data={
                "IdentifierList": {
                    "ListKey": 416703172138002372,
                    "Size": 356407,
                }
            }
        )

    monkeypatch.setattr(pubchem_client.requests, "get", fake_get)

    result = pubchem_client.fetch_assay_sid_listkey("540295")

    assert result == {
        "listkey": "416703172138002372",
        "size": 356407,
    }
    assert calls == [
        (
            f"{pubchem_client.BASE_URL}/assay/aid/540295/sids/JSON",
            {"list_return": "listkey"},
            pubchem_client.REQUEST_TIMEOUT,
        )
    ]


def test_fetch_assay_sid_listkey_rejects_missing_metadata(monkeypatch):
    monkeypatch.setattr(
        pubchem_client.requests,
        "get",
        lambda url, params, timeout: FakeResponse(
            json_data={"IdentifierList": {}}
        ),
    )

    with pytest.raises(
        ValueError,
        match="did not return a SID ListKey",
    ):
        pubchem_client.fetch_assay_sid_listkey("540295")


def test_fetch_assay_activity_csv_page_uses_listkey_pagination(monkeypatch):
    calls = []

    def fake_get(url, params, timeout):
        calls.append((url, params, timeout))
        return FakeResponse(text="PUBCHEM_RESULT_TAG\n1\n")

    monkeypatch.setattr(pubchem_client.requests, "get", fake_get)

    text = pubchem_client.fetch_assay_activity_csv_page(
        "540295",
        "416703172138002372",
        10000,
        count=5000,
    )

    assert text == "PUBCHEM_RESULT_TAG\n1\n"
    assert calls == [
        (
            f"{pubchem_client.BASE_URL}/assay/aid/540295/CSV",
            {
                "sid": "listkey",
                "listkey": "416703172138002372",
                "listkey_start": 10000,
                "listkey_count": 5000,
            },
            pubchem_client.REQUEST_TIMEOUT,
        )
    ]


@pytest.mark.parametrize(
    ("start", "count", "message"),
    [
        (-1, 1000, "start cannot be negative"),
        (0, 0, "count must be between"),
        (0, 10001, "count must be between"),
    ],
)
def test_fetch_assay_activity_csv_page_validates_bounds(
    start,
    count,
    message,
):
    with pytest.raises(ValueError, match=message):
        pubchem_client.fetch_assay_activity_csv_page(
            "540295",
            "listkey",
            start,
            count=count,
        )
