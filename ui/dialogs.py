# SPDX-License-Identifier: LGPL-3.0-or-later
import streamlit as st

from clients.backend_gateway import BackendGatewayError, get_backend_gateway
from services.job_models import JobStatus
from ui.state_keys import (
    CURRENT_TABLE,
    DATABASE_ID,
    INPUT_GENE_SYMBOL,
    INPUT_PROTEIN,
    PUBCHEM_JOB_COMPLETION_HANDLED,
    PUBCHEM_JOB_ID,
    RESOLVED_TARGET,
    SELECTED_ORGANISM_ID,
    SELECTED_PROTEINS,
    TARGET_INPUT_MODE,
)
from ui.session_state import refresh_database_state


GENE_SYMBOL_MODE = "Gene symbol"
UNIPROT_ACCESSION_MODE = "UniProt accession"
TARGET_INPUT_MODES = (GENE_SYMBOL_MODE, UNIPROT_ACCESSION_MODE)


def _is_database_locked_error(error):
    message = str(error).lower()
    return "database is locked" in message or "database table is locked" in message


def _clear_resolved_target():
    st.session_state[RESOLVED_TARGET] = None
    st.session_state[SELECTED_PROTEINS] = []


def _clear_pubchem_job_state():
    st.session_state[PUBCHEM_JOB_ID] = ""
    st.session_state[PUBCHEM_JOB_COMPLETION_HANDLED] = False
    _clear_resolved_target()


def _resolved_target_payload(resolution):
    return {
        "gene_symbol": resolution.gene_symbol,
        "organism_id": resolution.organism_id,
        "organism_name": resolution.organism_name,
        "common_name": resolution.common_name,
        "accession": resolution.accession,
        "entry_name": resolution.entry_name,
        "protein_name": resolution.protein_name,
        "reviewed": resolution.reviewed,
    }


def _store_resolved_target(resolution):
    payload = _resolved_target_payload(resolution)
    st.session_state[RESOLVED_TARGET] = payload
    st.session_state[SELECTED_PROTEINS] = [resolution.accession]
    return payload


def _current_target_accession():
    mode = st.session_state.get(TARGET_INPUT_MODE, GENE_SYMBOL_MODE)
    if mode == UNIPROT_ACCESSION_MODE:
        return str(st.session_state.get(INPUT_PROTEIN, "")).strip().upper()

    resolved = st.session_state.get(RESOLVED_TARGET)
    if not isinstance(resolved, dict):
        return ""

    gene_symbol = str(
        st.session_state.get(INPUT_GENE_SYMBOL, "")
    ).strip().upper()
    organism_id = st.session_state.get(SELECTED_ORGANISM_ID)
    if (
        resolved.get("gene_symbol") != gene_symbol
        or resolved.get("organism_id") != organism_id
    ):
        return ""
    return str(resolved.get("accession", "")).strip().upper()


def _current_target_identity(accession):
    normalized_accession = str(accession).strip().upper()
    if not normalized_accession:
        return None

    mode = st.session_state.get(TARGET_INPUT_MODE, GENE_SYMBOL_MODE)
    if mode == UNIPROT_ACCESSION_MODE:
        return {
            "input_mode": "uniprot_accession",
            "uniprot_accession": normalized_accession,
        }

    if _current_target_accession() != normalized_accession:
        return None
    resolved = st.session_state.get(RESOLVED_TARGET)
    if not isinstance(resolved, dict):
        return None
    return {
        "input_mode": "gene_symbol",
        "gene_symbol": resolved["gene_symbol"],
        "organism_id": resolved["organism_id"],
        "organism_name": resolved["organism_name"],
        "common_name": resolved.get("common_name"),
        "uniprot_accession": normalized_accession,
        "uniprot_entry_name": resolved["entry_name"],
        "protein_name": resolved["protein_name"],
        "reviewed": resolved["reviewed"],
    }


def _launch_single_target_search(database_id, accession, gateway):
    normalized_accession = str(accession).strip().upper()
    if not normalized_accession:
        raise ValueError("Enter or resolve one target before building.")

    target_identity = _current_target_identity(normalized_accession)
    if target_identity is None:
        raise ValueError("Target identity is unavailable or stale.")

    st.session_state[CURRENT_TABLE] = "main"
    st.session_state[SELECTED_PROTEINS] = [normalized_accession]
    job = gateway.launch_pubchem_protein_search(
        database_id,
        [normalized_accession],
        target_identity,
    )
    st.session_state[PUBCHEM_JOB_ID] = job.job_id
    st.session_state[PUBCHEM_JOB_COMPLETION_HANDLED] = False
    return job


