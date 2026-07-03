# SPDX-License-Identifier: LGPL-3.0-or-later
from typing import Any

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str


class DatabaseTablesResponse(BaseModel):
    database_id: str
    tables: list[str]


class TableMetricsResponse(BaseModel):
    database_id: str
    table: str
    row_count: int
    group_count: int


class TableMetadataResponse(BaseModel):
    database_id: str
    table: str
    columns: list[str]
    row_count: int
    preview_limit: int
    read_only: bool


class TablePreviewResponse(BaseModel):
    database_id: str
    table: str
    columns: list[str]
    rows: list[dict[str, Any]]
    limit: int
