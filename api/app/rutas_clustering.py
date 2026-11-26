"""Objetivo 1 · Clustering de platos: ¿qué tipo de plato es según su popularidad y su margen?"""
from __future__ import annotations

import pandas as pd
from fastapi import APIRouter, Depends, Path, Query, Response

from .dependencias import (ERR_ALMACEN, ERR_CONFLICTO, ERR_INTERNO, ERR_LOTE, ERR_MODELO, ERR_NO_ENCONTRADO, ERR_VALIDACION, Modelos,
                           comprobar_lote, obtener_modelos)
from .errores import RecursoNoEncontrado
from .esquemas import (GrupoInfo, ModeloResumen, MediaCategoria, NuevoPlatoEntrada, PlatoCarta, PopularidadReal, PlatoEntrada, PlatoLoteEntrada, PrediccionPlato,
                       RespuestaPlato, RespuestaPlatoLote)
from .modelos import sugerencia_de
from .nombres_platos import categoria_de, nombre_de

router = APIRouter(prefix="/clustering", tags=["Objetivo 1 · Clustering de platos"])


def _resumen(modelos: Modelos) -> ModeloResumen:
    info = modelos.clustering.info
    return ModeloResumen(nombre=info.nombre, version=info.version)


@router.post("/predecir", response_model=RespuestaPlato, summary="Clasificar un plato",
             responses={422: ERR_VALIDACION, 503: ERR_MODELO, 500: ERR_INTERNO})
def predecir_plato(plato: PlatoEntrada, modelos: Modelos = Depends(obtener_modelos)):
    """Dice a qué **grupo** pertenece un plato a partir de su **popularidad** y su **margen medio**.

    Los grupos son los que encontró el modelo K-Means del notebook 04 (por ejemplo, *Estrella*, *Popular pero poco rentable*…).
    La respuesta incluye lo lejos que está el plato del centro de su grupo y una sugerencia orientativa.

    **Plato nuevo sin ventas:** la `popularidad` es opcional. Si se omite, el modelo no se la inventa: prueba el plato con todas las
    popularidades de la carta actual y devuelve el grupo más frecuente como **provisional** (`popularidad_conocida: false`), junto con
    el reparto de `grupos_posibles`. Cuando el plato tenga ventas reales, hay que volver a clasificarlo con su popularidad.
    """
    tabla = pd.DataFrame([plato.model_dump(exclude={"id_plato"})])
    resultado = modelos.clustering.predecir(tabla)[0]
    return RespuestaPlato(id_plato=plato.id_plato, modelo=_resumen(modelos), **resultado)


@router.post("/predecir-lote", response_model=RespuestaPlatoLote, summary="Clasificar varios platos a la vez",
             responses={413: ERR_LOTE, 422: ERR_VALIDACION, 503: ERR_MODELO, 500: ERR_INTERNO})
def predecir_lote(lote: PlatoLoteEntrada, modelos: Modelos = Depends(obtener_modelos)):
    """Igual que `/clustering/predecir`, pero con una lista de platos. Los resultados salen **en el mismo orden** que la lista enviada."""
    comprobar_lote(len(lote.platos), modelos.ajustes)
    tabla = pd.DataFrame([p.model_dump(exclude={"id_plato"}) for p in lote.platos])
    resultados = modelos.clustering.predecir(tabla)
    return RespuestaPlatoLote(
        modelo=_resumen(modelos), n=len(resultados),
        resultados=[PrediccionPlato(id_plato=p.id_plato, **r) for p, r in zip(lote.platos, resultados)])


@router.get("/grupos", response_model=list[GrupoInfo], summary="Describir los grupos del modelo",
            responses={503: ERR_MODELO})
def listar_grupos(modelos: Modelos = Depends(obtener_modelos)):
    """Lista los grupos: su nombre, el plato \"medio\" de cada uno (centroide), cuántos platos de la carta tiene y qué hacer con ellos."""
    return modelos.clustering.grupos()


def _plato_carta(fila: pd.Series, nombre: str) -> PlatoCarta:
    """Un plato de la carta ORIGINAL (viene de la tabla que guardó el notebook 04 en MLflow)."""
    campos = ["popularidad", "margen_medio", "precio_medio", "coste_medio", "valoracion", "dificultad", "unidades_medias"]
    datos = {c: (None if pd.isna(fila.get(c)) else float(fila[c])) for c in campos if c in fila}
    id_plato = int(fila["id_plato"])
    return PlatoCarta(id_plato=id_plato, nombre=nombre_de(id_plato), categoria=categoria_de(id_plato), grupo=int(fila["grupo"]),
                      nombre_grupo=fila["nombre_grupo"], sugerencia=sugerencia_de(fila["nombre_grupo"]), **datos)


