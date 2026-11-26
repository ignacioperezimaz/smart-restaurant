"""
app.py — Dashboard Smart Restaurant: datos de pedidos SUCIOS (RAW) vs LIMPIOS (CLEAN).
Los dos se leen de HDFS. Ejecutar:   streamlit run app.py   (o con Docker: localhost:8501)
"""
import fsspec
import pandas as pd
import plotly.express as px
import streamlit as st

import importlib

import estilo
import load_data
import pag_drift
import pag_exploracion
import pag_modelos

# Streamlit solo recarga app.py al editarlo; estos dos módulos se quedaban en memoria con la versión vieja.
# Recargarlos aquí hace que los cambios en estilo.py y load_data.py se vean sin reiniciar el contenedor.
importlib.reload(estilo)
importlib.reload(load_data)
for _m in (pag_exploracion, pag_modelos, pag_drift):     # las páginas nuevas, igual: sin reiniciar el contenedor
    importlib.reload(_m)
from load_data import HDFS_HOST, HDFS_PORT, HDFS_USER, cargar_clean, cargar_raw

estilo.configurar("Smart Restaurant · Dashboard")  # debe ir antes de cualquier otro st.*


def miles(n: int) -> str:
    return f"{n:,}".replace(",", ".")


# La variable de salida se resalta con el melocotón de la marca (el mismo de estilo.py)


def resaltar(tabla: pd.DataFrame, columna):
    """Devuelve la tabla con `columna` en melocotón. Si no hay columna que resaltar (o aún no existe), la tabla tal cual."""
    if not columna or columna not in tabla.columns:
        return tabla
    return tabla.style.set_properties(
        subset=[columna],
        **{"background-color": estilo.MELOCOTON, "color": estilo.GRIS_TEXTO, "font-weight": "bold"},
    )


# ---------------------------------------------------------------- problemas por dataset
def problemas_pedidos(df, vc):
    dia = pd.to_numeric(df["dia_semana"].str.strip(), errors="coerce")
    return {
        "Filas con algún campo vacío": vc.any(axis=1),
        "Filas duplicadas exactas": df.duplicated(keep="first"),
        "dia_semana inválido (no es 1-7)": ~dia.between(1, 7) & ~vc["dia_semana"],
        "fecha en formato MM-DD-AAAA": df["fecha"].str.strip().str.fullmatch(r"\d{2}-\d{2}-\d{4}"),
        "hora en formato HH:MM (sin segundos)": df["hora"].str.strip().str.fullmatch(r"\d{1,2}:\d{2}"),
        "tiempo_prep_minutos escrito como HH:MM": df["tiempo_prep_minutos"].str.strip().str.fullmatch(r"\d{1,2}:\d{2}"),
    }


def problemas_ventas(df, vc):
    return {
        "Filas con algún campo vacío": vc.any(axis=1),
        "Filas duplicadas exactas": df.duplicated(keep="first"),
        "id_plato con prefijo (PL-64 en vez de 64)": df["id_plato"].str.strip().str.startswith("PL-"),
        "fecha en formato DD/MM/AAAA": df["fecha"].str.strip().str.fullmatch(r"\d{2}/\d{2}/\d{4}"),
        "precio_unidad con símbolo € o coma": df["precio_unidad"].str.contains("€|,", regex=True),
        "unidades_vendidas = 'muchos'": df["unidades_vendidas"].str.strip().str.lower().eq("muchos"),
    }


DATASETS = {
    # salida: variable de salida (lo que queremos predecir). Se resalta en melocotón en las tablas RAW y CLEAN.
    "Pedidos y tiempos de preparación": dict(clave="pedidos", problemas=problemas_pedidos, objetivo="tiempo_prep_minutos",
                                             salida="tiempo_prep_minutos"),
    "Ventas diarias de platos": dict(clave="ventas", problemas=problemas_ventas, objetivo="unidades_vendidas"),
}


# ---------------------------------------------------------------- carga (cacheada)
@st.cache_data(show_spinner="Leyendo los datos SUCIOS de HDFS...")
def datos_raw(clave: str):
    df = cargar_raw(clave)
    vc = df.apply(lambda s: s.str.strip().eq(""))                    # True donde la celda está vacía
    masks = {k: v.fillna(False).astype(bool) for k, v in next(
        d["problemas"] for d in DATASETS.values() if d["clave"] == clave)(df, vc).items()}
    problemas = pd.DataFrame({"Problema": list(masks), "Filas afectadas": [int(m.sum()) for m in masks.values()]})
    vacios = vc.sum()
    return df, vacios[vacios > 0].sort_values(), problemas, masks


