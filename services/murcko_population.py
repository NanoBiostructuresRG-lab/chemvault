from collections.abc import Sequence
from dataclasses import dataclass

from services.murcko_scaffold import derive_murcko_scaffold


_BINARY_OUTCOMES = {"Active", "Inactive"}


class MurckoPopulationError(ValueError):
    """Raised when a Murcko population analysis input is invalid."""


@dataclass(frozen=True)
class MurckoPopulationResult:
    total_count: int
    cyclic_count: int
    acyclic_count: int
    murcko_coverage: float
    scaffold_count: int
    assignments: tuple[str | None, ...]
    scaffold_outcome_counts: dict[str, dict[str, int]]


def analyze_murcko_population(
    smiles: Sequence[str],
    outcomes: Sequence[str],
) -> MurckoPopulationResult:
    """Characterize Murcko scaffold coverage for a molecular population."""
    smiles_values = tuple(smiles)
    outcome_values = tuple(outcomes)

    if len(smiles_values) != len(outcome_values):
        raise MurckoPopulationError(
            "The number of SMILES must match the number of outcomes."
        )

    if not smiles_values:
        raise MurckoPopulationError(
            "At least one molecular structure is required."
        )

    if set(outcome_values) != _BINARY_OUTCOMES:
        raise MurckoPopulationError(
            "Both Active and Inactive outcomes are required."
        )

    assignments: list[str | None] = []
    scaffold_outcome_counts: dict[str, dict[str, int]] = {}
    cyclic_count = 0

    for structure_smiles, outcome in zip(
        smiles_values,
        outcome_values,
        strict=True,
    ):
        scaffold = derive_murcko_scaffold(structure_smiles)
        scaffold_smiles = scaffold.scaffold_smiles

        assignments.append(scaffold_smiles)

        if scaffold_smiles is None:
            continue

        cyclic_count += 1

        counts = scaffold_outcome_counts.setdefault(
            scaffold_smiles,
            {
                "Active": 0,
                "Inactive": 0,
            },
        )
        counts[outcome] += 1

    total_count = len(smiles_values)
    acyclic_count = total_count - cyclic_count

    return MurckoPopulationResult(
        total_count=total_count,
        cyclic_count=cyclic_count,
        acyclic_count=acyclic_count,
        murcko_coverage=cyclic_count / total_count,
        scaffold_count=len(scaffold_outcome_counts),
        assignments=tuple(assignments),
        scaffold_outcome_counts=scaffold_outcome_counts,
    )
