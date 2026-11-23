"""
load_data.py — Carga de los 3 CSV para el dashboard.

Intenta leer de HDFS (WebHDFS) y, si no es posible (Docker apagado, red...),
usa los CSV locales de la carpeta data/. Devuelve también el ORIGEN de los
datos, para poder enseñarlo en el dashboard ("HDFS" o "CSV local").
"""
import os
from pathlib import Path

import pandas as pd

# --- Configuración de HDFS (WebHDFS del namenode, publicado en localhost:9870) ---
HDFS_HOST = os.environ.get("HDFS_HOST", "localhost")   # en Docker: "namenode"
HDFS_PORT = 9870
HDFS_USER = os.environ.get("HDFS_USER", "root")
RAW = "/datalake/raw"

# Carpeta local con los CSV: <repo>/data (este archivo está en <repo>/dashboard)
DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# nombre corto -> (carpeta en HDFS, nombre del archivo)
FUENTES = {
    "ventas": ("ventas_diarias_platos", "01_ventas_diarias_platos.csv"),
    "pedidos": ("pedidos_tiempos_preparacion", "02_pedidos_tiempos_preparacion.csv"),
    "carta": ("carta_platos", "03_carta_platos.csv"),
}

# dtype=str: los datos están sucios (texto en columnas numéricas), no los tocamos aquí.
# utf-8-sig: los CSV llevan BOM; sin esto la primera columna sale con un carácter invisible.
_OPCIONES_CSV = dict(dtype=str, encoding="utf-8-sig")


def _leer_hdfs(carpeta: str, archivo: str) -> pd.DataFrame:
    url = f"webhdfs://{HDFS_HOST}:{HDFS_PORT}{RAW}/{carpeta}/{archivo}"
    return pd.read_csv(url, storage_options={"user": HDFS_USER}, **_OPCIONES_CSV)


def _leer_local(archivo: str) -> pd.DataFrame:
    return pd.read_csv(DATA_DIR / archivo, **_OPCIONES_CSV)


def cargar(nombre: str) -> tuple[pd.DataFrame, str]:
    """Devuelve (DataFrame, origen). origen = 'HDFS' o 'CSV local'."""
    carpeta, archivo = FUENTES[nombre]
    try:
        return _leer_hdfs(carpeta, archivo), "HDFS"
    except Exception:
        # HDFS no disponible (o redirección al datanode sin resolver): usamos el CSV local
        return _leer_local(archivo), "CSV local"


# --- Pedidos: versión SUCIA (RAW) y versión LIMPIA (CLEAN), siempre desde HDFS ---
CLEAN = "/datalake/clean"
_BASE = f"webhdfs://{HDFS_HOST}:{HDFS_PORT}"


def cargar_pedidos_raw() -> pd.DataFrame:
    """CSV original sin tocar. Todo como texto y los vacíos se quedan como '' (no como NaN)."""
    url = f"{_BASE}{RAW}/pedidos_tiempos_preparacion/02_pedidos_tiempos_preparacion.csv"
    return pd.read_csv(url, storage_options={"user": HDFS_USER},
                       dtype=str, keep_default_na=False, encoding="utf-8-sig")


def cargar_pedidos_clean() -> pd.DataFrame:
    """Parquet que genera la limpieza del notebook 02 (tipos ya corregidos)."""
    url = f"{_BASE}{CLEAN}/pedidos_tiempos_preparacion/pedidos_limpio.parquet"
    return pd.read_parquet(url, storage_options={"user": HDFS_USER})


# --- Carga genérica RAW / CLEAN por nombre de dataset ("pedidos" o "ventas") ---
CLEAN_FUENTES = {
    "pedidos": "pedidos_tiempos_preparacion/pedidos_limpio.parquet",
    "ventas": "ventas_diarias_platos/ventas_limpio.parquet",
}


def cargar_raw(nombre: str) -> pd.DataFrame:
    """CSV original de HDFS sin tocar: todo texto y vacíos como ''."""
    carpeta, archivo = FUENTES[nombre]
    url = f"{_BASE}{RAW}/{carpeta}/{archivo}"
    return pd.read_csv(url, storage_options={"user": HDFS_USER},
                       dtype=str, keep_default_na=False, encoding="utf-8-sig")


def cargar_clean(nombre: str) -> pd.DataFrame:
    """Parquet limpio de HDFS (/datalake/clean)."""
    url = f"{_BASE}{CLEAN}/{CLEAN_FUENTES[nombre]}"
    return pd.read_parquet(url, storage_options={"user": HDFS_USER})
