# SPDX-License-Identifier: LGPL-3.0-or-later
import sqlite3

import streamlit as st

from services.builders import register_protein_search_build, run_protein_search
from services.database import update_headers
from services.job_models import JobStatus
from services.job_store import (
    ACTIVE_JOB_STATUSES,
    STALE_JOB_ERROR_MESSAGE,
    JobStore,
)
from state_keys import (
    DATABASE_ID,
    INPUT_PROTEIN,
    PUBCHEM_JOB_COMPLETION_HANDLED,
    PUBCHEM_JOB_DB_PATH,
    PUBCHEM_JOB_ID,
    SELECTED_PROTEINS,
)


def _load_pubchem_job(db_path, job_id):
    connection = sqlite3.connect(db_path)
    try:
        store = JobStore(connection)
        store.fail_stale_job(job_id)
        return store.get_job(job_id)
    finally:
        connection.close()


def _is_database_locked_error(error):
    message = str(error).lower()
    return "database is locked" in message or "database table is locked" in message


def _register_completed_pubchem_job(db_path, job):
    connection = sqlite3.connect(db_path)
    try:
        register_protein_search_build(
            connection,
            job.metadata.get("proteins", []),
        )
    finally:
        connection.close()


def _cancel_pubchem_job(db_path, job_id):
    connection = sqlite3.connect(db_path)
    try:
        return JobStore(connection).cancel_job(job_id, "Cancelled by user")
    finally:
        connection.close()


def _clear_pubchem_job_state():
    st.session_state[PUBCHEM_JOB_ID] = ""
    st.session_state[PUBCHEM_JOB_DB_PATH] = ""
    st.session_state[PUBCHEM_JOB_COMPLETION_HANDLED] = False
    st.session_state[SELECTED_PROTEINS] = []


def _render_job_dialog_exit(label):
    if st.button(label, key="pubchem_job_dialog_exit"):
        _clear_pubchem_job_state()
        st.rerun()


def _render_job_snapshot(job):
    st.info("Building the protein database. This can take a few minutes for targets with many BioAssays.")
    st.progress(min(max(job.progress, 0.0), 1.0))
    stage = job.current_stage.replace("_", " ").title() if job.current_stage else "Preparing"
    st.caption(f"Status: {job.status.title()} · Stage: {stage}")
    if job.message:
        st.write(job.message)


def _render_terminal_pubchem_job(db_path, job):
    _render_job_snapshot(job)
    if job.status == JobStatus.CANCELLED.value:
        st.info("Protein search cancelled.")
        _render_job_dialog_exit("Close")
        return

    if job.status == JobStatus.FAILED.value:
        if job.error_message == STALE_JOB_ERROR_MESSAGE:
            st.error(STALE_JOB_ERROR_MESSAGE)
        else:
            st.error(f"The protein search failed: {job.error_message}")
        _render_job_dialog_exit("Close")
        return

    if not st.session_state.get(PUBCHEM_JOB_COMPLETION_HANDLED, False):
        try:
            _register_completed_pubchem_job(db_path, job)
        except Exception as error:
            st.error(f"The completed search could not be registered: {error}")
            return
        st.session_state[PUBCHEM_JOB_COMPLETION_HANDLED] = True
        update_headers()

    st.success("Protein search completed.")
    _render_job_dialog_exit("Continue")


@st.fragment(run_every="2s")
def render_pubchem_job_status():
    job_id = st.session_state.get(PUBCHEM_JOB_ID, "")
    db_path = st.session_state.get(PUBCHEM_JOB_DB_PATH, "")
    if not job_id or not db_path:
        return

    try:
        job = _load_pubchem_job(db_path, job_id)
    except sqlite3.OperationalError as error:
        if _is_database_locked_error(error):
            st.info("The protein search database is busy. ChemVault will retry automatically.")
            return
        st.rerun()
    except Exception:
        st.rerun()
    if job is None:
        st.rerun()

    if job.status not in ACTIVE_JOB_STATUSES:
        st.rerun()
    _render_job_snapshot(job)
    if st.button("Cancel search", key="pubchem_job_cancel"):
        cancelled = _cancel_pubchem_job(db_path, job_id)
        if cancelled is not None:
            st.info("Cancellation requested. The worker will stop at the next safe checkpoint.")
        else:
            st.info("The protein search is no longer active.")
        st.rerun()


@st.dialog("Select Proteins", dismissible=False)
def select_proteins():
    if st.session_state.get(PUBCHEM_JOB_ID, ""):
        job_id = st.session_state[PUBCHEM_JOB_ID]
        db_path = st.session_state.get(PUBCHEM_JOB_DB_PATH, "")
        try:
            job = _load_pubchem_job(db_path, job_id)
        except sqlite3.OperationalError as error:
            if _is_database_locked_error(error):
                st.info("The protein search database is busy while the worker finishes writing. ChemVault will retry automatically.")
                render_pubchem_job_status()
                return
            st.error(f"The protein search status could not be read: {error}")
            _render_job_dialog_exit("Close")
            return
        except Exception as error:
            st.error(f"The protein search status could not be read: {error}")
            _render_job_dialog_exit("Close")
            return
        if job is None:
            st.error("The protein search status is unavailable.")
            _render_job_dialog_exit("Close")
            return
        if job.status in ACTIVE_JOB_STATUSES:
            render_pubchem_job_status()
        else:
            _render_terminal_pubchem_job(db_path, job)
        return

    st.write("Search CIDs by BioAssays, using a protein as target.")
    st.text_input(label="Protein", key=INPUT_PROTEIN, value="P34971")
    if st.button("Add to selection"):
        st.session_state[SELECTED_PROTEINS].append(st.session_state[INPUT_PROTEIN])
        st.markdown(f"Selected proteins: {st.session_state[SELECTED_PROTEINS]}.")
    if st.button("Confirm selection"):
        if len(st.session_state[SELECTED_PROTEINS]) == 0:
            st.toast("Select at least one protein")
            print("Select at least one protein")
        elif st.session_state[DATABASE_ID] == "":
            st.toast("First, enter a name for your SQL database")
            print("First, enter a name for your SQL database")
        else:
            st.info("Building the protein database. This can take a few minutes for targets with many BioAssays.")
            st.toast(f"Building database with proteins: {st.session_state[SELECTED_PROTEINS]}")
            try:
                job, db_path = run_protein_search(None)
            except Exception as error:
                st.error(f"The protein search could not be started: {error}")
                return
            st.session_state[PUBCHEM_JOB_ID] = job.job_id
            st.session_state[PUBCHEM_JOB_DB_PATH] = str(db_path)
            st.session_state[PUBCHEM_JOB_COMPLETION_HANDLED] = False
            st.rerun(scope="fragment")
            return
        st.rerun()
    if st.button("Cancel"):
        st.session_state[SELECTED_PROTEINS] = []
        st.rerun()
