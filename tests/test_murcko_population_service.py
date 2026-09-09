import pytest

from services import murcko_population as service


def test_murcko_population_tracks_coverage_and_scaffold_counts():
    smiles = [
        "Cc1ccccc1",
        "Oc1ccccc1",
        "c1ccncc1",
        "CCO",
        "CCN",
    ]
    outcomes = [
        "Active",
        "Inactive",
        "Active",
        "Active",
        "Inactive",
    ]

    result = service.analyze_murcko_population(
        smiles,
        outcomes,
    )

    assert result.total_count == 5
    assert result.cyclic_count == 3
    assert result.acyclic_count == 2
    assert result.murcko_coverage == pytest.approx(3 / 5)

    assert result.scaffold_count == 2

    assert result.assignments == (
        "c1ccccc1",
        "c1ccccc1",
        "c1ccncc1",
        None,
        None,
    )

    assert result.scaffold_outcome_counts == {
        "c1ccccc1": {
            "Active": 1,
            "Inactive": 1,
        },
        "c1ccncc1": {
            "Active": 1,
            "Inactive": 0,
        },
    }


def test_murcko_population_requires_matching_lengths():
    with pytest.raises(service.MurckoPopulationError):
        service.analyze_murcko_population(
            ["c1ccccc1", "CCO"],
            ["Active"],
        )


def test_murcko_population_requires_binary_outcomes():
    with pytest.raises(service.MurckoPopulationError):
        service.analyze_murcko_population(
            ["c1ccccc1", "c1ccncc1"],
            ["Active", "Unknown"],
        )
