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
