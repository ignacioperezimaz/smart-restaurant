# API de Smart-Restaurant (FastAPI)

Sirve por HTTP los **dos modelos** del proyecto, tal y como quedan registrados en MLflow:

| Objetivo | Qué responde | Rutas |
|---|---|---|
| **1 · Clustering de platos** | ¿Qué tipo de plato es (estrella, popular pero poco rentable…) según su popularidad y su margen? | `/clustering/...` |
| **2 · Tiempo de preparación** | ¿Cuántos minutos tardará en estar listo un pedido? | `/regresion/...` |

Además trae una **interfaz web** (HTML, CSS y JavaScript) para usar los dos modelos sin escribir código: **http://localhost:8000**
(la sirve la propia API desde la carpeta `interfaz/`; ver el apartado «Interfaz web»).

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
| POST | `/clustering/predecir` | Grupo de **un** plato nuevo (`margen_medio` y, si ya tiene ventas, `popularidad`) |
| POST | `/clustering/predecir-lote` | Grupo de **varios** platos |
| GET | `/clustering/grupos` | Descripción de los grupos: nombre, plato "medio", nº de platos y sugerencia |
| GET | `/clustering/platos` | Los 80 platos de la carta **más los añadidos**, con su grupo (`?grupo=2` para filtrar) |
| GET | `/clustering/platos/{id_plato}` | Un plato con su grupo y su perfil |
| POST | `/clustering/platos-nuevos` | **Añadir** un plato (nombre, categoría, precio, coste, dificultad y popularidad, o `estimar_popularidad: true` si aún no tiene ventas): calcula el margen, lo clasifica y lo guarda en `platos_nuevos.csv` |
| PATCH | `/clustering/platos-nuevos/{id_plato}` | Poner la **popularidad real** de un plato guardado con la estimada (lo reclasifica y actualiza el CSV) |
| GET | `/clustering/popularidad-por-categoria` | Popularidad media de entrantes, principales y postres (la que se usa para estimar) |
| DELETE | `/clustering/platos-nuevos/{id_plato}` | Eliminar un plato añadido (los 80 originales no se tocan) |
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

## Interfaz web

Al abrir http://localhost:8000 aparece el panel de Smart-Restaurant, con dos pestañas:

- **Estimar tiempo** (objetivo 2): resultado en minutos con un medidor por tramos y avisos de la API. Tras la primera estimación se actualiza solo al cambiar un dato. Tiene tres ejemplos de muestra (en una misma línea) y dos subsecciones:
  - **Cliente**: se eligen platos de la carta (con buscador, agrupados en entrantes, principales y postres) y las unidades de cada uno. De la cesta salen solos `n_platos`, `num_platos_complejos` (dificultad ≥ 7) y `complejidad_pedido` (dificultad media por unidad). Botones **Pedir** y **Estimar tiempo de preparación**. El modelo se entrenó con pedidos de 1 a 8 platos; con más, la interfaz avisa.
  - **Cocina**: el resto de datos (canal, prioridad, ingrediente agotado, pedidos en cola, cocineros, hora, lluvia y día) Los **pedidos recibidos** son la cola de la cocina: **no hay un control para ajustarla a mano**, la `cola_pedidos` que recibe el modelo es el número de pedidos recibidos pendientes (sube al pedir y baja al marcarlos como listos; al estimar un pedido ya recibido solo cuentan los que van antes que él). Los tres ejemplos de muestra preparan la cola con 2, 12 y 20 pedidos de ejemplo. Cada pedido tiene botones para estimarlo y para marcarlo como listo se ven solo en esta subsección, debajo del tiempo estimado (columna derecha). *Pedir* es una demostración: el pedido solo vive en la página abierta, no se guarda en el servidor ni cambia el valor de «pedidos en cola».
- **Ver grupos de platos** (objetivo 1): gráfico de los 80 platos por popularidad y margen (se puede filtrar por grupo) con el **nombre del plato al pasar el ratón** por encima de cada punto, tarjetas de cada grupo, tabla ordenable (con el nombre de cada plato) y un formulario para clasificar un plato nuevo, que aparece marcado en el gráfico. Pulsando un punto o una fila de la tabla se resalta ese plato en los dos sitios.

