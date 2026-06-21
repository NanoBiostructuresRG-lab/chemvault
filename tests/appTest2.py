# SPDX-License-Identifier: LGPL-3.0-or-later
# app.py
import streamlit as st
import pandas as pd
from modules.obtener_CIDs_Pubchem import obtener_CIDs_Pubchem

st.title("Carga de CIDs en tiempo real")
proteina = st.text_input("P34970 y P34971")

if "df" not in st.session_state:
    st.session_state.df = pd.DataFrame(columns=["CID"])

tabla = st.empty()
progreso = st.progress(0)
estado = st.empty()

# mostrar tabla actual al cargar
tabla.dataframe(st.session_state.df, use_container_width=True)

if st.button("Obtener CIDs"):

    df = st.session_state.df

    # primer protein
    obtener_CIDs_Pubchem(
        protein=proteina,
        df=df,
        placeholder=tabla,
        progreso=progreso,
        estado=estado
    )


    estado.success("Proceso terminado")


# csv
if not st.session_state.df.empty:
    csv = st.session_state.df.to_csv(index=False).encode("utf-8")

    st.download_button(
        label="Descargar CSV",
        data=csv,
        file_name="cids_pubchem.csv",
        mime="text/csv"
    )