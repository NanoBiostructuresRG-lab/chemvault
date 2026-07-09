# SPDX-License-Identifier: LGPL-3.0-or-later
from harmonsmile import PubChemIngest, PubChemConfig
import pandas as pd
import os 
import csv

HARMONSMILE_INPUT_CID_COLUMN = "CID"


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

    temp_dir = "tempFilesHarmonsile"
    os.makedirs(temp_dir, exist_ok=True)
    input_path = os.path.join(temp_dir, "res_pubchem.csv")
    temp_df = df.copy()
    temp_df.columns = [HARMONSMILE_INPUT_CID_COLUMN]
    with open(input_path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        # Empty second field forces HARMONSMILE's CSV sniffer to choose comma.
        writer.writerow([HARMONSMILE_INPUT_CID_COLUMN, ""])
        for cid in temp_df[HARMONSMILE_INPUT_CID_COLUMN]:
            writer.writerow([cid, ""])
    cfg = PubChemConfig(
        input_path=input_path,
        cid_col=HARMONSMILE_INPUT_CID_COLUMN,
        keep_extra_columns=True,
    )
    try:
        result_df = PubChemIngest(cfg).run()
    finally:
        if os.path.exists(input_path):
            os.remove(input_path)
    result_df.columns = ( #preparamos los datos para ser procesados por sql
        result_df.columns
        .str.replace(" ", "_", regex=False)
        .str.replace(":", "", regex=False)
    )
    if "PubChem_CID" not in result_df.columns and HARMONSMILE_INPUT_CID_COLUMN in result_df.columns:
        result_df = result_df.rename(
            columns={HARMONSMILE_INPUT_CID_COLUMN: "PubChem_CID"}
        )

    return result_df
