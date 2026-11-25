"""Rutas del sistema: estado de la API, información de los modelos y recarga."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from . import __version__
from .dependencias import ERR_MODELO, Modelos, obtener_modelos
from .errores import ModeloNoDisponible
from .esquemas import EstadoModelo, Salud

router = APIRouter(tags=["Sistema"])


def _estado(modelo) -> EstadoModelo:
    """Estado de un modelo SIN intentar cargarlo (así consultar la salud nunca se queda esperando a MLflow)."""
    return EstadoModelo(disponible=modelo.cargado, modelo=modelo.info, problema=modelo.problema)


@router.get("/salud", response_model=Salud, summary="Estado de la API y de los modelos")
def salud(modelos: Modelos = Depends(obtener_modelos)):
    """Responde siempre `200` si la API está viva. El campo `estado` es `ok` si los dos modelos están cargados y
    `degradado` si falta alguno (con el motivo en `problema`)."""
    clustering, regresion = _estado(modelos.clustering), _estado(modelos.regresion)
    ok = clustering.disponible and regresion.disponible
    return Salud(estado="ok" if ok else "degradado", version_api=__version__, mlflow_uri=modelos.ajustes.mlflow_uri,
                 clustering=clustering, regresion=regresion)


@router.get("/modelos", response_model=dict[str, EstadoModelo], summary="Información de los modelos cargados",
            responses={503: ERR_MODELO})
def info_modelos(modelos: Modelos = Depends(obtener_modelos)):
    """Qué versión de cada modelo está sirviendo la API, cuándo se entrenó y con qué notas. Intenta cargar los que falten."""
    for modelo in (modelos.clustering, modelos.regresion):
        try:
            modelo.obtener()
        except ModeloNoDisponible:
            pass                                   # se verá en el campo `problema`
    return {"clustering": _estado(modelos.clustering), "regresion": _estado(modelos.regresion)}


@router.post("/modelos/recargar", response_model=dict[str, EstadoModelo], summary="Recargar los modelos desde MLflow",
             responses={503: ERR_MODELO})
def recargar_modelos(modelos: Modelos = Depends(obtener_modelos)):
    """Vuelve a leer de MLflow la versión que tiene ahora el alias `actual`. Se usa **después de reentrenar y registrar
    una versión nueva** en los notebooks, para no tener que reiniciar la API. Si una recarga falla, se sigue usando la
    versión que ya estaba cargada.

    Nota: en esta primera versión no hay autenticación (la API solo escucha en `localhost`)."""
    for modelo in (modelos.clustering, modelos.regresion):
        try:
            modelo.recargar()
        except ModeloNoDisponible:
            pass                                   # el motivo queda en `problema` de cada modelo
    return {"clustering": _estado(modelos.clustering), "regresion": _estado(modelos.regresion)}
