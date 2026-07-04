# SPDX-License-Identifier: LGPL-3.0-or-later
"""Streamlit-independent state cycle for the HARMONSMILE command UI."""
import time

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
HARMONSMILE_POLL_INTERVAL_SECONDS = 0.5
HARMONSMILE_MAX_POLL_ATTEMPTS = 3600


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
    status_callback=None,
    sleep_callback=time.sleep,
):
    """Launch, poll HTTP jobs when needed, and always close the UI state."""
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
        if status_callback is not None:
            status_callback(status)

        if getattr(gateway, "mode", "local") == "http":
            for _attempt in range(HARMONSMILE_MAX_POLL_ATTEMPTS):
                if status.status in TERMINAL_JOB_STATUSES:
                    break
                status = gateway.get_job_status(database_id, status.job_id)
                if status_callback is not None:
                    status_callback(status)
                if status.status not in TERMINAL_JOB_STATUSES:
                    sleep_callback(HARMONSMILE_POLL_INTERVAL_SECONDS)
            else:
                raise TimeoutError(
                    "HARMONSMILE status polling reached its time limit."
                )
        elif status.status not in TERMINAL_JOB_STATUSES:
            raise RuntimeError(
                "Local HARMONSMILE execution returned a non-terminal status."
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