> **Nombres de los platos:** los datos solo traen un número por plato (`id_plato`, 1 a 80). Los nombres y la categoría (entrante, principal o postre) de cada plato (ensalada de tomate, croquetas de jamón, tortilla de patatas…) están en `app/nombres_platos.py` y los hemos puesto nosotros como ejemplo, **no salen de los datos**. Hay que decirlo así en la defensa.

Está hecha con HTML, CSS y JavaScript sin librerías (los colores, el logo y la tipografía Montserrat están en la propia carpeta, sin cargas externas).
Valida los datos en el navegador, muestra estados de carga y de error (por ejemplo, si la API o MLflow están caídos) y se puede usar con el teclado.
La API valida igualmente todo lo que recibe.

## Añadir platos y guardarlos para siempre

En la pestaña de grupos, el formulario **«Añadir un plato»** pide nombre, categoría, precio, coste, dificultad y popularidad. El **margen unitario se calcula solo** (`precio − coste`, igual que `margen_unitario` en los datos de ventas) y se ve mientras se escribe.

- **«Ver dónde cae»** solo prueba: dibuja el plato en el gráfico (un punto si hay popularidad; la línea si no la hay) y **no guarda nada**.
- **«Guardar plato»** lo clasifica con el modelo actual (con la popularidad real que se escriba), lo escribe en **`data/platos_nuevos.csv`** y desde entonces sale como un punto más (con un anillo discontinuo y la etiqueta «Añadido» en la tabla). Sigue ahí aunque se reinicie o se reconstruya la API.
- **Plato sin ventas:** con el interruptor «aún no tiene ventas» el botón pasa a **«Guardar con la media de su categoría»**. Se usa la popularidad media de los platos de su misma categoría (entrante, principal o postre) y el plato queda marcado como **popularidad estimada** (`popularidad_estimada = True` en el CSV; etiqueta en la tabla y aviso al pasar el ratón). La media se calcula con los 80 platos de la carta y los añadidos con popularidad real; **las estimaciones no entran en la media**, para que una estimación no se alimente de otras.
- Cuando ese plato ya tenga ventas, se selecciona en el gráfico o la tabla y se pulsa **«Poner popularidad real»**: se sustituye la estimada, se reclasifica y se actualiza el CSV.
- Se puede eliminar un plato añadido (botón «Eliminar plato» al pulsarlo, con confirmación) por si se escribió mal.
- No se puede repetir un nombre (ni usar el de un plato de la carta).

Cómo se guarda: la carpeta `data/` del repositorio se monta en la API (`docker-compose.yml`: `../data:/datos`) y el archivo es `platos_nuevos.csv` (columnas: `id_plato`, `nombre`, `categoria`, `precio_medio`, `coste_medio`, `margen_medio`, `dificultad`, `popularidad`, `grupo`, `nombre_grupo`, `fecha_alta_utc`). Es un archivo normal, así que se puede revisar y **subir a Git** con el resto del proyecto. Los ids empiezan en 81.

Ojo con la estimación: con estos datos sintéticos la media es casi igual en las tres categorías (≈ 0,503), porque la popularidad no depende de la categoría. Poner la media coloca el plato hacia el centro del eje horizontal, así que su grupo lo decide sobre todo el margen. Es un **supuesto de trabajo**, no una predicción: por eso queda marcado como estimado.

Lo que **no** hace (a propósito):
- No toca los datos originales (`01_ventas_diarias_platos.csv`, HDFS) ni la tabla `platos_con_grupo.csv` de MLflow.
- No reentrena el modelo: los platos añadidos se clasifican con el modelo que ya existe. Si se reentrena, su grupo se recalcula al listarlos (el que aparece en el CSV es el del momento de guardarlo).
- No se rellena la valoración ni las unidades vendidas de los platos añadidos (no las tenemos).
- Si se ejecuta la API sin montar `data/`, el CSV se guarda dentro del contenedor y se pierde al reconstruirlo.

