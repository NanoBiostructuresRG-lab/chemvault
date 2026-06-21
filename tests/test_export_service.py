import sqlite3

from services import export


def csv_text(data):
    return data.decode("utf-8").replace("\r\n", "\n")


def create_export_db():
    connection = sqlite3.connect(":memory:")
    connection.execute('CREATE TABLE "main" (CID TEXT, SMILES TEXT, group_id TEXT)')
    connection.executemany(
        'INSERT INTO "main" (CID, SMILES, group_id) VALUES (?, ?, ?)',
        [
            ("1", "CCO", "A"),
            ("2", "CCC", "B"),
            ("3", "CCN", "A"),
        ],
    )
    return connection


def test_export_table_returns_empty_csv_without_database(monkeypatch):
    monkeypatch.setattr(export.st, "session_state", {"database_id": "", "current_table": ""})

    assert csv_text(export.export_table()) == "\n"


def test_export_table_exports_all_columns_when_no_columns_are_selected(monkeypatch):
    connection = create_export_db()
    monkeypatch.setattr(export, "get_connection", lambda db_name: connection)
    monkeypatch.setattr(
        export.st,
        "session_state",
        {
            "database_id": "test_db",
            "current_table": "main",
            "headers": ["CID", "SMILES", "group_id"],
            "selected_headers": [],
        },
    )

    assert csv_text(export.export_table()) == "CID,SMILES,group_id\n1,CCO,A\n2,CCC,B\n3,CCN,A\n"


def test_export_table_exports_only_active_selected_columns(monkeypatch):
    connection = create_export_db()
    monkeypatch.setattr(export, "get_connection", lambda db_name: connection)
    monkeypatch.setattr(
        export.st,
        "session_state",
        {
            "database_id": "test_db",
            "current_table": "main",
            "headers": ["CID", "SMILES", "group_id"],
            "selected_headers": ["CID", "stale_column", "SMILES"],
        },
    )

    assert csv_text(export.export_table()) == "CID,SMILES\n1,CCO\n2,CCC\n3,CCN\n"


def test_export_table_by_sub_grupo_filters_rows_and_selected_columns(monkeypatch):
    connection = create_export_db()
    monkeypatch.setattr(export, "get_connection", lambda db_name: connection)
    monkeypatch.setattr(
        export.st,
        "session_state",
        {
            "database_id": "test_db",
            "current_table": "main",
            "headers": ["CID", "SMILES", "group_id"],
            "selected_headers": ["CID", "SMILES"],
        },
    )

    result = export.export_table_by_sub_grupo(codigo_buscar="A", columna_filtro="group_id")

    assert csv_text(result) == "CID,SMILES\n1,CCO\n3,CCN\n"


def test_export_table_by_sub_grupo_returns_empty_csv_for_invalid_filter_column(monkeypatch):
    monkeypatch.setattr(
        export.st,
        "session_state",
        {
            "database_id": "test_db",
            "current_table": "main",
            "headers": ["CID"],
            "selected_headers": ["CID"],
        },
    )

    assert csv_text(export.export_table_by_sub_grupo(codigo_buscar="A", columna_filtro="missing")) == "\n"