def _organism_label(organism):
    common_name = (
        f" — {organism.common_name}" if organism.common_name else ""
    )
    return (
        f"{organism.scientific_name}{common_name} "
        f"({organism.organism_id})"
    )


def _render_resolved_target():
    resolved = st.session_state.get(RESOLVED_TARGET)
    if not isinstance(resolved, dict) or not _current_target_accession():
        return

    st.success("Target resolved.")
    st.markdown(f"**Protein:** {resolved['protein_name']}")
    st.write(
        f"UniProt accession: {resolved['accession']} · "
        f"Entry: {resolved['entry_name']}"
    )
    st.caption(
        f"Gene: {resolved['gene_symbol']} · "
        f"Organism: {resolved['organism_name']} · "
        f"Status: {'Reviewed' if resolved['reviewed'] else 'Unreviewed'}"
    )


def _render_gene_target_input(gateway):
    try:
        organisms = gateway.list_uniprot_organisms()
    except BackendGatewayError as error:
        st.error(f"Supported organisms could not be loaded: {error}")
        return

    if not organisms:
        st.error("No organisms are enabled for UniProt target resolution.")
        return

    organisms_by_id = {
        organism.organism_id: organism for organism in organisms
    }
    organism_ids = tuple(organisms_by_id)
    if st.session_state.get(SELECTED_ORGANISM_ID) not in organism_ids:
        st.session_state[SELECTED_ORGANISM_ID] = organism_ids[0]

    st.text_input(
        "Gene symbol",
        key=INPUT_GENE_SYMBOL,
        placeholder="LEPR",
        on_change=_clear_resolved_target,
    )
    st.selectbox(
        "Organism",
        organism_ids,
        key=SELECTED_ORGANISM_ID,
        format_func=lambda organism_id: _organism_label(
            organisms_by_id[organism_id]
        ),
        on_change=_clear_resolved_target,
    )

    if st.button("Resolve target", key="resolve_gene_target"):
        try:
            resolution = gateway.resolve_gene_symbol(
                st.session_state.get(INPUT_GENE_SYMBOL, ""),
                st.session_state[SELECTED_ORGANISM_ID],
            )
        except BackendGatewayError as error:
            _clear_resolved_target()
            st.error(f"The gene target could not be resolved: {error}")
        else:
            _store_resolved_target(resolution)

    _render_resolved_target()


def _render_accession_target_input():
    st.text_input(
        "UniProt accession",
        key=INPUT_PROTEIN,
        placeholder="P48357",
        on_change=_clear_resolved_target,
    )
    st.caption(
        "Enter one UniProt accession. CHEMVAULT will normalize it to "
        "uppercase and use it to search PubChem BioAssays."
    )


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


@st.dialog("Select Target", dismissible=False)
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

    st.write(
        "Build a CHEMVAULT compound database from one protein target."
    )
    st.radio(
        "Target identifier",
        TARGET_INPUT_MODES,
        key=TARGET_INPUT_MODE,
        horizontal=True,
        on_change=_clear_resolved_target,
    )

    if st.session_state[TARGET_INPUT_MODE] == GENE_SYMBOL_MODE:
        _render_gene_target_input(gateway)
    else:
        _render_accession_target_input()

    accession = _current_target_accession()
    if st.button(
        "Build database",
        key="build_target_database",
        disabled=not bool(accession),
    ):
        if database_id == "":
            st.toast("First, enter a name for your SQL database")
        else:
            st.info(
                "Building the protein database. This can take a few "
                "minutes for targets with many BioAssays."
            )
            st.toast(f"Building database for target: {accession}")
            try:
                _launch_single_target_search(
                    database_id,
                    accession,
                    gateway,
                )
            except (BackendGatewayError, ValueError) as error:
                st.error(
                    "The protein search could not be started: "
                    f"{error}"
                )
                return
            st.rerun(scope="fragment")
            return

    if st.button("Cancel", key="target_dialog_cancel"):
        _clear_resolved_target()
        st.rerun()
