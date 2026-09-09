import pytest

from services import murcko_metrics as service
from services.murcko_population import MurckoPopulationResult


def test_murcko_metrics_decompose_scaffold_label_organization():
    population = MurckoPopulationResult(
        total_count=8,
        cyclic_count=6,
        acyclic_count=2,
        murcko_coverage=6 / 8,
        scaffold_count=3,
        assignments=(
            "S1",
            "S1",
            "S2",
            "S2",
            "S3",
            "S3",
            None,
            None,
        ),
        scaffold_outcome_counts={
            "S1": {"Active": 2, "Inactive": 0},
            "S2": {"Active": 0, "Inactive": 2},
            "S3": {"Active": 1, "Inactive": 1},
        },
    )

    result = service.calculate_murcko_structural_metrics(population)

    assert result.shared_scaffold_count == 1
    assert result.shared_molecule_count == 2

    assert result.shared_scaffold_fraction == pytest.approx(1 / 3)
    assert result.shared_molecular_coverage == pytest.approx(1 / 3)
    assert result.within_shared_balance == pytest.approx(1.0)

    assert result.global_balance == pytest.approx(1.0)
    assert result.within_balance == pytest.approx(1 / 3)
    assert result.within_ratio == pytest.approx(1 / 3)
    assert result.eta_squared == pytest.approx(2 / 3)

    assert result.null_within_ratio == pytest.approx(3 / 5)
    assert result.epsilon_squared == pytest.approx(4 / 9)


def test_murcko_metrics_preserve_negative_epsilon_squared():
    population = MurckoPopulationResult(
        total_count=6,
        cyclic_count=6,
        acyclic_count=0,
        murcko_coverage=1.0,
        scaffold_count=3,
        assignments=(
            "S1",
            "S1",
            "S1",
            "S1",
            "S2",
            "S3",
        ),
        scaffold_outcome_counts={
            "S1": {"Active": 2, "Inactive": 2},
            "S2": {"Active": 1, "Inactive": 0},
            "S3": {"Active": 0, "Inactive": 1},
        },
    )

    result = service.calculate_murcko_structural_metrics(population)

    assert result.global_balance == pytest.approx(1.0)
    assert result.within_balance == pytest.approx(2 / 3)
    assert result.within_ratio == pytest.approx(2 / 3)
    assert result.null_within_ratio == pytest.approx(3 / 5)

    assert result.epsilon_squared == pytest.approx(-1 / 9)


def test_murcko_metrics_leave_epsilon_undefined_without_within_scaffold_replication():
    population = MurckoPopulationResult(
        total_count=4,
        cyclic_count=4,
        acyclic_count=0,
        murcko_coverage=1.0,
        scaffold_count=4,
        assignments=("S1", "S2", "S3", "S4"),
        scaffold_outcome_counts={
            "S1": {"Active": 1, "Inactive": 0},
            "S2": {"Active": 1, "Inactive": 0},
            "S3": {"Active": 0, "Inactive": 1},
            "S4": {"Active": 0, "Inactive": 1},
        },
    )

    result = service.calculate_murcko_structural_metrics(population)

    assert result.shared_scaffold_fraction == pytest.approx(0.0)
    assert result.shared_molecular_coverage == pytest.approx(0.0)
    assert result.within_shared_balance is None

    assert result.global_balance == pytest.approx(1.0)
    assert result.within_balance == pytest.approx(0.0)
    assert result.within_ratio == pytest.approx(0.0)
    assert result.eta_squared == pytest.approx(1.0)

    assert result.null_within_ratio == pytest.approx(0.0)
    assert result.epsilon_squared is None
