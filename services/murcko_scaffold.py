from dataclasses import dataclass

from rdkit import Chem
from rdkit.Chem.Scaffolds import MurckoScaffold


class MurckoScaffoldError(ValueError):
    """Raised when a Murcko scaffold cannot be derived from an input."""


@dataclass(frozen=True)
class MurckoScaffoldResult:
    scaffold_smiles: str | None
    is_cyclic: bool


def derive_murcko_scaffold(smiles: str) -> MurckoScaffoldResult:
    """Derive the canonical atom- and bond-aware Bemis-Murcko scaffold."""
    if not isinstance(smiles, str) or not smiles.strip():
        raise MurckoScaffoldError(
            "A non-empty SMILES string is required."
        )

    molecule = Chem.MolFromSmiles(smiles)
    if molecule is None:
        raise MurckoScaffoldError(
            f"Invalid SMILES: {smiles!r}"
        )

    scaffold = MurckoScaffold.GetScaffoldForMol(molecule)

    if scaffold.GetNumAtoms() == 0:
        return MurckoScaffoldResult(
            scaffold_smiles=None,
            is_cyclic=False,
        )

    scaffold_smiles = Chem.MolToSmiles(
        scaffold,
        isomericSmiles=False,
    )

    return MurckoScaffoldResult(
        scaffold_smiles=scaffold_smiles,
        is_cyclic=True,
    )
