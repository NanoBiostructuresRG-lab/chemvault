# SPDX-License-Identifier: LGPL-3.0-or-later
"""Streamlit-independent state cycle for Modelability Index jobs."""

from __future__ import annotations

import csv
import io
import json
import math
from collections.abc import Iterable
from typing import TypedDict, cast

from molraptor import FingerprintType

from application.modelability_index import (
    DEFAULT_FINGERPRINT_TYPE,
    MURCKO_CONTEXT_CONTRACT_VERSION,
    MURCKO_SCAFFOLD_CHIRALITY,
    MURCKO_SCAFFOLD_DEFINITION,
    NEIGHBOR_RULE,
    SIMILARITY_METRIC,
    TIE_POLICY,
)
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
MURCKO_RELATIONSHIP_PROVENANCE_FIELDS = (
    "source_table",
    "fingerprint_type",
    "molraptor_profile_hash",
    "fingerprint_identity",
    "fingerprint_artifact_sha256",
    "population_identity",
    "chemvault_analysis_hash",
    "similarity_metric",
    "neighbor_rule",
    "tie_policy",
    "murcko_context_contract_version",
    "murcko_scaffold_definition",
    "murcko_scaffold_chirality",
)
MURCKO_RELATIONSHIP_FIELDS = (
    "structure_index",
    "structure_smiles",
    "structure_outcome",
    "structure_murcko_scaffold",
    "structure_is_cyclic",
    "nearest_neighbor_index",
    "nearest_neighbor_smiles",
    "nearest_neighbor_outcome",
    "nearest_neighbor_murcko_scaffold",
    "nearest_neighbor_is_cyclic",
    "tanimoto_similarity",
    "concordant",
    "transition_category",
    "cc_scaffold_relationship",
    "CC",
    "CA",
    "AC",
    "AA",
    "NS",
    "ND",
)
MURCKO_RELATIONSHIP_COLUMNS = (
    *MURCKO_RELATIONSHIP_PROVENANCE_FIELDS,
    *MURCKO_RELATIONSHIP_FIELDS,
)
_MURCKO_RELATIONSHIP_IDENTITY_FIELDS = (
    "molraptor_profile_hash",
    "fingerprint_identity",
    "fingerprint_artifact_sha256",
    "population_identity",
    "chemvault_analysis_hash",
)
_MURCKO_RELATIONSHIP_CONTRACT_VALUES = {
    "similarity_metric": SIMILARITY_METRIC,
    "neighbor_rule": NEIGHBOR_RULE,
    "tie_policy": TIE_POLICY,
    "murcko_context_contract_version": MURCKO_CONTEXT_CONTRACT_VERSION,
    "murcko_scaffold_definition": MURCKO_SCAFFOLD_DEFINITION,
    "murcko_scaffold_chirality": MURCKO_SCAFFOLD_CHIRALITY,
}


class MurckoRelationshipsExportError(ValueError):
    """Raised when persisted evidence cannot produce a valid export."""


class _ModelabilityExportResult(TypedDict, total=False):
    provenance: dict[str, object]
    diagnostics: Iterable[dict[str, object]]


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
    export_result = cast(_ModelabilityExportResult, result)
    provenance = export_result.get("provenance", {})
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
    for diagnostic in export_result.get("diagnostics", ()):
        writer.writerow({**diagnostic, **analysis_fields})
    return output.getvalue()


def _required_mapping(container: dict, key: str, label: str) -> dict:
    value = container.get(key)
    if not isinstance(value, dict):
        raise MurckoRelationshipsExportError(
            f"Persisted {label} is missing or invalid."
        )
    return value


def _required_sequence(container: dict, key: str, label: str) -> tuple:
    value = container.get(key)
    if not isinstance(value, (list, tuple)):
        raise MurckoRelationshipsExportError(
            f"Persisted {label} is missing or invalid."
        )
    return tuple(value)


def _required_count(container: dict, key: str, label: str) -> int:
    value = container.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise MurckoRelationshipsExportError(
            f"Persisted {label} is missing or invalid."
        )
    return value


