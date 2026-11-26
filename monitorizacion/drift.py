"""
drift.py
========
Herramientas para vigilar si un lote NUEVO de pedidos sigue "pareciéndose" al lote con el que
se entrenó el modelo (Objetivo 2: regresión del tiempo de preparación).

Hay dos preguntas distintas y por eso dos tipos de drift:

  1. DATA DRIFT (¿han cambiado las ENTRADAS?)
     Se mide SIN necesitar el tiempo real: compara la distribución de cada variable del lote
     nuevo con la del lote de referencia. Se puede calcular el mismo día que llegan los
     pedidos, antes de saber cuánto tardó cada uno. Es la ALERTA TEMPRANA.
       - PSI (Population Stability Index): cuánto se ha movido la distribución. Es la métrica
         principal porque con miles de pedidos cualquier test estadístico sale "significativo"
         por pequeña que sea la diferencia; el PSI mide el TAMAÑO del cambio, no si existe.
       - KS (Kolmogórov-Smirnov, variables numéricas) y chi² (categóricas): confirman el cambio
         con un test estadístico. Se guardan, pero NO se usan para decidir (ver arriba).

  2. MODEL DRIFT / CONCEPT DRIFT (¿ha empeorado el MODELO?)
     Necesita el tiempo REAL de cada pedido (llega con retraso: cuando el pedido ya se sirvió).
     Se pasa el modelo vigente por el lote nuevo y se compara su error (MAE, RMSE, R²) con el
     que tuvo en su examen original. Si el error sube mucho, la relación entre entradas y
     tiempo ha cambiado (concept drift) o las entradas se han ido a zonas que el modelo no vio.

Umbrales de decisión (PSI, regla habitual en banca/scoring):  < 0,10 estable · 0,10-0,25 vigilar · > 0,25 alerta.
Para el error del modelo: MAE hasta +15 % sobre la referencia = normal, +15 % a +30 % = vigilar, > +30 % = alerta.
Son valores de partida razonables, no verdades universales: conviene recalibrarlos con la experiencia del negocio.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

# ----------------------------------------------------------------------------------------------
# Umbrales (en un solo sitio para poder cambiarlos fácilmente)
# ----------------------------------------------------------------------------------------------
PSI_VIGILAR, PSI_ALERTA = 0.10, 0.25
MAE_VIGILAR, MAE_ALERTA = 0.15, 0.30        # subida relativa del MAE frente a la referencia
MIN_VARIABLES_EN_ALERTA = 2                 # nº de variables con PSI > 0,25 para pedir reentrenar por data drift
EPS = 1e-4                                  # evita log(0) cuando un tramo queda vacío
# Variables que SE MUESTRAN pero NO DECIDEN. La lluvia es un dato del DÍA (todos los pedidos de un día comparten
# el mismo valor), así que un mes solo aporta ~30 observaciones independientes aunque tenga miles de filas, y
# además es estacional (llueve más en invierno). Con tan pocas muestras el PSI mensual oscila mucho y daría
# falsas alarmas (lo comprobamos con el lote de control). Se vigila en el lote completo, no mes a mes.
INFORMATIVAS = ("precipitacion_mm",)


# ----------------------------------------------------------------------------------------------
# 1) Data drift
# ----------------------------------------------------------------------------------------------
def psi_numerica(ref: pd.Series, nuevo: pd.Series, tramos: int = 10) -> float:
    """PSI de una variable numérica. Los tramos salen de los cuantiles de la REFERENCIA
    (cada tramo contiene ~10 % de los pedidos de referencia); después se cuenta qué % del lote nuevo cae en cada uno."""
    ref, nuevo = ref.dropna().astype(float), nuevo.dropna().astype(float)
    cortes = np.unique(np.quantile(ref, np.linspace(0, 1, tramos + 1)))
    if len(cortes) < 3:                                   # variable casi constante (p. ej. ingrediente agotado 0/1)
        cortes = np.unique(np.concatenate([cortes, [ref.min() - 1, ref.max() + 1]]))
    cortes[0], cortes[-1] = -np.inf, np.inf               # el lote nuevo puede salirse del rango de la referencia
    p = np.histogram(ref, cortes)[0] / len(ref)
    q = np.histogram(nuevo, cortes)[0] / len(nuevo)
    p, q = np.clip(p, EPS, None), np.clip(q, EPS, None)
    return float(np.sum((q - p) * np.log(q / p)))


def psi_categorica(ref: pd.Series, nuevo: pd.Series) -> float:
    """PSI de una variable de texto: compara el % de cada categoría."""
    cats = sorted(set(ref.astype(str)) | set(nuevo.astype(str)))
    p = ref.astype(str).value_counts(normalize=True).reindex(cats).fillna(0).clip(lower=EPS)
    q = nuevo.astype(str).value_counts(normalize=True).reindex(cats).fillna(0).clip(lower=EPS)
    return float(np.sum((q - p) * np.log(q / p)))


def nivel_psi(psi: float) -> str:
    return "alerta" if psi > PSI_ALERTA else "vigilar" if psi > PSI_VIGILAR else "estable"


def data_drift(ref: pd.DataFrame, nuevo: pd.DataFrame, numericas: list[str], categoricas: list[str]) -> pd.DataFrame:
    """Una fila por variable: PSI + nivel + test (KS o chi²) + cómo se ha movido (media o categoría principal)."""
    from scipy import stats      # solo aquí: así el PSI se puede usar (p. ej. en el dashboard) sin instalar scipy
    filas = []
    for v in numericas:
        psi = psi_numerica(ref[v], nuevo[v])
        ks = stats.ks_2samp(ref[v].dropna(), nuevo[v].dropna())
        filas.append(dict(variable=v, tipo="numérica", psi=psi, nivel=nivel_psi(psi), test="KS",
                          estadistico=float(ks.statistic), p_valor=float(ks.pvalue),
                          referencia=float(ref[v].mean()), nuevo=float(nuevo[v].mean())))
    for v in categoricas:
        psi = psi_categorica(ref[v], nuevo[v])
        tabla = pd.concat([ref[v].astype(str).value_counts(), nuevo[v].astype(str).value_counts()], axis=1).fillna(0)
        chi2, p, *_ = stats.chi2_contingency(tabla.to_numpy())
        # En las categóricas se muestra el % de la categoría que más ha cambiado
        pc_ref, pc_new = ref[v].astype(str).value_counts(normalize=True), nuevo[v].astype(str).value_counts(normalize=True)
        dif = (pc_new.reindex(pc_ref.index).fillna(0) - pc_ref).abs()
        cat = dif.idxmax()
        filas.append(dict(variable=v, tipo="categórica", psi=psi, nivel=nivel_psi(psi), test="chi²",
                          estadistico=float(chi2), p_valor=float(p),
                          referencia=float(pc_ref[cat]), nuevo=float(pc_new.get(cat, 0)), detalle=f"% de «{cat}»"))
    t = pd.DataFrame(filas)
    t["decide"] = ~t["variable"].isin(INFORMATIVAS)          # False = solo informativa (ver INFORMATIVAS)
    if "detalle" not in t:
        t["detalle"] = ""
    t["detalle"] = t["detalle"].fillna("media")
    return t.sort_values("psi", ascending=False).reset_index(drop=True)


# ----------------------------------------------------------------------------------------------
# 2) Model drift
# ----------------------------------------------------------------------------------------------
def metricas(reales, predichos) -> dict[str, float]:
    """MAE y RMSE (minutos), R² y sesgo (media de real − predicho: positivo = el modelo se queda corto)."""
    from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score   # solo aquí (el dashboard no las necesita)
    reales = np.asarray(reales, float)
    predichos = np.asarray(predichos, float)
    return {"mae": float(mean_absolute_error(reales, predichos)),
            "rmse": float(np.sqrt(mean_squared_error(reales, predichos))),
            "r2": float(r2_score(reales, predichos)),
            "sesgo": float(np.mean(reales - predichos))}


def nivel_mae(subida: float) -> str:
    return "alerta" if subida > MAE_ALERTA else "vigilar" if subida > MAE_VIGILAR else "estable"


def model_drift(modelo, X_nuevo: pd.DataFrame, y_nuevo: pd.Series, mae_referencia: float) -> dict:
    """Pasa el modelo por el lote nuevo y compara su MAE con el de su examen original."""
    pred = modelo.predict(X_nuevo)
    m = metricas(y_nuevo, pred)
    subida = m["mae"] / mae_referencia - 1
    return {**m, "mae_referencia": mae_referencia, "subida_mae": subida, "nivel": nivel_mae(subida), "predicho": pred}


def mae_por_mes(df: pd.DataFrame, reales: str, predichos: np.ndarray) -> pd.DataFrame:
    """MAE de cada mes: sirve para ver CUÁNDO empieza a fallar el modelo (monitorización en el tiempo)."""
    t = pd.DataFrame({"mes": df["fecha"].dt.to_period("M").astype(str).values,
                      "error": np.abs(df[reales].values - predichos)})
    return t.groupby("mes")["error"].agg(mae="mean", pedidos="size").reset_index()


# ----------------------------------------------------------------------------------------------
# 3) Decisión: ¿qué hacemos con este lote?
# ----------------------------------------------------------------------------------------------
@dataclass
class Decision:
    accion: str            # "mantener" | "vigilar" | "reentrenar"
    motivos: list[str]

    def __str__(self) -> str:
        return f"{self.accion.upper()}: " + "; ".join(self.motivos)


def decidir(tabla_drift: pd.DataFrame, modelo: dict | None = None) -> Decision:
    """Regla de decisión (la misma que se propone en la estrategia):

    - REENTRENAR si el MAE del modelo sube más de un 30 %  -> la prueba definitiva: el modelo ya no sirve.
      También si 2 o más variables tienen PSI > 0,25 aunque aún no tengamos el tiempo real (alerta temprana:
      se adelanta la recogida de datos etiquetados para confirmar).
    - VIGILAR si el MAE sube entre un 15 % y un 30 %, o alguna variable tiene PSI > 0,25, o hay variables con PSI entre 0,10 y 0,25.
    - MANTENER en el resto de casos.
    """
    motivos = []
    tabla_drift = tabla_drift[tabla_drift["decide"]]          # las variables solo informativas no entran en la decisión
    n_alerta = int((tabla_drift["nivel"] == "alerta").sum())
    n_vigilar = int((tabla_drift["nivel"] == "vigilar").sum())
    peor = tabla_drift.iloc[0]
    if modelo is not None:
        motivos.append(f"MAE {modelo['mae']:.2f} min ({modelo['subida_mae']:+.0%} vs referencia, nivel {modelo['nivel']})")
    motivos.append(f"{n_alerta} variable(s) con PSI > {PSI_ALERTA} y {n_vigilar} entre {PSI_VIGILAR} y {PSI_ALERTA} "
                   f"(la peor: {peor['variable']}, PSI {peor['psi']:.2f})")

    if modelo is not None and modelo["nivel"] == "alerta":
        return Decision("reentrenar", motivos)
    if n_alerta >= MIN_VARIABLES_EN_ALERTA and modelo is None:
        return Decision("reentrenar", motivos)
    if (modelo is not None and modelo["nivel"] == "vigilar") or n_alerta >= 1 or n_vigilar >= 1:
        return Decision("vigilar", motivos)
    return Decision("mantener", motivos)


# ----------------------------------------------------------------------------------------------
# 4) Seguimiento en el tiempo: el mismo análisis, mes a mes
# ----------------------------------------------------------------------------------------------
def seguimiento_mensual(ref: pd.DataFrame, nuevo: pd.DataFrame, numericas: list[str], categoricas: list[str],
                        modelo, objetivo: str, mae_referencia: float) -> pd.DataFrame:
    """Aplica data drift + model drift + decisión a cada mes del lote nuevo.

    Es lo que haría una monitorización real: cada vez que se cierra un mes se evalúan sus pedidos y se
    guarda una fila. Así se ve CUÁNDO empieza el cambio, no solo que ha habido uno.
    """
    filas = []
    mes = nuevo["fecha"].dt.to_period("M")
    for m, grupo in nuevo.groupby(mes):
        tabla = data_drift(ref, grupo, numericas, categoricas)
        tabla_dec = tabla[tabla["decide"]]
        md = model_drift(modelo, grupo[numericas + categoricas], grupo[objetivo], mae_referencia)
        filas.append({"mes": str(m), "pedidos": len(grupo),
                      "variables_en_alerta": int((tabla_dec["nivel"] == "alerta").sum()),
                      "variables_a_vigilar": int((tabla_dec["nivel"] == "vigilar").sum()),
                      "peor_variable": tabla_dec.iloc[0]["variable"], "psi_max": float(tabla_dec.iloc[0]["psi"]),
                      "mae": md["mae"], "subida_mae": md["subida_mae"], "r2": md["r2"], "sesgo": md["sesgo"],
                      "decision": decidir(tabla, md).accion})
    return pd.DataFrame(filas)
