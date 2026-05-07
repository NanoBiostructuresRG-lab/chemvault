# modules/obtener_CIDs_Pubchem.py

import requests
import pandas as pd
import sqlite3
BASE_URL = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"


def obtener_CIDs_Pubchem(connection, proteins, progreso):
    cursor = connection.cursor()
    table = "main"

    
    cursor.execute(f"ALTER TABLE {table} ADD COLUMN CID TEXT")
    cursor.execute(f"ALTER TABLE {table} ADD COLUMN AIDs TEXT")
    cursor.execute(f"ALTER TABLE {table} ADD COLUMN Proteins TEXT")
    cursor.execute(f"""
    CREATE UNIQUE INDEX IF NOT EXISTS idx_cid_unique
    ON {table}(CID)
    """)
    connection.commit()
    
    #########
    trabajos = []
    for protein in proteins:
        url_aids = f"{BASE_URL}/assay/target/accession/{protein}/aids/JSON"

        try:
            response = requests.get(url_aids, timeout=30)
            response.raise_for_status()
            data = response.json()
            aids = data["IdentifierList"]["AID"]
            for aid in aids:
                trabajos.append((protein, aid))

        except Exception as e:
           print(f"Error con {protein}: {e}")
    
    total_steps = len(trabajos)
    print(f"Total de AIDs: {total_steps}")

    for step, (protein, aid) in enumerate(trabajos, start=1):
        try:
            url_cids = (
                f"{BASE_URL}/assay/aid/"
                f"{aid}/cids/JSON"
            )
            response = requests.get(url_cids, timeout=30)
            response.raise_for_status()
            print(response.status_code)
            cid_data = response.json()

            cids = (
                cid_data["InformationList"]
                ["Information"][0]["CID"]
            )
            for cid in cids:
                cursor.execute(f"""
                SELECT AIDs, Proteins
                FROM {table}
                WHERE CID = ?
                """, (cid,))

                result = cursor.fetchone()
                if result is None:
                    cursor.execute(f"""
                    INSERT INTO {table}
                    (CID, AIDs, Proteins)
                    VALUES (?, ?, ?)
                    """, (
                        cid,
                        str(aid),
                        protein
                    ))

                # =============================================
                # Si SI existe -> actualizar
                # =============================================
                else:

                    current_aids, current_proteins = result

                    aids_set = set(
                        current_aids.split(", ")
                    )

                    proteins_set = set(
                        current_proteins.split(", ")
                    )

                    aids_set.add(str(aid))
                    proteins_set.add(protein)

                    updated_aids = ", ".join(
                        sorted(aids_set)
                    )

                    updated_proteins = ", ".join(
                        sorted(proteins_set)
                    )

                    cursor.execute(f"""
                    UPDATE {table}
                    SET
                        AIDs = ?,
                        Proteins = ?
                    WHERE CID = ?
                    """, (
                        updated_aids,
                        updated_proteins,
                        cid
                    ))

            connection.commit()


        except Exception as e:
            print(
                f"Error procesando AID {aid}: {e}"
            )
        progreso.progress(step / total_steps)