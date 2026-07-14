# SPDX-License-Identifier: LGPL-3.0-or-later
"""Streamlit-independent state cycle for the HARMONSMILE command UI."""

from services.job_models import JobStatus
from state_keys import (
    HARMONSMILE_FEEDBACK_KIND,
    HARMONSMILE_FEEDBACK_MESSAGE,
    HARMONSMILE_JOB_ID,
    HARMONSMILE_RUNNING,
)


TERMINAL_JOB_STATUSES = {
    JobStatus.COMPLETED,
    JobStatus.FAILED,
    JobStatus.CANCELLED,
}


def clear_harmonsmile_runtime(session_state, *, clear_feedback=False):
    session_state[HARMONSMILE_RUNNING] = False
    session_state[HARMONSMILE_JOB_ID] = ""
    if clear_feedback:
        session_state[HARMONSMILE_FEEDBACK_KIND] = ""
        session_state[HARMONSMILE_FEEDBACK_MESSAGE] = ""


def consume_harmonsmile_feedback(session_state):
    feedback = (
        session_state.get(HARMONSMILE_FEEDBACK_KIND, ""),
        session_state.get(HARMONSMILE_FEEDBACK_MESSAGE, ""),
    )
    session_state[HARMONSMILE_FEEDBACK_KIND] = ""
    session_state[HARMONSMILE_FEEDBACK_MESSAGE] = ""
    return feedback


def _set_feedback(session_state, kind, message):
    session_state[HARMONSMILE_FEEDBACK_KIND] = kind
    session_state[HARMONSMILE_FEEDBACK_MESSAGE] = message


def _success_message(table_name, result):
    processed = result.get("processed_cids", 0)
    merged = result.get("merged_rows", 0)
    return (
        f"HARMONSMILE completed. Updated table '{table_name}'; "
        f"processed {processed} CIDs and merged {merged} rows."
    )


def _apply_terminal_status(
    session_state,
    status,
    table_name,
    refresh_callback,
):
    if status.status == JobStatus.COMPLETED:
        refresh_callback(session_state)
        _set_feedback(
            session_state,
            "success",
            _success_message(table_name, status.result or {}),
        )
    elif status.status == JobStatus.CANCELLED:
        _set_feedback(
            session_state,
            "warning",
            status.message or "HARMONSMILE was cancelled.",
        )
    else:
        _set_feedback(
            session_state,
            "error",
            status.error or status.message or "HARMONSMILE failed.",
        )
    clear_harmonsmile_runtime(session_state)


def sync_harmonsmile_runtime(
    session_state,
    gateway,
    database_id,
    table_name,
    refresh_callback,
    status_callback=None,
):
    """Reattach to an active job or consume its persisted terminal status."""
    job_id = session_state.get(HARMONSMILE_JOB_ID, "")
    try:
        if job_id:
            status = gateway.get_job_status(database_id, job_id)
        else:
            status = gateway.find_active_harmonsmile_job(
                database_id,
                table_name,
            )
        if status is None:
            clear_harmonsmile_runtime(session_state)
            return None

        session_state[HARMONSMILE_JOB_ID] = status.job_id
        if status_callback is not None:
            status_callback(status)
        if status.status in TERMINAL_JOB_STATUSES:
            _apply_terminal_status(
                session_state,
                status,
                table_name,
                refresh_callback,
            )
        else:
            session_state[HARMONSMILE_RUNNING] = True
        return status
    except Exception as error:
        if job_id:
            session_state[HARMONSMILE_RUNNING] = True
            _set_feedback(
                session_state,
                "warning",
                f"HARMONSMILE monitoring is temporarily unavailable: {error}",
            )
        return None


def execute_harmonsmile_command(
    session_state,
    gateway,
    database_id,
    table_name,
    cid_column,
    refresh_callback,
):
    """Launch or reattach and return without monitoring backend execution."""
    session_state[HARMONSMILE_RUNNING] = True
    _set_feedback(session_state, "", "")
    status = None

    try:
        job_id = session_state.get(HARMONSMILE_JOB_ID, "")
        if job_id:
            status = gateway.get_job_status(database_id, job_id)
        else:
            status = gateway.find_active_harmonsmile_job(
                database_id,
                table_name,
            )
            if status is None:
                status = gateway.launch_harmonsmile_job(
                    database_id,
                    table_name,
                    cid_column,
                )
        session_state[HARMONSMILE_JOB_ID] = status.job_id
        if status.status in TERMINAL_JOB_STATUSES:
            _apply_terminal_status(
                session_state,
                status,
                table_name,
                refresh_callback,
            )
        else:
            session_state[HARMONSMILE_RUNNING] = True
        return status
    except Exception as error:
        if session_state.get(HARMONSMILE_JOB_ID, ""):
            session_state[HARMONSMILE_RUNNING] = True
            message = (
                "HARMONSMILE monitoring is temporarily unavailable; "
                f"the backend job may still be running: {error}"
            )
            kind = "warning"
        elif getattr(gateway, "mode", "local") == "http":
            message = f"CHEMVAULT backend API is not available: {error}"
            kind = "error"
        else:
            message = f"HARMONSMILE could not be completed: {error}"
            kind = "error"
        _set_feedback(session_state, kind, message)
        return None
    finally:
        if status is None and not session_state.get(HARMONSMILE_JOB_ID, ""):
            clear_harmonsmile_runtime(session_state)
