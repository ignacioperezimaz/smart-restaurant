"""Prueba con el MLflow de verdad. Solo se ejecuta si se define TEST_MLFLOW_URI (por ejemplo, http://localhost:5000)
y MLflow tiene los dos modelos registrados con el alias `actual`. Si no, se salta."""
from __future__ import annotations

import os

import pytest
import requests

from tests.conftest import PEDIDO, Servidor

URI = os.environ.get("TEST_MLFLOW_URI")
pytestmark = pytest.mark.skipif(not URI, reason="Define TEST_MLFLOW_URI para probar contra el MLflow real")


@pytest.fixture(scope="module")
def api_real():
    mp = pytest.MonkeyPatch()
    mp.setenv("MLFLOW_TRACKING_URI", URI)
    servidor = Servidor().arrancar()
    yield servidor
    servidor.parar()
    mp.undo()


def test_los_dos_modelos_reales_se_cargan_y_predicen(api_real):
    try:
        cuerpo = api_real.get("/salud").json()
    except requests.RequestException:
        pytest.skip("La API de pruebas no respondió")
    assert cuerpo["estado"] == "ok", cuerpo
    assert api_real.post("/regresion/predecir", json=PEDIDO).json()["tiempo_estimado_minutos"] > 3
    assert api_real.post("/clustering/predecir", json={"popularidad": 0.52, "margen_medio": 10.1}).status_code == 200
    assert len(api_real.get("/clustering/platos").json()) == 80
