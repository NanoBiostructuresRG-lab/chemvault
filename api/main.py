# SPDX-License-Identifier: LGPL-3.0-or-later
from typing import Annotated

from fastapi import FastAPI, HTTPException, Path, Query
from fastapi.responses import Response

from api.schemas import (
    DatabaseTablesResponse,
    HealthResponse,
    HarmonsmileJobRequest,
    JobStatusResponse,
    OperationHistoryResponse,
    TableMetadataResponse,
    TableMetricsResponse,
    TablePreviewResponse,
)
from application.harmonsmile_jobs import (
    JobNotFoundError,
    get_harmonsmile_job_status,
    launch_harmonsmile_job,
)
from application.database_use_cases import (
    DatabaseNotFoundError,
    InvalidColumnError,
    TableNotFoundError,
    get_table_metrics,
    get_operation_history,
    get_table_schema,
    get_table_state,
    list_database_tables,
)
from application.table_use_cases import (
    export_table_csv,
    preview_selected_columns,
)


app = FastAPI(title="ChemVault API", version="0.1.0")

DatabaseId = Annotated[
    str,
    Path(min_length=1, pattern=r"^[A-Za-z0-9_-]+$"),
]
TableName = Annotated[str, Path(min_length=1)]


def _not_found(error):
    return HTTPException(status_code=404, detail=str(error))


def _table_state_or_404(database_id, table_name):
    try:
        return get_table_state(database_id, table_name)
    except (DatabaseNotFoundError, TableNotFoundError) as error:
        raise _not_found(error) from error


@app.get("/health", response_model=HealthResponse)
def health():
    return HealthResponse(status="ok")


@app.post(
    "/databases/{database_id}/jobs/harmonsmile",
    response_model=JobStatusResponse,
    status_code=201,
)
def launch_harmonsmile(
    database_id: DatabaseId,
    request: HarmonsmileJobRequest,
):
    try:
        return launch_harmonsmile_job(
            database_id,
            request.table_name,
            request.cid_column,
        )
    except (DatabaseNotFoundError, TableNotFoundError) as error:
        raise _not_found(error) from error
    except InvalidColumnError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.get(
    "/databases/{database_id}/jobs/{job_id}",
    response_model=JobStatusResponse,
)
def job_status(database_id: DatabaseId, job_id: str):
    try:
        return get_harmonsmile_job_status(database_id, job_id)
    except (DatabaseNotFoundError, JobNotFoundError) as error:
        raise _not_found(error) from error


@app.get(
    "/databases/{database_id}/tables",
    response_model=DatabaseTablesResponse,
)
def database_tables(database_id: DatabaseId):
    try:
        tables = list_database_tables(database_id)
    except DatabaseNotFoundError as error:
        raise _not_found(error) from error
    return DatabaseTablesResponse(database_id=database_id, tables=tables)


@app.get(
    "/databases/{database_id}/operations",
    response_model=OperationHistoryResponse,
)
def database_operations(database_id: DatabaseId):
    try:
        operations = get_operation_history(database_id)
    except DatabaseNotFoundError as error:
        raise _not_found(error) from error
    return OperationHistoryResponse(
        database_id=database_id,
        operations=list(operations),
    )


@app.get(
    "/databases/{database_id}/tables/{table_name}/metrics",
    response_model=TableMetricsResponse,
)
def table_metrics(
    database_id: DatabaseId,
    table_name: TableName,
    group_column: Annotated[str, Query()] = "",
):
    try:
        metrics = get_table_metrics(database_id, table_name, group_column)
    except (DatabaseNotFoundError, TableNotFoundError) as error:
        raise _not_found(error) from error
    except InvalidColumnError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return TableMetricsResponse(
        database_id=database_id,
        table=table_name,
        row_count=metrics.row_count,
        group_count=metrics.group_count,
    )


@app.get(
    "/databases/{database_id}/tables/{table_name}/metadata",
    response_model=TableMetadataResponse,
)
def table_metadata(
    database_id: DatabaseId,
    table_name: TableName,
):
    state = _table_state_or_404(database_id, table_name)
    try:
        metrics = get_table_metrics(database_id, table_name, "")
        schema = get_table_schema(database_id, table_name)
    except (DatabaseNotFoundError, TableNotFoundError) as error:
        raise _not_found(error) from error
    return TableMetadataResponse(
        database_id=database_id,
        table=table_name,
        columns=list(state.headers),
        row_count=metrics.row_count,
        preview_limit=10,
        read_only=True,
        schema=list(schema),
    )


@app.get(
    "/databases/{database_id}/tables/{table_name}/preview",
    response_model=TablePreviewResponse,
)
def table_preview(
    database_id: DatabaseId,
    table_name: TableName,
    columns: Annotated[list[str] | None, Query()] = None,
):
    state = _table_state_or_404(database_id, table_name)
    selected_columns = list(columns or state.headers)
    invalid_columns = [
        column
        for column in selected_columns
        if column not in state.headers
    ]
    if invalid_columns:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown columns: {', '.join(invalid_columns)}",
        )

    preview = preview_selected_columns(
        database_id,
        table_name,
        state.headers,
        selected_columns,
    )
    records = preview.astype(object).where(preview.notna(), None).to_dict(
        orient="records"
    )
    return TablePreviewResponse(
        database_id=database_id,
        table=table_name,
        columns=selected_columns,
        rows=records,
        limit=10,
    )


@app.get(
    "/databases/{database_id}/tables/{table_name}/export",
    response_class=Response,
    responses={200: {"content": {"text/csv": {}}}},
)
def table_export(
    database_id: DatabaseId,
    table_name: TableName,
    columns: Annotated[list[str] | None, Query()] = None,
):
    try:
        csv_bytes = export_table_csv(database_id, table_name, columns)
    except (DatabaseNotFoundError, TableNotFoundError) as error:
        raise _not_found(error) from error
    except InvalidColumnError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return Response(
        content=csv_bytes,
        media_type="text/csv",
        headers={
            "Content-Disposition": (
                'attachment; filename="chemvault_table_export.csv"'
            )
        },
    )
