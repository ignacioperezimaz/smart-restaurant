"""Platos que se añaden desde la interfaz: se guardan para siempre en un CSV y salen en el gráfico."""
import pandas as pd
import requests

from app.almacen import COLUMNAS, AlmacenPlatos

PLATO = {"nombre": "Tarta de la abuela", "categoria": "postre", "precio_medio": 6.5, "coste_medio": 2.1, "dificultad": 4, "popularidad": 0.51}


def _borrar_todos(api):
    for p in api.get("/clustering/platos").json():
        if p["es_nuevo"]:
            requests.delete(f"{api.url}/clustering/platos-nuevos/{p['id_plato']}", timeout=20)


def test_anadir_plato_calcula_el_margen_lo_clasifica_y_lo_guarda(api_almacen):
    _borrar_todos(api_almacen)
    r = api_almacen.post("/clustering/platos-nuevos", json=PLATO)
    assert r.status_code == 201
    plato = r.json()
    assert plato["id_plato"] == 81 and plato["es_nuevo"] is True and plato["nombre"] == "Tarta de la abuela"
    assert plato["margen_medio"] == 4.4                                              # 6,5 − 2,1
    assert plato["nombre_grupo"] and plato["categoria"] == "postre"
    csv = pd.read_csv(api_almacen.ruta_csv)                                          # y está en el archivo
    assert list(csv.columns) == COLUMNAS and csv.loc[0, "nombre"] == "Tarta de la abuela" and csv.loc[0, "margen_medio"] == 4.4


def test_el_plato_nuevo_sale_en_la_lista_y_sobrevive_a_un_reinicio(api_almacen):
    _borrar_todos(api_almacen)
    api_almacen.post("/clustering/platos-nuevos", json=PLATO)
    platos = api_almacen.get("/clustering/platos").json()
    assert len(platos) == 81 and [p["nombre"] for p in platos if p["es_nuevo"]] == ["Tarta de la abuela"]
    assert api_almacen.get("/clustering/platos/81").json()["nombre"] == "Tarta de la abuela"
    reiniciado = AlmacenPlatos(api_almacen.ruta_csv, [])                             # "otra API" leyendo el mismo archivo
    assert list(reiniciado.leer()["nombre"]) == ["Tarta de la abuela"]


def test_ids_correlativos_y_filtro_por_grupo(api_almacen):
    _borrar_todos(api_almacen)
    a = api_almacen.post("/clustering/platos-nuevos", json=PLATO).json()
    b = api_almacen.post("/clustering/platos-nuevos", json={**PLATO, "nombre": "Flan de la casa"}).json()
    assert (a["id_plato"], b["id_plato"]) == (81, 82)
    del_grupo = api_almacen.get("/clustering/platos", params={"grupo": a["grupo"]}).json()
    assert 81 in [p["id_plato"] for p in del_grupo]


def test_no_se_puede_repetir_el_nombre(api_almacen):
    _borrar_todos(api_almacen)
    api_almacen.post("/clustering/platos-nuevos", json=PLATO)
    repetido = api_almacen.post("/clustering/platos-nuevos", json={**PLATO, "nombre": "  tarta DE la abuela "})
    assert repetido.status_code == 409 and repetido.json()["error"]["codigo"] == "plato_duplicado"
    de_la_carta = api_almacen.post("/clustering/platos-nuevos", json={**PLATO, "nombre": "croquetas de jamón"})
    assert de_la_carta.status_code == 409


def test_validacion_de_los_datos_del_plato(api_almacen):
    casos = {"popularidad": {k: v for k, v in PLATO.items() if k != "popularidad"},     # sin popularidad ni petición de estimarla
             "las dos": {**PLATO, "estimar_popularidad": True},                          # o una cosa o la otra
             "categoria": {**PLATO, "categoria": "bebida"},
             "dificultad": {**PLATO, "dificultad": 0},
             "precio_medio": {**PLATO, "precio_medio": -1},
             "nombre": {**PLATO, "nombre": "=SUMA(1;1)"},                               # una fórmula en Excel
             "otro": {**PLATO, "margen_medio": 3}}                                       # el margen no se envía: se calcula
    for campo, cuerpo in casos.items():
        r = api_almacen.post("/clustering/platos-nuevos", json=cuerpo)
        assert r.status_code == 422, campo
    assert api_almacen.post("/clustering/platos-nuevos", json={**PLATO, "nombre": "x"}).status_code == 422


def test_eliminar_un_plato_anadido(api_almacen):
    _borrar_todos(api_almacen)
    plato = api_almacen.post("/clustering/platos-nuevos", json=PLATO).json()
    assert requests.delete(f"{api_almacen.url}/clustering/platos-nuevos/{plato['id_plato']}", timeout=20).status_code == 204
    assert len(api_almacen.get("/clustering/platos").json()) == 80
    segunda = requests.delete(f"{api_almacen.url}/clustering/platos-nuevos/{plato['id_plato']}", timeout=20)
    assert segunda.status_code == 404
    de_la_carta = requests.delete(f"{api_almacen.url}/clustering/platos-nuevos/5", timeout=20)   # los 80 originales no se tocan
    assert de_la_carta.status_code == 404 and len(api_almacen.get("/clustering/platos").json()) == 80


