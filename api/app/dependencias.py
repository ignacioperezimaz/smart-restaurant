"""Piezas compartidas por las rutas: acceso a los modelos, límite de lotes y descripción de las respuestas de error."""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request

from .almacen import AlmacenPlatos
from .config import Ajustes
from .errores import ErrorAPI, ErrorRespuesta
from .modelos import ModeloClustering, ModeloRegresion


@dataclass
class Modelos:
    """Los dos modelos de la API y los ajustes; se crean al arrancar y viven en `app.state`."""
    ajustes: Ajustes
    clustering: ModeloClustering
    regresion: ModeloRegresion
    almacen: AlmacenPlatos


class LoteDemasiadoGrande(ErrorAPI):
    estado = 413
    codigo = "lote_demasiado_grande"


def obtener_modelos(request: Request) -> Modelos:
    """Dependencia de FastAPI: da acceso a los modelos desde cualquier ruta."""
    return request.app.state.modelos


def comprobar_lote(n: int, ajustes: Ajustes) -> None:
    """Rechaza los lotes que superan el máximo configurado (así una petición enorme no bloquea la API)."""
    if n > ajustes.max_lote:
        raise LoteDemasiadoGrande(f"El lote tiene {n} elementos y el máximo permitido es {ajustes.max_lote}. "
                                  "Divídelo en varias peticiones.")


# Respuestas de error que se documentan en /docs
ERR_VALIDACION = {"model": ErrorRespuesta, "description": "Los datos enviados no son válidos (campo que falta, valor fuera de rango, tipo equivocado…)."}
ERR_MODELO = {"model": ErrorRespuesta, "description": "El modelo no está disponible: MLflow caído o modelo todavía sin registrar."}
ERR_LOTE = {"model": ErrorRespuesta, "description": "El lote supera el máximo de elementos permitido."}
ERR_INTERNO = {"model": ErrorRespuesta, "description": "Error interno al calcular la predicción."}
ERR_CONFLICTO = {"model": ErrorRespuesta, "description": "Ya existe un plato con ese nombre."}
ERR_ALMACEN = {"model": ErrorRespuesta, "description": "No se puede leer o escribir el CSV de platos nuevos."}
ERR_NO_ENCONTRADO = {"model": ErrorRespuesta, "description": "El recurso pedido no existe."}
