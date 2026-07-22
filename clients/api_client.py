# SPDX-License-Identifier: LGPL-3.0-or-later
from typing import Any
from email.message import Message
from urllib.parse import quote

import requests


DEFAULT_BASE_URL = "http://127.0.0.1:8000"


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

    def _get_download(self, path: str, params=None) -> tuple[bytes, str]:
        response = self._get_response(path, params=params)
        disposition = response.headers.get("Content-Disposition", "")
        message = Message()
        message["Content-Disposition"] = disposition
        filename = message.get_filename()
        if not filename:
            raise ChemVaultApiError(
                "CHEMVAULT API download response did not include a filename."
            )
        return response.content, filename

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

    def activate_scientific_runtime(self, database_id: str) -> dict[str, Any]:
        database_id = self._segment(database_id)
        return self._post(
            f"/databases/{database_id}/scientific-runtime/activate",
            timeout=self.timeout,
        )

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

    def export_modelability_fingerprints(
        self,
        database_id: str,
        table_name: str,
        analysis_identity: str,
    ) -> tuple[bytes, str]:
        database_id = self._segment(database_id)
        table_name = self._segment(table_name)
        return self._get_download(
            f"/databases/{database_id}/tables/{table_name}/"
            "modelability-index/fingerprints/export",
            params={"analysis_identity": analysis_identity},
        )

    def consolidate_structure_table(
        self,
        database_id: str,
        source_table: str,
    ) -> dict[str, Any]:
        database_id = self._segment(database_id)
        source_table = self._segment(source_table)
        return self._post(
            f"/databases/{database_id}/tables/{source_table}/"
            "structure-consolidation",
            timeout=self.timeout,
        )

    def launch_harmonsmile_job(
        self,
        database_id: str,
        table_name: str,
        cid_column: str,
    ) -> dict[str, Any]:
        return self.launch_scientific_job(
            database_id,
            "harmonsmile",
            {"table_name": table_name, "cid_column": cid_column},
        )

    def launch_scientific_job(
        self,
        database_id: str,
        job_type: str,
        request: dict[str, Any],
    ) -> dict[str, Any]:
        database_id = self._segment(database_id)
        job_type = self._segment(job_type)
        return self._post(
            f"/databases/{database_id}/jobs/{job_type}",
            json=request,
            timeout=self.timeout,
        )

    def get_job_status(
        self,
        database_id: str,
        job_id: str,
    ) -> dict[str, Any]:
        database_id = self._segment(database_id)
        job_id = self._segment(job_id)
        return self._get(f"/databases/{database_id}/jobs/{job_id}")

    def find_active_harmonsmile_job(
        self,
        database_id: str,
        table_name: str,
    ) -> dict[str, Any] | None:
        database_id = self._segment(database_id)
        return self._get(
            f"/databases/{database_id}/jobs/harmonsmile/active",
            params={"table_name": table_name},
        )
