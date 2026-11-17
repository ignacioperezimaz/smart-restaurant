"""
Acceso a los datos del proyecto (carpeta data/ del repositorio).

Una sola fuente de verdad para las páginas:
  - El manifiesto resumen_ensuciado.json (filas, bytes, columnas y errores
    inyectados de cada CSV). Si no se encuentra la carpeta data/, se usa una
    copia incluida en dashboard/datos/ para que el panel funcione igualmente.
  - Muestras de los CSV tal como vienen (con sus errores).
  - Indicadores de drift calculados en vivo sobre los CSV.

La carpeta de datos se puede cambiar con la variable de entorno DATA_DIR.
Por defecto es ../data respecto a este archivo (en Docker: /repo/data).
"""
import json
import os
from pathlib import Path

import pandas as pd
import streamlit as st

BASE_DIR = Path(__file__).parent
DATA_DIR = Path(os.environ.get("DATA_DIR", BASE_DIR.parent / "data"))
RESPALDO_JSON = BASE_DIR / "datos" / "resumen_ensuciado.json"

# Orden en que se muestran las fuentes y nombres de los lotes
FUENTES = ["afluencia_diaria", "reservas", "rendimiento_platos", "resenas"]
LOTES = {"historico": "Histórico", "lote_drift": "Lote drift"}


@st.cache_data(ttl=300, show_spinner=False)
def cargar_manifiesto():
    """Devuelve (manifiesto, origen) o (None, None) si no se encuentra el JSON."""
    candidatos = (
        (DATA_DIR / "resumen_ensuciado.json", "carpeta data del repositorio"),
        (RESPALDO_JSON, "copia incluida en el dashboard"),
    )
    for ruta, origen in candidatos:
        try:
            with open(ruta, encoding="utf-8") as f:
                return json.load(f), origen
        except (OSError, ValueError):
            continue
    return None, None


def tabla_archivos(manifiesto: dict) -> pd.DataFrame:
    """Una fila por CSV: fuente, lote, archivo, filas (del CSV, con duplicados) y bytes."""
    filas = []
    for nombre, info in manifiesto["archivos"].items():
        filas.append((info["fuente"], LOTES[info["lote"]], nombre, info["filas_csv"], info["bytes"]))
    df = pd.DataFrame(filas, columns=["fuente", "lote", "archivo", "filas", "bytes"])
    # Primero el lote histórico y luego el drift; dentro de cada lote, el orden de FUENTES
    df["_lote"] = df["lote"].map({v: i for i, v in enumerate(LOTES.values())})
    df["_fuente"] = df["fuente"].map({f: i for i, f in enumerate(FUENTES)})
    return df.sort_values(["_lote", "_fuente"]).drop(columns=["_lote", "_fuente"]).reset_index(drop=True)


# ---------------------------------------------------------------
# Muestras de los CSV tal como vienen
# ---------------------------------------------------------------
def _fila_con_error(fila) -> bool:
    """Detector sencillo de errores visibles: vacíos, marcadores, espacios, €, clave huérfana."""
    for valor in fila:
        texto = str(valor)
        if (
            texto == ""
            or texto != texto.strip()
            or texto.lower() in {"sin dato", "na", "null"}
            or "€" in texto
            or "RST-9999" in texto
        ):
            return True
    return False


@st.cache_data(ttl=300, show_spinner=False)
def muestras(archivo: str, n: int = 5):
    """
    Devuelve (primeras_filas, filas_con_error) de un CSV, todo como texto,
    o None si el archivo no existe. Se leen solo las 4.000 primeras filas.
    """
    ruta = DATA_DIR / archivo
    if not ruta.exists():
        return None
    # keep_default_na=False: así "NA" y los vacíos se ven tal cual, no como NaN
    df = pd.read_csv(ruta, dtype=str, keep_default_na=False, nrows=4000)
    primeras = df.head(n)
    con_error = df[df.apply(_fila_con_error, axis=1)].head(n)
    # Un campo vacío no se vería en la tabla: lo rotulamos
    return primeras.replace("", "(vacío)"), con_error.replace("", "(vacío)")


