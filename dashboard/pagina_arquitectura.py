"""
Página "Arquitectura": entorno Big Data (Docker + Hadoop/HDFS + Jupyter).

El contenido sale del resumen del trabajo del equipo. Las cifras de los
archivos se leen del manifiesto resumen_ensuciado.json (ver datos.py).
Al final hay una comprobación en vivo contra el namenode (WebHDFS, puerto
9870) que compara los tamaños reales con los del manifiesto. Si Docker no
está levantado, la página sigue funcionando con los datos documentados.
"""
import os

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

from componentes import formato_decimal, formato_numero, tabla_marca, tarjeta
from datos import cargar_manifiesto, tabla_archivos

# ---------------------------------------------------------------
# Constantes: paleta de marca y datos documentados
# ---------------------------------------------------------------
AZUL_PETROLEO = "#1F3A44"
NARANJA = "#F28C38"
GRIS_OSCURO = "#162930"

# API REST de HDFS (WebHDFS) y JMX del namenode, publicados por Docker en el puerto 9870.
# Si el dashboard corre dentro de un contenedor, "localhost" sería el propio contenedor:
# por eso la dirección se puede cambiar con la variable de entorno NAMENODE_URL
# (en Docker Desktop, http://host.docker.internal:9870 apunta al PC anfitrión).
NAMENODE = os.environ.get("NAMENODE_URL", "http://localhost:9870")
WEBHDFS = f"{NAMENODE}/webhdfs/v1"

# Servicios definidos en docker/docker-compose.yml
CONTENEDORES = pd.DataFrame(
    [
        ("namenode", "Índice de HDFS: sabe qué bloque está dónde", "9870 (clientes: 9000)"),
        ("datanode", "Guarda los bloques de datos", "9864"),
        ("resourcemanager", "YARN: reparte el cómputo", "8088"),
        ("nodemanager", "YARN: ejecuta las tareas", "8042"),
        ("jupyter", "Notebooks para la limpieza y el EDA (pandas, numpy, pyarrow)", "8889"),
    ],
    columns=["Contenedor", "Función", "Puerto web"],
)

# Carpeta de HDFS donde está cada lote
RUTA_LOTE = {"Histórico": "/datalake/raw/historico", "Lote drift": "/datalake/raw/lote_drift"}


