from collections.abc import Sequence
from dataclasses import dataclass

from services.modelability_index import ModelabilityIndexResult
from services.murcko_population import MurckoPopulationResult


_BINARY_OUTCOMES = {"Active", "Inactive"}


class MurckoNNInterfaceError(ValueError):
    """Raised when Murcko and nearest-neighbor evidence are misaligned."""


@dataclass(frozen=True)
class MurckoNNInterfaceResult:
    cc_count: int
    ca_count: int
    ac_count: int
    aa_count: int
    murcko_nn_coverage: float
    same_scaffold_count: int
    different_scaffold_count: int
    same_scaffold_nn_fraction: float | None
    same_scaffold_concordance: float | None
    different_scaffold_concordance: float | None
    reconstructed_active_concordance: float
    reconstructed_inactive_concordance: float
    reconstructed_modelability_index: float
    transition_counts: dict[str, int]


def analyze_murcko_nn_interface(
    population: MurckoPopulationResult,
    outcomes: Sequence[str],
    modelability: ModelabilityIndexResult,
) -> MurckoNNInterfaceResult:
    """Describe how selected nearest-neighbor edges cross Murcko domains."""
    outcome_values = tuple(outcomes)
    assignments = population.assignments
    neighbor_indices = modelability.neighbor_indices
    concordant = modelability.concordant

    total_count = population.total_count

    if len(assignments) != total_count:
        raise MurckoNNInterfaceError(
            "Murcko assignments must match the population size."
        )

    if len(outcome_values) != total_count:
        raise MurckoNNInterfaceError(
            "Outcomes must match the population size."
        )

    if len(neighbor_indices) != total_count:
        raise MurckoNNInterfaceError(
            "Neighbor indices must match the population size."
        )

    if len(concordant) != total_count:
        raise MurckoNNInterfaceError(
            "Concordance values must match the population size."
        )

    if set(outcome_values) != _BINARY_OUTCOMES:
        raise MurckoNNInterfaceError(
            "Both Active and Inactive outcomes are required."
        )

    transition_counts = {
        "CC": 0,
        "CA": 0,
        "AC": 0,
        "AA": 0,
    }

    same_scaffold_count = 0
    different_scaffold_count = 0
    same_scaffold_concordant = 0
    different_scaffold_concordant = 0

    active_count = 0
    inactive_count = 0
    active_concordant = 0
    inactive_concordant = 0

    for index, neighbor_index in enumerate(neighbor_indices):
        if neighbor_index < 0 or neighbor_index >= total_count:
            raise MurckoNNInterfaceError(
                "Neighbor index is outside the population."
            )

        source_scaffold = assignments[index]
        neighbor_scaffold = assignments[neighbor_index]

        source_cyclic = source_scaffold is not None
        neighbor_cyclic = neighbor_scaffold is not None

        if source_cyclic and neighbor_cyclic:
            transition = "CC"

            if source_scaffold == neighbor_scaffold:
                same_scaffold_count += 1
                if concordant[index]:
                    same_scaffold_concordant += 1
            else:
                different_scaffold_count += 1
                if concordant[index]:
                    different_scaffold_concordant += 1

        elif source_cyclic and not neighbor_cyclic:
            transition = "CA"

        elif not source_cyclic and neighbor_cyclic:
            transition = "AC"

        else:
            transition = "AA"

        transition_counts[transition] += 1

        expected_concordance = (
            outcome_values[index]
            == outcome_values[neighbor_index]
        )
        if bool(concordant[index]) != expected_concordance:
            raise MurckoNNInterfaceError(
                "Stored concordance is inconsistent with outcomes "
                "and the selected neighbor."
            )

        if outcome_values[index] == "Active":
            active_count += 1
            if concordant[index]:
                active_concordant += 1
        else:
            inactive_count += 1
            if concordant[index]:
                inactive_concordant += 1

    cc_count = transition_counts["CC"]
    ca_count = transition_counts["CA"]
    ac_count = transition_counts["AC"]
    aa_count = transition_counts["AA"]

    reconstructed_active_concordance = (
        active_concordant / active_count
    )
    reconstructed_inactive_concordance = (
        inactive_concordant / inactive_count
    )
    reconstructed_modelability_index = (
        reconstructed_active_concordance
        + reconstructed_inactive_concordance
    ) / 2.0

    return MurckoNNInterfaceResult(
        cc_count=cc_count,
        ca_count=ca_count,
        ac_count=ac_count,
        aa_count=aa_count,
        murcko_nn_coverage=cc_count / total_count,
        same_scaffold_count=same_scaffold_count,
        different_scaffold_count=different_scaffold_count,
        same_scaffold_nn_fraction=(
            same_scaffold_count / cc_count
            if cc_count > 0
            else None
        ),
        same_scaffold_concordance=(
            same_scaffold_concordant / same_scaffold_count
            if same_scaffold_count > 0
            else None
        ),
        different_scaffold_concordance=(
            different_scaffold_concordant
            / different_scaffold_count
            if different_scaffold_count > 0
            else None
        ),
        reconstructed_active_concordance=(
            reconstructed_active_concordance
        ),
        reconstructed_inactive_concordance=(
            reconstructed_inactive_concordance
        ),
        reconstructed_modelability_index=(
            reconstructed_modelability_index
        ),
        transition_counts=transition_counts,
    )
