# SPDX-License-Identifier: LGPL-3.0-or-later
"""Streamlit card for asynchronous Modelability Index analysis."""

import streamlit as st

from clients.backend_gateway import BackendGatewayError, get_backend_gateway
from state_keys import (
    CURRENT_TABLE,
    DATABASE_ID,
    MODELABILITY_FEEDBACK_KIND,
    MODELABILITY_FEEDBACK_MESSAGE,
    MODELABILITY_RUNNING,
)
from ui.modelability_state import (
    TERMINAL_JOB_STATUSES,
    launch_modelability_job,
    modelability_scope_matches,
    poll_modelability_job,
)


def _output_name_matches(table_name, source_table):
    base_name = f"{source_table}_structure_consolidated"
    if table_name == base_name:
        return True
    numbered_prefix = f"{base_name}_"
    if not table_name.startswith(numbered_prefix):
        return False
    suffix = table_name.removeprefix(numbered_prefix)
    return suffix.isdigit() and int(suffix) >= 2


def source_is_eligible(table_name, metadata, source_metadata):
    source_table = metadata.source_table or ""
    return (
        metadata.origin == "structure_consolidation"
        and source_table.startswith("activity_subset_")
        and source_table != "activity_subset_"
        and _output_name_matches(table_name, source_table)
        and source_metadata is not None
        and source_metadata.origin == "structured_activity_filtered_subset"
        and source_metadata.source_table == "compound_activities"
    )


def check_eligibility(gateway, database_id, table_name):
    try:
        metadata = gateway.get_table_metadata(database_id, table_name)
        source_table = metadata.source_table or ""
        if (
            metadata.origin != "structure_consolidation"
            or not source_table.startswith("activity_subset_")
            or source_table == "activity_subset_"
            or not _output_name_matches(table_name, source_table)
        ):
            return False, None
        source_metadata = gateway.get_table_metadata(database_id, source_table)
    except BackendGatewayError as error:
        return False, error
    return source_is_eligible(table_name, metadata, source_metadata), None


def refresh_status_once(database_id, table_name, gateway=None):
    gateway = gateway or get_backend_gateway()
    status = poll_modelability_job(
        st.session_state,
        gateway,
        database_id,
        table_name,
    )
    if status is not None and status.status not in TERMINAL_JOB_STATUSES:
        st.progress(min(max(status.progress, 0.0), 1.0))
        st.caption(status.message or "Modelability Index is running in the backend.")
    elif (
        modelability_scope_matches(st.session_state, database_id, table_name)
        and st.session_state.get(MODELABILITY_RUNNING, False)
    ):
        st.caption("Modelability Index status is temporarily unavailable; retrying.")
    return status


@st.fragment(run_every="2s")
def render_job_status(database_id, table_name):
    status = refresh_status_once(database_id, table_name)
    if status is not None and status.status in TERMINAL_JOB_STATUSES:
        st.rerun()


def render_modelability_card():
    database_id = st.session_state.get(DATABASE_ID, "")
    table_name = st.session_state.get(CURRENT_TABLE, "")
    gateway = get_backend_gateway() if database_id and table_name else None
    eligible, eligibility_error = (False, None)
    if gateway is not None:
        eligible, eligibility_error = check_eligibility(
            gateway,
            database_id,
            table_name,
        )

    scope_matches = modelability_scope_matches(
        st.session_state,
        database_id,
        table_name,
    )
    running = scope_matches and st.session_state.get(MODELABILITY_RUNNING, False)
    with st.container(border=True):
        st.markdown("**MODELABILITY INDEX**")
        run_requested = st.button(
            "Run",
            key="curate_run_modelability_index",
            disabled=not eligible or running,
        )
        if not database_id:
            st.caption("Load or select a database to enable Modelability Index.")
        elif not table_name:
            st.caption("Select an active table to enable Modelability Index.")
        elif eligibility_error is not None:
            st.error(
                "Modelability Index eligibility could not be checked: "
                f"{eligibility_error}"
            )
        elif not eligible:
            st.caption(
                "Select an ACTIVITY LABELS consolidated activity_subset table "
                "to enable Modelability Index."
            )

        if scope_matches:
            kind = st.session_state.get(MODELABILITY_FEEDBACK_KIND, "")
            message = st.session_state.get(MODELABILITY_FEEDBACK_MESSAGE, "")
            if kind == "success" and message:
                st.caption(message)
            elif kind == "error" and message:
                st.error(message)
            elif kind == "warning" and message:
                st.warning(message)

            if running:
                render_job_status(database_id, table_name)

        if run_requested:
            with st.spinner("Starting Modelability Index through the backend..."):
                launch_modelability_job(
                    st.session_state,
                    gateway,
                    database_id,
                    table_name,
                )
            st.rerun()
