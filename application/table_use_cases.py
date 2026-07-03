# SPDX-License-Identifier: LGPL-3.0-or-later
"""Application use cases for table selection, preview, and CSV export."""
from application.database_use_cases import InvalidColumnError, get_table_state
from services import export as export_service
from services import selection as selection_service


def resolve_selected_columns(headers, selected_headers):
    return selection_service.get_active_selected_headers(
        headers,
        selected_headers,
    )


def preview_selected_columns(
    database_id,
    current_table,
    headers,
    selected_headers,
):
    return selection_service.build_preview_table(
        database_id,
        current_table,
        headers,
        selected_headers,
    )


def load_selected_columns(
    database_id,
    current_table,
    headers,
    selected_headers,
):
    return selection_service.get_selected_columns(
        database_id,
        current_table,
        headers,
        selected_headers,
    )


def export_selected_columns(
    database_id,
    current_table,
    headers,
    selected_headers,
):
    return export_service.export_table(
        database_id,
        current_table,
        headers,
        selected_headers,
    )


def export_table_csv(
    database_id: str,
    table_name: str,
    columns: list[str] | None = None,
) -> bytes:
    """Export all rows and either selected or all table columns as CSV."""
    state = get_table_state(database_id, table_name)
    selected_columns = list(state.headers) if columns is None else list(columns)
    invalid_columns = [
        column for column in selected_columns if column not in state.headers
    ]
    if invalid_columns:
        raise InvalidColumnError(
            f"Unknown columns: {', '.join(invalid_columns)}"
        )
    return export_service.export_table(
        database_id,
        table_name,
        state.headers,
        selected_columns,
    )


def export_filtered_selection(
    search_value,
    filter_column,
    database_id,
    current_table,
    headers,
    selected_headers,
):
    return export_service.export_table_by_sub_grupo(
        codigo_buscar=search_value,
        columna_filtro=filter_column,
        database_id=database_id,
        current_table=current_table,
        headers=headers,
        selected_headers=selected_headers,
    )
