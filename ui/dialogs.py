# SPDX-License-Identifier: LGPL-3.0-or-later
import sqlite3

import streamlit as st

from services.pubchem_job_service import (
    cancel_pubchem_job,
    load_pubchem_job,
    register_completed_pubchem_job,
    start_pubchem_search,
)
from state_keys import (
    CURRENT_TABLE,
    DATABASE_ID,
    INPUT_PROTEIN,
    PUBCHEM_JOB_COMPLETION_HANDLED,
    PUBCHEM_JOB_DB_PATH,
    PUBCHEM_JOB_ID,
    SELECTED_PROTEINS,
)
from ui.session_state import refresh_database_state


def _is_database_locked_error(error):
    message = str(error).lower()
    return "database is locked" in message or "database table is locked" in message


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
    if job.is_cancelled:
        st.info("Protein search cancelled.")
        _render_job_dialog_exit("Close")
        return

    if job.is_failed:
        if job.is_stale_failure:
            st.error(job.error_message)
        else:
            st.error(f"The protein search failed: {job.error_message}")
        _render_job_dialog_exit("Close")
        return

    if job.is_completed and not st.session_state.get(
        PUBCHEM_JOB_COMPLETION_HANDLED,
        False,
    ):
        try:
            register_completed_pubchem_job(db_path, job)
        except Exception as error:
            st.error(f"The completed search could not be registered: {error}")
            return
        st.session_state[PUBCHEM_JOB_COMPLETION_HANDLED] = True
        refresh_database_state(st.session_state)

    if job.is_completed:
        st.success("Protein search completed.")
        _render_job_dialog_exit("Continue")


@st.fragment(run_every="2s")
def render_pubchem_job_status():
    job_id = st.session_state.get(PUBCHEM_JOB_ID, "")
    db_path = st.session_state.get(PUBCHEM_JOB_DB_PATH, "")
    if not job_id or not db_path:
        return

    try:
        job = load_pubchem_job(db_path, job_id)
    except sqlite3.OperationalError as error:
        if _is_database_locked_error(error):
            st.info("The protein search database is busy. ChemVault will retry automatically.")
            return
        st.rerun()
    except Exception:
        st.rerun()
    if job is None:
        st.rerun()

    if not job.is_active:
        st.rerun()
    _render_job_snapshot(job)
    if st.button("Cancel search", key="pubchem_job_cancel"):
        cancelled = cancel_pubchem_job(db_path, job_id)
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
            job = load_pubchem_job(db_path, job_id)
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
        if job.is_active:
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
        elif st.session_state[DATABASE_ID] == "":
            st.toast("First, enter a name for your SQL database")
        else:
            st.info("Building the protein database. This can take a few minutes for targets with many BioAssays.")
            st.toast(f"Building database with proteins: {st.session_state[SELECTED_PROTEINS]}")
            try:
                st.session_state[CURRENT_TABLE] = "main"
                job, db_path = start_pubchem_search(
                    st.session_state[DATABASE_ID],
                    list(st.session_state[SELECTED_PROTEINS]),
                )
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