def _platos_nuevos(modelos: Modelos) -> list[PlatoCarta]:
    """Platos guardados en el CSV, clasificados AHORA con el modelo vigente (si se reentrena, su grupo se actualiza solo)."""
    tabla = modelos.almacen.leer()
    if tabla.empty:
        return []
    resultados = modelos.clustering.predecir(tabla[["popularidad", "margen_medio"]])
    return [PlatoCarta(id_plato=int(f.id_plato), nombre=f.nombre, categoria=f.categoria, es_nuevo=True,
                       popularidad_estimada=bool(f.popularidad_estimada), grupo=r["grupo"],
                       nombre_grupo=r["nombre_grupo"], popularidad=float(f.popularidad), margen_medio=float(f.margen_medio),
                       precio_medio=float(f.precio_medio), coste_medio=float(f.coste_medio), dificultad=float(f.dificultad),
                       sugerencia=r["sugerencia"])
            for f, r in zip(tabla.itertuples(index=False), resultados)]


def _todos_los_platos(modelos: Modelos, grupo: int | None = None) -> list[PlatoCarta]:
    tabla = modelos.clustering.platos(grupo)
    platos = [_plato_carta(fila, fila["nombre_grupo"]) for _, fila in tabla.iterrows()] + _platos_nuevos(modelos)
    return platos if grupo is None else [p for p in platos if p.grupo == grupo]


@router.get("/platos", response_model=list[PlatoCarta], summary="Platos de la carta con su grupo",
            responses={422: ERR_VALIDACION, 503: ERR_MODELO})
def listar_platos(grupo: int | None = Query(default=None, ge=0, description="Si se indica, solo los platos de ese grupo."),
                  modelos: Modelos = Depends(obtener_modelos)):
    """Los 80 platos de la carta con el grupo que les asignó el modelo, **más los que se hayan añadido** desde la interfaz
    (`es_nuevo: true`). Con `?grupo=2` se filtra por grupo."""
    return _todos_los_platos(modelos, grupo)


@router.get("/platos/{id_plato}", response_model=PlatoCarta, summary="Grupo de un plato de la carta",
            responses={404: ERR_NO_ENCONTRADO, 422: ERR_VALIDACION, 503: ERR_MODELO})
def obtener_plato(id_plato: int = Path(ge=1, description="Identificador del plato (1 a 80 en la carta original; 81 en adelante, los añadidos)."),
                  modelos: Modelos = Depends(obtener_modelos)):
    """Devuelve un plato con su grupo y su perfil (precio, coste, valoración…)."""
    platos = _todos_los_platos(modelos)
    for plato in platos:
        if plato.id_plato == id_plato:
            return plato
    raise RecursoNoEncontrado(f"No existe el plato con id_plato={id_plato}. "
                              f"Los platos van del {min(p.id_plato for p in platos)} al {max(p.id_plato for p in platos)}.")


def _medias_por_categoria(modelos: Modelos) -> dict[str, MediaCategoria]:
    """Popularidad media de cada categoría: los 80 platos de la carta + los añadidos con popularidad REAL (las estimadas no cuentan,
    para que una estimación no se alimente de otras estimaciones)."""
    carta = modelos.clustering.platos()
    nuevos = modelos.almacen.leer()
    nuevos = nuevos[~nuevos["popularidad_estimada"]]
    todos = pd.DataFrame({"categoria": [categoria_de(int(i)) for i in carta["id_plato"]] + list(nuevos["categoria"]),
                          "popularidad": list(carta["popularidad"]) + list(nuevos["popularidad"])}).dropna()
    return {c: MediaCategoria(categoria=c, popularidad_media=round(float(g["popularidad"].mean()), 4), n_platos=len(g))
            for c, g in todos.groupby("categoria")}


@router.get("/popularidad-por-categoria", response_model=list[MediaCategoria], summary="Popularidad media de cada categoría",
            responses={503: ERR_MODELO})
def popularidad_por_categoria(modelos: Modelos = Depends(obtener_modelos)):
    """La media de popularidad de los entrantes, principales y postres. Es el valor que se usa al guardar un plato **sin ventas**."""
    return list(_medias_por_categoria(modelos).values())


@router.post("/platos-nuevos", response_model=PlatoCarta, status_code=201, summary="Añadir un plato (se guarda para siempre)",
             responses={409: ERR_CONFLICTO, 422: ERR_VALIDACION, 503: {**ERR_ALMACEN, "description": "Modelo no disponible o no se puede escribir el CSV."}})
