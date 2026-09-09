import pytest

from services import murcko_scaffold as service


def test_cyclic_structures_with_same_core_share_murcko_scaffold():
    toluene = service.derive_murcko_scaffold("Cc1ccccc1")
    phenol = service.derive_murcko_scaffold("Oc1ccccc1")

    assert toluene.is_cyclic is True
    assert phenol.is_cyclic is True
    assert toluene.scaffold_smiles == "c1ccccc1"
    assert phenol.scaffold_smiles == "c1ccccc1"


def test_acyclic_structure_has_no_murcko_scaffold():
    result = service.derive_murcko_scaffold("CCO")

    assert result.is_cyclic is False
    assert result.scaffold_smiles is None


def test_murcko_scaffold_preserves_atom_and_bond_identity():
    benzene = service.derive_murcko_scaffold("c1ccccc1")
    pyridine = service.derive_murcko_scaffold("c1ccncc1")
    cyclohexane = service.derive_murcko_scaffold("C1CCCCC1")

    assert benzene.scaffold_smiles == "c1ccccc1"
    assert pyridine.scaffold_smiles == "c1ccncc1"
    assert cyclohexane.scaffold_smiles == "C1CCCCC1"

    assert len(
        {
            benzene.scaffold_smiles,
            pyridine.scaffold_smiles,
            cyclohexane.scaffold_smiles,
        }
    ) == 3


def test_stereoisomers_share_scaffold_when_chirality_is_excluded():
    first = service.derive_murcko_scaffold(
        "C[C@H](O)c1ccccc1"
    )
    second = service.derive_murcko_scaffold(
        "C[C@@H](O)c1ccccc1"
    )

    assert first.scaffold_smiles == "c1ccccc1"
    assert second.scaffold_smiles == "c1ccccc1"
    assert first.scaffold_smiles == second.scaffold_smiles


@pytest.mark.parametrize(
    "smiles",
    [
        "",
        "not-a-smiles",
    ],
)
def test_invalid_smiles_raise_murcko_scaffold_error(smiles):
    with pytest.raises(service.MurckoScaffoldError):
        service.derive_murcko_scaffold(smiles)
