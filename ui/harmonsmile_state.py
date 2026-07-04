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


def execute_harmonsmile_command(
    session_state,
    gateway,
    database_id,
    table_name,
    cid_column,
    refresh_callback,
):
    """Execute the synchronous command and always close its UI state cycle."""
    session_state[HARMONSMILE_RUNNING] = True
    session_state[HARMONSMILE_JOB_ID] = ""
    _set_feedback(session_state, "", "")

    try:
        status = gateway.launch_harmonsmile_job(
            database_id,
            table_name,
            cid_column,
        )
        session_state[HARMONSMILE_JOB_ID] = status.job_id

        if status.status not in TERMINAL_JOB_STATUSES:
            raise RuntimeError(
                "HARMONSMILE backend returned a non-terminal status "
                f"('{status.status.value}') for a synchronous command."
            )

        if status.status == JobStatus.COMPLETED:
            refresh_callback(session_state)
            _set_feedback(
                session_state,
                "success",
                _success_message(table_name, status.result or {}),
            )
        else:
            _set_feedback(
                session_state,
                "error",
                status.error or status.message or "HARMONSMILE failed.",
            )
        return status
    except Exception as error:
        if getattr(gateway, "mode", "local") == "http":
            message = f"CHEMVAULT backend API is not available: {error}"
        else:
            message = f"HARMONSMILE could not be completed: {error}"
        _set_feedback(session_state, "error", message)
        return None
    finally:
        clear_harmonsmile_runtime(session_state)
