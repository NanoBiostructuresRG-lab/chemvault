# SPDX-License-Identifier: LGPL-3.0-or-later
from rdkit import Chem
import pandas as pd

# Ruta al archivo SDF
file = "watermelon-03-2026"

supplier = Chem.SDMolSupplier(file+".sdf")

data = []

for mol in supplier:
    if mol is None:
        continue
    props = mol.GetPropsAsDict()
    data.append(props)

df = pd.DataFrame(data)
df.to_csv(file+".csv", index=False)

print("Conversión completa")