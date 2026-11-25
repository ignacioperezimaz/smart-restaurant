"""Tests de la API. Cada test comprueba una cosa concreta; el nombre dice cuál."""
from __future__ import annotations


# ============================================================================================ sistema
def test_salud_ok_con_los_dos_modelos(api):
    r = api.get("/salud")
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["estado"] == "ok"
    assert cuerpo["clustering"]["disponible"] and cuerpo["regresion"]["disponible"]
    assert cuerpo["regresion"]["modelo"]["version"] == 7


def test_salud_degradada_sin_modelos_pero_la_api_responde(api_sin_modelos):
    r = api_sin_modelos.get("/salud")
    assert r.status_code == 200                                   # la API está viva aunque no haya modelos
    cuerpo = r.json()
    assert cuerpo["estado"] == "degradado"
    assert cuerpo["clustering"]["disponible"] is False
    assert "MLflow" in cuerpo["clustering"]["problema"]


def test_modelos_y_recarga_con_mlflow_caido_conserva_la_version_cargada(api):
    r = api.post("/modelos/recargar")
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["clustering"]["disponible"] is True             # sigue usando la versión que ya tenía
    assert "MLflow" in cuerpo["clustering"]["problema"]           # pero avisa de por qué falló la recarga
    assert api.post("/regresion/predecir", json={"n_platos": 1, "num_platos_complejos": 0, "complejidad_pedido": 2,
                    "cola_pedidos": 1, "cocineros_disponibles": 4, "precipitacion_mm": 0, "hora_dec": 12, "dia_semana": 3,
                    "canal": "mesa"}).status_code == 200


def test_raiz_redirige_a_la_documentacion(api):
    r = api.get("/", allow_redirects=False)
    assert r.status_code in (302, 307) and r.headers["location"] == "/docs"


def test_documentacion_openapi_incluye_todas_las_rutas(api):
    rutas = set(api.get("/openapi.json").json()["paths"])
    esperadas = {"/salud", "/modelos", "/modelos/recargar", "/clustering/predecir", "/clustering/predecir-lote",
                 "/clustering/grupos", "/clustering/platos", "/clustering/platos/{id_plato}", "/regresion/predecir",
                 "/regresion/predecir-lote"}
    assert esperadas <= rutas


# ============================================================================================ objetivo 1
def test_clustering_predecir_un_plato(api):
    r = api.post("/clustering/predecir", json={"id_plato": "x", "popularidad": 0.52, "margen_medio": 10.1})
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["id_plato"] == "x" and cuerpo["modelo"]["version"] == 7
    assert cuerpo["nombre_grupo"].startswith("Estrella")          # muy popular y con mucho margen
    assert cuerpo["distancia_al_centroide"] >= 0 and cuerpo["sugerencia"]


def test_clustering_lote_mantiene_el_orden(api):
    platos = [{"id_plato": "a", "popularidad": 0.52, "margen_medio": 10.2}, {"id_plato": "b", "popularidad": 0.47, "margen_medio": 9.6}]
    cuerpo = api.post("/clustering/predecir-lote", json={"platos": platos}).json()
    assert cuerpo["n"] == 2 and [x["id_plato"] for x in cuerpo["resultados"]] == ["a", "b"]
    assert cuerpo["resultados"][0]["nombre_grupo"] != cuerpo["resultados"][1]["nombre_grupo"]


def test_clustering_avisa_si_el_plato_esta_fuera_del_rango_de_la_carta(api):
    cuerpo = api.post("/clustering/predecir", json={"popularidad": 3.0, "margen_medio": 10.0}).json()
    assert any("fuera del rango" in a for a in cuerpo["avisos"])


def test_clustering_grupos_y_platos(api):
    grupos = api.get("/clustering/grupos").json()
    assert len(grupos) == 4 and sum(g["n_platos"] for g in grupos) == 80
    platos = api.get("/clustering/platos").json()
    assert len(platos) == 80
    un_grupo = api.get("/clustering/platos", params={"grupo": platos[0]["grupo"]}).json()
    assert 0 < len(un_grupo) <= 80 and all(p["grupo"] == platos[0]["grupo"] for p in un_grupo)


def test_clustering_plato_de_la_carta_y_plato_inexistente(api):
    assert api.get("/clustering/platos/5").json()["id_plato"] == 5
    r = api.get("/clustering/platos/999")
    assert r.status_code == 404 and r.json()["error"]["codigo"] == "no_encontrado"
    assert "1 al 80" in r.json()["error"]["mensaje"]


def test_clustering_id_plato_no_numerico_es_validacion(api):
    r = api.get("/clustering/platos/abc")
    assert r.status_code == 422 and r.json()["error"]["detalles"][0]["campo"] == "id_plato"


# ============================================================================================ objetivo 2
def test_regresion_predecir_un_pedido(api, pedido):
    r = api.post("/regresion/predecir", json=pedido)
    assert r.status_code == 200
    cuerpo = r.json()
    assert 3 < cuerpo["tiempo_estimado_minutos"] < 60
    assert cuerpo["error_medio_orientativo_minutos"] == 2.13 and cuerpo["avisos"] == []


def test_regresion_acepta_ingrediente_agotado_como_0_o_1(api, pedido):
    a = api.post("/regresion/predecir", json={**pedido, "ingrediente_agotado": 1}).json()
    b = api.post("/regresion/predecir", json={**pedido, "ingrediente_agotado": True}).json()
    assert a["tiempo_estimado_minutos"] == b["tiempo_estimado_minutos"]


