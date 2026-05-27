from chamanp import ChamanpConfig, ChamanpResult, validate_config, run
import pandas as pd
import os


def use_chamanp(df: pd.DataFrame, smiles_col: str, collections_col: str):
    files = os.listdir("artifacts")  
    for file_name in files:
        file_path = os.path.join("artifacts", file_name)
        if os.path.isfile(file_path) and not file_name == "notes.txt":
            os.remove(file_path)
    input_path = "tempFilesChamanp/data.csv"
    temp_df = df.copy()
    temp_df = temp_df.rename(columns={
        smiles_col: "canonical_smiles",
        collections_col: "collections"
    })
    temp_df.to_csv(input_path, index= False)
    cols = temp_df.columns.tolist() 
    print(cols)
    cfg = ChamanpConfig(
        DATABASE_PATH=input_path,
        REPORTS_PATH="artifacts",
        COLLECTION_TAXONOMY_PATH="source_data/coconut_taxonomy.json",
        TARGET_COLLECTIONS=["PubChem NPs"],
        COLLECTION_TAG="pubchem",
        COLLECTION_LOGIC="OR",
        MORGAN_RADIUS=2,
        MORGAN_BITS=1024,
        SELECTED_PROPERTIES=cols,
        REMOVE_STEREO_DUPLICATES=True,
    )
    validate_config(cfg)
    result = run(cfg)
    assert isinstance(result, ChamanpResult)
    print("CORREIDNO")
    os.remove(input_path)