@st.cache_data(show_spinner="Leyendo los datos LIMPIOS de HDFS...")
def datos_clean(clave: str):
    return cargar_clean(clave)


@st.cache_data(ttl=60, show_spinner="Leyendo la estructura de HDFS...")
def arbol_hdfs(raiz: str = "/datalake") -> str:
    """Árbol de carpetas y archivos de HDFS (con tamaños) como texto, listo para un pantallazo."""
    fs = fsspec.filesystem("webhdfs", host=HDFS_HOST, port=HDFS_PORT, user=HDFS_USER)

    def tamano(b: int) -> str:
        return f"{b / 1024 ** 2:,.1f} MB" if b >= 1024 ** 2 else f"{b / 1024:,.1f} KB"

    lineas = [raiz + "/"]

    def recorrer(ruta: str, prefijo: str) -> None:
        entradas = sorted(fs.ls(ruta, detail=True), key=lambda e: (e["type"] != "directory", e["name"]))
        for i, e in enumerate(entradas):
            ultimo = i == len(entradas) - 1
            rama = "└── " if ultimo else "├── "
            nombre = e["name"].rstrip("/").split("/")[-1]
            if e["type"] == "directory":
                lineas.append(f"{prefijo}{rama}{nombre}/")
                recorrer(e["name"], prefijo + ("    " if ultimo else "│   "))
            else:
                lineas.append(f"{prefijo}{rama}{nombre}  ({tamano(e['size'])})")

    recorrer(raiz, "")
    return "\n".join(lineas)


# ---------------------------------------------------------------- página de un dataset
def pagina_dataset(nombre_ds: str) -> None:
    cfg = DATASETS[nombre_ds]
    clave = cfg["clave"]
    st.caption(f"{nombre_ds}: datos sucios (RAW) frente a datos limpios (CLEAN), leídos de HDFS")

    try:
        raw, vacios, problemas, masks = datos_raw(clave)
    except Exception as e:
        st.error("No se han podido leer los datos SUCIOS de HDFS (/datalake/raw). "
                 "Comprueba que Docker está levantado (namenode y datanode).")
        st.exception(e)
        st.stop()

    try:
        clean = datos_clean(clave)
    except Exception as e:
        clean = None
        err_clean = e

    tab_res, tab_raw, tab_clean = st.tabs(["Resumen", "Datos sucios (RAW)", "Datos limpios (CLEAN)"])

    # ------------------------------------------------------------ resumen
    with tab_res:
        nulos_raw = int(vacios.sum())
        if clean is None:
            st.warning("Todavía no hay datos limpios de este dataset en HDFS (/datalake/clean). "
                       "Guarda el Parquet desde el notebook de limpieza y recarga esta página.")
        else:
            nulos_clean = int(clean.isna().sum().sum())
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Filas RAW → CLEAN", f"{miles(len(raw))} → {miles(len(clean))}")
            c2.metric("Filas descartadas", miles(len(raw) - len(clean)),
                      f"{(len(raw) - len(clean)) / len(raw):.1%} del total", delta_color="off", delta_arrow="off")
            c3.metric("Columnas RAW → CLEAN", f"{raw.shape[1]} → {clean.shape[1]}")
            c4.metric("Celdas vacías RAW → CLEAN", f"{miles(nulos_raw)} → {miles(nulos_clean)}")

        st.subheader("Problemas de calidad en los datos sucios")
        fig = px.bar(problemas.sort_values("Filas afectadas"), x="Filas afectadas", y="Problema",
                     orientation="h", text="Filas afectadas")
        fig.update_traces(texttemplate="%{text:,}", textposition="outside")
        fig.update_layout(yaxis_title=None, showlegend=False, height=380)
        st.plotly_chart(fig, width="stretch")

    # ------------------------------------------------------------ RAW
    with tab_raw:
        st.subheader("Datos sucios · /datalake/raw")
        c1, c2, c3 = st.columns(3)
        c1.metric("Filas", miles(len(raw)))
        c2.metric("Columnas", raw.shape[1])
        c3.metric("Celdas vacías", miles(nulos_raw))

        vista = st.selectbox("Qué filas quieres ver", ["Primeras filas"] + list(masks))
        n = st.slider("Número de filas a mostrar", 10, 500, 50, step=10)
        filas = raw if vista == "Primeras filas" else raw[masks[vista].fillna(False)]
        st.caption(f"{miles(len(filas))} filas cumplen el filtro; se muestran {min(n, len(filas))}. "
                   "Todo se ve como texto, tal cual está en el CSV.")
        st.dataframe(resaltar(filas.head(n), cfg.get("salida")), width="stretch")
        if cfg.get("salida") in filas.columns:
            st.caption(f"En melocotón: {cfg['salida']}, la variable de salida (lo que queremos predecir).")

        st.subheader("Vacíos por columna")
        fig = px.bar(vacios.reset_index().rename(columns={"index": "Columna", 0: "Vacíos"}),
                     x="Vacíos", y="Columna", orientation="h", text="Vacíos")
        fig.update_traces(texttemplate="%{text:,}", textposition="outside")
        fig.update_layout(yaxis_title=None, showlegend=False)
        st.plotly_chart(fig, width="stretch")

    # ------------------------------------------------------------ CLEAN
    with tab_clean:
        st.subheader("Datos limpios · /datalake/clean")
        if clean is None:
            st.error("No se han podido leer los datos limpios de HDFS.")
            st.exception(err_clean)
        else:
            c1, c2, c3 = st.columns(3)
            c1.metric("Filas", miles(len(clean)))
            c2.metric("Columnas", clean.shape[1])
            c3.metric("Celdas vacías", miles(int(clean.isna().sum().sum())))

            n2 = st.slider("Número de filas a mostrar", 10, 500, 50, step=10, key="n_clean")
            st.dataframe(resaltar(clean.head(n2), cfg.get("salida")), width="stretch")
            if cfg.get("salida") in clean.columns:
                st.caption(f"En melocotón: {cfg['salida']}, la variable de salida (lo que queremos predecir).")

            st.subheader("Tipos de dato")
            tipos = pd.DataFrame({"Columna": clean.columns, "Tipo": clean.dtypes.astype(str).values})
            st.dataframe(tipos, width="stretch", hide_index=True)

            st.subheader("Resumen estadístico")
            st.dataframe(clean.describe().T.round(2), width="stretch")

            st.subheader("Distribución de una variable numérica")
            numericas = clean.select_dtypes(include="number").columns.tolist()
            if numericas:
                por_defecto = numericas.index(cfg["objetivo"]) if cfg["objetivo"] in numericas else 0
                col = st.selectbox("Variable", numericas, index=por_defecto)
                fig = px.histogram(clean, x=col, nbins=60)
                fig.update_layout(xaxis_title=col, yaxis_title="Registros", showlegend=False)
                st.plotly_chart(fig, width="stretch")


