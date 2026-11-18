"""
load_data.py — Carga de los 3 CSV para el dashboard.

Intenta leer de HDFS (WebHDFS) y, si no es posible (Docker apagado, red...),
usa los CSV locales de la carpeta data/. Devuelve también el ORIGEN de los
datos, para poder enseñarlo en el dashboard ("HDFS" o "CSV local").
"""
from pathlib import Path

import pandas as pd

# --- Configuración de HDFS (WebHDFS del namenode, publicado en localhost:9870) ---
HDFS_HOST = "localhost"
HDFS_PORT = 9870
HDFS_USER = "root"
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
