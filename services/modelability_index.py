# SPDX-License-Identifier: LGPL-3.0-or-later
"""Numerical core for the binary Modelability Index."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt


_BLOCK_SIZE = 512
_BINARY_OUTCOMES = {"Active", "Inactive"}


class ModelabilityIndexError(ValueError):
    """Raised when the Modelability Index is not defined for an input."""


@dataclass(frozen=True)
class ModelabilityIndexResult:
    active_concordance: float
    inactive_concordance: float
    modelability_index: float
    neighbor_indices: tuple[int, ...]
    neighbor_similarities: tuple[float, ...]
    concordant: tuple[bool, ...]


@dataclass(frozen=True)
class NearestNeighborDiagnostics:
    maximum_neighbor_indices: tuple[tuple[int, ...], ...]
    maximum_similarities: tuple[float, ...]
    tied_neighbor_counts: tuple[int, ...]
    tie_fraction: float
    tie_sensitive_fraction: float
    fingerprint_identical_fraction: float
    fingerprint_identical_label_conflict_fraction: float
    active_concordance_min: float
    active_concordance_max: float
    inactive_concordance_min: float
    inactive_concordance_max: float
    modelability_index_min: float
    modelability_index_max: float


def calculate_modelability_index(
    fingerprints: npt.NDArray[np.uint8],
    outcomes: Sequence[str],
) -> ModelabilityIndexResult:
    """Calculate exact single-neighbor concordance for two outcome classes."""
    matrix = np.asarray(fingerprints)
    labels = np.asarray(tuple(outcomes), dtype=object)

    if matrix.ndim != 2 or matrix.shape[0] < 2:
        raise ModelabilityIndexError(
            "At least two fingerprint rows are required."
        )
    if len(labels) != matrix.shape[0]:
        raise ModelabilityIndexError(
            "The number of outcomes must match the fingerprint rows."
        )
    if set(labels) != _BINARY_OUTCOMES:
        raise ModelabilityIndexError(
            "Both Active and Inactive outcomes are required."
        )

    working = matrix.astype(np.int32, copy=False)
    bit_counts = working.sum(axis=1, dtype=np.int64)
    structure_count = matrix.shape[0]
    neighbor_indices = np.empty(structure_count, dtype=np.int64)
    neighbor_similarities = np.empty(structure_count, dtype=np.float64)

    for start in range(0, structure_count, _BLOCK_SIZE):
        end = min(start + _BLOCK_SIZE, structure_count)
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

        # argmax selects the lowest ordered index when similarities tie.
        block_neighbors = np.argmax(similarities, axis=1)
        neighbor_indices[start:end] = block_neighbors
        neighbor_similarities[start:end] = similarities[
            local_rows,
            block_neighbors,
        ]

    concordant = labels == labels[neighbor_indices]
    active_concordance = float(np.mean(concordant[labels == "Active"]))
    inactive_concordance = float(np.mean(concordant[labels == "Inactive"]))

    return ModelabilityIndexResult(
        active_concordance=active_concordance,
        inactive_concordance=inactive_concordance,
        modelability_index=(
            active_concordance + inactive_concordance
        ) / 2.0,
        neighbor_indices=tuple(int(index) for index in neighbor_indices),
        neighbor_similarities=tuple(
            float(similarity) for similarity in neighbor_similarities
        ),
        concordant=tuple(bool(value) for value in concordant),
    )


def calculate_nearest_neighbor_diagnostics(
    fingerprints: npt.NDArray[np.uint8],
    outcomes: Sequence[str],
) -> NearestNeighborDiagnostics:
    """Diagnose exact nearest-neighbor ties without changing index selection."""
    matrix = np.asarray(fingerprints)
    labels = np.asarray(tuple(outcomes), dtype=object)

    if matrix.ndim != 2 or matrix.shape[0] < 2:
        raise ModelabilityIndexError(
            "At least two fingerprint rows are required."
        )
    if len(labels) != matrix.shape[0]:
        raise ModelabilityIndexError(
            "The number of outcomes must match the fingerprint rows."
        )
    if set(labels) != _BINARY_OUTCOMES:
        raise ModelabilityIndexError(
            "Both Active and Inactive outcomes are required."
        )

    working = matrix.astype(np.int32, copy=False)
    bit_counts = working.sum(axis=1, dtype=np.int64)
    structure_count = matrix.shape[0]

    maximum_neighbor_indices: list[tuple[int, ...]] = []
    maximum_similarities = np.empty(structure_count, dtype=np.float64)
    tied_neighbor_counts = np.empty(structure_count, dtype=np.int64)
    concordance_min = np.empty(structure_count, dtype=bool)
    concordance_max = np.empty(structure_count, dtype=bool)
    fingerprint_identical = np.empty(structure_count, dtype=bool)
    fingerprint_identical_label_conflict = np.empty(
        structure_count,
        dtype=bool,
    )

    for start in range(0, structure_count, _BLOCK_SIZE):
        end = min(start + _BLOCK_SIZE, structure_count)
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

        for local_index, global_index in enumerate(global_rows):
            row = similarities[local_index]
            maximum_similarity = float(np.max(row))

            # Use exact equality because the existing argmax tie contract
            # is based on exactly equal similarity values.
            tied_indices = np.flatnonzero(
                row == maximum_similarity
            )

            tied_indices_tuple = tuple(
                int(index) for index in tied_indices
            )
            maximum_neighbor_indices.append(tied_indices_tuple)
            maximum_similarities[global_index] = maximum_similarity
            tied_neighbor_counts[global_index] = len(tied_indices_tuple)

            neighbor_labels = labels[tied_indices]
            same_label = neighbor_labels == labels[global_index]

            concordance_min[global_index] = bool(np.all(same_label))
            concordance_max[global_index] = bool(np.any(same_label))

            is_fingerprint_identical = maximum_similarity == 1.0
            fingerprint_identical[global_index] = (
                is_fingerprint_identical
            )
            fingerprint_identical_label_conflict[global_index] = (
                is_fingerprint_identical
                and bool(np.any(~same_label))
            )

    active_mask = labels == "Active"
    inactive_mask = labels == "Inactive"

    active_concordance_min = float(
        np.mean(concordance_min[active_mask])
    )
    active_concordance_max = float(
        np.mean(concordance_max[active_mask])
    )
    inactive_concordance_min = float(
        np.mean(concordance_min[inactive_mask])
    )
    inactive_concordance_max = float(
        np.mean(concordance_max[inactive_mask])
    )

    return NearestNeighborDiagnostics(
        maximum_neighbor_indices=tuple(maximum_neighbor_indices),
        maximum_similarities=tuple(
            float(value) for value in maximum_similarities
        ),
        tied_neighbor_counts=tuple(
            int(value) for value in tied_neighbor_counts
        ),
        tie_fraction=float(np.mean(tied_neighbor_counts > 1)),
        tie_sensitive_fraction=float(
            np.mean(concordance_min != concordance_max)
        ),
        fingerprint_identical_fraction=float(
            np.mean(fingerprint_identical)
        ),
        fingerprint_identical_label_conflict_fraction=float(
            np.mean(fingerprint_identical_label_conflict)
        ),
        active_concordance_min=active_concordance_min,
        active_concordance_max=active_concordance_max,
        inactive_concordance_min=inactive_concordance_min,
        inactive_concordance_max=inactive_concordance_max,
        modelability_index_min=(
            active_concordance_min + inactive_concordance_min
        )
        / 2.0,
        modelability_index_max=(
            active_concordance_max + inactive_concordance_max
        )
        / 2.0,
    )
