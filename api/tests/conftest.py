"""Ayudas para los tests: arrancan la API de verdad (con uvicorn, en un hilo) y la llaman con `requests`.

Los tests NO necesitan MLflow: se instalan modelos pequeños de mentira, entrenados aquí mismo, con la misma estructura
que los reales. Solo `test_integracion.py` usa el MLflow de verdad, y únicamente si se define TEST_MLFLOW_URI.
"""
from __future__ import annotations

import socket
import threading
import time

import numpy as np
import pandas as pd
import pytest
import requests
import uvicorn
from sklearn.cluster import KMeans
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LinearRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from app.esquemas import InfoModelo
from app.main import crear_app
from app.modelos import VARIABLES_REGRESION


def _puerto_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Servidor:
    """La API corriendo en un hilo, con una URL y una `app` a la que se pueden instalar modelos."""

    def __init__(self):
        self.app = crear_app()
        self.puerto = _puerto_libre()
        self.url = f"http://127.0.0.1:{self.puerto}"
        self._server = uvicorn.Server(uvicorn.Config(self.app, host="127.0.0.1", port=self.puerto, log_level="warning"))
        self._hilo = threading.Thread(target=self._server.run, daemon=True)

    def arrancar(self):
        self._hilo.start()
        for _ in range(100):                                   # espera (máx. 10 s) a que responda
            try:
                requests.get(self.url + "/salud", timeout=1)
                return self
            except requests.ConnectionError:
                time.sleep(0.1)
        raise RuntimeError("La API de pruebas no arrancó")

    def parar(self):
        self._server.should_exit = True
        self._hilo.join(timeout=10)

    @property
    def modelos(self):
        return self.app.state.modelos

    def get(self, ruta, **kw):
        return requests.get(self.url + ruta, timeout=20, **kw)

    def post(self, ruta, json=None, **kw):
        return requests.post(self.url + ruta, json=json, timeout=20, **kw)


# ---------------------------------------------------------------- modelos de mentira (misma estructura que los reales)
def pipeline_clustering_falso() -> tuple[Pipeline, pd.DataFrame]:
    azar = np.random.default_rng(0)
    datos = pd.DataFrame({"popularidad": azar.normal(0.50, 0.01, 80), "margen_medio": azar.normal(9.9, 0.15, 80)})
    modelo = Pipeline([("estandarizar", StandardScaler()), ("kmeans", KMeans(n_clusters=4, n_init=10, random_state=42))])
    modelo.fit(datos)
    return modelo, datos


def pipeline_regresion_falso() -> Pipeline:
    azar = np.random.default_rng(1)
    n = 500
    datos = pd.DataFrame({
        "n_platos": azar.integers(1, 9, n), "num_platos_complejos": azar.integers(0, 3, n),
        "complejidad_pedido": azar.uniform(1, 10, n), "cola_pedidos": azar.integers(0, 21, n),
        "cocineros_disponibles": azar.integers(1, 8, n), "precipitacion_mm": azar.uniform(0, 20, n),
        "hora_dec": azar.uniform(10, 23, n), "dia_semana": azar.integers(2, 8, n), "ingrediente_agotado": azar.integers(0, 2, n),
        "canal": azar.choice(["mesa", "delivery", "takeaway"], n), "prioridad_aux": azar.choice(["normal", "prioridad", "VIP"], n)})
    y = 14 + 2 * datos["n_platos"] + datos["cola_pedidos"] - 2 * datos["cocineros_disponibles"]
    preprocesado = ColumnTransformer([("categorias", OneHotEncoder(
        categories=[["mesa", "delivery", "takeaway"], ["normal", "prioridad", "VIP"]], drop="first", handle_unknown="ignore"),
        ["canal", "prioridad_aux"])], remainder="passthrough")
    modelo = Pipeline([("preprocesado", preprocesado), ("modelo", LinearRegression())])
    return modelo.fit(datos[VARIABLES_REGRESION], y)


def _info(nombre: str, metricas: dict | None = None) -> InfoModelo:
    return InfoModelo(nombre=nombre, version=7, alias="actual", run_id="abc123", fecha_entrenamiento="2026-01-01_10-00",
                      metricas=metricas or {}, cargado_en="2026-01-01 10:00:00")


def instalar_modelos_falsos(servidor: Servidor) -> None:
    modelo_c, datos = pipeline_clustering_falso()
    m = servidor.modelos
    m.clustering.instalar(modelo_c, _info(m.clustering.nombre))
    # tabla de platos de mentira, con el mismo formato que `platos_con_grupo.csv` del notebook 04
    platos = datos.assign(id_plato=range(1, 81), grupo=modelo_c.predict(datos), precio_medio=16.0, coste_medio=6.0,
                          valoracion=4.2, dificultad=5, unidades_medias=25.0, n_filas=1300)
    platos["nombre_grupo"] = platos["grupo"].map(m.clustering.obtener().extra["nombres"])
    extra = {**m.clustering.obtener().extra, "platos": platos,
             "rango": {v: (float(datos[v].min()), float(datos[v].max())) for v in ("popularidad", "margen_medio")}}
    m.clustering.instalar(modelo_c, _info(m.clustering.nombre), extra)
    m.regresion.instalar(pipeline_regresion_falso(), _info(m.regresion.nombre, {"test_mae": 2.13}))


@pytest.fixture(scope="module")
def api():
    """API con los dos modelos (falsos) cargados. Lote máximo de 3 elementos para poder probar el límite."""
    mp = pytest.MonkeyPatch()
    mp.setenv("MLFLOW_TRACKING_URI", "http://127.0.0.1:9")      # puerto cerrado: MLflow "caído" (falla al instante)
    mp.setenv("MAX_LOTE", "3")
    servidor = Servidor().arrancar()
    instalar_modelos_falsos(servidor)
    yield servidor
    servidor.parar()
    mp.undo()


@pytest.fixture(scope="module")
def api_sin_modelos():
    """API arrancada sin modelos (MLflow caído)."""
    mp = pytest.MonkeyPatch()
    mp.setenv("MLFLOW_TRACKING_URI", "http://127.0.0.1:9")
    mp.setenv("ESPERA_REINTENTO_S", "0")
    servidor = Servidor().arrancar()
    yield servidor
    servidor.parar()
    mp.undo()


PEDIDO = {"n_platos": 3, "num_platos_complejos": 1, "complejidad_pedido": 4.5, "cola_pedidos": 8, "cocineros_disponibles": 5,
          "precipitacion_mm": 0.0, "hora_dec": 20.5, "dia_semana": 6, "ingrediente_agotado": False,
          "canal": "delivery", "prioridad_aux": "normal"}


@pytest.fixture()
def pedido():
    return dict(PEDIDO)
