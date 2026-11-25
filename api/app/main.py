"""Punto de entrada de la API de Smart-Restaurant.

Arranque (dentro de Docker lo hace el servicio `api`):  uvicorn app.main:app --host 0.0.0.0 --port 8000
Documentación interactiva:  http://localhost:8000/docs   (y una versión de solo lectura en /redoc)
"""
from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse

from . import __version__
from .config import leer_ajustes
from .dependencias import Modelos
from .errores import ModeloNoDisponible, registrar_manejadores
from .modelos import ModeloClustering, ModeloRegresion
from .rutas_clustering import router as router_clustering
from .rutas_regresion import router as router_regresion
from .rutas_sistema import router as router_sistema

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s · %(message)s")
log = logging.getLogger("api")

DESCRIPCION = """
API del proyecto **Smart-Restaurant**. Sirve los **dos modelos** entrenados en los notebooks y guardados en MLflow:

| Objetivo | Qué responde | Rutas |
|---|---|---|
| **1 · Clustering de platos** | ¿Qué tipo de plato es (estrella, popular pero poco rentable…) según su popularidad y su margen? | `/clustering/...` |
| **2 · Tiempo de preparación** | ¿Cuántos minutos tardará en estar listo un pedido? | `/regresion/...` |

### Cómo probarla
Abre cualquier ruta de abajo, pulsa **Try it out**, edita el ejemplo y pulsa **Execute**. Cada ruta trae un ejemplo listo.

### Cómo funcionan los modelos
Los modelos no están dentro de la API: se piden a MLflow por su **nombre** y su **alias `actual`**. Tras reentrenar y registrar
una versión nueva en los notebooks, llama a `POST /modelos/recargar` y la API usa la nueva sin reiniciarse.

### Errores
Todos los errores tienen el mismo formato JSON:
```json
{"error": {"codigo": "validacion", "mensaje": "...", "detalles": [{"campo": "cola_pedidos", "mensaje": "..."}], "id_peticion": "a1b2c3d4"}}
```

| Estado | `codigo` | Cuándo |
|---|---|---|
| 404 | `no_encontrado` / `ruta_no_encontrada` | El plato pedido o la ruta no existen |
| 405 | `metodo_no_permitido` | Método HTTP equivocado (por ejemplo, GET en una ruta POST) |
| 413 | `lote_demasiado_grande` | Un lote supera el máximo de elementos |
| 422 | `validacion` | Falta un campo, un valor está fuera de rango o tiene el tipo equivocado |
| 500 | `error_prediccion` / `error_interno` | Fallo al calcular la predicción o error inesperado |
| 503 | `modelo_no_disponible` / `datos_no_disponibles` | MLflow caído o modelo todavía sin registrar |

**Aviso importante:** los datos del proyecto son **sintéticos**, así que las predicciones sirven para demostrar el sistema,
no para tomar decisiones reales de un restaurante.
"""

ETIQUETAS = [
    {"name": "Objetivo 1 · Clustering de platos", "description": "Agrupa los platos según su **popularidad** y su **margen** (modelo K-Means, notebook 04)."},
    {"name": "Objetivo 2 · Tiempo de preparación", "description": "Estima los **minutos de preparación** de un pedido (regresión, notebook 06)."},
    {"name": "Sistema", "description": "Estado de la API, información de los modelos cargados y recarga tras reentrenar."},
]


@asynccontextmanager
async def ciclo_de_vida(app: FastAPI):
    """Al arrancar: crea los modelos e intenta cargarlos. Si MLflow no está listo, la API arranca igualmente (modo degradado)."""
    ajustes = leer_ajustes()
    app.state.modelos = Modelos(ajustes=ajustes, clustering=ModeloClustering(ajustes, ajustes.modelo_clustering),
                                regresion=ModeloRegresion(ajustes, ajustes.modelo_regresion))
    for modelo in (app.state.modelos.clustering, app.state.modelos.regresion):
        try:
            modelo.recargar()
        except ModeloNoDisponible as error:
            log.warning("Arranque sin el modelo '%s': %s", modelo.nombre, error.mensaje)
    yield


def crear_app() -> FastAPI:
    app = FastAPI(title="Smart-Restaurant · API de modelos", version=__version__, description=DESCRIPCION,
                  openapi_tags=ETIQUETAS, lifespan=ciclo_de_vida)
    registrar_manejadores(app)

    @app.middleware("http")
    async def registro_de_peticiones(request: Request, call_next):
        """Da un identificador a cada petición (cabecera X-Request-ID) y apunta en el log cuánto tardó."""
        request.state.id_peticion = uuid.uuid4().hex[:8]
        inicio = time.perf_counter()
        respuesta = await call_next(request)
        respuesta.headers["X-Request-ID"] = request.state.id_peticion
        log.info("%s %s -> %s en %.0f ms [%s]", request.method, request.url.path, respuesta.status_code,
                 (time.perf_counter() - inicio) * 1000, request.state.id_peticion)
        return respuesta

    @app.get("/", include_in_schema=False)
    def inicio():
        return RedirectResponse("/docs")

    app.include_router(router_sistema)
    app.include_router(router_clustering)
    app.include_router(router_regresion)
    return app


app = crear_app()
