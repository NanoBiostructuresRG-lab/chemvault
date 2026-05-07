import streamlit as st

### ---------- SESSION STATE ----------
if "selected_proteins" not in st.session_state:
    st.session_state["selected_proteins"] = []

if "input_protein" not in st.session_state:
    st.session_state["input_protein"] = ""


### ---------- FUNCIONES ----------
def look_up_AIDs():
    protein = st.session_state["input_protein"]

    if protein.strip() == "":
        return

    st.toast(f"Looking up AIDs for {protein}...")
    
    # Aquí iría tu búsqueda real
    # aids = obtener_AIDs(protein)


def add_protein():
    protein = st.session_state["input_protein"].strip()

    if protein == "":
        return

    # Evitar duplicados
    if protein not in st.session_state["selected_proteins"]:
        st.session_state["selected_proteins"].append(protein)
        st.toast(f"{protein} agregado")

    st.session_state["input_protein"] = ""


### ---------- DIALOG ----------
@st.dialog("Seleccionar Proteínas", dismissible=False)
def select_proteins():

    st.write("Buscar CIDs por BioAssays usando proteína como target")

    col1, col2 = st.columns([3,1])

    with col1:
        st.text_input(
            label="Protein",
            key="input_protein",
            value="P34971"
        )

    with col2:
        st.write("")
        st.write("")

        if st.button("Buscar"):
            look_up_AIDs()

    st.divider()

    st.subheader("Proteínas seleccionadas")

    if len(st.session_state["selected_proteins"]) == 0:
        st.info("No hay proteínas seleccionadas")
    else:
        for protein in st.session_state["selected_proteins"]:
            st.write(f"• {protein}")

    col1, col2 = st.columns(2)

    with col1:
        if st.button("Agregar a selección"):
            add_protein()
            st.rerun()

    with col2:
        if st.button("Confirmar selección"):
            st.toast("Selección confirmada")
            st.rerun()


### ---------- BOTON PRINCIPAL ----------
if st.button("Abrir selector"):
    select_proteins()