# SPDX-License-Identifier: LGPL-3.0-or-later
"""Calculate a class-balanced nearest-neighbor modelability index."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt


BINARY_OUTCOMES = {
    "active": "Active",
    "inactive": "Inactive",
}

DEFAULT_BLOCK_SIZE = 512


class ModelabilityIndexError(ValueError):
    """Raised when a modelability index cannot be calculated safely."""


@dataclass(frozen=True)
class ModelabilityStructureDiagnostic:
    input_index: int
    outcome: str
    nearest_neighbor_index: int
    nearest_neighbor_outcome: str
    nearest_neighbor_similarity: float
    outcome_concordant: bool
    nearest_neighbor_tie_count: int


@dataclass(frozen=True)
class ModelabilityIndexResult:
    modelability_index: float
    active_contribution: float
    inactive_contribution: float
    active_count: int
    inactive_count: int
    total_structure_count: int
    concordant_structure_count: int
    discordant_structure_count: int
    tie_affected_structure_count: int
    diagnostics: tuple[ModelabilityStructureDiagnostic, ...]


def _validate_fingerprints(
    fingerprints: npt.ArrayLike,
) -> npt.NDArray[np.uint8]:
    try:
        array = np.asarray(fingerprints)
    except (TypeError, ValueError) as error:
        raise ModelabilityIndexError(
            "Fingerprints must be convertible to a rectangular array."
        ) from error

    if array.ndim != 2:
        raise ModelabilityIndexError(
            "Fingerprints must be a two-dimensional array."
        )
    if array.shape[0] < 2:
        raise ModelabilityIndexError(
            "At least two fingerprint rows are required."
        )
    if array.shape[1] == 0:
        raise ModelabilityIndexError(
            "Fingerprints must contain at least one bit."
        )

    if not (
        np.issubdtype(array.dtype, np.number)
        or np.issubdtype(array.dtype, np.bool_)
    ):
        raise ModelabilityIndexError(
            "Fingerprints must have a numeric or boolean dtype."
        )

    if (
        np.issubdtype(array.dtype, np.floating)
        and not np.isfinite(array).all()
    ):
        raise ModelabilityIndexError(
            "Fingerprints must contain only finite binary values."
        )

    if not np.all((array == 0) | (array == 1)):
        raise ModelabilityIndexError(
            "Fingerprints must contain only binary values 0 and 1."
        )

    binary = array.astype(np.uint8, copy=True)
    bit_counts = binary.sum(axis=1, dtype=np.int64)
    zero_rows = np.flatnonzero(bit_counts == 0)

    if zero_rows.size:
        indices = ", ".join(str(int(index)) for index in zero_rows)
        raise ModelabilityIndexError(
            "Fingerprint rows must contain at least one active bit; "
            f"all-zero rows: {indices}."
        )

    return binary


def _normalize_outcomes(
    outcomes: Sequence[str],
    expected_count: int,
) -> tuple[npt.NDArray[np.object_], dict[str, int]]:
    if isinstance(outcomes, (str, bytes)):
        raise ModelabilityIndexError(
            "Outcomes must be a sequence, not one string."
        )

    values = list(outcomes)
    if len(values) != expected_count:
        raise ModelabilityIndexError(
            "The number of outcomes must match the number of fingerprint rows."
        )

    normalized: list[str] = []
    invalid_indices: list[int] = []

    for index, value in enumerate(values):
        text = "" if value is None else str(value).strip().lower()
        outcome = BINARY_OUTCOMES.get(text)
        if outcome is None:
            invalid_indices.append(index)
        else:
            normalized.append(outcome)

    if invalid_indices:
        indices = ", ".join(str(index) for index in invalid_indices)
        raise ModelabilityIndexError(
            "Outcomes must contain only Active or Inactive; "
            f"invalid rows: {indices}."
        )

    labels = np.asarray(normalized, dtype=object)
    counts = {
        "Active": int(np.sum(labels == "Active")),
        "Inactive": int(np.sum(labels == "Inactive")),
    }

    if counts["Active"] == 0 or counts["Inactive"] == 0:
        raise ModelabilityIndexError(
            "Both Active and Inactive outcomes are required."
        )

    if counts["Active"] < 2 or counts["Inactive"] < 2:
        raise ModelabilityIndexError(
            "Each outcome class must contain at least two structures; "
            f"counts: Active={counts['Active']}, "
            f"Inactive={counts['Inactive']}."
        )

    return labels, counts


def _nearest_neighbors_by_tanimoto(
    fingerprints: npt.NDArray[np.uint8],
    *,
    block_size: int,
) -> tuple[
    npt.NDArray[np.int64],
    npt.NDArray[np.float64],
    npt.NDArray[np.int64],
]:
    structure_count = fingerprints.shape[0]

    working = fingerprints.astype(np.int32, copy=False)
    bit_counts = working.sum(axis=1, dtype=np.int64)

    neighbor_indices = np.empty(structure_count, dtype=np.int64)
    neighbor_similarities = np.empty(structure_count, dtype=np.float64)
    neighbor_tie_counts = np.empty(structure_count, dtype=np.int64)

    for start in range(0, structure_count, block_size):
        end = min(start + block_size, structure_count)

        intersections = working[start:end] @ working.T
        unions = (
            bit_counts[start:end, np.newaxis]
            + bit_counts[np.newaxis, :]
            - intersections
        )

        similarities = intersections.astype(np.float64) / unions

        local_rows = np.arange(end - start)
        global_rows = np.arange(start, end)
        similarities[local_rows, global_rows] = -1.0

        maximum_similarities = similarities.max(axis=1)
        tied_neighbors = (
            similarities == maximum_similarities[:, np.newaxis]
        )

        # np.argmax returns the first maximum, so equal similarities are
        # resolved deterministically by the lowest input index.
        neighbor_indices[start:end] = np.argmax(
            tied_neighbors,
            axis=1,
        )
        neighbor_similarities[start:end] = maximum_similarities
        neighbor_tie_counts[start:end] = tied_neighbors.sum(
            axis=1,
            dtype=np.int64,
        )

    return (
        neighbor_indices,
        neighbor_similarities,
        neighbor_tie_counts,
    )


def calculate_modelability_index(
    fingerprints: npt.ArrayLike,
    outcomes: Sequence[str],
    *,
    block_size: int = DEFAULT_BLOCK_SIZE,
) -> ModelabilityIndexResult:
    """Calculate macro-averaged nearest-neighbor outcome concordance."""
    if (
        isinstance(block_size, bool)
        or not isinstance(block_size, int)
        or block_size <= 0
    ):
        raise ModelabilityIndexError(
            "block_size must be a positive integer."
        )

    binary = _validate_fingerprints(fingerprints)
    labels, counts = _normalize_outcomes(
        outcomes,
        expected_count=binary.shape[0],
    )

    (
        neighbor_indices,
        neighbor_similarities,
        neighbor_tie_counts,
    ) = _nearest_neighbors_by_tanimoto(
        binary,
        block_size=block_size,
    )

    neighbor_labels = labels[neighbor_indices]
    concordant = labels == neighbor_labels

    active_mask = labels == "Active"
    inactive_mask = labels == "Inactive"

    active_contribution = float(np.mean(concordant[active_mask]))
    inactive_contribution = float(np.mean(concordant[inactive_mask]))
    index_value = (
        active_contribution + inactive_contribution
    ) / 2.0

    diagnostics = tuple(
        ModelabilityStructureDiagnostic(
            input_index=index,
            outcome=str(labels[index]),
            nearest_neighbor_index=int(neighbor_indices[index]),
            nearest_neighbor_outcome=str(neighbor_labels[index]),
            nearest_neighbor_similarity=float(
                neighbor_similarities[index]
            ),
            outcome_concordant=bool(concordant[index]),
            nearest_neighbor_tie_count=int(
                neighbor_tie_counts[index]
            ),
        )
        for index in range(binary.shape[0])
    )

    concordant_count = int(np.sum(concordant))

    return ModelabilityIndexResult(
        modelability_index=index_value,
        active_contribution=active_contribution,
        inactive_contribution=inactive_contribution,
        active_count=counts["Active"],
        inactive_count=counts["Inactive"],
        total_structure_count=binary.shape[0],
        concordant_structure_count=concordant_count,
        discordant_structure_count=(
            binary.shape[0] - concordant_count
        ),
        tie_affected_structure_count=int(
            np.sum(neighbor_tie_counts > 1)
        ),
        diagnostics=diagnostics,
    )