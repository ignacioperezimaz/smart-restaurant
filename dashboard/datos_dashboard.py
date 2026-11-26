"""
datos_dashboard.py — Carga de los datos LIMPIOS y de los lotes nuevos para las páginas de exploración, modelos y drift.

De dónde lee:
  - Normalmente, de HDFS por WebHDFS (el mismo que usa el resto del dashboard: ver load_data.py).
  - Si existe la variable de entorno DATALAKE_URI (por ejemplo una carpeta local con la misma estructura que /datalake),
    lee de ahí. Sirve para probar el dashboard sin Docker.

Estas funciones no guardan nada en caché: cada página las envuelve con st.cache_data.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import fsspec
import pandas as pd

import load_data

# Carpeta monitorizacion/ del repositorio (en Docker: /app/monitorizacion). Se reutiliza la limpieza del notebook 02 y el PSI.
REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
from monitorizacion import drift as D                                    # noqa: E402
from monitorizacion.limpieza_pedidos import limpiar_pedidos, leer_raw    # noqa: E402

LAKE = os.environ.get("DATALAKE_URI")                                   # opcional: lago local para pruebas
BASE = LAKE or f"webhdfs://{load_data.HDFS_HOST}:{load_data.HDFS_PORT}/datalake"
OPT = None if LAKE else {"user": load_data.HDFS_USER}

FORMATO_FECHA = "%d-%m-%Y"
CARPETA_PEDIDOS = "pedidos_tiempos_preparacion"
ARCHIVO_PEDIDOS = "02_pedidos_tiempos_preparacion.csv"

VARIABLES_NUMERICAS = ["n_platos", "num_platos_complejos", "complejidad_pedido", "cola_pedidos",
                       "cocineros_disponibles", "precipitacion_mm", "hora_dec", "dia_semana", "ingrediente_agotado"]
VARIABLES_CATEGORIA = ["canal", "prioridad_aux"]
OBJETIVO = "tiempo_prep_minutos"
DIAS = {1: "lunes", 2: "martes", 3: "miércoles", 4: "jueves", 5: "viernes", 6: "sábado", 7: "domingo"}


def _parquet(ruta_relativa: str) -> pd.DataFrame:
    return pd.read_parquet(f"{BASE}/{ruta_relativa}", storage_options=OPT)


def pedidos_limpio() -> pd.DataFrame:
    """Pedidos del lote 1 ya limpios (salida del notebook 02), con fecha como fecha real y ordenados en el tiempo."""
    df = _parquet(f"clean/{CARPETA_PEDIDOS}/pedidos_limpio.parquet")
    df["fecha"] = pd.to_datetime(df["fecha"], format=FORMATO_FECHA)
    df[VARIABLES_CATEGORIA] = df[VARIABLES_CATEGORIA].astype(str)
    return df.sort_values(["fecha", "hora_dec"]).reset_index(drop=True)


def ventas_limpio() -> pd.DataFrame:
    """Ventas diarias por plato ya limpias (notebook 01)."""
    df = _parquet("clean/ventas_diarias_platos/ventas_limpio.parquet")
    df["fecha"] = pd.to_datetime(df["fecha"], format=FORMATO_FECHA)
    return df


def platos_features() -> pd.DataFrame:
    """Una fila por plato con sus variables medias (notebook 03)."""
    return _parquet("clean/ventas_diarias_platos/platos_features.parquet")


def platos_clusters() -> pd.DataFrame:
    """Una fila por plato con su grupo (notebook 04)."""
    return _parquet("clean/ventas_diarias_platos/platos_clusters.parquet")


def lotes_disponibles() -> list[str]:
    """Nombres de los lotes nuevos guardados en HDFS: carpetas lote=<nombre> dentro de raw/pedidos_tiempos_preparacion."""
    fs, _, rutas = fsspec.get_fs_token_paths(f"{BASE}/raw/{CARPETA_PEDIDOS}", storage_options=OPT)
    entradas = fs.ls(rutas[0], detail=True)
    nombres = [e["name"].rstrip("/").split("/")[-1] for e in entradas if e["type"] == "directory"]
    return sorted(n.split("=", 1)[1] for n in nombres if n.startswith("lote="))


def lote_limpio(lote: str) -> tuple[pd.DataFrame, dict]:
    """Lee un lote RAW de HDFS y le aplica la MISMA limpieza que el lote 1 (monitorizacion/limpieza_pedidos.py)."""
    raw = leer_raw(f"{BASE}/raw/{CARPETA_PEDIDOS}/lote={lote}/{ARCHIVO_PEDIDOS}", storage_options=OPT)
    limpio, resumen = limpiar_pedidos(raw)
    limpio["fecha"] = pd.to_datetime(limpio["fecha"], format=FORMATO_FECHA)
    limpio[VARIABLES_CATEGORIA] = limpio[VARIABLES_CATEGORIA].astype(str)
    return limpio.sort_values(["fecha", "hora_dec"]).reset_index(drop=True), resumen


def referencia_entrenamiento(pedidos: pd.DataFrame, fraccion: float = 0.80) -> pd.DataFrame:
    """El 80 % más antiguo del lote 1: lo que vio el modelo al entrenar (la misma separación del notebook 06)."""
    corte = pedidos.sort_values(["fecha", "hora_dec"]).reset_index(drop=True).loc[int(len(pedidos) * fraccion), "fecha"]
    return pedidos[pedidos["fecha"] < corte]