## Qué pasa con un plato nuevo sin popularidad

La popularidad (unidades vendidas por cliente) solo existe cuando el plato ya se ha vendido, así que un plato recién creado **no la tiene**. El modelo de clustering usa dos variables (popularidad y margen), por eso no puede dar un grupo "seguro" sin una de ellas. Se decidió **no rellenar el hueco con la media** (eso empujaría siempre el plato al centro de la carta y daría una falsa seguridad) y hacer lo siguiente:

1. `popularidad` es **opcional** en `/clustering/predecir` y `/clustering/predecir-lote` (el `margen_medio` sigue siendo obligatorio).
2. Si falta, se prueba el plato con **101 popularidades repartidas entre la mínima y la máxima de la carta actual** (0,474–0,523), manteniendo su margen, y se cuenta en qué grupo cae cada vez.
3. La respuesta trae `popularidad_conocida: false`, `grupos_posibles` (por ejemplo, *Rentable pero poco popular* 56 % y *Estrella* 44 %), el grupo más frecuente como grupo **provisional** y un aviso. `distancia_al_centroide` es `null`.
4. Cuando el plato tenga ventas reales hay que **volver a clasificarlo con su popularidad**: ese es el resultado definitivo.

Con los datos actuales, el margen por sí solo casi nunca decide el grupo (los platos con margen medio quedan repartidos entre dos grupos); solo un margen muy fuera de la carta lo hace, y entonces además sale el aviso de "fuera de rango". En la interfaz se activa con el interruptor **"Plato nuevo: aún no tiene ventas"**: se muestra el reparto en barras y, en el gráfico, una línea que indica que el plato puede estar en cualquier punto de esa franja.

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
| 409 | `plato_duplicado` | Ya hay un plato con ese nombre |
| 405 | `metodo_no_permitido` | Método HTTP equivocado |
| 413 | `lote_demasiado_grande` | Un lote supera `MAX_LOTE` elementos (500 por defecto) |
| 422 | `validacion` | Falta un campo, un valor está fuera de rango, tiene el tipo equivocado o hay un campo desconocido |
| 500 | `error_prediccion` / `error_interno` | Falló la predicción o hubo un error inesperado (el detalle va al log, no al cliente) |
| 503 | `modelo_no_disponible` / `datos_no_disponibles` | MLflow caído o modelo todavía sin registrar |
| 503 | `almacen_no_disponible` | No se puede leer o escribir `platos_nuevos.csv` (carpeta sin montar, sin permisos…) |

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
| `RUTA_PLATOS_NUEVOS` | `/datos/platos_nuevos.csv` | CSV donde se guardan los platos añadidos (en Docker es `data/platos_nuevos.csv` del repositorio) |

## Tests

```bash
pip install -r requirements-dev.txt
pytest                                    # 46 tests; no necesitan MLflow (usan modelos pequeños de mentira)
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
│   ├── almacen.py           # CSV permanente de los platos añadidos (platos_nuevos.csv)
│   ├── nombres_platos.py    # nombres y categorías de ejemplo de los 80 platos
│   ├── errores.py           # errores y formato común de respuesta
│   ├── dependencias.py      # piezas compartidas por las rutas
│   └── rutas_*.py           # rutas: sistema, clustering (objetivo 1) y regresión (objetivo 2)
├── interfaz/                # interfaz web: index.html, estilos.css, app.js y assets/ (logos y fuente)
├── tests/
├── Dockerfile
└── requirements.txt
```

## Limitaciones

- Los datos son **sintéticos**: las predicciones demuestran el sistema, no sirven para decisiones reales.
- Sin autenticación (la API solo escucha en `localhost`). Antes de exponerla fuera habría que añadirla, sobre todo en `/modelos/recargar`.
- El modelo de regresión no ha visto lunes, ni más de 20 pedidos en cola, ni más de 7 cocineros: en esos casos avisa.
