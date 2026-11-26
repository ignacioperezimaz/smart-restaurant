"""
pag_exploracion.py — Páginas de EXPLORACIÓN (lo que vimos en los notebooks 01, 02, 03 y 05).

  · Pedidos (notebook 05): qué hace que un pedido tarde más o menos en prepararse.
  · Ventas (notebook 03): cómo se venden los platos y en qué se parecen o se diferencian.
Los datos son los LIMPIOS de HDFS (/datalake/clean). Cada gráfica trae una frase de cómo leerla.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st

import datos_dashboard as dd
import estilo
import graficos as g

ETIQUETAS = {"n_platos": "nº de platos", "num_platos_complejos": "nº de platos complejos", "complejidad_pedido": "complejidad del pedido",
             "cola_pedidos": "pedidos en cola", "cocineros_disponibles": "cocineros disponibles", "precipitacion_mm": "lluvia (mm)",
             "hora_dec": "hora del día", "dia_semana": "día de la semana", "ingrediente_agotado": "ingrediente agotado",
             "canal": "canal", "prioridad_aux": "prioridad", "tiempo_prep_minutos": "tiempo de preparación (min)"}
OBJ = dd.OBJETIVO


def miles(n) -> str:
    return f"{int(n):,}".replace(",", ".")


@st.cache_data(ttl=600, show_spinner="Leyendo los pedidos limpios de HDFS...")
def _pedidos() -> pd.DataFrame:
    return dd.pedidos_limpio()


@st.cache_data(ttl=600, show_spinner="Leyendo las ventas limpias de HDFS...")
def _ventas() -> pd.DataFrame:
    return dd.ventas_limpio()


@st.cache_data(ttl=600, show_spinner="Leyendo la tabla de platos de HDFS...")
def _platos() -> pd.DataFrame:
    return dd.platos_features()


def _media_por(df: pd.DataFrame, col: str, objetivo: str = OBJ) -> pd.DataFrame:
    """Para cada valor de `col`: tiempo medio, cuartiles 25 y 75 y número de pedidos."""
    t = df.groupby(col, observed=True)[objetivo].agg(media="mean", q25=lambda s: s.quantile(.25), q75=lambda s: s.quantile(.75), pedidos="size")
    return t.reset_index()


# ======================================================================================= PEDIDOS
def pagina_eda_pedidos() -> None:
    st.caption("Exploración de los pedidos (notebook 05): qué hace que un pedido tarde más o menos · datos limpios del lote 1 (2023-2025)")
    try:
        df = _pedidos()
    except Exception as e:
        st.error("No se han podido leer los pedidos limpios de HDFS (/datalake/clean/pedidos_tiempos_preparacion). "
                 "Ejecuta antes el notebook 02 y comprueba que Docker está levantado.")
        st.exception(e)
        st.stop()

    t = df[OBJ]
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Pedidos", miles(len(df)))
    c2.metric("Tiempo medio", f"{t.mean():.1f} min")
    c3.metric("Mediana", f"{t.median():.1f} min")
    c4.metric("Percentil 90", f"{t.quantile(.9):.0f} min", help="9 de cada 10 pedidos tardan menos que esto.")
    c5.metric("Periodo", f"{df['fecha'].min():%Y} – {df['fecha'].max():%Y}")

    tab1, tab2, tab3, tab4, tab5 = st.tabs(["Tiempo de preparación", "Qué lo hace tardar", "Hora y día", "Cocina saturada", "Correlaciones"])

    # ------------------------------------------------------------------ 1. objetivo
    with tab1:
        izq, der = st.columns(2)
        izq.plotly_chart(g.histograma(t, "¿Cuánto tarda un pedido?", "minutos de preparación", bins=55), width="stretch")
        izq.caption("Cada barra cuenta cuántos pedidos tardaron ese tiempo. Hay una cola larga a la derecha: unos pocos pedidos tardan mucho más que el resto.")
        mensual = df.groupby(df["fecha"].dt.to_period("M").dt.to_timestamp()).agg(media=(OBJ, "mean"), pedidos=(OBJ, "size")).reset_index()
        fig = g.linea_media(mensual.rename(columns={"fecha": "mes"}), "mes", "media", "pedidos", "Tiempo medio por mes", "mes", "minutos")
        der.plotly_chart(fig, width="stretch")
        der.caption("Tiempo medio de cada mes (el tamaño del punto es el nº de pedidos del mes). Sirve para ver si hay tendencia o estacionalidad.")

    # ------------------------------------------------------------------ 2. variables
    with tab2:
        st.subheader("Variables numéricas")
        var = st.selectbox("Variable", ["n_platos", "num_platos_complejos", "complejidad_pedido", "cola_pedidos", "cocineros_disponibles",
                                        "hora_dec", "precipitacion_mm"], format_func=lambda v: ETIQUETAS[v])
        d = df[[var, OBJ]].copy()
        if var == "complejidad_pedido":
            d[var] = (d[var] * 2).round() / 2                         # tramos de 0,5 puntos
        elif var == "hora_dec":
            d[var] = np.floor(d[var]).astype(int)                     # hora entera
        elif var == "precipitacion_mm":
            d[var] = pd.cut(d[var], [-0.01, 0, 2, 5, 10, 500], labels=["sin lluvia", "0-2", "2-5", "5-10", "más de 10"]).astype(str)
        tabla = _media_por(d, var)
        if var == "precipitacion_mm":
            tabla["_o"] = tabla[var].map({"sin lluvia": 0, "0-2": 1, "2-5": 2, "5-10": 3, "más de 10": 4}); tabla = tabla.sort_values("_o")
        st.plotly_chart(g.linea_media(tabla, var, "media", "pedidos", f"Tiempo medio según {ETIQUETAS[var]}", ETIQUETAS[var],
                                      "tiempo medio (min)", banda=("q25", "q75")), width="stretch")
        st.caption("La línea es el tiempo medio; la banda naranja recoge la mitad central de los pedidos. Cuanto más pronunciada es la subida, "
                   "más pesa esa variable. Los puntos pequeños (pocos pedidos) son menos fiables.")

        st.subheader("Variables de tipo categoría")
        cols = st.columns(3)
        for col, (v, tit) in zip(cols, [("canal", "Canal"), ("prioridad_aux", "Prioridad"), ("ingrediente_agotado", "Ingrediente agotado")]):
            tb = _media_por(df.assign(**{v: df[v].astype(str)}), v)
            col.plotly_chart(g.barras(tb, v, "media", f"{tit}: tiempo medio", "minutos", formato=".1f", alto=300), width="stretch")
        st.caption("Tiempo medio de cada opción. En «ingrediente agotado», 1 significa que faltó algún ingrediente.")

    # ------------------------------------------------------------------ 3. hora y día
    with tab3:
        d = df.assign(hora=np.floor(df["hora_dec"]).astype(int), dia=df["dia_semana"].map(dd.DIAS))
        orden = list(dd.DIAS.values())
        modo = st.radio("Qué quieres ver", ["Tiempo medio (min)", "Nº de pedidos"], horizontal=True)
        if modo.startswith("Tiempo"):
            m = d.pivot_table(index="dia", columns="hora", values=OBJ, aggfunc="mean").reindex(orden)
            fig = g.mapa_calor(m, "Tiempo medio por día y hora", "hora del día", "día de la semana", "minutos", alto=380)
        else:
            m = d.pivot_table(index="dia", columns="hora", values=OBJ, aggfunc="size").reindex(orden)
            fig = g.mapa_calor(m, "Pedidos por día y hora", "hora del día", "día de la semana", "pedidos", decimales=0, alto=380)
        st.plotly_chart(fig, width="stretch")
        st.caption("Cada casilla es una combinación de día y hora. Los lunes aparecen en blanco porque el restaurante cierra. "
                   "Las horas punta (comida y cena) concentran más pedidos y también más espera.")
        hp = d[d["hora"].isin([13, 14, 20, 21, 22])][OBJ].mean() - d[~d["hora"].isin([13, 14, 20, 21, 22])][OBJ].mean()
        st.info(f"Los pedidos de las horas punta (13-15 h y 20-23 h) tardan de media **{hp:+.1f} min** que el resto.")

    # ------------------------------------------------------------------ 4. cola y cocineros
    with tab4:
        izq, der = st.columns(2)
        m = df.pivot_table(index="cocineros_disponibles", columns="cola_pedidos", values=OBJ, aggfunc="mean")
        cuenta = df.pivot_table(index="cocineros_disponibles", columns="cola_pedidos", values=OBJ, aggfunc="size")
        m = m.where(cuenta >= 30)                                  # casillas con muy pocos pedidos se dejan en blanco
        izq.plotly_chart(g.mapa_calor(m, "Tiempo medio según cola y cocineros", "pedidos en cola", "cocineros disponibles", "minutos",
                                      decimales=0, alto=400, texto=False), width="stretch")
        izq.caption("Arriba a la derecha (mucha cola y pocos cocineros) la cocina se satura. Las casillas con menos de 30 pedidos se dejan en blanco.")
        carga = (df["cola_pedidos"] / df["cocineros_disponibles"]).round(1)
        tb = _media_por(df.assign(carga=carga.clip(upper=8)), "carga")
        der.plotly_chart(g.linea_media(tb, "carga", "media", "pedidos", "Tiempo medio según pedidos en cola por cocinero",
                                       "pedidos en cola por cocinero", "tiempo medio (min)", banda=("q25", "q75"), alto=400), width="stretch")
        der.caption("Cola dividida entre cocineros: la curva sube cada vez más deprisa (no es una recta). Por eso el Random Forest acierta más que la regresión lineal.")

    # ------------------------------------------------------------------ 5. correlaciones
    with tab5:
        num = dd.VARIABLES_NUMERICAS + [OBJ]
        corr = df[num].corr()
        corr.index = corr.columns = [ETIQUETAS[c] for c in corr.columns]
        izq, der = st.columns([3, 2])
        izq.plotly_chart(g.mapa_calor(corr, "Correlación entre variables", "", "", "correlación", decimales=2, divergente=True, alto=520), width="stretch")
        c_obj = corr[ETIQUETAS[OBJ]].drop(ETIQUETAS[OBJ]).sort_values(key=abs, ascending=False).reset_index()
        c_obj.columns = ["variable", "correlacion"]
        der.plotly_chart(g.barras_h(c_obj, "correlacion", "variable", "Correlación con el tiempo", "correlación (−1 a 1)",
                                    colores=[g.NARANJA if v > 0 else g.AZUL for v in c_obj["correlacion"]], alto=520), width="stretch")
        st.caption("Correlación de Pearson: 1 = sube a la vez, −1 = una sube cuando la otra baja, 0 = sin relación lineal. "
                   "Naranja: sube con el tiempo; azul: lo baja. Mide relaciones en línea recta: una relación curva puede parecer más débil de lo que es.")


# ======================================================================================= VENTAS
def pagina_eda_ventas() -> None:
    st.caption("Exploración de las ventas (notebooks 01 y 03): cómo se venden los platos · datos limpios de HDFS")
    try:
        v, platos = _ventas(), _platos()
    except Exception as e:
        st.error("No se han podido leer las ventas limpias de HDFS (/datalake/clean/ventas_diarias_platos). "
                 "Ejecuta antes los notebooks 01 y 03 y comprueba que Docker está levantado.")
        st.exception(e)
        st.stop()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Filas de ventas", miles(len(v)))
    c2.metric("Platos distintos", v["id_plato"].nunique())
    c3.metric("Unidades vendidas", miles(v["unidades_vendidas"].sum()))
    c4.metric("Periodo", f"{v['fecha'].min():%Y} – {v['fecha'].max():%Y}")

    tab1, tab2, tab3, tab4 = st.tabs(["Evolución", "Contexto de la venta", "Platos", "Relaciones entre variables"])

    with tab1:
        m = v.groupby([v["fecha"].dt.to_period("M").dt.to_timestamp(), "categoria"])["unidades_vendidas"].sum().reset_index()
        m.columns = ["mes", "categoria", "unidades"]
        fig = px.area(m, x="mes", y="unidades", color="categoria", color_discrete_sequence=estilo.SERIES + [estilo.AZUL_CLARO])
        fig.update_layout(title="Unidades vendidas por mes y categoría", height=400, yaxis_title="unidades", xaxis_title=None, legend_title=None)
        st.plotly_chart(fig, width="stretch")
        st.caption("Cada color es una categoría de plato. La altura total es lo vendido ese mes.")

    with tab2:
        cols = st.columns(3)
        for col, (var, tit) in zip(cols, [("franja", "Franja"), ("ciudad", "Ciudad"), ("categoria", "Categoría")]):
            tb = v.groupby(var)["unidades_vendidas"].mean().sort_values(ascending=False).reset_index()
            col.plotly_chart(g.barras(tb, var, "unidades_vendidas", f"{tit}: unidades por fila de venta", "unidades medias", formato=".1f", alto=320), width="stretch")
        m = v.pivot_table(index="categoria", columns="franja", values="unidades_vendidas", aggfunc="mean")
        st.plotly_chart(g.mapa_calor(m, "Unidades medias por categoría y franja", "franja", "categoría", "unidades", alto=300), width="stretch")
        st.caption("Cada fila de venta es un plato, un día, una franja y una ciudad. Las casillas más oscuras son las combinaciones que más venden.")

    with tab3:
        vars_plato = [c for c in ["popularidad", "precio_medio", "coste_medio", "margen_medio", "valoracion", "dificultad", "unidades_medias"] if c in platos.columns]
        izq, der = st.columns(2)
        x = izq.selectbox("Eje horizontal", vars_plato, index=vars_plato.index("precio_medio") if "precio_medio" in vars_plato else 0)
        y = der.selectbox("Eje vertical", vars_plato, index=vars_plato.index("popularidad") if "popularidad" in vars_plato else 1)
        fig = px.scatter(platos, x=x, y=y, size="unidades_medias" if "unidades_medias" in platos else None, hover_name="id_plato",
                         color_discrete_sequence=[g.NARANJA])
        fig.update_traces(marker=dict(line=dict(color=g.AZUL, width=1), opacity=0.85))
        fig.update_layout(title=f"Los {len(platos)} platos: {x} frente a {y}", height=440)
        st.plotly_chart(fig, width="stretch")
        st.caption("Cada punto es un plato (el tamaño es lo que vende de media). Aquí se ve si hay grupos naturales: es la idea del clustering (notebook 04).")
        var = st.selectbox("Distribución de una variable", vars_plato, key="dist_plato")
        st.plotly_chart(g.histograma(platos[var], f"Distribución de {var} entre los platos", var, bins=20, alto=300), width="stretch")

    with tab4:
        vars_plato = [c for c in ["popularidad", "precio_medio", "coste_medio", "margen_medio", "valoracion", "dificultad", "unidades_medias"] if c in platos.columns]
        corr = platos[vars_plato].corr()
        st.plotly_chart(g.mapa_calor(corr, "Correlación entre las variables de los platos", "", "", "correlación", decimales=2, divergente=True, alto=480), width="stretch")
        st.caption("Si dos variables están muy correlacionadas (precio y margen, por ejemplo) aportan casi la misma información; "
                   "por eso en el notebook 03 se eligieron solo algunas para el clustering.")
