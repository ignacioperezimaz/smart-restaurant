# API de Smart-Restaurant (FastAPI)

Sirve por HTTP los **dos modelos** del proyecto, tal y como quedan registrados en MLflow:

| Objetivo | Qué responde | Rutas |
|---|---|---|
| **1 · Clustering de platos** | ¿Qué tipo de plato es (estrella, popular pero poco rentable…) según su popularidad y su margen? | `/clustering/...` |
| **2 · Tiempo de preparación** | ¿Cuántos minutos tardará en estar listo un pedido? | `/regresion/...` |

La documentación interactiva se genera sola a partir del código: **http://localhost:8000/docs** (y una versión de solo lectura en `/redoc`).
Ahí se puede probar cada ruta con el botón **Try it out**; todas traen un ejemplo.

## Cómo arrancarla

Desde la carpeta `docker/`:

```bash
docker compose up -d --build api
```

Necesita que **MLflow tenga los dos modelos registrados** con el alias `actual` (se crean ejecutando los notebooks `04_modelo_clustering_platos` y `06_modelo_regresion_tiempos`).
Si todavía no lo están, la API **arranca igualmente** y contesta `503` con un mensaje que dice qué notebook ejecutar.

Para comprobar el estado: http://localhost:8000/salud

## Rutas

| Método | Ruta | Para qué sirve |
|---|---|---|
| GET | `/salud` | La API está viva; qué modelos hay cargados y, si falta alguno, por qué |
| GET | `/modelos` | Versión de cada modelo, cuándo se entrenó y sus notas (MAE, silhouette…) |
| POST | `/modelos/recargar` | Coger la versión nueva tras **reentrenar y registrar** en los notebooks (sin reiniciar la API) |
| POST | `/clustering/predecir` | Grupo de **un** plato nuevo (`popularidad` y `margen_medio`) |
| POST | `/clustering/predecir-lote` | Grupo de **varios** platos |
| GET | `/clustering/grupos` | Descripción de los grupos: nombre, plato "medio", nº de platos y sugerencia |
| GET | `/clustering/platos` | Los 80 platos de la carta con su grupo (`?grupo=2` para filtrar) |
| GET | `/clustering/platos/{id_plato}` | Un plato de la carta con su grupo y su perfil |
| POST | `/regresion/predecir` | Minutos estimados de **un** pedido |
| POST | `/regresion/predecir-lote` | Minutos estimados de **varios** pedidos |

En los lotes, los resultados salen **en el mismo orden** que los elementos enviados.

## Ejemplos

**Estimar el tiempo de un pedido** (Python, funciona igual en Windows, Mac y Linux):

```python
import requests

pedido = {
    "n_platos": 3, "num_platos_complejos": 1, "complejidad_pedido": 4.5,
    "cola_pedidos": 8, "cocineros_disponibles": 5, "precipitacion_mm": 0.0,
    "hora_dec": 20.5,            # las 20:30
    "dia_semana": 6,             # 1 = lunes ... 7 = domingo
    "canal": "delivery",         # mesa | delivery | takeaway
    "prioridad_aux": "normal",   # normal | prioridad | VIP
}
print(requests.post("http://localhost:8000/regresion/predecir", json=pedido).json())
# {'tiempo_estimado_minutos': 25.7, 'error_medio_orientativo_minutos': 2.13, 'avisos': [], 'modelo': {...}}
```

**Clasificar un plato** (PowerShell):

```powershell
Invoke-RestMethod -Method Post -Uri http://localhost:8000/clustering/predecir -ContentType "application/json" `
  -Body '{"popularidad": 0.52, "margen_medio": 10.1}'
```

(En PowerShell `curl` es otro comando; si prefieres curl, usa `curl.exe`.)

## Cómo controla los errores

Todos los errores tienen **el mismo formato**, en español, con un código corto para programas y un mensaje para personas:

```json
{"error": {"codigo": "validacion", "mensaje": "Los datos enviados no son válidos. Revisa los detalles.",
           "detalles": [{"campo": "canal", "mensaje": "Valor no permitido. Opciones válidas: 'mesa', 'delivery', 'takeaway'.", "valor_recibido": "drive"}],
           "id_peticion": "a1b2c3d4"}}
