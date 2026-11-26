"""
pag_drift.py — Página de MONITORIZACIÓN: data drift y model drift (lo que vimos en el notebook 07).

Qué enseña:
  · Resumen: qué decidió la monitorización con cada lote nuevo (mantener, vigilar o reentrenar).
  · Data drift: cuánto se han movido las variables de entrada (PSI) y cómo ha cambiado su forma.
  · Seguimiento mensual: cuándo empezó a fallar el modelo.
  · Reentrenamiento: qué modelo candidato salió mejor y qué versiones hay en MLflow.
  · Estrategia: qué se vigila, cada cuánto y cuándo se reentrena.
Las tablas y notas las guarda el notebook 07 en MLflow; las distribuciones se leen en vivo de HDFS.
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import datos_dashboard as dd
import graficos as g
import mlflow_rest as ml
from pag_modelos import MODELO_REGRESION, _csv, _ejecuciones, _imagen

D = dd.D                                          # monitorizacion/drift.py (PSI y umbrales)
EXP_DRIFT = "smart-restaurant-monitorizacion-drift"
ETIQUETAS = {"n_platos": "nº de platos", "num_platos_complejos": "nº de platos complejos", "complejidad_pedido": "complejidad del pedido",
             "cola_pedidos": "pedidos en cola", "cocineros_disponibles": "cocineros disponibles", "precipitacion_mm": "lluvia (mm)",
             "hora_dec": "hora del día", "dia_semana": "día de la semana", "ingrediente_agotado": "ingrediente agotado",
             "canal": "canal", "prioridad_aux": "prioridad"}
TEXTO_DECISION = {"mantener": "MANTENER el modelo", "vigilar": "VIGILAR", "reentrenar": "REENTRENAR"}


@st.cache_data(ttl=300, show_spinner="Leyendo los pedidos de referencia de HDFS...")
def _referencia() -> pd.DataFrame:
    return dd.referencia_entrenamiento(dd.pedidos_limpio())


@st.cache_data(ttl=300, show_spinner="Leyendo y limpiando el lote nuevo de HDFS...")
def _lote(nombre: str) -> pd.DataFrame:
    return dd.lote_limpio(nombre)[0]


@st.cache_data(ttl=120, show_spinner=False)
def _lotes() -> list[str]:
    return dd.lotes_disponibles()


def _decision_html(accion: str, detalle: str) -> str:
    color = g.COLOR_DECISION[accion]
    return (f"<div style='background:{color};color:white;border-radius:10px;padding:0.7rem 1rem;font-weight:700;font-size:1.1rem'>"
            f"{TEXTO_DECISION[accion]}<div style='font-weight:400;font-size:0.85rem;margin-top:2px'>{detalle}</div></div>")


def _decision_lote(clave: str, m: dict, tabla: pd.DataFrame | None) -> str:
    """Aplica la misma regla del notebook (drift.decidir) a las notas guardadas en MLflow."""
    if tabla is None or f"{clave}_subida_mae" not in m:
        return "mantener"
    subida = m[f"{clave}_subida_mae"]
    modelo = {"mae": m[f"{clave}_mae"], "subida_mae": subida, "nivel": D.nivel_mae(subida)}
    return D.decidir(tabla, modelo).accion


def pagina_drift() -> None:
    st.caption("Monitorización del modelo de tiempo de preparación (notebook 07): ¿han cambiado los datos? ¿ha empeorado el modelo? ¿qué hacemos?")
    runs = [r for r in _ejecuciones(EXP_DRIFT) if r["tags"].get("fase") == "monitorizacion"]
    if not runs:
        if not ml.disponible():
            st.warning(f"No se puede conectar con MLflow ({ml.URI}). Comprueba que el servicio está arrancado: `docker compose ps`.")
        else:
            st.warning("Todavía no hay ninguna monitorización guardada en MLflow. Ejecuta el notebook 07 (después de los notebooks 02 y 06 "
                       "y de ingerir los lotes con `scripts/ingesta_hdfs.sh`).")
        st.markdown(ESTRATEGIA)
        st.stop()

    run = runs[0]
    m = run["metricas"]
    claves = [c for c in ("control", "drift") if f"{c}_mae" in m]
    tablas = {c: _csv(run, f"data_drift_{c}.csv") for c in claves}
    seguimientos = {c: _csv(run, f"seguimiento_mensual_{c}.csv") for c in claves}
    mae_ref = m["control_mae"] / (1 + m["control_subida_mae"]) if "control_subida_mae" in m else None
    st.caption(f"Última monitorización: {run['nombre']} · {run['inicio']:%d/%m/%Y %H:%M} · modelo vigente: {run['tags'].get('modelo_vigente', '—')}")

    tab1, tab2, tab3, tab4, tab5 = st.tabs(["Resumen", "Data drift", "Seguimiento mensual", "Reentrenamiento", "Estrategia"])

    # ------------------------------------------------------------------ 1. resumen
    with tab1:
        st.markdown("Pasamos por el **modelo vigente** (sin reentrenarlo) dos lotes nuevos de enero a junio de 2026: uno donde **nada cambia** "
                    "(*control*, para comprobar que no hay falsas alarmas) y otro donde **desde marzo** cambian la carta, la plantilla, la demanda y el delivery "
                    "(*drift*). Los dos son **sintéticos**.")
        cols = st.columns(len(claves))
        for col, c in zip(cols, claves):
            with col:
                accion = _decision_lote(c, m, tablas.get(c))
                st.markdown(_decision_html(accion, f"Lote {c}"), unsafe_allow_html=True)
                a, b = st.columns(2)
                a.metric("Error medio (MAE)", f"{m[f'{c}_mae']:.2f} min", f"{m[f'{c}_subida_mae']:+.0%} vs referencia",
                         delta_color="inverse" if m[f"{c}_subida_mae"] > D.MAE_VIGILAR else "off")
                b.metric("R²", f"{m[f'{c}_r2']:.2f}")
                a, b = st.columns(2)
                b.metric("Sesgo (real − predicho)", f"{m[f'{c}_sesgo']:+.2f} min", help="Positivo: el modelo se queda corto y promete menos de lo que tarda.")
                if f"{c}_psi_max" in m:
                    a.metric("PSI máximo", f"{m[f'{c}_psi_max']:.2f}", help="La variable que más se ha movido. Más de 0,25 = alerta.")
        st.markdown(
            f"**Umbrales:** PSI menor de {D.PSI_VIGILAR} estable · {D.PSI_VIGILAR}–{D.PSI_ALERTA} vigilar · mayor de {D.PSI_ALERTA} alerta. "
            f"MAE: hasta +{D.MAE_VIGILAR:.0%} sobre el de referencia normal · +{D.MAE_VIGILAR:.0%} a +{D.MAE_ALERTA:.0%} vigilar · más de +{D.MAE_ALERTA:.0%} alerta."
            + (f" MAE de referencia: **{mae_ref:.2f} min**." if mae_ref else ""))

    # ------------------------------------------------------------------ 2. data drift
    with tab2:
        st.markdown("El **PSI** mide cuánto se ha movido cada variable respecto a los pedidos con los que se entrenó el modelo. "
                    "Se puede calcular **sin saber cuánto tardó cada pedido**, así que es la alerta temprana.")
        c = st.radio("Lote", claves, horizontal=True, format_func=lambda x: f"lote {x}")
        t = tablas.get(c)
        if t is None:
            st.info("No se ha podido leer la tabla de data drift de MLflow.")
        else:
            t = t.sort_values("psi", ascending=False).copy()
            t["etiqueta"] = t["variable"].map(ETIQUETAS) + t["decide"].map({True: "", False: " (solo informativa)"})
            colores = [g.COLOR_NIVEL.get(n, g.GRIS) if d else "#B8C4C9" for n, d in zip(t["nivel"], t["decide"])]
            fig = g.barras_h(t, "psi", "etiqueta", f"PSI de cada variable · lote {c}", "PSI (cuánto se ha movido)", colores=colores, alto=420)
            for umbral, texto in ((D.PSI_VIGILAR, "vigilar"), (D.PSI_ALERTA, "alerta")):
                fig.add_vline(x=umbral, line_dash="dash", line_color=g.GRIS, annotation_text=texto, annotation_position="top")
            st.plotly_chart(fig, width="stretch")
            st.caption("Verde: estable · naranja: vigilar · rojo: alerta. La lluvia sale en gris porque solo se muestra: es un dato del día y es estacional, "
                       "así que no decide. Un semestre mezcla meses normales y cambiados, y por eso el cambio se diluye (mira el seguimiento mensual).")
            vista = t[["etiqueta", "psi", "nivel", "test", "estadistico", "p_valor", "referencia", "nuevo", "detalle"]].rename(
                columns={"etiqueta": "variable", "referencia": "entrenamiento", "nuevo": "lote nuevo", "detalle": "qué se compara"})
            st.dataframe(vista.round(3), width="stretch", hide_index=True)
            st.caption("Los tests KS y chi² salen casi siempre «significativos» con tantos pedidos, por pequeña que sea la diferencia; "
                       "por eso decidimos con el PSI, que mide cuánto ha cambiado.")

            st.subheader("Cómo ha cambiado la forma de una variable")
            lotes = [n for n in _lotes() if n.endswith(c)]
            if not lotes:
                st.info(f"No hay un lote «{c}» en HDFS (/datalake/raw/pedidos_tiempos_preparacion/lote=...). Ingiérelo con scripts/ingesta_hdfs.sh.")
            else:
                var = st.selectbox("Variable", list(t["variable"]), format_func=lambda v: ETIQUETAS.get(v, v))
                ref, nuevo = _referencia(), _lote(lotes[0])
                if var in dd.VARIABLES_CATEGORIA:
                    fig = g.barras_categorias_doble(ref[var], nuevo[var], "entrenamiento (2023-2025)", f"lote {c}", ETIQUETAS[var])
                else:
                    fig = g.histograma_doble(ref[var], nuevo[var], "entrenamiento (2023-2025)", f"lote {c}", ETIQUETAS[var], ETIQUETAS[var],
                                             bins=7 if ref[var].nunique() <= 10 else 30)
                st.plotly_chart(fig, width="stretch")
                st.caption("Las dos distribuciones están en % de pedidos para poder compararlas aunque los lotes tengan tamaños distintos. "
                           "Si las barras azules y las naranjas coinciden, la variable no ha cambiado.")

    # ------------------------------------------------------------------ 3. seguimiento mensual
    with tab3:
        st.markdown("En la práctica se evalúa **cada mes que se cierra**. Así se ve **cuándo** empieza el problema, no solo que existe.")
        if not all(s is not None for s in seguimientos.values()) or not seguimientos:
            st.info("No se ha podido leer el seguimiento mensual de MLflow.")
        else:
            fig = go.Figure()
            estilo_lote = {"control": (g.VERDE, "circle"), "drift": (g.ROJO, "square")}
            for c, s in seguimientos.items():
                fig.add_scatter(x=s["mes"], y=s["mae"], mode="lines+markers", name=f"lote {c}", line=dict(color=estilo_lote[c][0], width=3),
                                marker=dict(symbol=estilo_lote[c][1], size=9))
            if mae_ref:
                fig.add_hline(y=mae_ref, line_color=g.AZUL, annotation_text=f"MAE de referencia ({mae_ref:.2f})", annotation_position="bottom right")
                fig.add_hline(y=mae_ref * (1 + D.MAE_VIGILAR), line_dash="dash", line_color=g.NARANJA, annotation_text=f"vigilar (+{D.MAE_VIGILAR:.0%})",
                              annotation_position="top left")
                fig.add_hline(y=mae_ref * (1 + D.MAE_ALERTA), line_dash="dash", line_color=g.ROJO, annotation_text=f"alerta (+{D.MAE_ALERTA:.0%})",
                              annotation_position="top left")
            fig.update_layout(title="Error del modelo vigente, mes a mes", height=420, yaxis_title="MAE (minutos)", xaxis_title="mes de 2026",
                              yaxis_rangemode="tozero", legend=dict(orientation="h", y=1.12))
            st.plotly_chart(fig, width="stretch")
            st.caption("Mientras la línea esté por debajo de la naranja, el modelo sigue como el día del examen. Al cruzar la roja, la decisión es reentrenar.")

            elegido = st.radio("Detalle del lote", list(seguimientos), horizontal=True, format_func=lambda x: f"lote {x}", key="seg_lote")
            s = seguimientos[elegido].copy()
            vista = s[["mes", "pedidos", "variables_en_alerta", "variables_a_vigilar", "peor_variable", "psi_max", "mae", "subida_mae", "sesgo", "decision"]].copy()
            vista["peor_variable"] = vista["peor_variable"].map(lambda v: ETIQUETAS.get(v, v))
            vista["subida_mae"] = vista["subida_mae"].map(lambda x: f"{x:+.0%}")
            estilos = vista.style.map(lambda v: f"background-color:{g.COLOR_DECISION.get(v, 'white')};color:white;font-weight:bold", subset=["decision"]) \
                .format({"psi_max": "{:.2f}", "mae": "{:.2f}", "sesgo": "{:+.2f}"})
            st.dataframe(estilos, width="stretch", hide_index=True)

    # ------------------------------------------------------------------ 4. reentrenamiento
    with tab4:
        comp = _csv(run, "comparativa_candidatos.csv", index_col=0)
        if comp is None:
            st.info("No se ha podido leer la comparación de candidatos de MLflow.")
        else:
            comp = comp.reset_index().rename(columns={"index": "modelo"})
            colores = [g.GRIS if str(n).startswith("vigente") else g.AZUL for n in comp["modelo"]]
            izq, der = st.columns([3, 2])
            izq.plotly_chart(g.barras(comp, "modelo", "mae_examen_nuevo", "Error con los pedidos más recientes (más bajo = mejor)", "MAE (minutos)",
                                      colores=colores, alto=400), width="stretch")
            izq.caption("El examen son los pedidos más recientes del lote nuevo, que ningún candidato ha visto al aprender. "
                        "Todos usan el mismo Random Forest: solo cambian los datos con los que se entrena.")
            mejor = run["params"].get("mejor_candidato", "—")
            der.metric("Mejor candidato", mejor)
            if "mejora_relativa" in m:
                der.metric("Mejora frente al vigente", f"{m['mejora_relativa']:.0%}", f"MAE {m['vigente_mae_examen_nuevo']:.2f} → {m['candidato_mae_examen_nuevo']:.2f} min",
                           delta_color="off")
            der.markdown(f"**Condiciones para promoverlo:** bajar el MAE al menos un **{float(run['params'].get('mejora_minima', 0.1)):.0%}**, "
                         f"R² no más de **{run['params'].get('tolerancia_r2', '0.05')}** peor que el de referencia y sesgo dentro de "
                         f"**±{run['params'].get('sesgo_maximo', '1.0')} min**.")
            st.dataframe(comp.round(3), width="stretch", hide_index=True)
        versiones = ml.versiones_modelo(MODELO_REGRESION)
        if versiones:
            st.subheader("Versiones del modelo en MLflow")
            st.caption("`actual` es lo que usa la API. El candidato reentrenado queda como `candidato` y solo pasa a `actual` si una persona lo decide.")
            st.dataframe(pd.DataFrame(versiones)[["version", "alias", "creada", "descripcion"]], width="stretch", hide_index=True)
        img = _imagen(run, "candidatos.png")
        if img:
            with st.expander("Gráfica guardada por el notebook 07"):
                st.image(img, width="stretch")

    # ------------------------------------------------------------------ 5. estrategia
    with tab5:
        st.markdown(ESTRATEGIA)


ESTRATEGIA = f"""
### Qué se vigila, cada cuánto y con qué umbral

