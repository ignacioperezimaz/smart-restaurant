"""Errores de la API: todos se devuelven con el MISMO formato JSON, en español, para que sean fáciles de tratar.

    {"error": {"codigo": "validacion", "mensaje": "...", "detalles": [...], "id_peticion": "a1b2c3d4"}}

- `codigo`: palabra corta y estable (para programas). `mensaje`: frase para personas.
- `detalles`: solo en errores de validación; una entrada por campo mal rellenado.
- `id_peticion`: el mismo identificador que sale en la cabecera `X-Request-ID` y en los registros (logs).
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("api.errores")


# ----------------------------------------------------------------------------------------------
# Esquemas del error (aparecen en la documentación /docs)
# ----------------------------------------------------------------------------------------------
class DetalleError(BaseModel):
    campo: str = Field(description="Campo con el problema (por ejemplo `cola_pedidos` o `pedidos[2].canal`).",
                       examples=["cola_pedidos"])
    mensaje: str = Field(description="Qué está mal y cómo arreglarlo.", examples=["Debe ser mayor o igual que 0."])
    valor_recibido: str | None = Field(default=None, description="Lo que se envió en ese campo (recortado).",
                                       examples=["-3"])


class CuerpoError(BaseModel):
    codigo: str = Field(description="Código corto del error.", examples=["validacion"])
    mensaje: str = Field(description="Explicación para personas.", examples=["Los datos enviados no son válidos."])
    detalles: list[DetalleError] | None = Field(default=None, description="Solo en errores de validación.")
    id_peticion: str | None = Field(default=None, description="Identificador de la petición (para buscarla en los logs).")


class ErrorRespuesta(BaseModel):
    error: CuerpoError


# ----------------------------------------------------------------------------------------------
# Excepciones propias: el resto del código las lanza y aquí se convierten en respuestas
# ----------------------------------------------------------------------------------------------
class ErrorAPI(Exception):
    """Base de los errores controlados de la API."""
    estado = 500
    codigo = "error_interno"

    def __init__(self, mensaje: str):
        super().__init__(mensaje)
        self.mensaje = mensaje


class ModeloNoDisponible(ErrorAPI):
    """El modelo no se pudo cargar (MLflow caído, o todavía no se ha entrenado y registrado)."""
    estado = 503
    codigo = "modelo_no_disponible"


class DatosNoDisponibles(ErrorAPI):
    """Falta algún dato auxiliar del modelo (por ejemplo, la tabla de platos con su grupo)."""
    estado = 503
    codigo = "datos_no_disponibles"


class RecursoNoEncontrado(ErrorAPI):
    """Se pidió algo que no existe (por ejemplo, un plato con un id que no está en la carta)."""
    estado = 404
    codigo = "no_encontrado"


class ErrorPrediccion(ErrorAPI):
    """El modelo se cargó, pero la predicción falló o dio un valor inválido."""
    estado = 500
    codigo = "error_prediccion"


# ----------------------------------------------------------------------------------------------
# Traducción de los errores de validación de Pydantic al español
# ----------------------------------------------------------------------------------------------
def _traducir(error: dict) -> str:
    """Convierte un error de Pydantic en una frase en español que diga qué hacer."""
    tipo, ctx = error.get("type", ""), error.get("ctx", {}) or {}
    plantillas = {
        "missing": "Campo obligatorio: falta en la petición.",
        "extra_forbidden": "Campo no reconocido. Revisa si está bien escrito (consulta /docs).",
        "int_parsing": "Debe ser un número entero (por ejemplo, 3).",
        "int_from_float": "Debe ser un número entero, sin decimales.",
        "float_parsing": "Debe ser un número (por ejemplo, 4.5).",
        "bool_parsing": "Debe ser verdadero/falso (o 1/0).",
        "string_type": "Debe ser un texto.",
        "json_invalid": "El cuerpo de la petición no es un JSON válido.",
        "model_attributes_type": "Se esperaba un objeto JSON con los campos del apartado de ejemplo.",
        "dict_type": "Se esperaba un objeto JSON con los campos del apartado de ejemplo.",
        "list_type": "Se esperaba una lista.",
        "greater_than_equal": f"Debe ser mayor o igual que {ctx.get('ge')}.",
        "greater_than": f"Debe ser mayor que {ctx.get('gt')}.",
        "less_than_equal": f"Debe ser menor o igual que {ctx.get('le')}.",
        "less_than": f"Debe ser menor que {ctx.get('lt')}.",
        "too_short": f"Debe tener al menos {ctx.get('min_length')} elemento(s).",
        "too_long": f"Demasiados elementos: el máximo permitido es {ctx.get('max_length')}.",
        "string_too_long": f"Texto demasiado largo (máximo {ctx.get('max_length')} caracteres).",
        "literal_error": f"Valor no permitido. Opciones válidas: {ctx.get('expected')}.",
        "finite_number": "Debe ser un número finito (sin NaN ni infinito).",
    }
    if tipo == "value_error":                       # errores de nuestras propias comprobaciones
        return str(error.get("msg", "")).removeprefix("Value error, ")
    return plantillas.get(tipo, error.get("msg", "Valor no válido."))


def _campo(loc: tuple) -> str:
    """Pasa la ruta del error a texto legible: ('body','pedidos',2,'canal') -> 'pedidos[2].canal'."""
    partes = [p for p in loc if p not in ("body", "query", "path")]
    texto = ""
    for p in partes:
        texto += f"[{p}]" if isinstance(p, int) else (f".{p}" if texto else str(p))
    return texto or "cuerpo"


def _detalles(errores: list[dict]) -> list[DetalleError]:
    detalles = []
    for e in errores:
        valor = None
        if e.get("type") not in ("missing", "json_invalid") and "input" in e:
            valor = str(e["input"])[:80]
        detalles.append(DetalleError(campo=_campo(tuple(e.get("loc", ()))), mensaje=_traducir(e), valor_recibido=valor))
    return detalles


# ----------------------------------------------------------------------------------------------
# Construcción de la respuesta y registro de los manejadores
# ----------------------------------------------------------------------------------------------
def _respuesta(request: Request, estado: int, codigo: str, mensaje: str,
               detalles: list[DetalleError] | None = None) -> JSONResponse:
    id_peticion = getattr(request.state, "id_peticion", None)
    cuerpo = ErrorRespuesta(error=CuerpoError(codigo=codigo, mensaje=mensaje, detalles=detalles, id_peticion=id_peticion))
    cabeceras = {"X-Request-ID": id_peticion} if id_peticion else None
    return JSONResponse(status_code=estado, content=cuerpo.model_dump(exclude_none=True), headers=cabeceras)


def registrar_manejadores(app: FastAPI) -> None:
    """Conecta cada tipo de error con su respuesta en el formato común."""

    @app.exception_handler(ErrorAPI)
    async def _error_api(request: Request, exc: ErrorAPI):
        log.warning("%s (%s): %s", exc.codigo, request.url.path, exc.mensaje)
        return _respuesta(request, exc.estado, exc.codigo, exc.mensaje)

    @app.exception_handler(RequestValidationError)
    async def _validacion(request: Request, exc: RequestValidationError):
        detalles = _detalles(exc.errors())
        log.info("validacion (%s): %d campo(s) con problemas", request.url.path, len(detalles))
        return _respuesta(request, 422, "validacion", "Los datos enviados no son válidos. Revisa los detalles.", detalles)

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException):
        if exc.status_code == 404:
            return _respuesta(request, 404, "ruta_no_encontrada",
                              f"La ruta {request.url.path} no existe. Consulta /docs para ver las rutas disponibles.")
        if exc.status_code == 405:
            return _respuesta(request, 405, "metodo_no_permitido",
                              f"El método {request.method} no está permitido en {request.url.path}. Consulta /docs.")
        return _respuesta(request, exc.status_code, "error_http", str(exc.detail))

    @app.exception_handler(Exception)
    async def _inesperado(request: Request, exc: Exception):
        # Un fallo que no esperábamos: se guarda TODO en el log, pero al cliente solo se le da un mensaje general
        # (no se enseñan detalles internos del servidor).
        log.exception("Error inesperado en %s %s", request.method, request.url.path)
        return _respuesta(request, 500, "error_interno",
                          "Error interno del servidor. Indica el id_peticion a quien mantenga la API.")