def pagina_pedidos() -> None:
    pagina_dataset("Pedidos y tiempos de preparación")


def pagina_ventas() -> None:
    pagina_dataset("Ventas diarias de platos")


def pagina_hdfs() -> None:
    st.caption("Estructura del data lake en HDFS · RAW: datos originales sin tocar · CLEAN: datos ya limpios")
    try:
        st.code(arbol_hdfs("/datalake"), language=None)
    except Exception as e:
        st.error("No se ha podido leer la estructura de HDFS.")
        st.exception(e)


# ---------------------------------------------------------------- menú lateral + cabecera común
menu = st.navigation({
    "Datos": [
        st.Page(pagina_pedidos, title="Pedidos", icon=":material/receipt_long:", url_path="pedidos", default=True),
        st.Page(pagina_ventas, title="Ventas", icon=":material/storefront:", url_path="ventas"),
        st.Page(pagina_hdfs, title="Estructura HDFS", icon=":material/account_tree:", url_path="hdfs"),
    ],
    "Exploración": [
        st.Page(pag_exploracion.pagina_eda_pedidos, title="Pedidos: qué los hace tardar", icon=":material/query_stats:", url_path="eda-pedidos"),
        st.Page(pag_exploracion.pagina_eda_ventas, title="Ventas: cómo se venden los platos", icon=":material/bar_chart:", url_path="eda-ventas"),
    ],
    "Modelos": [
        st.Page(pag_modelos.pagina_regresion, title="Tiempo de preparación", icon=":material/timer:", url_path="regresion"),
        st.Page(pag_modelos.pagina_clustering, title="Clustering de platos", icon=":material/bubble_chart:", url_path="clustering"),
    ],
    "Monitorización": [
        st.Page(pag_drift.pagina_drift, title="Drift del modelo", icon=":material/monitor_heart:", url_path="drift"),
    ],
})

with st.container(border=True):
    col_logo, col_titulo = st.columns([1, 5], vertical_alignment="center")
    col_logo.image(str(estilo.ASSETS / "smart-restaurant_positivo.png"), width=150)
    with col_titulo:
        st.title("Smart Restaurant · Dashboard")
        st.caption(f"Sección: {menu.title}")

menu.run()
