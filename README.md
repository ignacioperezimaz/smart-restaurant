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

Crea una carpeta local en el equipo. 

Clona el repositorio o descarga el ZIP y extráelo en la carpeta local que has creado.

Abre PowerShell y cambia a la carpeta `docker` dentro del proyecto. Por ejemplo:

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

El script crea las zonas `/datalake/raw` y `/datalake/clean`, carga los dos CSV en `/datalake/raw` y comprueba que los tamaños coinciden con los originales. Para revisar el contenido cargado:

```powershell
docker exec namenode hdfs dfs -ls -R /datalake
```

El script crea la carpeta `clean`, pero no genera los Parquet limpios. Esos archivos se producen al ejecutar el proceso de limpieza correspondiente en los notebooks. El dashboard puede usar los CSV locales para algunas vistas; las vistas limpias necesitan que existan los Parquet que espera la aplicación.

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
├── notebooks/       Análisis y modelado
└── scripts/         Scripts auxiliares, incluida la carga a HDFS
```
