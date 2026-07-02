# SPDX-License-Identifier: LGPL-3.0-or-later
"""Application use cases for table selection, preview, and CSV export."""
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
