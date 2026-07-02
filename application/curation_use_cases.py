# SPDX-License-Identifier: LGPL-3.0-or-later
"""Application use cases for molecular dataset curation."""
from services import curation as curation_service


def is_cid_header(header):
    return curation_service.is_cid_header(header)


def run_harmonsmile(selected_columns_df):
    return curation_service.run_harmonsmile(selected_columns_df)


def run_chamanp(
    selected_columns_df,
    identifier_column,
    smiles_column,
    collections_column,
):
    return curation_service.run_chamanp(
        selected_columns_df,
        identifier_column,
        smiles_column,
        collections_column,
    )


def merge_curated_dataframe(
    dataframe,
    primary_key,
    foreign_key,
    database_id,
    current_table,
):
    return curation_service.agregar_df_por_pk(
        dataframe,
        primary_key,
        foreign_key,
        database_id,
        current_table,
    )
