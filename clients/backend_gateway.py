# SPDX-License-Identifier: LGPL-3.0-or-later
"""Single read-only backend boundary for Streamlit database exploration."""
import os
from dataclasses import dataclass
from typing import Protocol

import pandas as pd

from application.database_use_cases import (
    DatabaseMetrics,
    get_table_metrics as get_local_table_metrics,
    get_table_schema as get_local_table_schema,
    get_table_state,
    refresh_database,
)
from application.table_use_cases import preview_selected_columns
from clients.api_client import ChemVaultApiClient, ChemVaultApiError


DEFAULT_PREVIEW_LIMIT = 10


class BackendGatewayError(RuntimeError):
    """Raised when the selected read-only backend cannot serve a request."""


@dataclass(frozen=True)
class TableMetadata:
    columns: tuple[str, ...]
    row_count: int
    preview_limit: int = DEFAULT_PREVIEW_LIMIT
    read_only: bool = True


class _ReadOnlyBackend(Protocol):
    def list_tables(self, database_id: str) -> tuple[str, ...]: ...

    def get_table_metadata(
        self,
        database_id: str,
        table_name: str,
    ) -> TableMetadata: ...

    def get_table_metrics(
        self,
        database_id: str,
        table_name: str,
        group_column: str = "",
    ) -> DatabaseMetrics: ...

    def get_table_schema(
        self,
        database_id: str,
        table_name: str,
    ) -> tuple[dict[str, object], ...]: ...

    def preview_table(
        self,
        database_id: str,
        table_name: str,
        columns: list[str] | None = None,
        limit: int = DEFAULT_PREVIEW_LIMIT,
    ) -> pd.DataFrame: ...


def _validate_preview_limit(limit: int) -> int:
    limit = int(limit)
    if not 1 <= limit <= DEFAULT_PREVIEW_LIMIT:
        raise ValueError(
            f"Preview limit must be between 1 and {DEFAULT_PREVIEW_LIMIT}."
        )
    return limit


class _LocalReadOnlyBackend:
    def list_tables(self, database_id: str) -> tuple[str, ...]:
        return tuple(refresh_database(database_id).all_tables)

    def get_table_metadata(
        self,
        database_id: str,
        table_name: str,
    ) -> TableMetadata:
        state = get_table_state(database_id, table_name)
        metrics = get_local_table_metrics(database_id, table_name)
        return TableMetadata(
            columns=tuple(state.headers),
            row_count=metrics.row_count,
        )

    def get_table_metrics(
        self,
        database_id: str,
        table_name: str,
        group_column: str = "",
    ) -> DatabaseMetrics:
        return get_local_table_metrics(
            database_id,
            table_name,
            group_column,
        )

    def get_table_schema(
        self,
        database_id: str,
        table_name: str,
    ) -> tuple[dict[str, object], ...]:
        return get_local_table_schema(database_id, table_name)

    def preview_table(
        self,
        database_id: str,
        table_name: str,
        columns: list[str] | None = None,
        limit: int = DEFAULT_PREVIEW_LIMIT,
    ) -> pd.DataFrame:
        limit = _validate_preview_limit(limit)
        state = get_table_state(database_id, table_name)
        selected_columns = list(state.headers) if columns is None else columns
        preview = preview_selected_columns(
            database_id,
            table_name,
            state.headers,
            selected_columns,
        )
        return preview.head(limit)


class _HttpReadOnlyBackend:
    def __init__(self, base_url: str):
        self._client = ChemVaultApiClient(base_url=base_url)

    @staticmethod
    def _raise_gateway_error(error: ChemVaultApiError):
        raise BackendGatewayError(str(error)) from error

    def list_tables(self, database_id: str) -> tuple[str, ...]:
        try:
            response = self._client.list_tables(database_id)
        except ChemVaultApiError as error:
            self._raise_gateway_error(error)
        return tuple(response.get("tables", []))

    def get_table_metadata(
        self,
        database_id: str,
        table_name: str,
    ) -> TableMetadata:
        try:
            response = self._client.get_table_metadata(
                database_id,
                table_name,
            )
        except ChemVaultApiError as error:
            self._raise_gateway_error(error)
        return TableMetadata(
            columns=tuple(response.get("columns", [])),
            row_count=response.get("row_count", 0),
            preview_limit=response.get(
                "preview_limit",
                DEFAULT_PREVIEW_LIMIT,
            ),
            read_only=response.get("read_only", True),
        )

    def get_table_metrics(
        self,
        database_id: str,
        table_name: str,
        group_column: str = "",
    ) -> DatabaseMetrics:
        try:
            response = self._client.get_table_metrics(
                database_id,
                table_name,
                group_column=group_column,
            )
        except ChemVaultApiError as error:
            self._raise_gateway_error(error)
        return DatabaseMetrics(
            row_count=response["row_count"],
            group_count=response["group_count"],
        )

    def get_table_schema(
        self,
        database_id: str,
        table_name: str,
    ) -> tuple[dict[str, object], ...]:
        try:
            response = self._client.get_table_metadata(
                database_id,
                table_name,
            )
        except ChemVaultApiError as error:
            self._raise_gateway_error(error)
        return tuple(response.get("schema", []))

    def preview_table(
        self,
        database_id: str,
        table_name: str,
        columns: list[str] | None = None,
        limit: int = DEFAULT_PREVIEW_LIMIT,
    ) -> pd.DataFrame:
        limit = _validate_preview_limit(limit)
        try:
            response = self._client.preview_table(
                database_id,
                table_name,
                columns=columns,
            )
        except ChemVaultApiError as error:
            self._raise_gateway_error(error)
        response_columns = response.get("columns", columns or [])
        return pd.DataFrame(
            response.get("rows", []),
            columns=response_columns,
        ).head(limit)


class ReadOnlyBackendGateway:
    """Facade exposing one stable contract to Streamlit."""

    def __init__(self, backend: _ReadOnlyBackend, mode: str):
        self._backend = backend
        self.mode = mode

    def list_tables(self, database_id: str) -> tuple[str, ...]:
        return self._backend.list_tables(database_id)

    def get_table_metadata(
        self,
        database_id: str,
        table_name: str,
    ) -> TableMetadata:
        return self._backend.get_table_metadata(database_id, table_name)

    def get_table_metrics(
        self,
        database_id: str,
        table_name: str,
        group_column: str = "",
    ) -> DatabaseMetrics:
        return self._backend.get_table_metrics(
            database_id,
            table_name,
            group_column,
        )

    def get_table_schema(
        self,
        database_id: str,
        table_name: str,
    ) -> tuple[dict[str, object], ...]:
        return self._backend.get_table_schema(database_id, table_name)

    def preview_table(
        self,
        database_id: str,
        table_name: str,
        columns: list[str] | None = None,
        limit: int = DEFAULT_PREVIEW_LIMIT,
    ) -> pd.DataFrame:
        return self._backend.preview_table(
            database_id,
            table_name,
            columns,
            limit,
        )


def get_backend_gateway() -> ReadOnlyBackendGateway:
    """Select the backend once, at the Streamlit boundary."""
    api_url = os.getenv("CHEMVAULT_API_URL", "").strip()
    if api_url:
        return ReadOnlyBackendGateway(
            _HttpReadOnlyBackend(api_url),
            mode="http",
        )
    return ReadOnlyBackendGateway(_LocalReadOnlyBackend(), mode="local")
