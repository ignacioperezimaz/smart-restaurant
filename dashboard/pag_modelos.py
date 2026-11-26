"""
pag_modelos.py — Páginas de MODELOS (lo que vimos en los notebooks 04 y 06).

  · Clustering de platos (Objetivo 1): qué grupos de platos encontró el modelo y cómo se eligió el nº de grupos.
  · Regresión del tiempo de preparación (Objetivo 2): qué modelo ganó, cuánto se equivoca y qué variables pesan.
Las notas de cada prueba se leen de MLflow (lo que guardaron los notebooks) y los grupos de los platos, de HDFS.
"""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

import datos_dashboard as dd
import estilo
import graficos as g
import mlflow_rest as ml

EXP_CLUSTERING = "smart-restaurant-clustering-platos"
EXP_REGRESION = "smart-restaurant-regresion-tiempo-prep"
MODELO_REGRESION = "smart_restaurant_regresion_tiempo_prep"
NOMBRE_LEGIBLE = {"linea_base_media": "línea base (la media)", "regresion_lineal": "regresión lineal", "knn": "KNN", "random_forest": "Random Forest"}
VARS_PERFIL = {"popularidad": "popularidad", "margen_medio": "margen medio (€)", "precio_medio": "precio medio (€)",
               "coste_medio": "coste medio (€)", "valoracion": "valoración", "dificultad": "dificultad", "unidades_medias": "unidades medias"}


@st.cache_data(ttl=120, show_spinner="Leyendo MLflow...")
def _ejecuciones(experimento: str) -> list[dict]:
    return ml.ejecuciones(experimento)


@st.cache_data(ttl=300, show_spinner=False)
def _csv(run: dict, ruta: str, **opciones):
    return ml.artefacto_csv(run, ruta, **opciones)


@st.cache_data(ttl=300, show_spinner=False)
def _imagen(run: dict, ruta: str):
    return ml.artefacto_imagen(run, ruta)


@st.cache_data(ttl=300, show_spinner="Leyendo los grupos de platos de HDFS...")
def _clusters() -> pd.DataFrame:
    return dd.platos_clusters()


def _aviso_mlflow(experimento: str, notebook: str) -> None:
    if not ml.disponible():
        st.warning(f"No se puede conectar con MLflow ({ml.URI}). Comprueba que el servicio está arrancado: `docker compose ps`.")
    else:
        st.warning(f"MLflow no tiene todavía el experimento «{experimento}». Ejecuta antes el notebook {notebook}.")


