"""Configuración de la API. Todo se puede cambiar con variables de entorno (en docker-compose.yml)."""
from __future__ import annotations

import os
from dataclasses import dataclass

# MLflow, por defecto, reintenta muchas veces y espera 2 minutos: si el servidor está caído, la API parecería colgada.
# Con estos valores falla en unos segundos y podemos contestar con un error claro. (Se fijan ANTES de importar mlflow.)
os.environ.setdefault("MLFLOW_HTTP_REQUEST_TIMEOUT", "10")       # segundos de espera por petición
os.environ.setdefault("MLFLOW_HTTP_REQUEST_MAX_RETRIES", "1")    # reintentos
os.environ.setdefault("MLFLOW_HTTP_REQUEST_BACKOFF_FACTOR", "1")


@dataclass(frozen=True)
class Ajustes:
    """Valores de configuración (inmutables) que lee la API al arrancar."""
    mlflow_uri: str            # dónde está el servidor MLflow (dentro de Docker se llama "mlflow")
    modelo_clustering: str     # nombre del modelo del objetivo 1 en el Model Registry
    modelo_regresion: str      # nombre del modelo del objetivo 2 en el Model Registry
    alias: str                 # alias que apunta a la versión vigente de cada modelo
    max_lote: int              # máximo de elementos en una petición por lotes
    espera_reintento_s: float  # tras un fallo al cargar un modelo, segundos antes de volver a intentarlo


def leer_ajustes() -> Ajustes:
    """Lee las variables de entorno y devuelve los ajustes (con valores por defecto del proyecto)."""
    return Ajustes(
        mlflow_uri=os.environ.get("MLFLOW_TRACKING_URI", "http://mlflow:5000"),
        modelo_clustering=os.environ.get("MODELO_CLUSTERING", "smart_restaurant_clustering_platos"),
        modelo_regresion=os.environ.get("MODELO_REGRESION", "smart_restaurant_regresion_tiempo_prep"),
        alias=os.environ.get("ALIAS_MODELO", "actual"),
        max_lote=int(os.environ.get("MAX_LOTE", "500")),
        espera_reintento_s=float(os.environ.get("ESPERA_REINTENTO_S", "5")),
    )