# ---------------------------------------------------------------
# Indicadores de drift calculados en vivo
# ---------------------------------------------------------------
def _num(serie: pd.Series) -> pd.Series:
    """Convierte a número aceptando coma decimal y símbolo €; lo no numérico pasa a NaN."""
    texto = serie.astype(str).str.replace("€", "", regex=False).str.replace(",", ".", regex=False)
    return pd.to_numeric(texto.str.strip(), errors="coerce")


def _norm(serie: pd.Series) -> pd.Series:
    """Normaliza texto: sin espacios sobrantes y en minúsculas."""
    return serie.astype(str).str.strip().str.lower()


def _entre(serie: pd.Series, minimo: float, maximo: float) -> pd.Series:
    """Se queda con los valores plausibles; descarta errores y outliers."""
    return serie[(serie >= minimo) & (serie <= maximo)]


def _indicadores_lote(lote: str) -> dict:
    """Calcula los indicadores de un lote leyendo solo las columnas necesarias."""
    leer = lambda fuente, cols: pd.read_csv(  # noqa: E731
        DATA_DIR / f"{fuente}_{lote}.csv", dtype=str, usecols=["id_registro", *cols]
    ).drop_duplicates("id_registro")  # los duplicados inyectados no cuentan dos veces

    # Reservas: % que no se cumplen (cancelada + no_show) y % por web
    r = leer("reservas", ["estado_final", "canal"])
    estado = _norm(r["estado_final"])
    estado = estado[estado.isin(["asistio", "cancelada", "no_show"])]
    canal = _norm(r["canal"])
    canal = canal[canal.isin(["web", "telefono"])]
    fallan = 100 * estado.isin(["cancelada", "no_show"]).mean()
    web = 100 * (canal == "web").mean()

    # Reseñas: sentimiento a partir de la puntuación (TheFork puntúa de 2 a 10: se divide entre 2)
    s = leer("resenas", ["plataforma", "puntuacion"])
    punt = _num(s["puntuacion"])
    punt = punt.where(_norm(s["plataforma"]) != "thefork", punt / 2)
    punt = _entre(punt, 1, 5)
    positiva = 100 * (punt >= 3.5).mean()
    negativa = 100 * (punt < 2.5).mean()

    # Afluencia: clientes medios por restaurante y día, clima previsto
    a = leer("afluencia_diaria", ["clientes_reales", "temperatura_prevista_c", "lluvia_prevista_mm"])
    clientes = _entre(_num(a["clientes_reales"]), 0, 1000).mean()
    temperatura = _entre(_num(a["temperatura_prevista_c"]), -20, 50).mean()
    lluvia = _entre(_num(a["lluvia_prevista_mm"]), 0, 200).mean()

    # Platos: ratio coste/precio y unidades vendidas medias
    p = leer("rendimiento_platos", ["precio_unitario_eur", "coste_unitario_eur", "unidades_vendidas"])
    precio, coste = _num(p["precio_unitario_eur"]), _num(p["coste_unitario_eur"])
    valido = (precio > 0) & (precio < 200) & (coste > 0) & (coste < 200)
    ratio = 100 * (coste[valido] / precio[valido]).mean()
    unidades = _entre(_num(p["unidades_vendidas"]), 0, 500).mean()

    return {
        "fallan": fallan, "web": web, "positiva": positiva, "negativa": negativa,
        "clientes": clientes, "temperatura": temperatura, "lluvia": lluvia,
        "ratio": ratio, "unidades": unidades,
    }


@st.cache_data(ttl=300, show_spinner=False)
def indicadores_drift():
    """Indicadores de los dos lotes, o None si faltan los CSV."""
    try:
        return {lote: _indicadores_lote(lote) for lote in LOTES}
    except (OSError, ValueError, KeyError):
        return None