| Qué | Cómo | Cuándo | Umbral | ¿Necesita el tiempo real? |
|---|---|---|---|---|
| **Calidad de captura** | % de filas que descarta la limpieza | Cada lote | 3 puntos por encima del histórico | No |
| **Data drift** | PSI de cada variable contra el entrenamiento | Mensual | {D.PSI_VIGILAR} vigilar · {D.PSI_ALERTA} alerta | **No** (alerta temprana) |
| **Model drift** | MAE, RMSE, R² y sesgo del modelo vigente | Mensual, cuando se conoce el tiempo real | +{D.MAE_VIGILAR:.0%} vigilar · +{D.MAE_ALERTA:.0%} alerta | Sí |
| **Variables de contexto** (lluvia) | PSI sobre el lote completo | Trimestral | Solo informativa (es estacional) | No |

### Cuándo se reentrena
1. **Por alarma:** MAE +{D.MAE_ALERTA:.0%}, o 2 o más variables con PSI > {D.PSI_ALERTA} mientras llega el tiempo real.
2. **Por calendario:** cada 6 meses aunque todo esté en verde (el drift gradual y estacional no siempre cruza los umbrales).
3. **Por evento conocido:** carta nueva, apertura o cierre de un local, cambio de plantilla.

### Cómo se reentrena (y por qué es seguro)
- Se limpia el lote con **la misma función** que el lote original y se comparan varias formas de reentrenar con un examen **posterior en el tiempo**.
- Nunca se despliega a ciegas: el candidato entra con el alias `candidato` y solo pasa a `actual` si mejora el MAE, mantiene un R² comparable y deja el sesgo casi a cero.
- Es **reversible** (volver atrás es mover un alias) y **trazable** (cada ejecución guarda en MLflow umbrales, tablas y gráficas).
- Tras promover un modelo, **la referencia se reinicia**: su entrenamiento pasa a ser la nueva «normalidad».

> Los lotes son sintéticos y el cambio del lote *drift* está programado a propósito: demuestra que el método detecta cambios y se calla cuando no los hay, no cómo cambian los restaurantes reales. Los umbrales son convenciones habituales que habría que recalibrar con la experiencia del negocio.
"""
