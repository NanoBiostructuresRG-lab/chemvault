# SPDX-License-Identifier: LGPL-3.0-or-later
import pytest

from application import table_use_cases


def test_resolve_selected_columns_delegates_explicit_selection(monkeypatch):
    calls = []
    monkeypatch.setattr(
        table_use_cases.selection_service,
        "get_active_selected_headers",
        lambda headers, selected: calls.append((headers, selected)) or ["CID"],
    )

    result = table_use_cases.resolve_selected_columns(
        ["CID", "SMILES"],
        ["CID", "stale_column"],
    )

    assert result == ["CID"]
    assert calls == [(["CID", "SMILES"], ["CID", "stale_column"])]


@pytest.mark.parametrize(
    ("use_case_name", "service_name"),
    [
        ("preview_selected_columns", "build_preview_table"),
        ("load_selected_columns", "get_selected_columns"),
    ],
)
def test_table_read_use_cases_delegate_explicit_state(
    monkeypatch,
    use_case_name,
    service_name,
):
    expected = object()
    calls = []
    monkeypatch.setattr(
        table_use_cases.selection_service,
        service_name,
        lambda *args: calls.append(args) or expected,
    )

    result = getattr(table_use_cases, use_case_name)(
        "test_db",
        "main",
        ["CID", "SMILES"],
        ["CID"],
    )

    assert result is expected
    assert calls == [("test_db", "main", ["CID", "SMILES"], ["CID"])]


def test_export_selected_columns_delegates_explicit_state(monkeypatch):
    expected = b"CID\n1\n"
    calls = []
    monkeypatch.setattr(
        table_use_cases.export_service,
        "export_table",
        lambda *args: calls.append(args) or expected,
    )

    result = table_use_cases.export_selected_columns(
        "test_db",
        "main",
        ["CID", "SMILES"],
        ["CID"],
    )

    assert result == expected
    assert calls == [("test_db", "main", ["CID", "SMILES"], ["CID"])]


def test_export_filtered_selection_maps_filter_arguments(monkeypatch):
    expected = b"CID\n1\n"
    calls = []

    def fake_export(**kwargs):
        calls.append(kwargs)
        return expected

    monkeypatch.setattr(
        table_use_cases.export_service,
        "export_table_by_sub_grupo",
        fake_export,
    )

    result = table_use_cases.export_filtered_selection(
        "A",
        "group_id",
        "test_db",
        "main",
        ["CID", "group_id"],
        ["CID"],
    )

    assert result == expected
    assert calls == [
        {
            "codigo_buscar": "A",
            "columna_filtro": "group_id",
            "database_id": "test_db",
            "current_table": "main",
            "headers": ["CID", "group_id"],
            "selected_headers": ["CID"],
        }
    ]
