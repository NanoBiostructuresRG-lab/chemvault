import streamlit as st
import pandas as pd
import os

st.set_page_config(layout="wide")
st.title('Curador BD')

ruta_custom = "BDs/custom"
archivos = ["None"] + [f for f in os.listdir(ruta_custom) if os.path.isfile(os.path.join(ruta_custom, f))]

archivo_seleccionado = st.sidebar.selectbox("Selecciona un archivo", archivos, index=0)

# Inicializamos en session_state si no existe
if "Tabla" not in st.session_state:
    st.session_state["Tabla"] = None

# Usamos match para controlar estados
match archivo_seleccionado:
    case "None":
        st.write("Seleccionar archivo")

    case _ if st.session_state["Tabla"] is None:
        if st.button("Cargar csv"):
            ruta_archivo = os.path.join(ruta_custom, archivo_seleccionado)
            try:
                st.session_state["Tabla"] = pd.read_csv(ruta_archivo)
                st.success("Archivo cargado correctamente")
                st.data_editor(st.session_state["Tabla"], use_container_width=True)
            except Exception as e:
                st.error(f"Error al cargar el archivo: {e}")

    case _:
        st.data_editor(st.session_state["Tabla"], use_container_width=True)



# Obtener archivos



