# SPDX-License-Identifier: LGPL-3.0-or-later
from application import curation_use_cases


def test_is_cid_header_delegates_to_curation_service(monkeypatch):
    calls = []
    monkeypatch.setattr(
        curation_use_cases.curation_service,
        "is_cid_header",
        lambda header: calls.append(header) or True,
    )

    result = curation_use_cases.is_cid_header("PubChem CID")

    assert result is True
    assert calls == ["PubChem CID"]


def test_run_harmonsmile_delegates_dataframe(monkeypatch):
    dataframe = object()
    expected = object()
    calls = []
    monkeypatch.setattr(
        curation_use_cases.curation_service,
        "run_harmonsmile",
        lambda value: calls.append(value) or expected,
    )

    result = curation_use_cases.run_harmonsmile(dataframe)

    assert result is expected
    assert calls == [dataframe]


def test_run_chamanp_maps_explicit_columns(monkeypatch):
    dataframe = object()
    expected = object()
    calls = []
    monkeypatch.setattr(
        curation_use_cases.curation_service,
        "run_chamanp",
        lambda *args: calls.append(args) or expected,
    )

    result = curation_use_cases.run_chamanp(
        dataframe,
        "identifier",
        "canonical_smiles",
        "collections",
    )

    assert result is expected
    assert calls == [
        (dataframe, "identifier", "canonical_smiles", "collections")
    ]


def test_merge_curated_dataframe_maps_explicit_database_state(monkeypatch):
    dataframe = object()
    calls = []
    monkeypatch.setattr(
        curation_use_cases.curation_service,
        "agregar_df_por_pk",
        lambda *args: calls.append(args) or True,
    )

    result = curation_use_cases.merge_curated_dataframe(
        dataframe,
        "CID",
        "PubChem_CID",
        "test_db",
        "main",
    )

    assert result is True
    assert calls == [
        (dataframe, "CID", "PubChem_CID", "test_db", "main")
    ]
