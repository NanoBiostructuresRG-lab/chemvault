# SPDX-License-Identifier: LGPL-3.0-or-later
"""Streamlit-independent state cycle for Modelability Index jobs."""

from __future__ import annotations

import csv
import io

from services.job_models import JobStatus
from state_keys import (
    MODELABILITY_FEEDBACK_KIND,
    MODELABILITY_FEEDBACK_MESSAGE,
    MODELABILITY_JOB_DATABASE_ID,
    MODELABILITY_JOB_ID,
    MODELABILITY_JOB_TABLE_NAME,
    MODELABILITY_RESULT,
    MODELABILITY_RUNNING,
)


TERMINAL_JOB_STATUSES = {
    JobStatus.COMPLETED,
    JobStatus.FAILED,
    JobStatus.CANCELLED,
}
DIAGNOSTIC_COLUMNS = (
    "smiles",
    "outcome",
    "nearest_neighbor_smiles",
    "nearest_neighbor_outcome",
    "tanimoto_similarity",
    "concordant",
)


def modelability_scope_matches(session_state, database_id, table_name) -> bool:
    return (
        session_state.get(MODELABILITY_JOB_DATABASE_ID, "") == database_id
        and session_state.get(MODELABILITY_JOB_TABLE_NAME, "") == table_name
    )


def _set_scope(session_state, database_id, table_name) -> None:
    session_state[MODELABILITY_JOB_DATABASE_ID] = database_id
    session_state[MODELABILITY_JOB_TABLE_NAME] = table_name


def _apply_status(session_state, status, *, restored=False) -> None:
    session_state[MODELABILITY_JOB_ID] = status.job_id
    if status.status == JobStatus.COMPLETED:
        session_state[MODELABILITY_RUNNING] = False
        session_state[MODELABILITY_RESULT] = status.result or {}
        session_state[MODELABILITY_FEEDBACK_KIND] = "success"
        session_state[MODELABILITY_FEEDBACK_MESSAGE] = (
            "Result restored from persisted analysis."
            if restored
            else "Modelability Index calculation completed."
        )
    elif status.status in {JobStatus.FAILED, JobStatus.CANCELLED}:
        session_state[MODELABILITY_RUNNING] = False
        session_state[MODELABILITY_RESULT] = None
        session_state[MODELABILITY_FEEDBACK_KIND] = "error"
        session_state[MODELABILITY_FEEDBACK_MESSAGE] = (
            status.error
            or status.message
            or "Modelability Index calculation failed."
        )
    else:
        session_state[MODELABILITY_RUNNING] = True


def launch_modelability_job(
    session_state,
    gateway,
    database_id,
    table_name,
):
    """Launch or deduplicate one scoped job and return immediately."""
    _set_scope(session_state, database_id, table_name)
    session_state[MODELABILITY_JOB_ID] = ""
    session_state[MODELABILITY_RUNNING] = True
    session_state[MODELABILITY_RESULT] = None
    session_state[MODELABILITY_FEEDBACK_KIND] = ""
    session_state[MODELABILITY_FEEDBACK_MESSAGE] = ""
    try:
        status = gateway.launch_scientific_job(
            database_id,
            "modelability_index",
            {"table_name": table_name},
        )
    except Exception as error:
        session_state[MODELABILITY_RUNNING] = False
        session_state[MODELABILITY_FEEDBACK_KIND] = "error"
        session_state[MODELABILITY_FEEDBACK_MESSAGE] = (
            f"Modelability Index could not be started: {error}"
        )
        return None
    _apply_status(
        session_state,
        status,
        restored=status.status == JobStatus.COMPLETED,
    )
    return status


def poll_modelability_job(
    session_state,
    gateway,
    database_id,
    table_name,
):
    """Read one status snapshot only when the persisted scope matches."""
    job_id = session_state.get(MODELABILITY_JOB_ID, "")
    if (
        not job_id
        or not session_state.get(MODELABILITY_RUNNING, False)
        or not modelability_scope_matches(
            session_state,
            database_id,
            table_name,
        )
    ):
        return None
    try:
        status = gateway.get_job_status(database_id, job_id)
    except Exception as error:
        session_state[MODELABILITY_FEEDBACK_KIND] = "warning"
        session_state[MODELABILITY_FEEDBACK_MESSAGE] = (
            "Modelability Index status is temporarily unavailable; "
            f"retrying: {error}"
        )
        return None
    _apply_status(session_state, status)
    return status


def diagnostics_csv(result: dict[str, object]) -> str:
    """Serialize diagnostics in memory without persisting an artifact."""
    output = io.StringIO(newline="")
    writer = csv.DictWriter(
        output,
        fieldnames=DIAGNOSTIC_COLUMNS,
        extrasaction="ignore",
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerows(result.get("diagnostics", ()))
    return output.getvalue()
