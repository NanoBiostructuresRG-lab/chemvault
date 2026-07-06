# SPDX-License-Identifier: LGPL-3.0-or-later
"""Single backend boundary for Streamlit reads and supported commands."""
import os
from dataclasses import dataclass
from typing import Protocol

import pandas as pd

from application.database_use_cases import (
    DatabaseMetrics,
    get_operation_history as get_local_operation_history,
    get_table_metrics as get_local_table_metrics,
    get_table_schema as get_local_table_schema,
    get_table_state,
    refresh_database,
)
from application.table_use_cases import (
    export_table_csv,
    preview_selected_columns,
)
from application.harmonsmile_jobs import (
    get_harmonsmile_job_status as get_local_harmonsmile_job_status,
    launch_harmonsmile_job as launch_local_harmonsmile_job,
)
from application.job_contracts import JobStatusContract, job_status_from_payload
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


class _Backend(Protocol):
    def list_tables(self, database_id: str) -> tuple[str, ...]: ...

    def get_operation_history(
        self,
        database_id: str,
    ) -> tuple[dict[str, object], ...]: ...

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

    def export_table(
        self,
        database_id: str,
        table_name: str,
        columns: list[str] | None = None,
    ) -> bytes: ...

    def launch_harmonsmile_job(
        self,
        database_id: str,
        table_name: str,
        cid_column: str,
    ) -> JobStatusContract: ...

    def get_job_status(
        self,
        database_id: str,
        job_id: str,
    ) -> JobStatusContract: ...


def _validate_preview_limit(limit: int) -> int:
    limit = int(limit)
    if not 1 <= limit <= DEFAULT_PREVIEW_LIMIT:
        raise ValueError(
            f"Preview limit must be between 1 and {DEFAULT_PREVIEW_LIMIT}."
        )
    return limit


class _LocalBackend:
    def list_tables(self, database_id: str) -> tuple[str, ...]:
        return tuple(refresh_database(database_id).all_tables)

    def get_operation_history(
        self,
        database_id: str,
    ) -> tuple[dict[str, object], ...]:
        return get_local_operation_history(database_id)

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

    def export_table(
        self,
        database_id: str,
        table_name: str,
        columns: list[str] | None = None,
    ) -> bytes:
        return export_table_csv(database_id, table_name, columns)

    def launch_harmonsmile_job(
        self,
        database_id: str,
        table_name: str,
        cid_column: str,
    ) -> JobStatusContract:
        return launch_local_harmonsmile_job(
            database_id, table_name, cid_column
        )

    def get_job_status(
        self,
        database_id: str,
        job_id: str,
    ) -> JobStatusContract:
        return get_local_harmonsmile_job_status(database_id, job_id)


class _HttpBackend:
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

    def get_operation_history(
        self,
        database_id: str,
    ) -> tuple[dict[str, object], ...]:
        try:
            response = self._client.get_operation_history(database_id)
        except ChemVaultApiError as error:
            self._raise_gateway_error(error)
        return tuple(response.get("operations", []))

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

    def export_table(
        self,
        database_id: str,
        table_name: str,
        columns: list[str] | None = None,
    ) -> bytes:
        try:
            return self._client.export_table(
                database_id,
                table_name,
                columns=columns,
            )
        except ChemVaultApiError as error:
            self._raise_gateway_error(error)

    def launch_harmonsmile_job(
        self,
        database_id: str,
        table_name: str,
        cid_column: str,
    ) -> JobStatusContract:
        try:
            response = self._client.launch_harmonsmile_job(
                database_id, table_name, cid_column
            )
        except ChemVaultApiError as error:
            self._raise_gateway_error(error)
        return job_status_from_payload(response)

    def get_job_status(
        self,
        database_id: str,
        job_id: str,
    ) -> JobStatusContract:
        try:
            response = self._client.get_job_status(database_id, job_id)
        except ChemVaultApiError as error:
            self._raise_gateway_error(error)
        return job_status_from_payload(response)


class BackendGateway:
    """Facade exposing one stable contract to Streamlit."""

    def __init__(self, backend: _Backend, mode: str):
        self._backend = backend
        self.mode = mode

    def list_tables(self, database_id: str) -> tuple[str, ...]:
        return self._backend.list_tables(database_id)

    def get_operation_history(
        self,
        database_id: str,
    ) -> tuple[dict[str, object], ...]:
        return self._backend.get_operation_history(database_id)

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

    def export_table(
        self,
        database_id: str,
        table_name: str,
        columns: list[str] | None = None,
    ) -> bytes:
        return self._backend.export_table(
            database_id,
            table_name,
            columns,
        )

    def launch_harmonsmile_job(
        self,
        database_id: str,
        table_name: str,
        cid_column: str,
    ) -> JobStatusContract:
        return self._backend.launch_harmonsmile_job(
            database_id, table_name, cid_column
        )

    def get_job_status(
        self,
        database_id: str,
        job_id: str,
    ) -> JobStatusContract:
        return self._backend.get_job_status(database_id, job_id)


# Compatibility for existing imports while the boundary evolves beyond reads.
ReadOnlyBackendGateway = BackendGateway


def get_backend_gateway() -> BackendGateway:
    """Select the backend once, at the Streamlit boundary."""
    api_url = os.getenv("CHEMVAULT_API_URL", "").strip()
    if api_url:
        return BackendGateway(
            _HttpBackend(api_url),
            mode="http",
        )
    return BackendGateway(_LocalBackend(), mode="local")