def _finite_float(value, label: str) -> float:
    if isinstance(value, bool):
        raise MurckoRelationshipsExportError(
            f"Persisted {label} is missing or invalid."
        )
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise MurckoRelationshipsExportError(
            f"Persisted {label} is missing or invalid."
        ) from error
    if not math.isfinite(number):
        raise MurckoRelationshipsExportError(
            f"Persisted {label} is missing or invalid."
        )
    return number


def _indicator(value, label: str) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int) and value in (0, 1):
        return value
    raise MurckoRelationshipsExportError(
        f"Persisted {label} is missing or invalid."
    )


def _validate_murcko_relationship_provenance(provenance: dict) -> None:
    required_text_fields = (
        "source_table",
        "fingerprint_type",
        *_MURCKO_RELATIONSHIP_IDENTITY_FIELDS,
    )
    invalid_text_fields = [
        field
        for field in required_text_fields
        if not isinstance(provenance.get(field), str)
        or not provenance[field].strip()
    ]
    if invalid_text_fields:
        raise MurckoRelationshipsExportError(
            "Persisted Murcko relationship provenance contains empty or invalid "
            "text fields or identities: "
            + ", ".join(invalid_text_fields)
            + "."
        )

    incompatible_contracts = [
        field
        for field, expected in _MURCKO_RELATIONSHIP_CONTRACT_VALUES.items()
        if type(provenance.get(field)) is not type(expected)
        or provenance[field] != expected
    ]
    if incompatible_contracts:
        raise MurckoRelationshipsExportError(
            "Persisted Murcko relationship provenance is incompatible with the "
            "current scientific contracts: "
            + ", ".join(incompatible_contracts)
            + "."
        )


