# SPDX-License-Identifier: LGPL-3.0-or-later
from harmonsmile import PubChemIngest, PubChemConfig
import pandas as pd
import os 

def use_PubchemIngest(df: pd.DataFrame) -> pd.DataFrame:
    if df.shape[1] != 1:
        raise ValueError("El DataFrame debe tener exactamente una columna.")
    # Validación dura: la columna debe contener solo CIDs (enteros positivos)
    col = df.iloc[:, 0]
    numeric = pd.to_numeric(col, errors="coerce")
    SQLITE_MAX_INT = 9223372036854775807  # límite de INTEGER en SQLite (64 bits)
    if numeric.isna().any() or (numeric <= 0).any() or (numeric > SQLITE_MAX_INT).any():
        raise ValueError(
            "The selected column does not contain valid PubChem CIDs. "
            "CIDs must be positive integers within a valid range. "
            "Please select the column that contains PubChem CIDs."
        )

    input_path = "tempFilesHarmonsile/res_pubchem.csv"
    output_path = "tempFilesHarmonsile/res_pubchem_harmonized.csv"
    temp_df = df.copy()
    temp_df.columns = ["PubChem CID"] ##nota para doctor: harmonsmile me estaba separando la columna pubchem CID en dos cuando solo le mandaba una
    temp_df.to_csv(input_path, index=True)
    cfg = PubChemConfig(
        input_path=input_path,
        output_path=output_path,
    )
    PubChemIngest(cfg).run()
    result_df = pd.read_csv(output_path)
    result_df.columns = ( #preparamos los datos para ser procesados por sql
        result_df.columns
        .str.replace(" ", "_", regex=False)
        .str.replace(":", "", regex=False)
    )
    os.remove(input_path)
    os.remove(output_path)

    return result_df