def test_regresion_mas_cola_mas_tiempo(api, pedido):
    poca = api.post("/regresion/predecir", json={**pedido, "cola_pedidos": 2}).json()["tiempo_estimado_minutos"]
    mucha = api.post("/regresion/predecir", json={**pedido, "cola_pedidos": 18}).json()["tiempo_estimado_minutos"]
    assert mucha > poca


def test_regresion_avisos_lunes_y_datos_fuera_de_rango(api, pedido):
    cuerpo = api.post("/regresion/predecir", json={**pedido, "dia_semana": 1, "cola_pedidos": 40}).json()
    texto = " ".join(cuerpo["avisos"])
    assert "lunes" in texto and "cola_pedidos=40" in texto


def test_regresion_lote_mantiene_el_orden(api, pedido):
    lote = [{**pedido, "cola_pedidos": 1}, {**pedido, "cola_pedidos": 20}]
    cuerpo = api.post("/regresion/predecir-lote", json={"pedidos": lote}).json()
    assert cuerpo["n"] == 2
    assert cuerpo["resultados"][0]["tiempo_estimado_minutos"] < cuerpo["resultados"][1]["tiempo_estimado_minutos"]


# ============================================================================================ errores
def test_validacion_varios_errores_a_la_vez_en_espanol(api, pedido):
    mal = {**pedido, "cola_pedido": 3, "canal": "drive", "hora_dec": "tarde", "cocineros_disponibles": 0}
    r = api.post("/regresion/predecir", json=mal)
    assert r.status_code == 422
    error = r.json()["error"]
    assert error["codigo"] == "validacion"
    por_campo = {d["campo"]: d["mensaje"] for d in error["detalles"]}
    assert "no reconocido" in por_campo["cola_pedido"]
    assert "mesa" in por_campo["canal"] and "takeaway" in por_campo["canal"]
    assert "número" in por_campo["hora_dec"]
    assert "mayor o igual que 1" in por_campo["cocineros_disponibles"]


def test_validacion_mas_platos_complejos_que_platos(api, pedido):
    r = api.post("/regresion/predecir", json={**pedido, "n_platos": 2, "num_platos_complejos": 5})
    assert r.status_code == 422
    assert "no puede ser mayor que n_platos" in r.json()["error"]["detalles"][0]["mensaje"]


def test_validacion_campo_obligatorio(api, pedido):
    del pedido["canal"]
    d = api.post("/regresion/predecir", json=pedido).json()["error"]["detalles"][0]
    assert d["campo"] == "canal" and "obligatorio" in d["mensaje"]


def test_validacion_json_invalido(api):
    r = api.post("/regresion/predecir", data="{esto no es json", headers={"Content-Type": "application/json"})
    assert r.status_code == 422 and "JSON" in r.json()["error"]["detalles"][0]["mensaje"]


def test_validacion_numeros_no_finitos_y_negativos(api):
    assert api.post("/clustering/predecir", json={"popularidad": -1, "margen_medio": 10}).status_code == 422
    r = api.post("/clustering/predecir", data='{"popularidad": NaN, "margen_medio": 10}', headers={"Content-Type": "application/json"})
    assert r.status_code == 422


def test_validacion_lote_vacio_y_campo_dentro_del_lote(api, pedido):
    assert api.post("/regresion/predecir-lote", json={"pedidos": []}).status_code == 422
    r = api.post("/regresion/predecir-lote", json={"pedidos": [pedido, {**pedido, "canal": "x"}]})
    assert r.json()["error"]["detalles"][0]["campo"] == "pedidos[1].canal"


def test_lote_demasiado_grande(api, pedido):
    r = api.post("/regresion/predecir-lote", json={"pedidos": [pedido] * 4})          # el máximo de los tests es 3
    assert r.status_code == 413 and r.json()["error"]["codigo"] == "lote_demasiado_grande"


def test_ruta_inexistente_y_metodo_no_permitido(api):
    r = api.get("/no-existe")
    assert r.status_code == 404 and r.json()["error"]["codigo"] == "ruta_no_encontrada"
    r = api.get("/regresion/predecir")
    assert r.status_code == 405 and r.json()["error"]["codigo"] == "metodo_no_permitido"


def test_modelo_no_disponible_devuelve_503_con_el_mismo_formato(api_sin_modelos, pedido):
    for ruta, cuerpo in [("/regresion/predecir", pedido), ("/clustering/predecir", {"popularidad": 0.5, "margen_medio": 9.9})]:
        r = api_sin_modelos.post(ruta, json=cuerpo)
        assert r.status_code == 503
        assert r.json()["error"]["codigo"] == "modelo_no_disponible" and "MLflow" in r.json()["error"]["mensaje"]
    assert api_sin_modelos.get("/clustering/grupos").status_code == 503


def test_fallo_del_modelo_da_500_sin_detalles_internos(api, pedido):
    class Roto:                                                    # un modelo que siempre falla al predecir
        def predict(self, X):
            raise RuntimeError("SECRETO-INTERNO /ruta/interna")
    original = api.modelos.regresion._estado.pipeline
    api.modelos.regresion._estado.pipeline = Roto()
    try:
        r = api.post("/regresion/predecir", json=pedido)
    finally:
        api.modelos.regresion._estado.pipeline = original
    assert r.status_code == 500 and r.json()["error"]["codigo"] == "error_prediccion"
    assert "SECRETO" not in r.text                                  # no se filtra información interna


def test_id_de_peticion_en_cabecera_y_en_el_error(api):
    r = api.post("/regresion/predecir", json={})
    assert r.headers["X-Request-ID"] == r.json()["error"]["id_peticion"]
