from harmonsmile import PubChemIngest, PubChemConfig
import pandas as pd
import os 

def use_PubchemIngest(df: pd.DataFrame) -> pd.DataFrame:
    if df.shape[1] != 1:
        raise ValueError("El DataFrame debe tener exactamente una columna.")
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
