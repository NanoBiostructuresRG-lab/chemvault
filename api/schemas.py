# SPDX-License-Identifier: LGPL-3.0-or-later
from typing import Any

from pydantic import BaseModel, Field

from services.job_models import JobStatus


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


class HarmonsmileJobRequest(BaseModel):
    table_name: str = Field(min_length=1)
    cid_column: str = Field(min_length=1)


class JobStatusResponse(BaseModel):
    job_id: str
    job_type: str
    status: JobStatus
    database_id: str
    stage: str
    progress: float = Field(ge=0.0, le=1.0)
    message: str | None
    created_at: str
    updated_at: str
    started_at: str | None
    finished_at: str | None
    error: str | None
    result: dict[str, Any] | None
    cancellable: bool


class RecoveredJobResponse(JobStatusResponse):
    table_name: str


class ScientificRuntimeActivationResponse(BaseModel):
    database_id: str
    recovered_jobs: list[RecoveredJobResponse]
