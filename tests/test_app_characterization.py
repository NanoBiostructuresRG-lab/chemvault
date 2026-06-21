import ast
import types
from pathlib import Path

import pytest

from state_keys import (
    CURRENT_TABLE,
    CUSTOM_QUERY,
    DATABASE_ID,
    GROUP_BY_COLUMN,
    HEADERS,
    NEW_TABLE_NAME,
    ORDER_BY_COLUMN,
    ORDER_DIRECTION,
    TYPE_OF_FILTER,
    WHERE_COLUMN,
    WHERE_CONDITION,
)
from services.sql_utils import is_valid_table_name, quote_identifier


APP_PATH = Path(__file__).resolve().parents[1] / "app.py"


def load_app_functions(function_names):
    tree = ast.parse(APP_PATH.read_text(encoding="utf-8"))
    selected_nodes = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in function_names
    ]
    module = ast.Module(body=selected_nodes, type_ignores=[])
    ast.fix_missing_locations(module)

    namespace = {
        "st": types.SimpleNamespace(session_state={}),
        "quote_identifier": quote_identifier,
        "is_valid_table_name": is_valid_table_name,
        "CURRENT_TABLE": CURRENT_TABLE,
        "CUSTOM_QUERY": CUSTOM_QUERY,
        "DATABASE_ID": DATABASE_ID,
        "GROUP_BY_COLUMN": GROUP_BY_COLUMN,
        "HEADERS": HEADERS,
        "NEW_TABLE_NAME": NEW_TABLE_NAME,
        "ORDER_BY_COLUMN": ORDER_BY_COLUMN,
        "ORDER_DIRECTION": ORDER_DIRECTION,
        "TYPE_OF_FILTER": TYPE_OF_FILTER,
        "WHERE_COLUMN": WHERE_COLUMN,
        "WHERE_CONDITION": WHERE_CONDITION,
    }
    exec(compile(module, str(APP_PATH), "exec"), namespace)
    return namespace


def normalize_sql(sql):
    return " ".join(sql.split())


def test_quote_identifier_preserves_sqlite_identifier_quoting():
    assert quote_identifier("main") == '"main"'
    assert quote_identifier("PubChem CID") == '"PubChem CID"'
    assert quote_identifier('a"b') == '"a""b"'


@pytest.mark.parametrize(
    ("table_name", "expected"),
    [
        ("main", True),
        ("Nueva_tabla", True),
        ("table_01", True),
        ("", False),
        (None, False),
        ("1_table", False),
        ("table name", False),
        ("table-name", False),
    ],
)
def test_is_valid_table_name_characterizes_current_rules(table_name, expected):
    assert is_valid_table_name(table_name) is expected


def load_query_builder(session_state):
    ns = load_app_functions(
        [
            "construir_linea_query",
        ]
    )
    ns["get_active_selected_headers"] = lambda: [
        col
        for col in ns["st"].session_state.get("selected_headers", [])
        if col in ns["st"].session_state.get("headers", [])
    ]
    ns["st"].session_state.update(session_state)
    return ns


def test_construir_linea_query_without_filter_uses_active_selected_headers():
    ns = load_query_builder(
        {
            "new_table_name": "Derived_table",
            "headers": ["CID", "SMILES", "MW"],
            "selected_headers": ["CID", "stale_column", "SMILES"],
            "current_table": "main",
            "type_of_filter": "None",
        }
    )

    query = normalize_sql(ns["construir_linea_query"]())

    assert query == 'CREATE TABLE "Derived_table" AS SELECT "CID", "SMILES" FROM "main"'


def test_construir_linea_query_with_group_by_requires_selected_column():
    ns = load_query_builder(
        {
            "new_table_name": "Grouped",
            "headers": ["CID", "SMILES"],
            "selected_headers": ["CID", "SMILES"],
            "current_table": "main",
            "type_of_filter": "GROUP BY",
            "group_by_column": "CID",
        }
    )

    query = normalize_sql(ns["construir_linea_query"]())

    assert query == 'CREATE TABLE "Grouped" AS SELECT "CID", "SMILES" FROM "main" GROUP BY "CID"'


def test_construir_linea_query_with_where_allows_any_active_header():
    ns = load_query_builder(
        {
            "new_table_name": "Filtered",
            "headers": ["CID", "SMILES", "MW"],
            "selected_headers": ["CID", "SMILES"],
            "current_table": "main",
            "type_of_filter": "WHERE",
            "where_column": "MW",
            "where_condition": "> 100",
        }
    )

    query = normalize_sql(ns["construir_linea_query"]())

    assert query == 'CREATE TABLE "Filtered" AS SELECT "CID", "SMILES" FROM "main" WHERE "MW" > 100'


def test_construir_linea_query_with_order_by_requires_selected_column():
    ns = load_query_builder(
        {
            "new_table_name": "Sorted",
            "headers": ["CID", "SMILES"],
            "selected_headers": ["CID", "SMILES"],
            "current_table": "main",
            "type_of_filter": "ORDER BY",
            "order_by_column": "SMILES",
            "order_direction": "DESC",
        }
    )

    query = normalize_sql(ns["construir_linea_query"]())

    assert query == 'CREATE TABLE "Sorted" AS SELECT "CID", "SMILES" FROM "main" ORDER BY "SMILES" DESC'


def test_construir_linea_query_rejects_invalid_group_by_column():
    ns = load_query_builder(
        {
            "new_table_name": "Bad_group",
            "headers": ["CID", "SMILES", "MW"],
            "selected_headers": ["CID", "SMILES"],
            "current_table": "main",
            "type_of_filter": "GROUP BY",
            "group_by_column": "MW",
        }
    )

    with pytest.raises(ValueError, match="GROUP BY column"):
        ns["construir_linea_query"]()


def test_construir_linea_query_requires_selected_columns():
    ns = load_query_builder(
        {
            "new_table_name": "Empty_selection",
            "headers": ["CID", "SMILES"],
            "selected_headers": [],
            "current_table": "main",
            "type_of_filter": "None",
        }
    )

    with pytest.raises(ValueError, match="Select at least one column"):
        ns["construir_linea_query"]()
