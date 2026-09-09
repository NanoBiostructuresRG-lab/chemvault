from dataclasses import dataclass

from services.murcko_population import MurckoPopulationResult


@dataclass(frozen=True)
class MurckoStructuralMetrics:
    shared_scaffold_count: int
    shared_molecule_count: int
    shared_scaffold_fraction: float | None
    shared_molecular_coverage: float | None
    within_shared_balance: float | None
    global_balance: float | None
    within_balance: float | None
    within_ratio: float | None
    eta_squared: float | None
    null_within_ratio: float | None
    epsilon_squared: float | None


def calculate_murcko_structural_metrics(
    population: MurckoPopulationResult,
) -> MurckoStructuralMetrics:
    """Quantify binary-label organization across Murcko scaffolds."""
    cyclic_count = population.cyclic_count
    scaffold_count = population.scaffold_count

    shared_scaffold_count = 0
    shared_molecule_count = 0

    within_balance_sum = 0.0
    shared_balance_sum = 0.0

    active_count = 0
    inactive_count = 0

    for counts in population.scaffold_outcome_counts.values():
        active = counts["Active"]
        inactive = counts["Inactive"]
        scaffold_size = active + inactive

        active_count += active
        inactive_count += inactive

        if scaffold_size == 0:
            continue

        active_fraction = active / scaffold_size
        scaffold_balance = (
            4.0
            * active_fraction
            * (1.0 - active_fraction)
        )

        within_balance_sum += scaffold_size * scaffold_balance

        if active > 0 and inactive > 0:
            shared_scaffold_count += 1
            shared_molecule_count += scaffold_size
            shared_balance_sum += scaffold_size * scaffold_balance

    shared_scaffold_fraction = (
        shared_scaffold_count / scaffold_count
        if scaffold_count > 0
        else None
    )

    shared_molecular_coverage = (
        shared_molecule_count / cyclic_count
        if cyclic_count > 0
        else None
    )

    within_shared_balance = (
        shared_balance_sum / shared_molecule_count
        if shared_molecule_count > 0
        else None
    )

    if cyclic_count > 0:
        active_fraction_global = active_count / cyclic_count
        global_balance = (
            4.0
            * active_fraction_global
            * (1.0 - active_fraction_global)
        )
        within_balance = within_balance_sum / cyclic_count
    else:
        global_balance = None
        within_balance = None

    if global_balance is not None and global_balance > 0.0:
        within_ratio = within_balance / global_balance
        eta_squared = 1.0 - within_ratio
    else:
        within_ratio = None
        eta_squared = None

    if cyclic_count > 1:
        null_within_ratio = (
            cyclic_count - scaffold_count
        ) / (cyclic_count - 1)
    else:
        null_within_ratio = None

    if (
        within_ratio is not None
        and null_within_ratio is not None
        and null_within_ratio > 0.0
    ):
        epsilon_squared = (
            1.0
            - within_ratio / null_within_ratio
        )
    else:
        epsilon_squared = None

    return MurckoStructuralMetrics(
        shared_scaffold_count=shared_scaffold_count,
        shared_molecule_count=shared_molecule_count,
        shared_scaffold_fraction=shared_scaffold_fraction,
        shared_molecular_coverage=shared_molecular_coverage,
        within_shared_balance=within_shared_balance,
        global_balance=global_balance,
        within_balance=within_balance,
        within_ratio=within_ratio,
        eta_squared=eta_squared,
        null_within_ratio=null_within_ratio,
        epsilon_squared=epsilon_squared,
    )
