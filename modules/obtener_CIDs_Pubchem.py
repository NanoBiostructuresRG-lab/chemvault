# modules/obtener_CIDs_Pubchem.py

import requests
import pandas as pd

BASE_URL = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"


def obtener_CIDs_Pubchem(protein, df, placeholder, progreso, estado):

    url_aids = f"{BASE_URL}/assay/target/accession/{protein}/aids/JSON"

    try:
        response = requests.get(url_aids, timeout=30)
        response.raise_for_status()

        data = response.json()
        aids = data["IdentifierList"]["AID"]

    except Exception as e:
        estado.error(f"Error con {protein}: {e}")
        return

    if "CID" not in df.columns:
        df["CID"] = pd.Series(dtype="Int64")
    # dropna para eliminar datos vacios, en teoria no deberia de pasar
    cids_agregados = set(df["CID"].dropna().astype(int).tolist())

    fila_actual = len(df)
    total = len(aids)

    for i, aid in enumerate(aids):

        estado.write(f"{protein} | AID {aid}")

        try:
            url_cids = f"{BASE_URL}/assay/aid/{aid}/cids/JSON"

            response = requests.get(url_cids, timeout=30)
            response.raise_for_status()

            cid_data = response.json()

            cids = cid_data["InformationList"]["Information"][0]["CID"]

            for cid in cids:

                if cid not in cids_agregados:
                    cids_agregados.add(cid)

                    # modifica df 
                    df.loc[fila_actual, "CID"] = cid
                    fila_actual += 1

                    # actualizar streamlit en vivo
                    placeholder.dataframe(df, use_container_width=True)


        except:
            pass

        progreso.progress((i + 1) / total)