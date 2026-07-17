# SPDX-License-Identifier: LGPL-3.0-or-later

import numpy as np
import pytest

from services.modelability_index import (
    ModelabilityIndexError,
    calculate_modelability_index,
)


def _perfectly_separated_fingerprints():
    return np.asarray(
        [
            [1, 1, 0, 0],
            [1, 1, 0, 1],
            [0, 0, 1, 1],
            [0, 0, 1, 0],
        ],
        dtype=np.uint8,
    )


def test_calculates_perfect_binary_modelability_index():
    result = calculate_modelability_index(
        _perfectly_separated_fingerprints(),
        ["Active", "Active", "Inactive", "Inactive"],
        block_size=2,
    )

    assert result.modelability_index == pytest.approx(1.0)
    assert result.active_contribution == pytest.approx(1.0)
    assert result.inactive_contribution == pytest.approx(1.0)

    assert result.active_count == 2
    assert result.inactive_count == 2
    assert result.total_structure_count == 4
    assert result.concordant_structure_count == 4
    assert result.discordant_structure_count == 0
    assert result.tie_affected_structure_count == 0

    first = result.diagnostics[0]
    assert first.input_index == 0
    assert first.outcome == "Active"
    assert first.nearest_neighbor_index == 1
    assert first.nearest_neighbor_outcome == "Active"
    assert first.nearest_neighbor_similarity == pytest.approx(2 / 3)
    assert first.outcome_concordant is True
    assert first.nearest_neighbor_tie_count == 1


def test_macro_average_weights_active_and_inactive_equally():
    fingerprints = np.asarray(
        [
            [1, 0],
            [0, 1],
            [1, 1],
            [1, 1],
        ],
        dtype=np.uint8,
    )

    result = calculate_modelability_index(
        fingerprints,
        ["Active", "Active", "Inactive", "Inactive"],
    )

    assert result.active_contribution == pytest.approx(0.0)
    assert result.inactive_contribution == pytest.approx(1.0)
    assert result.modelability_index == pytest.approx(0.5)

    assert result.concordant_structure_count == 2
    assert result.discordant_structure_count == 2


def test_equal_similarity_uses_lowest_index_and_records_ties():
    fingerprints = np.asarray(
        [
            [1, 0],
            [0, 1],
            [1, 1],
            [1, 1],
        ],
        dtype=np.uint8,
    )

    result = calculate_modelability_index(
        fingerprints,
        ["Active", "Active", "Inactive", "Inactive"],
        block_size=2,
    )

    assert result.diagnostics[0].nearest_neighbor_index == 2
    assert result.diagnostics[0].nearest_neighbor_tie_count == 2

    assert result.diagnostics[1].nearest_neighbor_index == 2
    assert result.diagnostics[1].nearest_neighbor_tie_count == 2

    assert result.tie_affected_structure_count == 2


def test_block_size_does_not_change_exact_result():
    fingerprints = _perfectly_separated_fingerprints()
    outcomes = ["Active", "Active", "Inactive", "Inactive"]

    one_row_blocks = calculate_modelability_index(
        fingerprints,
        outcomes,
        block_size=1,
    )
    one_block = calculate_modelability_index(
        fingerprints,
        outcomes,
        block_size=4,
    )

    assert one_row_blocks == one_block


def test_outcomes_are_normalized_to_canonical_binary_labels():
    result = calculate_modelability_index(
        _perfectly_separated_fingerprints(),
        [" active ", "ACTIVE", "inactive", " Inactive "],
    )

    assert tuple(
        diagnostic.outcome for diagnostic in result.diagnostics
    ) == (
        "Active",
        "Active",
        "Inactive",
        "Inactive",
    )


def test_does_not_mutate_input_fingerprint_array():
    fingerprints = _perfectly_separated_fingerprints()
    original = fingerprints.copy()

    calculate_modelability_index(
        fingerprints,
        ["Active", "Active", "Inactive", "Inactive"],
    )

    np.testing.assert_array_equal(fingerprints, original)


def test_rejects_outcome_count_mismatch():
    with pytest.raises(
        ModelabilityIndexError,
        match="number of outcomes",
    ):
        calculate_modelability_index(
            _perfectly_separated_fingerprints(),
            ["Active", "Active"],
        )


def test_rejects_non_binary_outcome():
    with pytest.raises(
        ModelabilityIndexError,
        match="only Active or Inactive",
    ):
        calculate_modelability_index(
            _perfectly_separated_fingerprints(),
            ["Active", "Active", "Inactive", "Unknown"],
        )


@pytest.mark.parametrize(
    "outcomes, expected_message",
    [
        (
            ["Active", "Active", "Active", "Active"],
            "Both Active and Inactive",
        ),
        (
            ["Active", "Active", "Active", "Inactive"],
            "at least two structures",
        ),
    ],
)
def test_requires_two_binary_classes_with_two_structures_each(
    outcomes,
    expected_message,
):
    with pytest.raises(
        ModelabilityIndexError,
        match=expected_message,
    ):
        calculate_modelability_index(
            _perfectly_separated_fingerprints(),
            outcomes,
        )


@pytest.mark.parametrize(
    "fingerprints, expected_message",
    [
        (
            np.asarray([1, 0, 1]),
            "two-dimensional",
        ),
        (
            np.empty((4, 0), dtype=np.uint8),
            "at least one bit",
        ),
        (
            np.asarray(
                [
                    [1, 0],
                    [1, 2],
                    [0, 1],
                    [1, 1],
                ]
            ),
            "only binary values",
        ),
        (
            np.asarray(
                [
                    [1, 0],
                    [0, 0],
                    [0, 1],
                    [1, 1],
                ]
            ),
            "all-zero rows: 1",
        ),
        (
            np.asarray(
                [
                    [1.0, 0.0],
                    [1.0, np.nan],
                    [0.0, 1.0],
                    [1.0, 1.0],
                ]
            ),
            "finite binary values",
        ),
    ],
)
def test_rejects_invalid_fingerprint_matrices(
    fingerprints,
    expected_message,
):
    with pytest.raises(
        ModelabilityIndexError,
        match=expected_message,
    ):
        calculate_modelability_index(
            fingerprints,
            ["Active", "Active", "Inactive", "Inactive"],
        )


@pytest.mark.parametrize("block_size", [0, -1, True, 1.5])
def test_rejects_invalid_block_size(block_size):
    with pytest.raises(
        ModelabilityIndexError,
        match="positive integer",
    ):
        calculate_modelability_index(
            _perfectly_separated_fingerprints(),
            ["Active", "Active", "Inactive", "Inactive"],
            block_size=block_size,
        )