```

| Estado | `codigo` | Cuándo |
|---|---|---|
| 404 | `no_encontrado` / `ruta_no_encontrada` | El plato pedido o la ruta no existen |
| 405 | `metodo_no_permitido` | Método HTTP equivocado |
| 413 | `lote_demasiado_grande` | Un lote supera `MAX_LOTE` elementos (500 por defecto) |
| 422 | `validacion` | Falta un campo, un valor está fuera de rango, tiene el tipo equivocado o hay un campo desconocido |
| 500 | `error_prediccion` / `error_interno` | Falló la predicción o hubo un error inesperado (el detalle va al log, no al cliente) |
| 503 | `modelo_no_disponible` / `datos_no_disponibles` | MLflow caído o modelo todavía sin registrar |

Decisiones que conviene saber (y poder explicar):

- **Se valida todo lo que entra** (tipos, rangos, opciones permitidas, que `num_platos_complejos` no supere a `n_platos`) y se **rechazan campos desconocidos**, para que una errata no pase desapercibida.
- **Lo que queda fuera de lo visto al entrenar no es un error, es un aviso.** Por ejemplo, un pedido con 40 pedidos en cola (el modelo se entrenó con 0 a 20) o un lunes (el restaurante cierra) se responde, pero con una lista `avisos` que dice que la estimación es menos fiable.
- **Si MLflow se cae, la API no se cae**: sigue sirviendo los modelos que ya tenía en memoria. Si una recarga falla, conserva la versión anterior y lo cuenta en `/salud`.
- **Cada petición lleva un identificador** (`X-Request-ID`, y `id_peticion` en los errores) que también sale en el log, para localizarla.

## Cómo elige los modelos

La API no lleva los modelos dentro: pide a MLflow la versión con el alias `actual` de cada modelo registrado.
Flujo cuando alguien mejora un modelo: ejecutar el notebook (se crea una versión nueva y el alias `actual` pasa a ella) → `POST /modelos/recargar`.

La imagen de Docker parte de la **misma imagen que Jupyter**, para tener las mismas versiones de scikit-learn, pandas y numpy con las que se entrenaron los modelos.

## Configuración (variables de entorno en `docker-compose.yml`)

| Variable | Por defecto | Qué hace |
|---|---|---|
| `MLFLOW_TRACKING_URI` | `http://mlflow:5000` | Dónde está MLflow |
| `MODELO_CLUSTERING` | `smart_restaurant_clustering_platos` | Nombre del modelo del objetivo 1 |
| `MODELO_REGRESION` | `smart_restaurant_regresion_tiempo_prep` | Nombre del modelo del objetivo 2 |
| `ALIAS_MODELO` | `actual` | Alias que marca la versión vigente |
| `MAX_LOTE` | `500` | Máximo de elementos por lote |

## Tests

```bash
pip install -r requirements-dev.txt
pytest                                    # 27 tests; no necesitan MLflow (usan modelos pequeños de mentira)
TEST_MLFLOW_URI=http://localhost:5000 pytest tests/test_integracion.py   # prueba con los modelos reales de MLflow
```

## Estructura

```
api/
├── app/
│   ├── main.py              # crea la app, la documentación y el registro de peticiones
│   ├── config.py            # ajustes (variables de entorno)
│   ├── esquemas.py          # datos de entrada y salida, con sus reglas de validación
│   ├── modelos.py           # carga de los modelos desde MLflow y predicción
│   ├── errores.py           # errores y formato común de respuesta
│   ├── dependencias.py      # piezas compartidas por las rutas
│   └── rutas_*.py           # rutas: sistema, clustering (objetivo 1) y regresión (objetivo 2)
├── tests/
├── Dockerfile
└── requirements.txt
```

## Limitaciones

- Los datos son **sintéticos**: las predicciones demuestran el sistema, no sirven para decisiones reales.
- Sin autenticación (la API solo escucha en `localhost`). Antes de exponerla fuera habría que añadirla, sobre todo en `/modelos/recargar`.
- El modelo de regresión no ha visto lunes, ni más de 20 pedidos en cola, ni más de 7 cocineros: en esos casos avisa.
