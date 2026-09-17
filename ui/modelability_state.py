# SPDX-License-Identifier: LGPL-3.0-or-later
"""Streamlit-independent state cycle for Modelability Index jobs."""

from __future__ import annotations

import csv
import io
import json

from molraptor import FingerprintType

from application.modelability_index import DEFAULT_FINGERPRINT_TYPE
from services.job_models import JobStatus
from ui.state_keys import (
    MODELABILITY_FEEDBACK_KIND,
    MODELABILITY_FEEDBACK_MESSAGE,
    MODELABILITY_JOB_DATABASE_ID,
    MODELABILITY_JOB_FINGERPRINT_TYPE,
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
    "fingerprint_type",
    "chemvault_analysis_hash",
    "population_identity",
    "smiles",
    "outcome",
    "nearest_neighbor_smiles",
    "nearest_neighbor_outcome",
    "tanimoto_similarity",
    "concordant",
)
SUMMARY_FIELDS = (
    "structure_count",
    "active_count",
    "inactive_count",
    "active_concordance",
    "inactive_concordance",
    "modelability_index",
)
PROVENANCE_FIELDS = (
    "source_table",
    "fingerprint_type",
    "fingerprint_profile",
    "molraptor_profile_hash",
    "molraptor_ordered_input_hash",
    "chemvault_analysis_hash",
    "molraptor_version",
    "rdkit_version",
    "fingerprint_source",
    "fingerprint_identity",
    "population_identity",
    "fingerprint_artifact_sha256",
    "similarity_metric",
    "neighbor_rule",
    "tie_policy",
    "aggregation",
    "murcko_context_contract_version",
    "murcko_scaffold_definition",
    "murcko_scaffold_chirality",
)
NEAREST_NEIGHBOR_DIAGNOSTIC_FIELDS = (
    "maximum_neighbor_indices",
    "maximum_similarities",
    "tied_neighbor_counts",
    "tie_fraction",
    "tie_sensitive_fraction",
    "fingerprint_identical_fraction",
    "fingerprint_identical_label_conflict_fraction",
    "active_concordance_min",
    "active_concordance_max",
    "inactive_concordance_min",
    "inactive_concordance_max",
    "modelability_index_min",
    "modelability_index_max",
)
MURCKO_POPULATION_FIELDS = (
    "total_count",
    "cyclic_count",
    "acyclic_count",
    "murcko_coverage",
    "scaffold_count",
    "assignments",
    "scaffold_outcome_counts",
)
MURCKO_METRIC_FIELDS = (
    "shared_scaffold_count",
    "shared_molecule_count",
    "shared_scaffold_fraction",
    "shared_molecular_coverage",
    "within_shared_balance",
    "global_balance",
    "within_balance",
    "within_ratio",
    "eta_squared",
    "null_within_ratio",
    "epsilon_squared",
)
MURCKO_NN_INTERFACE_FIELDS = (
    "cc_count",
    "ca_count",
    "ac_count",
    "aa_count",
    "murcko_nn_coverage",
    "same_scaffold_count",
    "different_scaffold_count",
    "same_scaffold_nn_fraction",
    "same_scaffold_concordance",
    "different_scaffold_concordance",
    "reconstructed_active_concordance",
    "reconstructed_inactive_concordance",
    "reconstructed_modelability_index",
    "transition_counts",
)


def modelability_scope_matches(
    session_state,
    database_id,
    table_name,
    fingerprint_type: FingerprintType = DEFAULT_FINGERPRINT_TYPE,
) -> bool:
    return (
        session_state.get(MODELABILITY_JOB_DATABASE_ID, "") == database_id
        and session_state.get(MODELABILITY_JOB_TABLE_NAME, "") == table_name
        and session_state.get(
            MODELABILITY_JOB_FINGERPRINT_TYPE,
            DEFAULT_FINGERPRINT_TYPE,
        )
        == fingerprint_type
    )


def _set_scope(
    session_state,
    database_id,
    table_name,
    fingerprint_type: FingerprintType,
) -> None:
    session_state[MODELABILITY_JOB_DATABASE_ID] = database_id
    session_state[MODELABILITY_JOB_TABLE_NAME] = table_name
    session_state[MODELABILITY_JOB_FINGERPRINT_TYPE] = fingerprint_type


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
    fingerprint_type: FingerprintType = DEFAULT_FINGERPRINT_TYPE,
):
    """Launch or deduplicate one scoped job and return immediately."""
    _set_scope(session_state, database_id, table_name, fingerprint_type)
    session_state[MODELABILITY_JOB_ID] = ""
    session_state[MODELABILITY_RUNNING] = True
    session_state[MODELABILITY_RESULT] = None
    session_state[MODELABILITY_FEEDBACK_KIND] = ""
    session_state[MODELABILITY_FEEDBACK_MESSAGE] = ""
    try:
        status = gateway.launch_scientific_job(
            database_id,
            "modelability_index",
            {
                "table_name": table_name,
                "fingerprint_type": fingerprint_type,
            },
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
    fingerprint_type: FingerprintType = DEFAULT_FINGERPRINT_TYPE,
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
            fingerprint_type,
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
    provenance = result.get("provenance", {})
    analysis_fields = {
        field: provenance.get(field)
        for field in DIAGNOSTIC_COLUMNS[:3]
    }
    output = io.StringIO(newline="")
    writer = csv.DictWriter(
        output,
        fieldnames=DIAGNOSTIC_COLUMNS,
        extrasaction="ignore",
        lineterminator="\n",
    )
    writer.writeheader()
    for diagnostic in result.get("diagnostics", ()):
        writer.writerow({**diagnostic, **analysis_fields})
    return output.getvalue()


def analysis_report_json(result: dict[str, object]) -> str:
    """Serialize the existing analysis result without recomputation."""
    provenance = result.get("provenance", {})
    structural_context = result.get("structural_context", {})
    if not isinstance(structural_context, dict):
        structural_context = {}
    nearest_neighbor_diagnostics = structural_context.get(
        "nearest_neighbor_diagnostics", {}
    )
    if not isinstance(nearest_neighbor_diagnostics, dict):
        nearest_neighbor_diagnostics = {}
    murcko_sections = (
        ("murcko_population", MURCKO_POPULATION_FIELDS),
        ("murcko_metrics", MURCKO_METRIC_FIELDS),
        ("murcko_nn_interface", MURCKO_NN_INTERFACE_FIELDS),
    )
    serialized_structural_context = {}
    for section_name, fields in murcko_sections:
        section = structural_context.get(section_name)
        if not isinstance(section, dict):
            section = {}
        serialized_structural_context[section_name] = {
            field: section[field]
            for field in fields
            if field in section
        }
    report = {
        "schema_name": "chemvault_modelability_analysis",
        "schema_version": 2,
        "summary": {
            field: result[field]
            for field in SUMMARY_FIELDS
        },
        "provenance": {
            field: provenance[field]
            for field in PROVENANCE_FIELDS
            if field in provenance
        },
        "nearest_neighbor_diagnostics": {
            field: nearest_neighbor_diagnostics[field]
            for field in NEAREST_NEIGHBOR_DIAGNOSTIC_FIELDS
            if field in nearest_neighbor_diagnostics
        },
        "structural_context": serialized_structural_context,
    }
    return json.dumps(
        report,
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
    ) + "\n"
