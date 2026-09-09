import pytest

from services import murcko_nn_interface as service
from services.modelability_index import ModelabilityIndexResult
from services.murcko_population import MurckoPopulationResult


def test_murcko_nn_interface_decomposes_selected_neighbor_graph():
    population = MurckoPopulationResult(
        total_count=6,
        cyclic_count=3,
        acyclic_count=3,
        murcko_coverage=0.5,
        scaffold_count=2,
        assignments=(
            "S1",
            "S1",
            "S2",
            None,
            None,
            None,
        ),
        scaffold_outcome_counts={
            "S1": {"Active": 2, "Inactive": 0},
            "S2": {"Active": 0, "Inactive": 1},
        },
    )
    outcomes = (
        "Active",
        "Active",
        "Inactive",
        "Inactive",
        "Active",
        "Inactive",
    )
    modelability = ModelabilityIndexResult(
        active_concordance=1 / 3,
        inactive_concordance=2 / 3,
        modelability_index=0.5,
        neighbor_indices=(1, 2, 3, 2, 5, 4),
        neighbor_similarities=(0.9, 0.8, 0.7, 0.7, 0.6, 0.6),
        concordant=(True, False, True, True, False, False),
    )

    result = service.analyze_murcko_nn_interface(
        population,
        outcomes,
        modelability,
    )

    assert result.cc_count == 2
    assert result.ca_count == 1
    assert result.ac_count == 1
    assert result.aa_count == 2

    assert result.murcko_nn_coverage == pytest.approx(2 / 6)
    assert result.murcko_nn_coverage <= population.murcko_coverage

    assert result.same_scaffold_count == 1
    assert result.different_scaffold_count == 1
    assert result.same_scaffold_nn_fraction == pytest.approx(1 / 2)

    assert result.same_scaffold_concordance == pytest.approx(1.0)
    assert result.different_scaffold_concordance == pytest.approx(0.0)

    assert result.reconstructed_active_concordance == pytest.approx(
        modelability.active_concordance
    )
    assert result.reconstructed_inactive_concordance == pytest.approx(
        modelability.inactive_concordance
    )
    assert result.reconstructed_modelability_index == pytest.approx(
        modelability.modelability_index
    )

    assert sum(result.transition_counts.values()) == population.total_count
