# SPDX-License-Identifier: LGPL-3.0-or-later
import streamlit as st

from clients.backend_gateway import BackendGatewayError, get_backend_gateway
from services.job_models import JobStatus
from ui.state_keys import (
    CURRENT_TABLE,
    DATABASE_ID,
    INPUT_PROTEIN,
    PUBCHEM_JOB_COMPLETION_HANDLED,
    PUBCHEM_JOB_ID,
    SELECTED_PROTEINS,
)
from ui.session_state import refresh_database_state


def _is_database_locked_error(error):
    message = str(error).lower()
    return "database is locked" in message or "database table is locked" in message


def _clear_pubchem_job_state():
    st.session_state[PUBCHEM_JOB_ID] = ""
    st.session_state[PUBCHEM_JOB_COMPLETION_HANDLED] = False
    st.session_state[SELECTED_PROTEINS] = []


def _render_job_dialog_exit(label):
    if st.button(label, key="pubchem_job_dialog_exit"):
        _clear_pubchem_job_state()
        st.rerun()


def _render_job_snapshot(job):
    st.info(
        "Building the protein database. This can take a few minutes "
        "for targets with many BioAssays."
    )
    st.progress(min(max(job.progress, 0.0), 1.0))
    stage = job.stage.replace("_", " ").title() if job.stage else "Preparing"
    st.caption(
        f"Status: {job.status.value.title()} · Stage: {stage}"
    )
    if job.message:
        st.write(job.message)


def _render_terminal_pubchem_job(database_id, job, gateway=None):
    _render_job_snapshot(job)
    if job.status == JobStatus.CANCELLED:
        st.info("Protein search cancelled.")
        _render_job_dialog_exit("Close")
        return

    if job.status == JobStatus.FAILED:
        message = job.error or "Unknown backend error."
        st.error(f"The protein search failed: {message}")
        _render_job_dialog_exit("Close")
        return

    if (
        job.status == JobStatus.COMPLETED
        and not st.session_state.get(
            PUBCHEM_JOB_COMPLETION_HANDLED,
            False,
        )
    ):
        gateway = gateway or get_backend_gateway()
        try:
            gateway.finalize_pubchem_protein_search(
                database_id,
                job.job_id,
            )
        except BackendGatewayError as error:
            st.error(
                "The completed search could not be registered: "
                f"{error}"
            )
            return
        st.session_state[PUBCHEM_JOB_COMPLETION_HANDLED] = True
        refresh_database_state(st.session_state)

    if job.status == JobStatus.COMPLETED:
        st.success("Protein search completed.")
        _render_job_dialog_exit("Continue")


@st.fragment(run_every="2s")
def render_pubchem_job_status():
    job_id = st.session_state.get(PUBCHEM_JOB_ID, "")
    database_id = st.session_state.get(DATABASE_ID, "")
    if not job_id or not database_id:
        return

    gateway = get_backend_gateway()
    try:
        job = gateway.get_pubchem_protein_search_status(
            database_id,
            job_id,
        )
    except BackendGatewayError as error:
        if _is_database_locked_error(error):
            st.info(
                "The protein search database is busy. "
                "ChemVault will retry automatically."
            )
        else:
            st.info(
                "The protein search status is temporarily unavailable. "
                "ChemVault will retry automatically."
            )
        return

    if job.status not in {JobStatus.PENDING, JobStatus.RUNNING}:
        st.rerun()
    _render_job_snapshot(job)
    if (
        job.cancellable
        and st.button("Cancel search", key="pubchem_job_cancel")
    ):
        try:
            cancelled = gateway.cancel_pubchem_protein_search(
                database_id,
                job_id,
            )
        except BackendGatewayError as error:
            st.error(f"The protein search could not be cancelled: {error}")
            return
        if cancelled.status == JobStatus.CANCELLED:
            st.info(
                "Cancellation requested. The worker will stop at the "
                "next safe checkpoint."
            )
        else:
            st.info("The protein search is no longer active.")
        st.rerun()


@st.dialog("Select Proteins", dismissible=False)
def select_proteins():
    database_id = st.session_state.get(DATABASE_ID, "")
    gateway = get_backend_gateway()

    if st.session_state.get(PUBCHEM_JOB_ID, ""):
        job_id = st.session_state[PUBCHEM_JOB_ID]
        try:
            job = gateway.get_pubchem_protein_search_status(
                database_id,
                job_id,
            )
        except BackendGatewayError as error:
            if _is_database_locked_error(error):
                st.info(
                    "The protein search database is busy while the "
                    "worker finishes writing. ChemVault will retry "
                    "automatically."
                )
                render_pubchem_job_status()
                return
            st.error(
                "The protein search status could not be read: "
                f"{error}"
            )
            _render_job_dialog_exit("Close")
            return
        if job.status in {JobStatus.PENDING, JobStatus.RUNNING}:
            render_pubchem_job_status()
        else:
            _render_terminal_pubchem_job(
                database_id,
                job,
                gateway,
            )
        return

    st.write("Search CIDs by BioAssays, using a protein as target.")
    st.text_input(label="Protein", key=INPUT_PROTEIN, value="P34971")
    if st.button("Add to selection"):
        st.session_state[SELECTED_PROTEINS].append(
            st.session_state[INPUT_PROTEIN]
        )
        st.markdown(
            f"Selected proteins: "
            f"{st.session_state[SELECTED_PROTEINS]}."
        )
    if st.button("Confirm selection"):
        if len(st.session_state[SELECTED_PROTEINS]) == 0:
            st.toast("Select at least one protein")
        elif database_id == "":
            st.toast("First, enter a name for your SQL database")
        else:
            st.info(
                "Building the protein database. This can take a few "
                "minutes for targets with many BioAssays."
            )
            st.toast(
                "Building database with proteins: "
                f"{st.session_state[SELECTED_PROTEINS]}"
            )
            try:
                st.session_state[CURRENT_TABLE] = "main"
                job = gateway.launch_pubchem_protein_search(
                    database_id,
                    list(st.session_state[SELECTED_PROTEINS]),
                )
            except BackendGatewayError as error:
                st.error(
                    "The protein search could not be started: "
                    f"{error}"
                )
                return
            st.session_state[PUBCHEM_JOB_ID] = job.job_id
            st.session_state[PUBCHEM_JOB_COMPLETION_HANDLED] = False
            st.rerun(scope="fragment")
            return
        st.rerun()
    if st.button("Cancel"):
        st.session_state[SELECTED_PROTEINS] = []
        st.rerun()
