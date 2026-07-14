# SPDX-License-Identifier: LGPL-3.0-or-later
"""Consolidate HARMONSMILE-enriched activity rows by molecular structure."""

from __future__ import annotations

import json
from dataclasses import dataclass

import pandas as pd


REQUIRED_COLUMNS = {
    "CID",
    "AID",
    "Outcome",
    "InChIKey",
    "SMILES_Harmonized",
    "SMILES_Harmonization_Status",
}

VALID_HARMONIZATION_STATUSES = {"ok", "ok_with_warnings"}
BINARY_OUTCOMES = {"active": "Active", "inactive": "Inactive"}

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
    conflicting_structure_count: int
    non_binary_structure_count: int
    unusable_row_count: int
    consolidated_duplicate_count: int
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

        ordered_group = group.copy()
        ordered_group["__cid_sort"] = ordered_group["CID"].map(_cid_sort_key)
        ordered_group["__aid_sort"] = ordered_group["AID"].map(_cid_sort_key)
        ordered_group = ordered_group.sort_values(
            by=["__cid_sort", "__aid_sort", "__row_tie_break"],
            kind="stable",
        )
        representative = ordered_group.iloc[0]

        row: dict[str, object] = {
            "SMILES_Harmonized": smiles,
            "InChIKey": representative["InChIKey"],
            "Outcome": next(iter(binary_outcomes)),
            "Representative_CID": _clean_text(representative["CID"]),
            "Representative_AID": _clean_text(representative["AID"]),
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
                row[column] = representative[column]

        output_rows.append(row)

    preferred_order = [
        "SMILES_Harmonized",
        "InChIKey",
        "Outcome",
        "Representative_CID",
        "Representative_AID",
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

    unique_structure_count = int(usable["__smiles"].nunique())
    valid_source_row_count = int(len(usable))

    return StructureConsolidationResult(
        dataframe=output,
        source_row_count=int(len(source)),
        valid_source_row_count=valid_source_row_count,
        unique_structure_count=unique_structure_count,
        created_row_count=int(len(output)),
        active_structure_count=active_count,
        inactive_structure_count=inactive_count,
        conflicting_structure_count=len(excluded_conflicts),
        non_binary_structure_count=len(excluded_non_binary),
        unusable_row_count=int(len(unusable)),
        consolidated_duplicate_count=sum(
            int(row["Source_Row_Count"]) - 1 for row in output_rows
        ),
        excluded_conflicts=tuple(excluded_conflicts),
        excluded_non_binary=tuple(excluded_non_binary),
        excluded_unusable=tuple(excluded_unusable),
    )
