# Smart Restaurant

Proyecto local de análisis de datos para restauración. El entorno reúne un dashboard en Streamlit, notebooks de Jupyter, almacenamiento HDFS, gestión de trabajos con YARN y seguimiento de experimentos con MLflow. Todos los servicios se ejecutan en Docker Compose en el ordenador del usuario.

> La configuración está pensada para desarrollo y prácticas locales en un clúster Hadoop de un solo nodo. No está preparada para exponer los servicios a Internet ni para producción.

## Arquitectura

| Servicio | Función | Dirección local |
| --- | --- | --- |
| Dashboard (Streamlit) | Explorar los datos y resultados del proyecto | [http://localhost:8501](http://localhost:8501) |
| Jupyter | Ejecutar los notebooks | [http://localhost:8889](http://localhost:8889) |
| MLflow | Consultar experimentos y modelos registrados | [http://localhost:5000](http://localhost:5000) |
| NameNode (HDFS) | Administrar el sistema de archivos distribuido | [http://localhost:9870](http://localhost:9870) |
| DataNode (HDFS) | Almacenar bloques de datos | [http://localhost:9864](http://localhost:9864) |
| ResourceManager (YARN) | Administrar recursos y trabajos | [http://localhost:8088](http://localhost:8088) |
| NodeManager (YARN) | Ejecutar trabajos asignados por YARN | [http://localhost:8042](http://localhost:8042) |

## Requisitos

- Windows 10/11 de 64 bits.
- Docker Desktop instalado y en ejecución, con soporte para contenedores Linux (WSL 2 es la opción habitual en Windows).
- Git para clonar el repositorio, o un navegador para descargarlo como ZIP.
- Espacio libre para descargar y construir las imágenes de Docker y guardar los datos.

No hace falta instalar Python, Hadoop ni Jupyter directamente en Windows. Docker prepara esos entornos.

## Preparar el repositorio

Clona el repositorio o descarga el ZIP y extráelo en una carpeta local. Abre PowerShell y cambia a la carpeta `docker` dentro del proyecto. Por ejemplo:

```powershell
cd C:\proyectos\smart-restaurant\docker
```

Sustituye la ruta del ejemplo por la ubicación en la que guardaste el proyecto. En esa carpeta deben estar `docker-compose.yml` y `hadoop.env`.

## Iniciar el proyecto

Desde la carpeta `docker`, ejecuta:

```powershell
docker compose up --build -d
```

La primera vez, Docker descarga las imágenes y construye los servicios del dashboard, Jupyter y MLflow. Puede tardar varios minutos. Comprueba el estado con:

```powershell
docker compose ps
```

Si un servicio tarda en arrancar o muestra un error, consulta sus registros. Por ejemplo:

```powershell
docker compose logs --tail 100 namenode
docker compose logs --tail 100 dashboard
```

## Cargar los datos en HDFS

Guarda estos dos archivos en `data/`, en la raíz del repositorio:

```text
data/01_ventas_diarias_platos.csv
data/02_pedidos_tiempos_preparacion.csv
```

La información de la carta que necesita este trabajo está integrada en esos datos; no se requiere un CSV de carta separado.

Con los contenedores en marcha, ejecuta desde la carpeta `docker`:

```powershell
docker exec namenode bash /scripts/cargar_hdfs.sh
```

El script (que delega en `ingesta_hdfs.sh`, descrito abajo) crea las zonas `/datalake/raw` y `/datalake/clean`, carga los CSV de `data/` en `/datalake/raw` y comprueba que bytes y MD5 coinciden con los originales. Si regeneraste un CSV que ya estaba en HDFS, añade `--forzar` para reemplazarlo. Para revisar el contenido cargado:

```powershell
docker exec namenode hdfs dfs -ls -R /datalake
```

El script crea la carpeta `clean`, pero no genera los Parquet limpios. Esos archivos se producen al ejecutar el proceso de limpieza correspondiente en los notebooks. El dashboard puede usar los CSV locales para algunas vistas; las vistas limpias necesitan que existan los Parquet que espera la aplicación.

## Ingesta automática a HDFS (input)

`scripts/ingesta_hdfs.sh` automatiza la **entrada** de datos a HDFS, en lugar de subir cada fichero a mano con `hdfs dfs -put`. Para cada CSV:

1. **Detecta la fuente** por sus columnas (el nombre del fichero da igual).
2. **Valida el contrato de datos**: tiene que traer las columnas que exige cada fuente (el orden da igual, pueden sobrar otras). Se ven con `--esquema`.
3. **Lo coloca con la estructura de Smart-Restaurant** y el nombre estándar.
4. **Verifica bytes y MD5** contra el original y anota la ingesta en `/datalake/raw/_ingesta/registro.csv`.
5. **Es idempotente**: lo que no ha cambiado no se vuelve a subir, así que se puede ejecutar cuantas veces haga falta.

```powershell
docker exec namenode bash /scripts/ingesta_hdfs.sh              # una pasada
docker exec namenode bash /scripts/ingesta_hdfs.sh --esquema    # columnas exigidas por fuente
docker exec namenode bash /scripts/ingesta_hdfs.sh --simular    # muestra qué haría sin subir nada
docker exec namenode bash /scripts/ingesta_hdfs.sh --vigilar    # se queda esperando ficheros nuevos (Ctrl+C para salir)
```

Estructura que genera en HDFS (la misma para cualquiera que use el modelo):

```text
/datalake/raw/ventas_diarias_platos/01_ventas_diarias_platos.csv
/datalake/raw/pedidos_tiempos_preparacion/02_pedidos_tiempos_preparacion.csv
/datalake/raw/platos_nuevos/platos_nuevos.csv                      <- platos añadidos desde la interfaz
/datalake/raw/<fuente>/lote=<nombre>/<archivo estándar>            <- lotes adicionales (p. ej. el del drift)
/datalake/raw/_ingesta/registro.csv                                <- qué se ingirió, cuándo, bytes y MD5
/datalake/clean/                                                   <- datos limpios (Parquet)
```

**Cómo usarlo con tus propios datos.** Deja tus CSV (con las mismas columnas que los nuestros) en `data/entrada/` y ejecuta el script. Una subcarpeta crea un lote: `data/entrada/lote_drift/pedidos.csv` termina en `/datalake/raw/pedidos_tiempos_preparacion/lote=lote_drift/`. El segundo lote del análisis de drift entra por el mismo proceso que el primero.

**Seguridad del dato original.** La zona `raw` no se sobrescribe: si el lote principal ya tiene un fichero distinto, el script avisa y no lo toca (usa un lote nuevo o `--forzar`). `platos_nuevos.csv` es la excepción: se actualiza cada vez que cambia.

**Ingesta continua (opcional).** Un servicio de Compose ejecuta el modo `--vigilar` en segundo plano, revisando `data/` y `data/entrada/` cada 30 s. No arranca por defecto:

```powershell
docker compose --profile ingesta up -d ingesta
docker logs -f ingesta
```

## Monitorización del modelo: data drift y model drift

El modelo de tiempo de preparación se entrenó con pedidos de 2023-2025. El notebook `notebooks/07_monitorizacion_drift.ipynb` demuestra con un **segundo lote** (enero-junio de 2026) cómo detectar que los datos han cambiado y que el modelo empeora, qué decisión tomar y cómo reentrenar sin romper nada.

El segundo lote es **sintético** y se genera en dos versiones con el mismo generador:

| Lote | Qué representa | Resultado esperado |
|---|---|---|
| `2026h1_control` | El restaurante sigue igual que en 2023-2025. | Mantener el modelo (sin falsas alarmas). |
| `2026h1_drift` | Desde el 1 de marzo cambian carta, plantilla, demanda y delivery. | Alarma en marzo y decisión de reentrenar. |

Pasos, desde la raíz del repositorio y con Docker en marcha:

```powershell
# 1. Los dos CSV ya están en data/entrada/2026h1_control/ y data/entrada/2026h1_drift/.
#    (Para regenerarlos: python data/generar_lote_drift.py --escenario drift --entrada data)
# 2. Ingerirlos en HDFS: cada subcarpeta de data/entrada/ se guarda como un lote aparte
docker exec namenode bash /scripts/ingesta_hdfs.sh
# 3. Tener el modelo vigente: ejecutar antes los notebooks 02 y 06
# 4. Abrir y ejecutar notebooks/07_monitorizacion_drift.ipynb en Jupyter
```

Los lotes quedan en `/datalake/raw/pedidos_tiempos_preparacion/lote=<nombre>/`. El notebook **no cambia el modelo en producción**: registra el modelo reentrenado como una versión nueva con el alias `candidato` y el alias `actual` (el que usa la API) solo se mueve si lo decide una persona o se activa `PROMOVER_AUTOMATICAMENTE`.

El código reutilizable está en `monitorizacion/`:

- `limpieza_pedidos.py`: la limpieza del notebook 02 como función (así un lote nuevo se limpia igual que el original).
- `drift.py`: PSI, tests KS y chi², error del modelo, regla de decisión y seguimiento mensual.

## Usar Jupyter

Abre [http://localhost:8889](http://localhost:8889). La carpeta del repositorio está disponible dentro de Jupyter en:

```text
/home/jovyan/work
```

Los notebooks están en `notebooks/`. Sigue el orden y las indicaciones de cada notebook. Los cambios guardados en esa carpeta se reflejan en el repositorio local.

## Detener y volver a iniciar

Para detener los servicios, desde la carpeta `docker` ejecuta:

```powershell
docker compose down
```

Los volúmenes con nombre conservan los datos de HDFS y MLflow aunque se eliminen los contenedores. Para iniciar de nuevo:

```powershell
docker compose up -d
```

`docker compose down -v` elimina también esos volúmenes y los datos guardados en ellos. Úsalo solo si quieres borrar el estado persistente y empezar desde cero.

## Solución de problemas

- **Docker no responde:** abre Docker Desktop y espera a que el motor indique que está listo.
- **Un servicio no arranca:** desde `docker`, revisa `docker compose ps` y `docker compose logs --tail 100 <servicio>`.
- **Un puerto está ocupado:** cierra la aplicación que lo esté usando o cambia el puerto publicado en `docker/docker-compose.yml`. En cada asignación `PUERTO_LOCAL:PUERTO_CONTENEDOR`, cambia el número de la izquierda.
- **Falla la carga a HDFS:** comprueba que los dos CSV están en `data/` con los nombres indicados y que NameNode y DataNode están activos.
- **No aparecen datos limpios:** ejecuta el proceso de limpieza de los notebooks y confirma que los Parquet se han guardado en las rutas `/datalake/clean` esperadas por el dashboard.

## Estructura principal

```text
smart-restaurant/
├── dashboard/       Aplicación Streamlit
├── data/            CSV de entrada y archivos relacionados con los datos
├── docker/          Docker Compose y configuración de Hadoop
│   ├── jupyter/     Imagen y dependencias de Jupyter
│   └── mlflow/      Imagen del servidor MLflow
├── monitorizacion/  Limpieza de lotes nuevos y métricas de drift (usado por el notebook 07)
├── notebooks/       Análisis y modelado
└── scripts/         Scripts auxiliares, incluida la ingesta a HDFS
```