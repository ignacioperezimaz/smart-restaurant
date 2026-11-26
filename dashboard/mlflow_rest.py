"""
mlflow_rest.py — Lee de MLflow lo que guardaron los notebooks (experimentos, métricas, tablas y gráficos).

Usa solo la API REST de MLflow con `requests` (ya instalado en el dashboard): no hace falta instalar mlflow ni scikit-learn.
Si el servidor no responde, las funciones devuelven None / [] y la página avisa de que falta MLflow, en vez de romperse.
"""
from __future__ import annotations

import io
import os

import pandas as pd
import requests

# En Docker es "http://mlflow:5000" (lo fija docker-compose.yml); fuera de Docker, el puerto publicado en localhost
URI = os.environ.get("MLFLOW_TRACKING_URI", "http://localhost:5000").rstrip("/")
TIMEOUT = 8


def disponible() -> bool:
    """¿Responde el servidor MLflow?"""
    try:
        requests.get(f"{URI}/health", timeout=3).raise_for_status()
        return True
    except Exception:
        return False


def _api(metodo: str, ruta: str, **kwargs) -> dict:
    r = requests.request(metodo, f"{URI}/api/2.0/mlflow/{ruta}", timeout=TIMEOUT, **kwargs)
    r.raise_for_status()
    return r.json()


def id_experimento(nombre: str) -> str | None:
    """Id del experimento con ese nombre (o None si no existe todavía)."""
    try:
        return _api("GET", "experiments/get-by-name", params={"experiment_name": nombre})["experiment"]["experiment_id"]
    except Exception:
        return None


def ejecuciones(nombre_experimento: str, maximo: int = 300) -> list[dict]:
    """Ejecuciones del experimento, de la más reciente a la más antigua, con parámetros, métricas y etiquetas ya como diccionarios."""
    exp = id_experimento(nombre_experimento)
    if exp is None:
        return []
    try:
        datos = _api("POST", "runs/search", json={"experiment_ids": [exp], "max_results": maximo,
                                                  "order_by": ["attributes.start_time DESC"]})
    except Exception:
        return []
    salida = []
    for run in datos.get("runs", []):
        d = run["data"]
        salida.append({
            "run_id": run["info"]["run_id"],
            "nombre": run["info"].get("run_name", ""),
            "estado": run["info"]["status"],
            "inicio": pd.to_datetime(run["info"]["start_time"], unit="ms"),
            "artifact_uri": run["info"].get("artifact_uri", ""),
            "params": {p["key"]: p["value"] for p in d.get("params", [])},
            "metricas": {m["key"]: m["value"] for m in d.get("metrics", [])},
            "tags": {t["key"]: t["value"] for t in d.get("tags", [])},
        })
    return salida


def _bytes_artefacto(run: dict, ruta: str) -> bytes | None:
    """Descarga un archivo guardado en la ejecución (el servidor MLflow del proyecto sirve los artefactos con --serve-artifacts)."""
    uri = run.get("artifact_uri", "")
    intentos = []
    if uri.startswith("mlflow-artifacts:"):
        intentos.append(f"{URI}/api/2.0/mlflow-artifacts/artifacts/{uri.split(':', 1)[1].strip('/')}/{ruta}")
    intentos.append(f"{URI}/get-artifact?run_uuid={run['run_id']}&path={ruta}")
    for url in intentos:
        try:
            r = requests.get(url, timeout=TIMEOUT)
            if r.ok:
                return r.content
        except Exception:
            continue
    return None


def artefacto_csv(run: dict, ruta: str, **opciones) -> pd.DataFrame | None:
    """Un CSV guardado con mlflow.log_text en esa ejecución, como tabla."""
    contenido = _bytes_artefacto(run, ruta)
    if contenido is None:
        return None
    try:
        return pd.read_csv(io.BytesIO(contenido), **opciones)
    except Exception:
        return None


def artefacto_imagen(run: dict, ruta: str) -> bytes | None:
    """Una imagen (PNG) guardada con mlflow.log_figure en esa ejecución."""
    return _bytes_artefacto(run, ruta)


def versiones_modelo(nombre_modelo: str) -> list[dict]:
    """Versiones registradas de un modelo, con sus alias (actual, candidato...), de la más nueva a la más antigua."""
    try:
        datos = _api("GET", "model-versions/search", params={"filter": f"name='{nombre_modelo}'", "max_results": 100})
        versiones = datos.get("model_versions", [])
        modelo = _api("GET", "registered-models/get", params={"name": nombre_modelo})["registered_model"]
    except Exception:
        return []
    alias = {}
    for a in modelo.get("aliases", []):
        alias.setdefault(str(a["version"]), []).append(a["alias"])
    filas = [{"version": int(v["version"]), "alias": ", ".join(alias.get(str(v["version"]), [])) or "—",
              "creada": pd.to_datetime(int(v["creation_timestamp"]), unit="ms"),
              "run_id": v.get("run_id", ""), "descripcion": v.get("description", "")} for v in versiones]
    return sorted(filas, key=lambda f: -f["version"])