def anadir_plato(plato: NuevoPlatoEntrada, modelos: Modelos = Depends(obtener_modelos)):
    """Añade un plato nuevo y lo guarda en `platos_nuevos.csv`.

    - El **margen** se calcula solo: `precio_medio − coste_medio`.
    - Si ya tiene ventas, se envía su `popularidad`. Si **todavía no**, se envía `estimar_popularidad: true`: se usa la **media de
      popularidad de su categoría** y el plato queda marcado como `popularidad_estimada` (es un supuesto, no un dato).
      Cuando tenga ventas reales se corrige con `PATCH /clustering/platos-nuevos/{id}`.
    - Se clasifica con el modelo de clustering actual (no se reentrena).
    - Desde ese momento sale como un punto más en el gráfico y en la tabla, y sigue ahí aunque se reinicie la API.
    """
    estimada = plato.estimar_popularidad
    popularidad = _medias_por_categoria(modelos)[plato.categoria].popularidad_media if estimada else plato.popularidad
    resultado = modelos.clustering.predecir(pd.DataFrame([{"popularidad": popularidad, "margen_medio": plato.margen_medio}]))[0]
    registro = modelos.almacen.anadir({
        "nombre": plato.nombre, "categoria": plato.categoria, "precio_medio": plato.precio_medio, "coste_medio": plato.coste_medio,
        "margen_medio": plato.margen_medio, "dificultad": plato.dificultad, "popularidad": popularidad,
        "popularidad_estimada": estimada, "grupo": resultado["grupo"], "nombre_grupo": resultado["nombre_grupo"]})
    return PlatoCarta(id_plato=registro["id_plato"], nombre=plato.nombre, categoria=plato.categoria, es_nuevo=True, popularidad_estimada=estimada,
                      grupo=resultado["grupo"], nombre_grupo=resultado["nombre_grupo"], popularidad=popularidad, margen_medio=plato.margen_medio,
                      precio_medio=plato.precio_medio, coste_medio=plato.coste_medio, dificultad=float(plato.dificultad),
                      sugerencia=resultado["sugerencia"])


@router.patch("/platos-nuevos/{id_plato}", response_model=PlatoCarta, summary="Poner la popularidad real de un plato añadido",
              responses={404: ERR_NO_ENCONTRADO, 422: ERR_VALIDACION, 503: {**ERR_ALMACEN, "description": "Modelo no disponible o no se puede escribir el CSV."}})
def actualizar_popularidad(datos: PopularidadReal, id_plato: int = Path(ge=1, description="Identificador del plato añadido (81 en adelante)."),
                           modelos: Modelos = Depends(obtener_modelos)):
    """Sustituye la popularidad (estimada o no) de un plato añadido por la real, lo vuelve a clasificar y actualiza el CSV.
    Es el paso que convierte un plato «con la media de su categoría» en un plato con datos reales."""
    actual = next((f for f in modelos.almacen.leer().itertuples(index=False) if int(f.id_plato) == id_plato), None)
    if actual is None:
        raise RecursoNoEncontrado(f"No hay ningún plato añadido con id_plato={id_plato} (los de la carta original, del 1 al 80, no se pueden modificar).")
    resultado = modelos.clustering.predecir(pd.DataFrame([{"popularidad": datos.popularidad, "margen_medio": float(actual.margen_medio)}]))[0]
    modelos.almacen.actualizar(id_plato, {"popularidad": datos.popularidad, "popularidad_estimada": False,
                                          "grupo": resultado["grupo"], "nombre_grupo": resultado["nombre_grupo"]})
    return PlatoCarta(id_plato=id_plato, nombre=actual.nombre, categoria=actual.categoria, es_nuevo=True, popularidad_estimada=False,
                      grupo=resultado["grupo"], nombre_grupo=resultado["nombre_grupo"], popularidad=datos.popularidad,
                      margen_medio=float(actual.margen_medio), precio_medio=float(actual.precio_medio), coste_medio=float(actual.coste_medio),
                      dificultad=float(actual.dificultad), sugerencia=resultado["sugerencia"])


@router.delete("/platos-nuevos/{id_plato}", status_code=204, summary="Eliminar un plato añadido",
               responses={404: ERR_NO_ENCONTRADO, 422: ERR_VALIDACION, 503: ERR_ALMACEN})
def eliminar_plato(id_plato: int = Path(ge=1, description="Identificador del plato añadido (81 en adelante)."),
                   modelos: Modelos = Depends(obtener_modelos)):
    """Borra un plato añadido (por ejemplo, si se escribió mal). Los 80 platos de la carta original no se pueden borrar."""
    if not modelos.almacen.eliminar(id_plato):
        raise RecursoNoEncontrado(f"No hay ningún plato añadido con id_plato={id_plato} (los de la carta original, del 1 al 80, no se pueden eliminar).")
    return Response(status_code=204)