# ======================================================================================= CLUSTERING
def pagina_clustering() -> None:
    st.caption("Objetivo 1 (notebook 04): agrupar los platos por rendimiento con clustering · notas de MLflow y grupos de HDFS")
    try:
        platos = _clusters()
    except Exception as e:
        st.error("No se han podido leer los grupos de platos de HDFS (/datalake/clean/ventas_diarias_platos/platos_clusters.parquet). "
                 "Ejecuta antes el notebook 04.")
        st.exception(e)
        st.stop()

    runs = _ejecuciones(EXP_CLUSTERING)
    final = next((r for r in runs if r["tags"].get("fase") == "final"), None)
    comparacion = [r for r in runs if r["tags"].get("fase") == "comparacion" and "k" in r["params"]]

    if final:
        m = final["metricas"]
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Grupos (k)", final["params"].get("k", "—"))
        c2.metric("Silhouette", f"{m.get('silhouette', float('nan')):.2f}", help="De −1 a 1: cuánto se separan los grupos. Más alto = mejor.")
        c3.metric("Davies-Bouldin", f"{m.get('davies_bouldin', float('nan')):.2f}", help="Más bajo = grupos más compactos y separados.")
        c4.metric("Estabilidad", f"{m.get('estabilidad', float('nan')):.2f}", help="1 = K-Means da siempre los mismos grupos aunque cambie el azar.")
        c5.metric("Platos", len(platos))
    else:
        _aviso_mlflow(EXP_CLUSTERING, "04")

    tab1, tab2, tab3 = st.tabs(["Los grupos", "Cómo se eligió el nº de grupos", "Platos de cada grupo"])

    # ------------------------------------------------------------------ 1. grupos
    with tab1:
        orden = platos.groupby("nombre_grupo").size().sort_values(ascending=False)
        colores = {n: c for n, c in zip(orden.index, estilo.SERIES + ["#6FA8A0", "#B8C4C9", "#8E5C5C"])}
        izq, der = st.columns([3, 2])
        vars_ok = [v for v in VARS_PERFIL if v in platos.columns]
        x = izq.selectbox("Eje horizontal", vars_ok, index=vars_ok.index("popularidad") if "popularidad" in vars_ok else 0, format_func=VARS_PERFIL.get)
        y = izq.selectbox("Eje vertical", vars_ok, index=vars_ok.index("margen_medio") if "margen_medio" in vars_ok else 1, format_func=VARS_PERFIL.get)
        fig = px.scatter(platos, x=x, y=y, color="nombre_grupo", hover_name="id_plato", color_discrete_map=colores,
                         category_orders={"nombre_grupo": list(orden.index)}, labels={x: VARS_PERFIL[x], y: VARS_PERFIL[y], "nombre_grupo": ""})
        fig.update_traces(marker=dict(size=11, line=dict(color=g.AZUL, width=1), opacity=0.9))
        fig.update_layout(title="Cada plato, coloreado por su grupo", height=430, legend=dict(orientation="h", y=-0.2))
        izq.plotly_chart(fig, width="stretch")
        tam = orden.reset_index(); tam.columns = ["grupo", "platos"]
        der.plotly_chart(g.barras_h(tam, "platos", "grupo", "Platos por grupo", "nº de platos", colores=[colores[n] for n in tam["grupo"]],
                                    texto="platos", alto=430), width="stretch")
        st.caption("Cada punto es un plato; los colores son los grupos que encontró K-Means con todas las variables a la vez "
                   "(en un gráfico de solo dos variables, los grupos pueden verse solapados).")

        st.subheader("Perfil de cada grupo")
        medias = platos.groupby("nombre_grupo")[vars_ok].mean().reindex(orden.index)
        z = (medias - platos[vars_ok].mean()) / platos[vars_ok].std()          # cuántas desviaciones se aleja cada grupo de la media de todos los platos
        z.columns = [VARS_PERFIL[c] for c in z.columns]
        st.plotly_chart(g.mapa_calor(z, "Cómo se diferencia cada grupo de la media (en desviaciones típicas)", "variable", "grupo", "desviaciones",
                                     decimales=1, divergente=True, alto=70 + 70 * len(z)), width="stretch")
        st.caption("Naranja: el grupo está por encima de la media de todos los platos en esa variable; azul: por debajo. "
                   "Así se leen los nombres de los grupos (por ejemplo, «Estrella» = popularidad y margen altos).")
        tabla = medias.round(2).rename(columns=VARS_PERFIL)
        tabla.insert(0, "platos", orden)
        st.dataframe(tabla, width="stretch")

    # ------------------------------------------------------------------ 2. elegir k
    with tab2:
        if not comparacion:
            _aviso_mlflow(EXP_CLUSTERING, "04")
        else:
            filas = [{"algoritmo": r["params"]["algoritmo"], "k": int(r["params"]["k"]), **r["metricas"]} for r in comparacion if "algoritmo" in r["params"]]
            t = pd.DataFrame(filas).drop_duplicates(["algoritmo", "k"]).sort_values(["algoritmo", "k"])
            nombres = {"silhouette": "Silhouette (más alto = mejor)", "davies_bouldin": "Davies-Bouldin (más bajo = mejor)",
                       "calinski_harabasz": "Calinski-Harabasz (más alto = mejor)"}
            metrica = st.radio("Nota", [m for m in nombres if m in t.columns], format_func=nombres.get, horizontal=True)
            fig = px.line(t, x="k", y=metrica, color="algoritmo", markers=True, color_discrete_sequence=[g.NARANJA, g.AZUL])
            if final:
                fig.add_vline(x=int(final["params"]["k"]), line_dash="dash", line_color=g.GRIS, annotation_text="k elegido")
            fig.update_layout(title=f"{nombres[metrica]} según el nº de grupos", height=400, xaxis=dict(dtick=1), xaxis_title="nº de grupos (k)",
                              legend_title=None)
            st.plotly_chart(fig, width="stretch")
            st.caption("Se probaron dos algoritmos (K-Means y jerárquico) con varios k. No se elige solo el k con mejor nota: "
                       "también se miró que los grupos fueran estables, no demasiado pequeños y que los dos algoritmos coincidieran (notebook 04).")
            st.dataframe(t.round(3), width="stretch", hide_index=True)

    # ------------------------------------------------------------------ 3. platos
    with tab3:
        grupo = st.selectbox("Grupo", list(orden.index))
        sel = platos[platos["nombre_grupo"] == grupo].sort_values("popularidad", ascending=False)
        st.caption(f"{len(sel)} platos en «{grupo}», de más a menos populares.")
        st.dataframe(sel.drop(columns=["grupo", "nombre_grupo"]).round(2).rename(columns=VARS_PERFIL), width="stretch", hide_index=True)


