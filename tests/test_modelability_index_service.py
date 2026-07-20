# SPDX-License-Identifier: LGPL-3.0-or-later

import numpy as np
import pytest

from services import modelability_index as service
from services.modelability_index import ModelabilityIndexError


def test_exact_tanimoto_neighbors_exclude_self_across_blocks(monkeypatch):
    monkeypatch.setattr(service, "_BLOCK_SIZE", 2)
    fingerprints = np.asarray(
        [
            [1, 1, 0, 0],
            [1, 1, 0, 1],
            [0, 0, 1, 1],
            [0, 0, 1, 0],
        ],
        dtype=np.uint8,
    )

    result = service.calculate_modelability_index(
        fingerprints,
        ["Active", "Active", "Inactive", "Inactive"],
    )

    assert result.neighbor_indices == (1, 0, 3, 2)
    assert result.neighbor_similarities == pytest.approx(
        (2 / 3, 2 / 3, 1 / 2, 1 / 2)
    )
    assert all(
        index != neighbor
        for index, neighbor in enumerate(result.neighbor_indices)
    )
    assert result.active_concordance == pytest.approx(1.0)
    assert result.inactive_concordance == pytest.approx(1.0)
    assert result.modelability_index == pytest.approx(1.0)


def test_equal_similarity_ties_use_lowest_ordered_index():
    fingerprints = np.asarray(
        [
            [1, 0],
            [0, 1],
            [1, 1],
            [1, 1],
        ],
        dtype=np.uint8,
    )

    result = service.calculate_modelability_index(
        fingerprints,
        ["Active", "Active", "Inactive", "Inactive"],
    )

    assert result.neighbor_indices == (2, 2, 3, 2)
    assert result.neighbor_similarities == pytest.approx(
        (0.5, 0.5, 1.0, 1.0)
    )


def test_macro_average_differs_from_micro_average_for_imbalanced_classes():
    fingerprints = np.asarray(
        [
            [1, 0],
            [1, 0],
            [0, 1],
            [0, 1],
            [0, 1],
        ],
        dtype=np.uint8,
    )
    outcomes = ["Active", "Active", "Active", "Inactive", "Inactive"]

    result = service.calculate_modelability_index(fingerprints, outcomes)

    assert result.concordant == (True, True, False, False, False)
    assert result.active_concordance == pytest.approx(2 / 3)
    assert result.inactive_concordance == pytest.approx(0.0)
    assert result.modelability_index == pytest.approx(1 / 3)
    assert np.mean(result.concordant) == pytest.approx(2 / 5)
    assert result.modelability_index != pytest.approx(
        np.mean(result.concordant)
    )


def test_singleton_class_is_supported():
    fingerprints = np.asarray(
        [
            [1, 0],
            [1, 1],
            [0, 1],
        ],
        dtype=np.uint8,
    )

    result = service.calculate_modelability_index(
        fingerprints,
        ["Active", "Inactive", "Inactive"],
    )

    assert result.active_concordance == pytest.approx(0.0)
    assert result.inactive_concordance == pytest.approx(0.5)
    assert result.modelability_index == pytest.approx(0.25)


@pytest.mark.parametrize(
    "fingerprints, outcomes, message",
    [
        (np.asarray([[1, 0]], dtype=np.uint8), ["Active"], "At least two"),
        (
            np.asarray([[1, 0], [0, 1]], dtype=np.uint8),
            ["Active", "Active"],
            "Both Active and Inactive",
        ),
        (
            np.asarray([[1, 0], [0, 1]], dtype=np.uint8),
            ["Active"],
            "number of outcomes",
        ),
    ],
)
def test_rejects_only_inputs_where_the_index_is_undefined(
    fingerprints,
    outcomes,
    message,
):
    with pytest.raises(ModelabilityIndexError, match=message):
        service.calculate_modelability_index(fingerprints, outcomes)
