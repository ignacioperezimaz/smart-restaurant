"""Objetivo 1 · Clustering de platos: ¿qué tipo de plato es según su popularidad y su margen?"""
from __future__ import annotations

import pandas as pd
from fastapi import APIRouter, Depends, Path, Query

from .dependencias import (ERR_INTERNO, ERR_LOTE, ERR_MODELO, ERR_NO_ENCONTRADO, ERR_VALIDACION, Modelos,
                           comprobar_lote, obtener_modelos)
from .errores import RecursoNoEncontrado
from .esquemas import (GrupoInfo, ModeloResumen, PlatoCarta, PlatoEntrada, PlatoLoteEntrada, PrediccionPlato,
                       RespuestaPlato, RespuestaPlatoLote)
from .modelos import sugerencia_de

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
    campos = ["popularidad", "margen_medio", "precio_medio", "coste_medio", "valoracion", "dificultad", "unidades_medias"]
    datos = {c: (None if pd.isna(fila.get(c)) else float(fila[c])) for c in campos if c in fila}
    return PlatoCarta(id_plato=int(fila["id_plato"]), grupo=int(fila["grupo"]), nombre_grupo=nombre,
                      sugerencia=sugerencia_de(nombre), **datos)


@router.get("/platos", response_model=list[PlatoCarta], summary="Platos de la carta con su grupo",
            responses={422: ERR_VALIDACION, 503: ERR_MODELO})
def listar_platos(grupo: int | None = Query(default=None, ge=0, description="Si se indica, solo los platos de ese grupo."),
                  modelos: Modelos = Depends(obtener_modelos)):
    """Los 80 platos de la carta con el grupo que les asignó el modelo. Con `?grupo=2` se filtra por grupo."""
    tabla = modelos.clustering.platos(grupo)
    return [_plato_carta(fila, fila["nombre_grupo"]) for _, fila in tabla.iterrows()]


@router.get("/platos/{id_plato}", response_model=PlatoCarta, summary="Grupo de un plato de la carta",
            responses={404: ERR_NO_ENCONTRADO, 422: ERR_VALIDACION, 503: ERR_MODELO})
def obtener_plato(id_plato: int = Path(ge=1, description="Identificador del plato en la carta (1 a 80)."),
                  modelos: Modelos = Depends(obtener_modelos)):
    """Devuelve un plato de la carta actual con su grupo y su perfil (precio, coste, valoración…)."""
    tabla = modelos.clustering.platos()
    fila = tabla[tabla["id_plato"] == id_plato]
    if fila.empty:
        raise RecursoNoEncontrado(f"No existe el plato con id_plato={id_plato}. "
                                  f"Los platos de la carta van del {int(tabla['id_plato'].min())} al {int(tabla['id_plato'].max())}.")
    return _plato_carta(fila.iloc[0], fila.iloc[0]["nombre_grupo"])