# ======================================================================================= REGRESIÓN
def _ultimo_por_modelo(runs: list[dict]) -> dict[str, dict]:
    """La ejecución más reciente de cada modelo (el nombre de la ejecución es «<modelo>_<fecha>»)."""
    salida = {}
    for r in runs:
        if r["tags"].get("fase") != "comparacion" or "test_mae" not in r["metricas"]:
            continue
        clave = r["nombre"].rsplit("_20", 1)[0]
        salida.setdefault(clave, r)                     # las ejecuciones vienen de la más reciente a la más antigua
    return salida


def pagina_regresion() -> None:
    st.caption("Objetivo 2 (notebook 06): predecir el tiempo de preparación de un pedido, en minutos · notas guardadas en MLflow")
    runs = _ejecuciones(EXP_REGRESION)
    por_modelo = _ultimo_por_modelo(runs)
    if not por_modelo:
        _aviso_mlflow(EXP_REGRESION, "06")
        st.stop()
    padre = next((r for r in runs if "linea_base_test_mae" in r["metricas"]), None)

    filas = []
    if padre:
        filas.append({"modelo": NOMBRE_LEGIBLE["linea_base_media"], "MAE": padre["metricas"]["linea_base_test_mae"],
                      "RMSE": padre["metricas"]["linea_base_test_rmse"], "R²": padre["metricas"]["linea_base_test_r2"]})
    for clave in ("regresion_lineal", "knn", "random_forest"):
        if clave in por_modelo:
            m = por_modelo[clave]["metricas"]
            filas.append({"modelo": NOMBRE_LEGIBLE[clave], "MAE": m["test_mae"], "RMSE": m["test_rmse"], "R²": m["test_r2"]})
    tabla = pd.DataFrame(filas)
    mejor = tabla.loc[tabla["modelo"] != NOMBRE_LEGIBLE["linea_base_media"], "RMSE"].idxmin()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Mejor modelo", tabla.loc[mejor, "modelo"])
    c2.metric("Error medio (MAE)", f"{tabla.loc[mejor, 'MAE']:.2f} min", help="Cuántos minutos se equivoca de media. Más bajo = mejor.")
    c3.metric("RMSE", f"{tabla.loc[mejor, 'RMSE']:.2f} min", help="Como el MAE, pero castiga más los errores grandes.")
    c4.metric("R²", f"{tabla.loc[mejor, 'R²']:.3f}", help="Qué parte de lo que varía el tiempo explica el modelo (1 = todo).")

    tab1, tab2, tab3, tab4 = st.tabs(["Comparación de modelos", "Qué variables pesan", "Dónde se equivoca", "Versiones del modelo"])
    run_rf = por_modelo.get("random_forest")

    with tab1:
        larga = tabla.melt(id_vars="modelo", value_vars=["MAE", "RMSE"], var_name="nota", value_name="minutos")
        fig = px.bar(larga, x="modelo", y="minutos", color="nota", barmode="group", text="minutos", color_discrete_sequence=[g.AZUL, g.NARANJA])
        fig.update_traces(texttemplate="%{text:.2f}", textposition="outside")
        fig.update_layout(title="Error de cada modelo con los pedidos de prueba (más bajo = mejor)", height=400, xaxis_title=None, legend_title=None,
                          yaxis_title="minutos")
        izq, der = st.columns([3, 2])
        izq.plotly_chart(fig, width="stretch")
        izq.caption("La línea base siempre predice la media: es el listón mínimo. Un modelo que no la mejora con holgura no aporta nada.")
        der.plotly_chart(g.barras(tabla, "modelo", "R²", "R² (más alto = mejor)", "R²", formato=".2f", colores=[g.GRIS, g.NARANJA, g.VERDE, g.AZUL][:len(tabla)], alto=400),
                         width="stretch")
        st.dataframe(tabla.round(3), width="stretch", hide_index=True)
        if run_rf:
            col_a, col_b = st.columns(2)
            for col, archivo in ((col_a, "real_vs_predicho.png"), (col_b, "errores.png")):
                img = _imagen(run_rf, archivo)
                if img:
                    col.image(img, caption=f"Random Forest · {archivo.replace('.png', '').replace('_', ' ')}", width="stretch")

    with tab2:
        if run_rf and (imp := _csv(run_rf, "importancia_permutacion.csv")) is not None:
            imp = imp.sort_values("empeora_mae_min", ascending=False)
            st.plotly_chart(g.barras_h(imp, "empeora_mae_min", "variable", "Importancia de cada variable (Random Forest)",
                                       "minutos que empeora el error al desordenar la variable", alto=420), width="stretch")
            st.caption("Se desordena una variable al azar y se mide cuánto empeora el modelo: si empeora mucho, esa variable es importante.")
        run_lin = por_modelo.get("regresion_lineal")
        if run_lin and (coef := _csv(run_lin, "coeficientes.csv")) is not None:
            coef = coef.sort_values("minutos", key=abs, ascending=False)
            st.plotly_chart(g.barras_h(coef, "minutos", "variable", "Regresión lineal: minutos que suma cada variable",
                                       "minutos por unidad (naranja suma, azul resta)", colores=[g.NARANJA if v > 0 else g.AZUL for v in coef["minutos"]], alto=440),
                            width="stretch")
            st.caption("La regresión lineal es fácil de leer: cada barra son los minutos que suma (o resta) esa variable por cada unidad más.")

    with tab3:
        if run_rf and (tr := _csv(run_rf, "error_por_tramo.csv")) is not None:
            tr = tr.rename(columns={tr.columns[0]: "tramo"})
            izq, der = st.columns(2)
            izq.plotly_chart(g.barras(tr, "tramo", "mae", "Error medio según el tiempo REAL del pedido", "MAE (min)", formato=".2f"), width="stretch")
            der.plotly_chart(g.barras(tr, "tramo", "error_medio", "Error con signo (real − predicho)", "minutos", formato=".2f",
                                      colores=[g.NARANJA if v > 0 else g.AZUL for v in tr["error_medio"]]), width="stretch")
            st.caption("Positivo (naranja): el modelo se queda corto y promete menos tiempo del que luego tarda el pedido. "
                       "Lo habitual es que falle más en los pedidos más lentos, que son los más raros.")
            st.dataframe(tr.round(3), width="stretch", hide_index=True)
        else:
            st.info("No se ha podido leer el error por tramos de MLflow.")

    with tab4:
        versiones = ml.versiones_modelo(MODELO_REGRESION)
        if not versiones:
            st.info("MLflow todavía no tiene versiones registradas de este modelo.")
        else:
            st.markdown("El alias **`actual`** es la versión que usa la API; **`candidato`** es un modelo reentrenado que espera a que una persona lo apruebe "
                        "(notebook 07).")
            v = pd.DataFrame(versiones)[["version", "alias", "creada", "descripcion"]]
            st.dataframe(v, width="stretch", hide_index=True)