def test_si_no_se_puede_escribir_el_csv_se_avisa(api_almacen, tmp_path):
    _borrar_todos(api_almacen)
    original = api_almacen.modelos.almacen.ruta
    archivo = tmp_path / "es_un_archivo"
    archivo.write_text("x")
    api_almacen.modelos.almacen.ruta = archivo / "platos_nuevos.csv"                     # una "carpeta" que en realidad es un archivo
    try:
        r = api_almacen.post("/clustering/platos-nuevos", json=PLATO)
        assert r.status_code == 503 and r.json()["error"]["codigo"] == "almacen_no_disponible"
    finally:
        api_almacen.modelos.almacen.ruta = original


def test_sin_modelo_no_se_guarda_nada(api_sin_modelos):
    r = api_sin_modelos.post("/clustering/platos-nuevos", json=PLATO)
    assert r.status_code == 503 and r.json()["error"]["codigo"] == "modelo_no_disponible"
    assert not api_sin_modelos.modelos.almacen.ruta.exists()


SIN_VENTAS = {k: v for k, v in PLATO.items() if k != "popularidad"} | {"nombre": "Flan de la casa", "estimar_popularidad": True}


def _medias(api):
    return {m["categoria"]: m for m in api.get("/clustering/popularidad-por-categoria").json()}


def test_medias_por_categoria(api_almacen):
    _borrar_todos(api_almacen)
    medias = _medias(api_almacen)
    assert set(medias) == {"entrante", "principal", "postre"}
    assert sum(m["n_platos"] for m in medias.values()) == 80                              # los 80 platos de la carta, cada uno en su categoría
    carta = api_almacen.get("/clustering/platos").json()
    postres = [p["popularidad"] for p in carta if p["categoria"] == "postre"]
    assert abs(medias["postre"]["popularidad_media"] - sum(postres) / len(postres)) < 1e-3


def test_guardar_sin_ventas_usa_la_media_de_su_categoria(api_almacen):
    _borrar_todos(api_almacen)
    media = _medias(api_almacen)["postre"]["popularidad_media"]
    r = api_almacen.post("/clustering/platos-nuevos", json=SIN_VENTAS)
    assert r.status_code == 201
    plato = r.json()
    assert plato["popularidad_estimada"] is True and plato["popularidad"] == media
    csv = pd.read_csv(api_almacen.ruta_csv)
    assert bool(csv.loc[0, "popularidad_estimada"]) is True and csv.loc[0, "popularidad"] == media
    assert [p["popularidad_estimada"] for p in api_almacen.get("/clustering/platos").json() if p["es_nuevo"]] == [True]


def test_una_estimacion_no_alimenta_la_media(api_almacen):
    _borrar_todos(api_almacen)
    antes = _medias(api_almacen)
    api_almacen.post("/clustering/platos-nuevos", json=SIN_VENTAS)
    assert _medias(api_almacen) == antes                                                  # el plato estimado no cuenta en la media
    api_almacen.post("/clustering/platos-nuevos", json={**PLATO, "nombre": "Arroz del domingo", "popularidad": 0.52})
    assert _medias(api_almacen)["postre"]["n_platos"] == antes["postre"]["n_platos"] + 1   # uno con ventas reales sí


def test_poner_la_popularidad_real_de_un_plato_estimado(api_almacen):
    _borrar_todos(api_almacen)
    plato = api_almacen.post("/clustering/platos-nuevos", json=SIN_VENTAS).json()
    r = requests.patch(f"{api_almacen.url}/clustering/platos-nuevos/{plato['id_plato']}", json={"popularidad": 0.523}, timeout=20)
    assert r.status_code == 200 and r.json()["popularidad"] == 0.523 and r.json()["popularidad_estimada"] is False
    csv = pd.read_csv(api_almacen.ruta_csv)
    assert csv.loc[0, "popularidad"] == 0.523 and bool(csv.loc[0, "popularidad_estimada"]) is False
    assert requests.patch(f"{api_almacen.url}/clustering/platos-nuevos/5", json={"popularidad": 0.5}, timeout=20).status_code == 404   # carta original
    assert requests.patch(f"{api_almacen.url}/clustering/platos-nuevos/{plato['id_plato']}", json={"popularidad": -1}, timeout=20).status_code == 422


def test_un_csv_guardado_antes_de_la_columna_de_estimacion_sigue_valiendo(api_almacen):
    _borrar_todos(api_almacen)
    api_almacen.ruta_csv.write_text(
        "id_plato,nombre,categoria,precio_medio,coste_medio,margen_medio,dificultad,popularidad,grupo,nombre_grupo,fecha_alta_utc\n"
        "81,Plato antiguo,postre,16.0,6.0,10.0,5,0.51,1,Estrella,2026-11-25T10:00:00+00:00\n", encoding="utf-8")
    nuevos = [p for p in api_almacen.get("/clustering/platos").json() if p["es_nuevo"]]
    assert [p["nombre"] for p in nuevos] == ["Plato antiguo"] and nuevos[0]["popularidad_estimada"] is False


def test_medias_y_guardado_cuando_todavia_no_existe_el_csv(api_almacen):
    _borrar_todos(api_almacen)
    api_almacen.ruta_csv.unlink(missing_ok=True)                                          # como la primera vez que se usa
    assert api_almacen.get("/clustering/popularidad-por-categoria").status_code == 200
    assert api_almacen.post("/clustering/platos-nuevos", json=SIN_VENTAS).status_code == 201
    assert api_almacen.ruta_csv.exists()