def murcko_relationships_csv(result: dict[str, object]) -> str:
    """Serialize validated persisted Murcko relationships in memory."""
    structure_count = result.get("structure_count")
    if (
        isinstance(structure_count, bool)
        or not isinstance(structure_count, int)
        or structure_count <= 0
    ):
        raise MurckoRelationshipsExportError(
            "Persisted structure count is missing or invalid."
        )

    provenance = _required_mapping(result, "provenance", "provenance")
    missing_provenance = [
        field
        for field in MURCKO_RELATIONSHIP_PROVENANCE_FIELDS
        if field not in provenance or provenance[field] is None
    ]
    if missing_provenance:
        raise MurckoRelationshipsExportError(
            "Persisted Murcko relationship provenance is incomplete: "
            + ", ".join(missing_provenance)
            + "."
        )
    _validate_murcko_relationship_provenance(provenance)

    diagnostics = _required_sequence(result, "diagnostics", "diagnostics")
    structural_context = _required_mapping(
        result,
        "structural_context",
        "structural context",
    )
    population = _required_mapping(
        structural_context,
        "murcko_population",
        "Murcko population",
    )
    nearest = _required_mapping(
        structural_context,
        "nearest_neighbor_diagnostics",
        "nearest-neighbor diagnostics",
    )
    interface = _required_mapping(
        structural_context,
        "murcko_nn_interface",
        "Murcko nearest-neighbor interface",
    )
    assignments = _required_sequence(
        population,
        "assignments",
        "Murcko assignments",
    )
    maximum_neighbor_indices = _required_sequence(
        nearest,
        "maximum_neighbor_indices",
        "maximum-neighbor indices",
    )
    maximum_similarities = _required_sequence(
        nearest,
        "maximum_similarities",
        "maximum similarities",
    )

    lengths = {
        "diagnostics": len(diagnostics),
        "Murcko assignments": len(assignments),
        "maximum-neighbor indices": len(maximum_neighbor_indices),
        "maximum similarities": len(maximum_similarities),
    }
    mismatched = [
        label for label, length in lengths.items()
        if length != structure_count
    ]
    if mismatched:
        raise MurckoRelationshipsExportError(
            "Persisted row counts do not match the structure count: "
            + ", ".join(mismatched)
            + "."
        )
    if _required_count(population, "total_count", "Murcko total count") != structure_count:
        raise MurckoRelationshipsExportError(
            "Persisted Murcko total count does not match the structure count."
        )

    required_diagnostic_fields = (
        "smiles",
        "outcome",
        "nearest_neighbor_smiles",
        "nearest_neighbor_outcome",
        "tanimoto_similarity",
        "concordant",
    )
    diagnostic_rows = []
    for index, diagnostic in enumerate(diagnostics):
        if not isinstance(diagnostic, dict):
            raise MurckoRelationshipsExportError(
                f"Persisted diagnostic row {index} is invalid."
            )
        missing = [
            field for field in required_diagnostic_fields
            if field not in diagnostic
        ]
        if missing:
            raise MurckoRelationshipsExportError(
                f"Persisted diagnostic row {index} is incomplete: "
                + ", ".join(missing)
                + "."
            )
        smiles = diagnostic["smiles"]
        outcome = diagnostic["outcome"]
        if not isinstance(smiles, str) or not smiles:
            raise MurckoRelationshipsExportError(
                f"Persisted source SMILES at row {index} is invalid."
            )
        if outcome not in {"Active", "Inactive"}:
            raise MurckoRelationshipsExportError(
                f"Persisted source outcome at row {index} is invalid."
            )
        diagnostic_rows.append(diagnostic)

    source_smiles = [row["smiles"] for row in diagnostic_rows]
    if len(set(source_smiles)) != structure_count:
        raise MurckoRelationshipsExportError(
            "Persisted source SMILES must be unique."
        )
    index_by_smiles = {
        smiles: index for index, smiles in enumerate(source_smiles)
    }

    for index, scaffold in enumerate(assignments):
        if scaffold is not None and (
            not isinstance(scaffold, str) or not scaffold
        ):
            raise MurckoRelationshipsExportError(
                f"Persisted Murcko assignment at row {index} is invalid."
            )

    provenance_values = {
        field: provenance[field]
        for field in MURCKO_RELATIONSHIP_PROVENANCE_FIELDS
    }
    relationship_rows = []
    category_counts = {
        "CC": 0,
        "CA": 0,
        "AC": 0,
        "AA": 0,
        "NS": 0,
        "ND": 0,
    }
    for index, diagnostic in enumerate(diagnostic_rows):
        neighbor_smiles = diagnostic["nearest_neighbor_smiles"]
        if not isinstance(neighbor_smiles, str):
            raise MurckoRelationshipsExportError(
                f"Persisted selected-neighbor SMILES at row {index} is invalid."
            )
        neighbor_index = index_by_smiles.get(neighbor_smiles)
        if neighbor_index is None:
            raise MurckoRelationshipsExportError(
                f"Persisted selected neighbor at row {index} cannot be resolved."
            )
        if neighbor_index == index:
            raise MurckoRelationshipsExportError(
                f"Persisted selected neighbor at row {index} is the source structure."
            )

        neighbor = diagnostic_rows[neighbor_index]
        if diagnostic["nearest_neighbor_outcome"] != neighbor["outcome"]:
            raise MurckoRelationshipsExportError(
                f"Persisted selected-neighbor outcome at row {index} is inconsistent."
            )
        concordant = _indicator(
            diagnostic["concordant"],
            f"concordance at row {index}",
        )
        expected_concordance = int(
            diagnostic["outcome"] == neighbor["outcome"]
        )
        if concordant != expected_concordance:
            raise MurckoRelationshipsExportError(
                f"Persisted concordance at row {index} is inconsistent."
            )

        candidates = maximum_neighbor_indices[index]
        if not isinstance(candidates, (list, tuple)) or not candidates:
            raise MurckoRelationshipsExportError(
                f"Persisted maximum-neighbor candidates at row {index} are invalid."
            )
        if any(
            isinstance(candidate, bool)
            or not isinstance(candidate, int)
            or candidate < 0
            or candidate >= structure_count
            for candidate in candidates
        ):
            raise MurckoRelationshipsExportError(
                f"Persisted maximum-neighbor candidates at row {index} are invalid."
            )
        if index in candidates:
            raise MurckoRelationshipsExportError(
                f"Persisted maximum-neighbor candidates at row {index} include the source."
            )
        if neighbor_index != min(candidates):
            raise MurckoRelationshipsExportError(
                f"Persisted selected neighbor at row {index} violates the tie policy."
            )

        similarity = _finite_float(
            diagnostic["tanimoto_similarity"],
            f"selected similarity at row {index}",
        )
        maximum_similarity = _finite_float(
            maximum_similarities[index],
            f"maximum similarity at row {index}",
        )
        if not math.isclose(
            similarity,
            maximum_similarity,
            rel_tol=1e-12,
            abs_tol=1e-15,
        ):
            raise MurckoRelationshipsExportError(
                f"Persisted selected similarity at row {index} is inconsistent."
            )

        source_scaffold = assignments[index]
        neighbor_scaffold = assignments[neighbor_index]
        source_is_cyclic = int(source_scaffold is not None)
        neighbor_is_cyclic = int(neighbor_scaffold is not None)
        scaffold_relationship = ""
        if source_is_cyclic and neighbor_is_cyclic:
            transition = "CC"
            scaffold_relationship = (
                "NS" if source_scaffold == neighbor_scaffold else "ND"
            )
            category_counts[scaffold_relationship] += 1
        elif source_is_cyclic:
            transition = "CA"
        elif neighbor_is_cyclic:
            transition = "AC"
        else:
            transition = "AA"
        category_counts[transition] += 1

        flags = {
            category: int(
                category == transition
                or category == scaffold_relationship
            )
            for category in ("CC", "CA", "AC", "AA", "NS", "ND")
        }
        relationship_rows.append({
            **provenance_values,
            "structure_index": index,
            "structure_smiles": diagnostic["smiles"],
            "structure_outcome": diagnostic["outcome"],
            "structure_murcko_scaffold": source_scaffold or "",
            "structure_is_cyclic": source_is_cyclic,
            "nearest_neighbor_index": neighbor_index,
            "nearest_neighbor_smiles": neighbor_smiles,
            "nearest_neighbor_outcome": diagnostic["nearest_neighbor_outcome"],
            "nearest_neighbor_murcko_scaffold": neighbor_scaffold or "",
            "nearest_neighbor_is_cyclic": neighbor_is_cyclic,
            "tanimoto_similarity": diagnostic["tanimoto_similarity"],
            "concordant": concordant,
            "transition_category": transition,
            "cc_scaffold_relationship": scaffold_relationship,
            **flags,
        })

    transition_total = sum(
        category_counts[category]
        for category in ("CC", "CA", "AC", "AA")
    )
    if transition_total != structure_count:
        raise MurckoRelationshipsExportError(
            "Reconstructed Murcko transition counts do not match the structure count."
        )
    if category_counts["NS"] + category_counts["ND"] != category_counts["CC"]:
        raise MurckoRelationshipsExportError(
            "Reconstructed Murcko scaffold relationships do not match CC."
        )

    transition_counts = _required_mapping(
        interface,
        "transition_counts",
        "Murcko transition counts",
    )
    persisted_counts = {
        "CC": _required_count(interface, "cc_count", "CC count"),
        "CA": _required_count(interface, "ca_count", "CA count"),
        "AC": _required_count(interface, "ac_count", "AC count"),
        "AA": _required_count(interface, "aa_count", "AA count"),
        "NS": _required_count(
            interface,
            "same_scaffold_count",
            "same-scaffold count",
        ),
        "ND": _required_count(
            interface,
            "different_scaffold_count",
            "different-scaffold count",
        ),
    }
    for category in ("CC", "CA", "AC", "AA"):
        transition_count = _required_count(
            transition_counts,
            category,
            f"{category} transition count",
        )
        if transition_count != persisted_counts[category]:
            raise MurckoRelationshipsExportError(
                f"Persisted {category} transition counts are inconsistent."
            )
    if persisted_counts != category_counts:
        raise MurckoRelationshipsExportError(
            "Reconstructed Murcko relationship counts do not match the persisted interface."
        )

    output = io.StringIO(newline="")
    writer = csv.DictWriter(
        output,
        fieldnames=MURCKO_RELATIONSHIP_COLUMNS,
        extrasaction="ignore",
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerows(relationship_rows)
    return output.getvalue()


def analysis_report_json(result: dict[str, object]) -> str:
    """Serialize the existing analysis result without recomputation."""
    export_result = cast(_ModelabilityExportResult, result)
    provenance = export_result.get("provenance", {})
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
