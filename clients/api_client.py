# SPDX-License-Identifier: LGPL-3.0-or-later
from typing import Any
from urllib.parse import quote

import requests


DEFAULT_BASE_URL = "http://127.0.0.1:8000"
HARMONSMILE_REQUEST_TIMEOUT = (5.0, 1800.0)


class ChemVaultApiError(RuntimeError):
    """Raised when the CHEMVAULT API cannot satisfy a request."""


class ChemVaultApiClient:
    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 10.0,
        session: requests.Session | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = session or requests.Session()

    def _get_response(self, path: str, params=None) -> requests.Response:
        url = f"{self.base_url}{path}"
        try:
            response = self.session.get(
                url,
                params=params,
                timeout=self.timeout,
            )
        except requests.RequestException as error:
            raise ChemVaultApiError(
                f"CHEMVAULT API request failed: {error}"
            ) from error

        try:
            response.raise_for_status()
        except requests.HTTPError as error:
            detail = response.text
            try:
                detail = response.json().get("detail", detail)
            except (ValueError, AttributeError):
                pass
            message = f"CHEMVAULT API returned HTTP {response.status_code}"
            if detail:
                message = f"{message}: {detail}"
            raise ChemVaultApiError(message) from error

        return response

    def _get(self, path: str, params=None) -> dict[str, Any]:
        response = self._get_response(path, params=params)

        try:
            return response.json()
        except ValueError as error:
            raise ChemVaultApiError(
                "CHEMVAULT API returned an invalid JSON response."
            ) from error

    def _get_bytes(self, path: str, params=None) -> bytes:
        return self._get_response(path, params=params).content

    def _post(self, path: str, json=None, timeout=10.0) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        try:
            response = self.session.post(
                url,
                json=json,
                timeout=timeout,
            )
        except requests.RequestException as error:
            raise ChemVaultApiError(
                f"CHEMVAULT API request failed: {error}"
            ) from error
        try:
            response.raise_for_status()
        except requests.HTTPError as error:
            detail = response.text
            try:
                detail = response.json().get("detail", detail)
            except (ValueError, AttributeError):
                pass
            message = f"CHEMVAULT API returned HTTP {response.status_code}"
            if detail:
                message = f"{message}: {detail}"
            raise ChemVaultApiError(message) from error
        try:
            return response.json()
        except ValueError as error:
            raise ChemVaultApiError(
                "CHEMVAULT API returned an invalid JSON response."
            ) from error

    @staticmethod
    def _segment(value: str) -> str:
        return quote(value, safe="")

    def health(self) -> dict[str, Any]:
        return self._get("/health")

    def list_tables(self, database_id: str) -> dict[str, Any]:
        database_id = self._segment(database_id)
        return self._get(f"/databases/{database_id}/tables")

    def get_operation_history(self, database_id: str) -> dict[str, Any]:
        database_id = self._segment(database_id)
        return self._get(f"/databases/{database_id}/operations")

    def get_table_metadata(
        self,
        database_id: str,
        table_name: str,
    ) -> dict[str, Any]:
        database_id = self._segment(database_id)
        table_name = self._segment(table_name)
        return self._get(
            f"/databases/{database_id}/tables/{table_name}/metadata"
        )

    def get_table_metrics(
        self,
        database_id: str,
        table_name: str,
        group_column: str = "",
    ) -> dict[str, Any]:
        database_id = self._segment(database_id)
        table_name = self._segment(table_name)
        return self._get(
            f"/databases/{database_id}/tables/{table_name}/metrics",
            params={"group_column": group_column},
        )

    def preview_table(
        self,
        database_id: str,
        table_name: str,
        columns: list[str] | None = None,
    ) -> dict[str, Any]:
        database_id = self._segment(database_id)
        table_name = self._segment(table_name)
        params = [("columns", column) for column in columns] if columns else None
        return self._get(
            f"/databases/{database_id}/tables/{table_name}/preview",
            params=params,
        )

    def export_table(
        self,
        database_id: str,
        table_name: str,
        columns: list[str] | None = None,
    ) -> bytes:
        database_id = self._segment(database_id)
        table_name = self._segment(table_name)
        params = (
            [("columns", column) for column in columns]
            if columns
            else None
        )
        return self._get_bytes(
            f"/databases/{database_id}/tables/{table_name}/export",
            params=params,
        )

    def launch_harmonsmile_job(
        self,
        database_id: str,
        table_name: str,
        cid_column: str,
    ) -> dict[str, Any]:
        database_id = self._segment(database_id)
        return self._post(
            f"/databases/{database_id}/jobs/harmonsmile",
            json={"table_name": table_name, "cid_column": cid_column},
            timeout=HARMONSMILE_REQUEST_TIMEOUT,
        )

    def get_job_status(
        self,
        database_id: str,
        job_id: str,
    ) -> dict[str, Any]:
        database_id = self._segment(database_id)
        job_id = self._segment(job_id)
        return self._get(f"/databases/{database_id}/jobs/{job_id}")
