# SPDX-License-Identifier: LGPL-3.0-or-later
from typing import Any

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str


class DatabaseTablesResponse(BaseModel):
    database_id: str
    tables: list[str]


class OperationRecord(BaseModel):
    operation_type: str
    target_table: str | None
    source_table: str | None
    source_columns: str | None
    created_at: str
    status: str
    details: str | None


class OperationHistoryResponse(BaseModel):
    database_id: str
    operations: list[OperationRecord]


class TableMetricsResponse(BaseModel):
    database_id: str
    table: str
    row_count: int
    group_count: int


class TableColumnSchema(BaseModel):
    cid: int
    name: str
    data_type: str
    not_null: bool
    default_value: Any | None
    primary_key: bool


class TableMetadataResponse(BaseModel):
    database_id: str
    table: str
    columns: list[str]
    row_count: int
    preview_limit: int
    read_only: bool
    table_schema: list[TableColumnSchema] = Field(alias="schema")


class TablePreviewResponse(BaseModel):
    database_id: str
    table: str
    columns: list[str]
    rows: list[dict[str, Any]]
    limit: int