# ---------------------------------------------------------------
# Bloques de la página
# ---------------------------------------------------------------
def bloque_flujo() -> None:
    """Diagrama del recorrido de los datos. Los pasos pendientes van en melocotón."""
    st.markdown(
        """
        <div class="flujo">
          <div class="paso"><div class="t">Generador</div>
            <div class="d">generar_datasets.py · datos sintéticos, semilla fija</div></div>
          <div class="flecha">→</div>
          <div class="paso"><div class="t">Docker + Hadoop</div>
            <div class="d">5 contenedores con Docker Compose</div></div>
          <div class="flecha">→</div>
          <div class="paso"><div class="t">HDFS · raw</div>
            <div class="d">CSV originales; cargar_hdfs.sh compara los bytes</div></div>
          <div class="flecha">→</div>
          <div class="paso pendiente"><div class="t">Limpieza y EDA</div>
            <div class="d">Pendiente · Jupyter + pandas (Maitane)</div></div>
          <div class="flecha">→</div>
          <div class="paso pendiente"><div class="t">HDFS · clean</div>
            <div class="d">Pendiente · datos limpios en Parquet</div></div>
          <div class="flecha">→</div>
          <div class="paso pendiente"><div class="t">Modelos de ML</div>
            <div class="d">Pendiente · regresión, clasificación, clustering</div></div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def bloque_docker() -> None:
    """Tabla de contenedores y decisiones de configuración."""
    st.markdown("## Entorno Docker")
    st.write(
        "Usamos **Docker Desktop (WSL2) con Docker Compose**: cualquiera del equipo "
        "levanta el mismo entorno con `docker compose up -d`. Hadoop usa las imágenes "
        "`bde2020/hadoop-*:2.0.0-hadoop3.2.1-java8`, y Jupyter, `scipy-notebook` con Python 3.11."
    )
    tabla_marca(CONTENEDORES)
    st.caption(
        "Verificado con `hdfs fsck` y con las webs de HDFS (puerto 9870) y de YARN (puerto 8088)."
    )


def bloque_hdfs() -> None:
    """Organización de carpetas en HDFS."""
    st.markdown("## Organización en HDFS")
    col_arbol, col_texto = st.columns([1, 1])
    with col_arbol:
        # st.code muestra el árbol en tipografía monoespaciada
        st.code(
            "/datalake\n"
            "├── raw\n"
            "│   ├── historico/    ← 4 CSV (2024-2025)\n"
            "│   └── lote_drift/   ← 4 CSV (2026, con drift)\n"
            "└── clean/            ← Parquet limpio (Maitane)",
            language=None,
        )
    with col_texto:
        st.write(
            "Separar **raw** y **clean** nos permite volver siempre al dato original "
            "si la limpieza sale mal. Los scripts vacían `raw` al recargar, pero nunca tocan `clean`."
        )
        st.write(
            "La carpeta `data/` se monta en el namenode en **solo lectura** (`/datos`) y "
            "`scripts/` en `/scripts`. Cada miembro del equipo tiene su propio HDFS; "
            "lo que se comparte es el repositorio."
        )


def bloque_datos_cargados() -> None:
    """KPIs, tabla y gráfica de los 8 archivos cargados (leídos del manifiesto)."""
    st.markdown("## Datos cargados en HDFS")

    manifiesto, origen = cargar_manifiesto()
    if manifiesto is None:
        st.error("No se encuentra el manifiesto `resumen_ensuciado.json` de la carpeta `data/`.")
        return
    archivos = tabla_archivos(manifiesto)

    periodos = manifiesto["periodos"]
    st.write(
        f"Datos sintéticos de **{manifiesto['restaurantes']['validos']} restaurantes** y "
        f"**{manifiesto['platos']} platos**, con {formato_numero(manifiesto['clientes']['pool'])} clientes "
        f"seudonimizados. El histórico cubre del {periodos['historico']['desde']} al "
        f"{periodos['historico']['hasta']} ({periodos['historico']['dias']} días) y el lote drift "
        f"del {periodos['lote_drift']['desde']} al {periodos['lote_drift']['hasta']} "
        f"({periodos['lote_drift']['dias']} días)."
    )

    # Totales calculados desde la tabla, para que nunca se desincronicen
    total_bytes = int(archivos["bytes"].sum())
    total_filas = int(archivos["filas"].sum())

    c1, c2, c3 = st.columns(3)
    with c1:
        tarjeta("Archivos CSV", str(len(archivos)), "4 fuentes × 2 lotes")
    with c2:
        tarjeta("Filas totales", formato_numero(total_filas), "histórico + lote drift")
    with c3:
        tarjeta("Tamaño total", f"{formato_decimal(total_bytes / 1e6)} MB", f"{formato_numero(total_bytes)} bytes")

    st.write("")  # separación vertical

    # Tabla: filas y bytes con puntos de millares
    tabla = archivos.copy()
    tabla["filas"] = tabla["filas"].map(formato_numero)
    tabla["bytes"] = tabla["bytes"].map(formato_numero)
    tabla.columns = ["Fuente", "Lote", "Archivo", "Filas", "Bytes"]
    tabla_marca(tabla)
    st.caption(
        f"Cifras del manifiesto `resumen_ensuciado.json` ({origen}). Las filas incluyen los duplicados "
        "inyectados a propósito. Para verificar HDFS usa la comprobación en vivo de más abajo."
    )

    # Gráfica: tamaño en MB por fuente, una serie por lote
    figura = go.Figure()
    for lote, color in (("Histórico", AZUL_PETROLEO), ("Lote drift", NARANJA)):
        parte = archivos[archivos["lote"] == lote]
        figura.add_bar(
            name=lote,
            x=parte["fuente"],
            y=parte["bytes"] / 1e6,
            marker_color=color,
            text=[formato_decimal(v / 1e6) for v in parte["bytes"]],
            textposition="outside",
        )
    figura.update_layout(
        title=dict(text="<b>Tamaño de cada fuente en HDFS (MB)</b>", font=dict(color=AZUL_PETROLEO)),
        barmode="group",
        plot_bgcolor="white",
        paper_bgcolor="white",
        font=dict(family="Montserrat, Arial, sans-serif", color=GRIS_OSCURO, size=13),
        yaxis=dict(title="MB", gridcolor="#EAF2F4"),
        xaxis=dict(title=None),
        legend=dict(orientation="h", y=-0.15),
        margin=dict(t=60, b=40, l=40, r=20),
    )
    st.plotly_chart(figura, width="stretch")


def consultar_hdfs() -> tuple[dict, list]:
    """
    Pregunta al namenode por el estado del sistema y por los archivos de cada lote.
    Devuelve (estado, archivos). Lanza requests.RequestException si no hay conexión.
    """
    # JMX: estado general del sistema de ficheros y datanodes activos
    jmx = requests.get(
        f"{NAMENODE}/jmx",
        params={"qry": "Hadoop:service=NameNode,name=FSNamesystemState"},
        timeout=3,
    )
    jmx.raise_for_status()
    estado = jmx.json()["beans"][0]

    # WebHDFS LISTSTATUS: lista cada carpeta (solo habla con el namenode)
    archivos = []
    for lote, ruta in RUTA_LOTE.items():
        r = requests.get(f"{WEBHDFS}{ruta}", params={"op": "LISTSTATUS"}, timeout=3)
        r.raise_for_status()
        for f in r.json()["FileStatuses"]["FileStatus"]:
            archivos.append((lote, f["pathSuffix"], int(f["length"])))
    return estado, archivos


def bloque_comprobacion() -> None:
    """Botón que consulta HDFS en vivo y compara con el manifiesto."""
    st.markdown("## Comprobación en vivo")
    st.write(
        "Consulta ahora mismo el namenode y compara el tamaño real de cada archivo "
        "con el del manifiesto."
    )

    if not st.button("Comprobar HDFS ahora", key="hdfs_check"):
        return

    manifiesto, _ = cargar_manifiesto()
    if manifiesto is None:
        st.error("No se encuentra el manifiesto con el que comparar.")
        return
    previstos = tabla_archivos(manifiesto)

    try:
        estado, archivos = consultar_hdfs()
    except (requests.RequestException, KeyError, ValueError):
        # Sin conexión o respuesta inesperada: no rompemos la página
        st.warning(
            "No se pudo conectar con HDFS. Comprueba que Docker está levantado "
            "(`docker compose up -d` en la carpeta `docker`). "
            "Mientras tanto, arriba tienes los datos documentados."
        )
        return

    # KPIs de estado
    c1, c2 = st.columns(2)
    with c1:
        tarjeta("Estado de HDFS", str(estado.get("FSState", "desconocido")), "namenode")
    with c2:
        tarjeta("Datanodes activos", str(estado.get("NumLiveDataNodes", "?")), "replicación = 1")
    st.write("")

    # Comparación archivo a archivo con el manifiesto
    esperado = dict(zip(previstos["archivo"], previstos["bytes"]))
    lote_de = dict(zip(previstos["archivo"], previstos["lote"]))
    filas = []
    encontrados = set()
    for lote, nombre, tamano in archivos:
        encontrados.add(nombre)
        previsto = esperado.get(nombre)
        if previsto is None:
            coincide = "No esperado (¿versión antigua?)"  # archivo que ya no forma parte del conjunto
        elif previsto == tamano:
            coincide = "Sí"
        else:
            coincide = "No (tamaño distinto)"
        filas.append((lote, nombre, formato_numero(tamano), coincide))
    # Archivos que deberían estar en HDFS y no aparecen
    for nombre in esperado:
        if nombre not in encontrados:
            filas.append((lote_de[nombre], nombre, "—", "Falta en HDFS"))
    tabla_marca(pd.DataFrame(filas, columns=["Lote", "Archivo en HDFS", "Bytes (en vivo)", "Coincide"]))

    if all(f[3] == "Sí" for f in filas):
        st.success(f"Los {len(esperado)} archivos están en HDFS y coinciden byte a byte con el manifiesto.")
    else:
        st.warning(
            f"HDFS no coincide del todo con los {len(esperado)} CSV actuales: revisa la columna «Coincide». "
            "Si faltan o sobran archivos, vuelve a cargarlos con `docker exec namenode bash /scripts/cargar_hdfs.sh`."
        )


def bloque_reproducir() -> None:
    """Pasos para regenerar y recargar los datos."""
    with st.expander("Cómo regenerar y recargar los datos"):
        st.write("Desde la carpeta del repositorio, con Docker en marcha:")
        st.code(
            "docker exec jupyter python /home/jovyan/work/data/generar_datasets.py\n"
            "docker exec namenode bash /scripts/cargar_hdfs.sh\n"
            "docker exec namenode hdfs dfs -ls -R /datalake/raw\n"
            "docker exec namenode hdfs dfs -du -h /datalake/raw",
            language="bash",
        )
        st.write(
            "`cargar_hdfs.sh` vacía primero la zona `raw` (no toca `clean`), sube los 8 CSV "
            "y compara los bytes de cada archivo con el original."
        )


def bloque_decisiones() -> None:
    """Decisiones de diseño y limitaciones, para mencionarlas en la presentación."""
    with st.expander("Decisiones de diseño y limitaciones"):
        st.markdown(
            """
**Decisiones**
- **Hive en lugar de MongoDB**, como opción secundaria: SQL sobre el Parquet limpio, comprobación de metadatos y visualización.
- **Limpieza con pandas y Jupyter**, no con Spark. El resultado se guarda en Parquet en `/datalake/clean`.
- `dfs.replication = 1` (un solo datanode), permisos de HDFS desactivados y WebHDFS activo.
- Memoria de YARN limitada a 4096 MB; volúmenes `namenode_data` y `datanode_data` para conservar los datos.
- Volumen limitado (24 restaurantes) por los límites de archivo de GitHub (aviso a 50 MB, bloqueo a 100 MB).
- `.gitattributes` fuerza saltos de línea LF en `*.sh`, `*.env` y `*.yml` para evitar fallos de Windows.

**Limitaciones (a mencionar en el informe)**
- Datos **sintéticos**: los resultados no demuestran nada sobre restaurantes reales.
- Un solo nodo: no es un clúster real, y sin permisos: válido para aprendizaje, no para producción.
- Imágenes `bde2020` antiguas (Hadoop 3.2.1, de 2021) y sin mantenimiento.
            """
        )


# ---------------------------------------------------------------
# Punto de entrada de la página
# ---------------------------------------------------------------
def mostrar() -> None:
    """Dibuja la página completa. La llama app.py."""
    st.title("Arquitectura Big Data")
    st.write(
        "Así viajan los datos desde el generador hasta HDFS, "
        "donde quedan listos para la limpieza y el Machine Learning."
    )
    st.markdown("## Flujo de datos")
    bloque_flujo()
    bloque_docker()
    bloque_hdfs()
    bloque_datos_cargados()
    bloque_comprobacion()
    bloque_reproducir()
    bloque_decisiones()
