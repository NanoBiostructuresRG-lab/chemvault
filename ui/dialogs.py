# SPDX-License-Identifier: LGPL-3.0-or-later
import streamlit as st

from services.builders import build_from_proteins
from services.database import update_headers
from state_keys import DATABASE_ID, INPUT_PROTEIN, SELECTED_PROTEINS


@st.dialog("Select Proteins", dismissible=False)
def select_proteins():
    st.write("Search CIDs by BioAssays, using a protein as target.")
    st.text_input(label="Protein", key=INPUT_PROTEIN, value="P34971")
    if st.button("Add to selection"):
        st.session_state[SELECTED_PROTEINS].append(st.session_state[INPUT_PROTEIN])
        st.markdown(f"Selected proteins: {st.session_state[SELECTED_PROTEINS]}.")
    if st.button("Confirm selection"):
        if len(st.session_state[SELECTED_PROTEINS]) == 0:
            st.toast("Select at least one protein")
            print("Select at least one protein")
        elif st.session_state[DATABASE_ID] == "":
            st.toast("First, enter a name for your SQL database")
            print("First, enter a name for your SQL database")
        else:
            st.info("Building the protein database. This can take a few minutes for targets with many BioAssays.")
            progreso = st.progress(0)
            st.toast(f"Building database with proteins: {st.session_state[SELECTED_PROTEINS]}")
            build_from_proteins(progreso)
            update_headers()
        st.rerun()
    if st.button("Cancel"):
        st.session_state[SELECTED_PROTEINS] = []
        st.rerun()
