# SPDX-License-Identifier: LGPL-3.0-or-later
from harmonsmile import PubChemIngest, PubChemConfig
import pandas as pd
from pathlib import Path
from tempfile import TemporaryDirectory

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

    temp_root = Path("tempFilesHarmonsile")
    temp_root.mkdir(parents=True, exist_ok=True)
    temp_df = df.copy()
    temp_df.columns = [HARMONSMILE_INPUT_CID_COLUMN]
    with TemporaryDirectory(prefix="ingest-", dir=temp_root) as invocation_dir:
        input_path = Path(invocation_dir) / "res_pubchem.csv"
        temp_df.to_csv(input_path, index=False, sep=",")
        cfg = PubChemConfig(
            input_path=str(input_path),
            cid_col=HARMONSMILE_INPUT_CID_COLUMN,
            keep_extra_columns=True,
        )
        result_df = PubChemIngest(cfg).run()
    result_df.columns = ( #preparamos los datos para ser procesados por sql
        result_df.columns
        .str.replace(" ", "_", regex=False)
        .str.replace(":", "", regex=False)
    )

    return result_df
