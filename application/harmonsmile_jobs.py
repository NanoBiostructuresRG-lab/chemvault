# SPDX-License-Identifier: LGPL-3.0-or-later
"""Application orchestration for the minimal HARMONSMILE job runtime."""
from collections.abc import Callable

from application.curation_use_cases import run_harmonsmile
from application.database_use_cases import (
    DatabaseNotFoundError,
    InvalidColumnError,
    TableNotFoundError,
    get_table_state,
    list_database_tables,
)
from application.job_contracts import JobStatusContract, job_status_from_record
from services.database_core import get_connection
from services.db_audit import register_operation
from services.harmonsmile_cache import (
    merge_harmonsmile_cache_to_table,
    prepare_harmonsmile_job,
    run_harmonsmile_chunks,
)
from services.job_models import JobType
from services.job_store import JobStore


class JobNotFoundError(LookupError):
    """Raised when a job does not exist in the requested database."""


def _register_operation_safely(connection, **kwargs):
    """Keep audit failures from leaving the persisted job active forever."""
    try:
        register_operation(connection, "harmonsmile_run", **kwargs)
    except Exception:
        pass


def _result_summary(prepared, run_result, merged_rows, output_columns):
    return {
        "source_table": prepared["source_table"],
        "cid_column": prepared["cid_column"],
        "total_cids": prepared["total_cids"],
        "cached_cids": len(prepared["cached_cids"]),
        "pending_cids": len(prepared["pending_cids"]),
        "invalid_cids": len(prepared["invalid_cids"]),
        "processed_cids": len(run_result["processed_cids"]),
        "failed_cids": len(run_result["failed_cids"]),
        "missing_cids": len(run_result.get("missing_cids", [])),
        "merged_rows": merged_rows,
        "output_columns": output_columns,
    }


def launch_harmonsmile_job(
    database_id: str,
    table_name: str,
    cid_column: str,
    *,
    runner: Callable = run_harmonsmile,
    progress_callback: Callable | None = None,
) -> JobStatusContract:
    """Run HARMONSMILE synchronously for the local gateway."""
    created = create_harmonsmile_job(database_id, table_name, cid_column)
    return execute_harmonsmile_job(
        database_id,
        created.job_id,
        runner=runner,
        progress_callback=progress_callback,
    )


def create_harmonsmile_job(
    database_id: str,
    table_name: str,
    cid_column: str,
) -> JobStatusContract:
    """Validate and persist a queued HARMONSMILE job without executing it."""
    state = get_table_state(database_id, table_name)
    if cid_column not in state.headers:
        raise InvalidColumnError(f"Unknown column: {cid_column}")

    connection = get_connection(database_id)
    try:
        store = JobStore(connection)
        request_metadata = {
            "table_name": table_name,
            "cid_column": cid_column,
        }
        record = store.create_job(
            job_type=JobType.HARMONSMILE,
            database_id=database_id,
            metadata=request_metadata,
        )
        record = store.update_progress(
            record.job_id,
            "queued",
            0.0,
            "HARMONSMILE job queued",
            request_metadata,
        )
        return job_status_from_record(record)
    finally:
        connection.close()


def execute_harmonsmile_job(
    database_id: str,
    job_id: str,
    *,
    runner: Callable = run_harmonsmile,
    progress_callback: Callable | None = None,
) -> JobStatusContract:
    """Execute a previously queued HARMONSMILE job."""
    connection = get_connection(database_id)
    store = JobStore(connection)
    record = store.get_job(job_id)
    if record is None or record.database_id != database_id:
        connection.close()
        raise JobNotFoundError(
            f"Job '{job_id}' was not found in database '{database_id}'."
        )

    request_metadata = dict(record.metadata)
    table_name = request_metadata["table_name"]
    cid_column = request_metadata["cid_column"]
    started = store.start_job(job_id)
    if started is None:
        current = store.get_job(job_id)
        connection.close()
        return job_status_from_record(current)

    try:
        state = get_table_state(database_id, table_name)
        prepared = prepare_harmonsmile_job(connection, table_name, cid_column)
        store.update_progress(
            job_id,
            "prepared",
            0.05,
            "HARMONSMILE input prepared",
            request_metadata,
        )

        def report_progress(snapshot):
            total = snapshot.get("total_chunks", 0)
            current = snapshot.get("current_chunk", 0)
            progress = 0.1 if total == 0 else 0.1 + (0.75 * current / total)
            store.update_progress(
                job_id,
                snapshot.get("status", "running"),
                min(progress, 0.85),
                f"HARMONSMILE chunk {current}/{total}",
                request_metadata,
            )
            if progress_callback is not None:
                progress_callback(snapshot)

        run_result = run_harmonsmile_chunks(
            connection,
            prepared["pending_cids"],
            runner,
            progress_callback=report_progress,
        )
        before_columns = set(state.headers)
        merged_rows = merge_harmonsmile_cache_to_table(
            connection,
            table_name,
            cid_column,
            cids=prepared["valid_cids"],
        )
        after_state = get_table_state(database_id, table_name)
        output_columns = [
            column for column in after_state.headers if column not in before_columns
        ]
        result = _result_summary(
            prepared, run_result, merged_rows, output_columns
        )
        details = (
            "Processed HARMONSMILE with cache/chunks. "
            f"Cached: {result['cached_cids']}; Pending: {result['pending_cids']}; "
            f"Merged rows: {merged_rows}; Failed: {result['failed_cids']}; "
            f"Missing: {result['missing_cids']}."
        )

        if run_result["status"] != "success":
            error = run_result.get("error_message") or "HARMONSMILE failed"
            _register_operation_safely(
                connection,
                target_table=table_name,
                source_columns=[cid_column],
                output_columns=output_columns,
                created_by="launch_harmonsmile_job",
                status="failed",
                details=f"{details} Error: {error}",
            )
            final = store.fail_job(
                job_id, error, {**request_metadata, "result": result}
            )
        else:
            _register_operation_safely(
                connection,
                target_table=table_name,
                source_columns=[cid_column],
                output_columns=output_columns,
                created_by="launch_harmonsmile_job",
                details=details,
            )
            store.update_progress(
                job_id,
                "completed",
                0.95,
                "HARMONSMILE results merged",
                {**request_metadata, "result": result},
            )
            final = store.complete_job(
                job_id, {**request_metadata, "result": result}
            )
    except Exception as error:
        _register_operation_safely(
            connection,
            target_table=table_name,
            source_columns=[cid_column],
            created_by="launch_harmonsmile_job",
            status="failed",
            details=str(error),
        )
        final = store.fail_job(job_id, str(error), request_metadata)

    result = job_status_from_record(final)
    connection.close()
    return result


def get_harmonsmile_job_status(
    database_id: str,
    job_id: str,
) -> JobStatusContract:
    """Return a job only from the database named in the route."""
    list_database_tables(database_id)
    connection = get_connection(database_id)
    try:
        record = JobStore(connection).get_job(job_id)
    finally:
        connection.close()
    if record is None or record.database_id != database_id:
        raise JobNotFoundError(
            f"Job '{job_id}' was not found in database '{database_id}'."
        )
    return job_status_from_record(record)
