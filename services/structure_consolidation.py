# SPDX-License-Identifier: LGPL-3.0-or-later
"""Consolidate HARMONSMILE-enriched activity rows by molecular structure."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass

import pandas as pd


REQUIRED_COLUMNS = {
    "CID",
    "AID",
    "Outcome",
    "InChIKey",
    "SMILES_Harmonized",
    "SMILES_Harmonization_Status",
    "Activity_Type",
    "Relation",
    "Activity_Value",
    "Activity_Value_Raw",
    "Unit",
}

VALID_HARMONIZATION_STATUSES = {"ok", "ok_with_warnings"}
BINARY_OUTCOMES = {"active": "Active", "inactive": "Inactive"}
EXACT_RELATIONS = {"", "="}
ACTIVITY_UNIT_TO_UM = {
    "NANOMOLAR": 0.001,
    "MICROMOLAR": 1.0,
}

HARMONSMILE_COLUMNS = (
    "InChI",
    "InChIKey",
    "SMILES",
    "ConnectivitySMILES",
    "SMILES_RDKit",
    "SMILES_Harmonized",
    "SMILES_Harmonization_Status",
    "SMILES_Harmonization_Message",
    "MolecularFormula",
    "MW",
    "XLogP",
    "TPSA",
    "Charge",
    "HBondDonorCount",
    "HBondAcceptorCount",
    "RotatableBondCount",
    "HeavyAtomCount",
)


class StructureConsolidationError(ValueError):
    """Raised when a source table cannot be consolidated safely."""


@dataclass(frozen=True)
class StructureConsolidationResult:
    dataframe: pd.DataFrame
    source_row_count: int
    valid_source_row_count: int
    unique_structure_count: int
    created_row_count: int
    active_structure_count: int
    inactive_structure_count: int
    active_distinct_aid_count: int
    active_source_observation_count: int
    inactive_distinct_aid_count: int
    inactive_source_observation_count: int
    conflicting_structure_count: int
    non_binary_structure_count: int
    unusable_row_count: int
    consolidated_duplicate_count: int
    represented_source_row_count: int
    selected_reference_count: int
    no_eligible_activity_count: int
    excluded_conflicts: tuple[dict[str, object], ...]
    excluded_non_binary: tuple[dict[str, object], ...]
    excluded_unusable: tuple[dict[str, object], ...]


def _clean_text(value) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip()


def _cid_sort_key(value) -> tuple[int, object]:
    text = _clean_text(value)
    try:
        return (0, int(text))
    except (TypeError, ValueError):
        return (1, text)


def _sorted_unique(values) -> list[str]:
    cleaned = {_clean_text(value) for value in values}
    cleaned.discard("")
    return sorted(cleaned, key=_cid_sort_key)


def _stable_value(value) -> tuple[str, str]:
    if pd.isna(value):
        return ("null", "")
    return (type(value).__name__, str(value))


def _stable_row_tie_break(row, columns) -> str:
    values = [
        (str(column), *_stable_value(row[column]))
        for column in sorted(columns, key=str)
    ]
    return json.dumps(values, ensure_ascii=False, separators=(",", ":"))


def _validate_columns(dataframe: pd.DataFrame) -> None:
    missing = sorted(REQUIRED_COLUMNS.difference(dataframe.columns))
    if missing:
        raise StructureConsolidationError(
            "The source table is missing required columns: "
            + ", ".join(missing)
        )


def _validate_activity_type(dataframe: pd.DataFrame) -> str:
    activity_types = sorted(
        {
            activity_type
            for value in dataframe["Activity_Type"]
            if (activity_type := _clean_text(value))
        }
    )
    if len(activity_types) != 1:
        found = ", ".join(activity_types) if activity_types else "none"
        raise StructureConsolidationError(
            "The source table must contain exactly one non-empty "
            "Activity_Type among usable rows; found: " + found
        )
    return activity_types[0]


def _activity_value_um(row, activity_type: str) -> float | None:
    if _clean_text(row["Activity_Type"]) != activity_type:
        return None
    if _clean_text(row["Relation"]) not in EXACT_RELATIONS:
        return None

    try:
        value = float(row["Activity_Value"])
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value) or value <= 0:
        return None

    factor = ACTIVITY_UNIT_TO_UM.get(_clean_text(row["Unit"]).upper())
    if factor is None:
        return None
    converted = value * factor
    if not math.isfinite(converted) or converted <= 0:
        return None
    return converted


def _stable_order(dataframe: pd.DataFrame) -> pd.DataFrame:
    ordered = dataframe.copy()
    ordered["__cid_sort"] = ordered["CID"].map(_cid_sort_key)
    ordered["__aid_sort"] = ordered["AID"].map(_cid_sort_key)
    return ordered.sort_values(
        by=["__cid_sort", "__aid_sort", "__row_tie_break"],
        kind="stable",
    )


def consolidate_harmonized_structures(
    dataframe: pd.DataFrame,
) -> StructureConsolidationResult:
    """Create one row per consistently labeled harmonized structure."""
    _validate_columns(dataframe)

    source = dataframe.copy(deep=True)
    source_columns = tuple(source.columns)
    source["__row_tie_break"] = source.apply(
        _stable_row_tie_break,
        axis=1,
        columns=source_columns,
    )
    source["__smiles"] = source["SMILES_Harmonized"].map(_clean_text)
    source["__status"] = (
        source["SMILES_Harmonization_Status"]
        .map(_clean_text)
        .str.lower()
    )
    source["__outcome"] = source["Outcome"].map(_clean_text).str.lower()

    usable_mask = (
        source["__smiles"].ne("")
        & source["__status"].isin(VALID_HARMONIZATION_STATUSES)
    )

    usable = source.loc[usable_mask].copy()
    unusable = source.loc[~usable_mask].copy()
    activity_type = _validate_activity_type(usable)

    output_rows: list[dict[str, object]] = []
    excluded_conflicts: list[dict[str, object]] = []
    excluded_non_binary: list[dict[str, object]] = []
    excluded_unusable: list[dict[str, object]] = []

    for _, row in unusable.iterrows():
        if row["__smiles"] == "":
            reason = "missing_smiles_harmonized"
        else:
            reason = f"harmonization_status:{row['__status'] or 'missing'}"

        excluded_unusable.append(
            {
                "CID": _clean_text(row["CID"]),
                "AID": _clean_text(row["AID"]),
                "Outcome": _clean_text(row["Outcome"]),
                "SMILES_Harmonized": row["__smiles"],
                "SMILES_Harmonization_Status": _clean_text(
                    row["SMILES_Harmonization_Status"]
                ),
                "reason": reason,
            }
        )

    for smiles, group in usable.groupby("__smiles", sort=True):
        normalized_outcomes = set(group["__outcome"])
        binary_outcomes = {
            BINARY_OUTCOMES[value]
            for value in normalized_outcomes
            if value in BINARY_OUTCOMES
        }

        trace = {
            "SMILES_Harmonized": smiles,
            "Source_CIDs": _sorted_unique(group["CID"]),
            "Source_AIDs": _sorted_unique(group["AID"]),
            "Source_Row_Count": int(len(group)),
            "Outcomes": sorted(
                {_clean_text(value) for value in group["Outcome"]}
            ),
        }

        if {"active", "inactive"}.issubset(normalized_outcomes):
            excluded_conflicts.append(
                {
                    **trace,
                    "reason": "active_inactive_conflict",
                }
            )
            continue

        if any(value not in BINARY_OUTCOMES for value in normalized_outcomes):
            excluded_non_binary.append(
                {
                    **trace,
                    "reason": "non_binary_or_missing_outcome",
                }
            )
            continue

        ordered_group = _stable_order(group)
        molecular_source = ordered_group.iloc[0]

        activity_values_um = group.apply(
            _activity_value_um,
            axis=1,
            activity_type=activity_type,
        )
        eligible = group.loc[activity_values_um.notna()].copy()
        reference = None
        geometric_mean_um = None
        if not eligible.empty:
            eligible["__activity_value_um"] = activity_values_um.loc[
                eligible.index
            ].astype(float)
            log_values = eligible["__activity_value_um"].map(math.log)
            log_mean = math.fsum(log_values.tolist()) / len(log_values)
            geometric_mean_um = math.exp(log_mean)
            eligible["__activity_distance"] = log_values.map(
                lambda value: abs(value - log_mean)
            )
            eligible = _stable_order(eligible).sort_values(
                by=[
                    "__activity_distance",
                    "__cid_sort",
                    "__aid_sort",
                    "__row_tie_break",
                ],
                kind="stable",
            )
            reference = eligible.iloc[0]
            molecular_source = reference

        row: dict[str, object] = {
            "SMILES_Harmonized": smiles,
            "InChIKey": molecular_source["InChIKey"],
            "Outcome": next(iter(binary_outcomes)),
            "Reference_CID": (
                _clean_text(reference["CID"])
                if reference is not None
                else None
            ),
            "Reference_AID": (
                _clean_text(reference["AID"])
                if reference is not None
                else None
            ),
            "Reference_Activity_Type": (
                _clean_text(reference["Activity_Type"])
                if reference is not None
                else None
            ),
            "Reference_Relation": (
                _clean_text(reference["Relation"])
                if reference is not None
                else None
            ),
            "Reference_Activity_Value": (
                float(reference["Activity_Value"])
                if reference is not None
                else None
            ),
            "Reference_Activity_Value_Raw": (
                reference["Activity_Value_Raw"]
                if reference is not None
                and not pd.isna(reference["Activity_Value_Raw"])
                else None
            ),
            "Reference_Unit": (
                _clean_text(reference["Unit"])
                if reference is not None
                else None
            ),
            "Reference_Activity_Value_uM": (
                float(reference["__activity_value_um"])
                if reference is not None
                else None
            ),
            "Geometric_Mean_Activity_uM": geometric_mean_um,
            "Reference_Selection_Status": (
                "selected"
                if reference is not None
                else "no_eligible_activity"
            ),
            "Source_CIDs": json.dumps(
                _sorted_unique(group["CID"]),
                ensure_ascii=False,
            ),
            "Source_AIDs": json.dumps(
                _sorted_unique(group["AID"]),
                ensure_ascii=False,
            ),
            "Source_Row_Count": int(len(group)),
            "Source_AID_Count": len(_sorted_unique(group["AID"])),
        }

        for column in HARMONSMILE_COLUMNS:
            if (
                column in source.columns
                and column not in row
                and column != "SMILES_Harmonized"
            ):
                row[column] = molecular_source[column]

        output_rows.append(row)

    preferred_order = [
        "SMILES_Harmonized",
        "InChIKey",
        "Outcome",
        "Reference_CID",
        "Reference_AID",
        "Reference_Activity_Type",
        "Reference_Relation",
        "Reference_Activity_Value",
        "Reference_Activity_Value_Raw",
        "Reference_Unit",
        "Reference_Activity_Value_uM",
        "Geometric_Mean_Activity_uM",
        "Reference_Selection_Status",
        "Source_CIDs",
        "Source_AIDs",
        "Source_Row_Count",
        "Source_AID_Count",
    ]
    remaining = [
        column
        for column in HARMONSMILE_COLUMNS
        if column in source.columns and column not in preferred_order
    ]
    output = pd.DataFrame(
        output_rows,
        columns=[*preferred_order, *remaining],
    )

    active_count = (
        int((output["Outcome"] == "Active").sum())
        if not output.empty
        else 0
    )
    inactive_count = (
        int((output["Outcome"] == "Inactive").sum())
        if not output.empty
        else 0
    )
    outcome_source_aids = {"Active": set(), "Inactive": set()}
    outcome_source_observations = {"Active": 0, "Inactive": 0}
    for row in output_rows:
        outcome = row["Outcome"]
        outcome_source_aids[outcome].update(json.loads(row["Source_AIDs"]))
        outcome_source_observations[outcome] += int(
            row["Source_Row_Count"]
        )

    unique_structure_count = int(usable["__smiles"].nunique())
    valid_source_row_count = int(len(usable))
    created_row_count = int(len(output))
    represented_source_row_count = sum(
        int(row["Source_Row_Count"]) for row in output_rows
    )
    consolidated_duplicate_count = sum(
        int(row["Source_Row_Count"]) - 1 for row in output_rows
    )
    selected_reference_count = sum(
        row["Reference_Selection_Status"] == "selected"
        for row in output_rows
    )
    no_eligible_activity_count = sum(
        row["Reference_Selection_Status"] == "no_eligible_activity"
        for row in output_rows
    )

    if active_count + inactive_count != created_row_count:
        raise StructureConsolidationError(
            "Consolidation outcome-count invariant failed."
        )
    if (
        outcome_source_observations["Active"]
        + outcome_source_observations["Inactive"]
        != represented_source_row_count
    ):
        raise StructureConsolidationError(
            "Consolidation outcome-evidence invariant failed."
        )
    if (
        selected_reference_count + no_eligible_activity_count
        != created_row_count
    ):
        raise StructureConsolidationError(
            "Consolidation reference-count invariant failed."
        )
    if (
        represented_source_row_count - created_row_count
        != consolidated_duplicate_count
    ):
        raise StructureConsolidationError(
            "Consolidation represented-row invariant failed."
        )

    return StructureConsolidationResult(
        dataframe=output,
        source_row_count=int(len(source)),
        valid_source_row_count=valid_source_row_count,
        unique_structure_count=unique_structure_count,
        created_row_count=created_row_count,
        active_structure_count=active_count,
        inactive_structure_count=inactive_count,
        active_distinct_aid_count=len(outcome_source_aids["Active"]),
        active_source_observation_count=(
            outcome_source_observations["Active"]
        ),
        inactive_distinct_aid_count=len(outcome_source_aids["Inactive"]),
        inactive_source_observation_count=(
            outcome_source_observations["Inactive"]
        ),
        conflicting_structure_count=len(excluded_conflicts),
        non_binary_structure_count=len(excluded_non_binary),
        unusable_row_count=int(len(unusable)),
        consolidated_duplicate_count=consolidated_duplicate_count,
        represented_source_row_count=represented_source_row_count,
        selected_reference_count=selected_reference_count,
        no_eligible_activity_count=no_eligible_activity_count,
        excluded_conflicts=tuple(excluded_conflicts),
        excluded_non_binary=tuple(excluded_non_binary),
        excluded_unusable=tuple(excluded_unusable),
    )
