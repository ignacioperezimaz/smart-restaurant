"""
app.py — Dashboard Smart Restaurant (paso 1: comprobar que se leen los datos).
Ejecutar desde la carpeta dashboard/:   streamlit run app.py
"""
import pandas as pd
import plotly.express as px
import streamlit as st

import estilo
from load_data import FUENTES, cargar

estilo.configurar("Smart Restaurant · Dashboard")  # debe ir antes de cualquier otro st.*


@st.cache_data(show_spinner="Leyendo datos...")
def datos(nombre: str):
    # Se cachea para no releer el CSV en cada interacción
    return cargar(nombre)


# Cabecera: logo a color (positivo, fondo claro) + título
col_logo, col_titulo = st.columns([1, 4], vertical_alignment="center")
col_logo.image(str(estilo.ASSETS / "smart-restaurant_positivo.png"), width="stretch")
with col_titulo:
    st.title("Smart Restaurant · Dashboard")
    st.caption("Paso 1: comprobación de la lectura de datos")

resumen = []
for nombre in FUENTES:
    df, origen = datos(nombre)
    resumen.append({"fuente": nombre, "filas": len(df), "origen": origen})

    st.subheader(nombre.capitalize())
    c1, c2, c3 = st.columns(3)
    c1.metric("Filas", f"{len(df):,}".replace(",", "."))
    c2.metric("Columnas", df.shape[1])
    c3.metric("Origen", origen)
    st.dataframe(df.head(5), width="stretch")

# Gráfica de ejemplo con la plantilla de la marca
st.subheader("Filas por fuente de datos")
fig = px.bar(pd.DataFrame(resumen), x="fuente", y="filas", text="filas")
fig.update_traces(texttemplate="%{text:,}", textposition="outside")
fig.update_layout(xaxis_title=None, yaxis_title="Filas", showlegend=False)
st.plotly_chart(fig, width="stretch")
