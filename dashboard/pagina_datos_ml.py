"""
Página "Datos para el ML": los datos que vamos a usar para entrenar los modelos.

Orden de la página:
  1. Objetivos de ML y qué datos alimenta cada uno.
  2. Las cuatro fuentes (muestras reales de los CSV, con sus errores).
  3. Calidad: errores inyectados a propósito (del manifiesto resumen_ensuciado.json).
  4. Drift: qué cambia entre el lote histórico y el de 2026 (calculado en vivo).
  5. Validación hecha al generar los datos y avisos sobre los datos sintéticos.
"""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from componentes import formato_decimal, formato_numero, tabla_marca, tarjeta
from datos import DATA_DIR, FUENTES, LOTES, cargar_manifiesto, indicadores_drift, muestras

# ---------------------------------------------------------------
# Constantes: paleta de marca y textos
# ---------------------------------------------------------------
AZUL_PETROLEO = "#1F3A44"
NARANJA = "#F28C38"
GRIS_OSCURO = "#162930"

NOMBRES_FUENTE = {
    "afluencia_diaria": "Afluencia diaria",
    "reservas": "Reservas",
    "rendimiento_platos": "Rendimiento de platos",
    "resenas": "Reseñas",
}

# Papel de cada fuente en el ML: qué se predice, con qué y qué hay que vigilar
ROLES = {
    "afluencia_diaria": {
        "objetivo": "**Objetivo 1 · regresión:** predecir `clientes_reales`, los clientes de un restaurante en un día.",
        "entradas": (
            "Calendario (`dia_semana`, `mes`, `temporada`, `festivo_simulado`, `evento_local_previsto`), "
            "clima previsto (`temperatura_prevista_c`, `lluvia_prevista_mm`), datos del restaurante "
            "(`tipo_restaurante`, `capacidad_asientos`, `horas_apertura_planificadas`) y, desde `reservas`, "
            "las reservas conocidas en `fecha_corte_prediccion`."
        ),
        "ojo": (
            "`clientes_con_reserva_reales` + `clientes_sin_reserva_reales` suman `clientes_reales`: "
            "no pueden usarse como entrada (fuga de información)."
        ),
    },
    "reservas": {
        "objetivo": (
            "**Objetivo 1 · clasificación:** predecir si la reserva se cumple. `estado_final` toma tres valores: "
            "`asistio`, `cancelada` y `no_show` (las dos últimas significan que no asistirá)."
        ),
        "entradas": (
            "`turno`, `hora_reserva`, `comensales`, `antelacion_dias`, `canal`, el día y el historial del cliente "
            "(`reservas_previas_cliente`, `cancelaciones_previas_cliente`, `no_shows_previos_cliente`)."
        ),
        "ojo": (
            "`id_cliente` es un identificador seudonimizado, no una entrada. El historial del cliente es la señal "
            "más fuerte: sin él, el AUC baja de 0,77 a 0,61."
        ),
    },
    "rendimiento_platos": {
        "objetivo": (
            "**Objetivo 2 · clustering:** agrupar los platos por popularidad (`unidades_vendidas`), "
            "precio (`precio_unitario_eur`), coste (`coste_unitario_eur`) y margen (`margen_contribucion_eur`)."
        ),
        "entradas": (
            "Cada fila es un restaurante, un día y un plato: para agrupar platos hay que agregar por `id_plato` "
            "(20 platos). `ofertado` indica si el plato se ofertó ese día."
        ),
        "ojo": "`ventas_netas_eur` y `coste_total_eur` se derivan de las columnas anteriores: no aportan información nueva.",
    },
    "resenas": {
        "objetivo": (
            "**Objetivo 2 · clasificación:** sentimiento de la reseña (negativa, neutra o positiva), "
            "derivado de `puntuacion`."
        ),
        "entradas": "`plataforma`, `id_plato`, `comentario` (texto libre) y las fechas de visita y de reseña.",
        "ojo": (
            "TheFork puntúa de 2 a 10 y las demás plataformas de 1 a 5: hay que reescalar. Los comentarios salen de "
            "plantillas, así que un clasificador de texto llega a F1 = 1,0, un resultado poco realista. Si el objetivo "
            "sale de `puntuacion`, esta no puede ser entrada."
        ),
    },
}

# Tipos de error inyectados: (clave en el manifiesto, nombre para mostrar)
TIPOS_ERROR = [
    ("nulos", "Nulos"),
    ("tipos", "Tipo erróneo"),
    ("incorrectos", "Valores incorrectos"),
    ("outliers", "Outliers"),
    ("formatos", "Formatos distintos"),
    ("clave_huerfana", "Claves huérfanas"),
    ("categorias", "Categorías mal escritas"),
    ("duplicado", "Duplicados"),
]


# ---------------------------------------------------------------
# Utilidades de formato y de gráficas
# ---------------------------------------------------------------
def estilo_figura(figura: go.Figure, titulo: str) -> go.Figure:
    """Aplica el estilo de marca a una gráfica: título en negrita, fondo claro, Montserrat."""
    figura.update_layout(
        title=dict(text=f"<b>{titulo}</b>", font=dict(color=AZUL_PETROLEO)),
        plot_bgcolor="white",
        paper_bgcolor="white",
        font=dict(family="Montserrat, Arial, sans-serif", color=GRIS_OSCURO, size=13),
        margin=dict(t=60, b=40, l=40, r=20),
    )
    return figura


def porcentaje(valor: float) -> str:
    """12.345 -> '12,3 %'."""
    return f"{formato_decimal(valor, 1)} %"


# ---------------------------------------------------------------
# Bloque 1: objetivos
# ---------------------------------------------------------------
def bloque_objetivos() -> None:
    st.markdown("## Del problema a los datos")
    st.write(
        "Tenemos **dos objetivos de ML**, y en cada uno una clasificación se encadena con el modelo principal: "
        "la salida del clasificador sirve de entrada al siguiente paso."
    )
    objetivos = pd.DataFrame(
        [
            ("1", "Regresión", "Clientes diarios de cada restaurante (`clientes_reales`)", "afluencia_diaria + reservas"),
            ("1 · encadenado", "Clasificación", "Si cada reserva se cumple o no (`estado_final`)", "reservas"),
            ("2", "Clustering", "Grupos de platos por popularidad, precio, coste y margen", "rendimiento_platos"),
            ("2 · encadenado", "Clasificación", "Sentimiento de la reseña: positiva, neutra o negativa", "resenas"),
        ],
        columns=["Objetivo", "Técnica", "Qué predecimos o agrupamos", "Fuentes"],
    )
    # Quitamos los acentos graves de las celdas: la tabla de marca muestra texto plano
    objetivos = objetivos.map(lambda texto: str(texto).replace("`", ""))
    tabla_marca(objetivos)


# ---------------------------------------------------------------
# Bloque 2: las cuatro fuentes
# ---------------------------------------------------------------
def bloque_fuentes(manifiesto: dict) -> None:
    st.markdown("## Las cuatro fuentes")

    # Tarjetas con el tamaño del conjunto, calculado desde el manifiesto
    total_filas = sum(a["filas_csv"] for a in manifiesto["archivos"].values())
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        tarjeta("Restaurantes", str(manifiesto["restaurantes"]["validos"]), "RST-0001 a RST-0024")
    with c2:
        tarjeta("Platos", str(manifiesto["platos"]), "carta común")
    with c3:
        tarjeta("Clientes", formato_numero(manifiesto["clientes"]["pool"]), "seudonimizados")
    with c4:
        tarjeta("Filas totales", formato_numero(total_filas), "8 CSV")
    st.write("")

    st.caption(
        "Una pestaña por fuente. Las tablas de muestra son filas reales de los CSV, tal como llegan a HDFS, "
        "con sus errores."
    )
    pestanas = st.tabs([NOMBRES_FUENTE[f] for f in FUENTES])
    for pestana, fuente in zip(pestanas, FUENTES):
        with pestana:
            dibujar_fuente(manifiesto, fuente)


def dibujar_fuente(manifiesto: dict, fuente: str) -> None:
    """Contenido de la pestaña de una fuente."""
    archivos = manifiesto["archivos"]
    hist = archivos[f"{fuente}_historico.csv"]
    drift = archivos[f"{fuente}_lote_drift.csv"]
    rol = ROLES[fuente]

    st.write(f"**{hist['descripcion']}.** Granularidad: {hist['granularidad']}. Clave primaria: `{hist['clave_primaria']}`.")
    st.write(
        f"{formato_numero(hist['filas_csv'])} filas en el histórico y {formato_numero(drift['filas_csv'])} "
        f"en el lote drift · {hist['n_columnas']} columnas."
    )

    # Papel de la fuente en el ML
    st.markdown(rol["objetivo"])
    st.markdown(f"**Entradas:** {rol['entradas']}")
    st.markdown(f"**Ojo:** {rol['ojo']}")

    with st.expander(f"Las {hist['n_columnas']} columnas"):
        st.code(", ".join(hist["columnas"]), language=None)

    # Muestras reales del CSV histórico
    resultado = muestras(f"{fuente}_historico.csv")
    if resultado is None:
        st.info(
            f"No encuentro los CSV en `{DATA_DIR}`. Para ver las muestras, ejecuta el dashboard con la "
            "carpeta del repositorio montada (comando `docker run` con `-v ...:/repo`)."
        )
        return
    primeras, con_error = resultado
    st.markdown("**Así llegan los datos (primeras filas del histórico)**")
    tabla_marca(primeras, ancha=True)
    st.markdown("**Ejemplos de filas con errores** (vacíos, marcadores `sin dato`, espacios, símbolo €, clave `RST-9999`)")
    tabla_marca(con_error, ancha=True)


# ---------------------------------------------------------------
# Bloque 3: calidad de los datos
# ---------------------------------------------------------------
def bloque_calidad(manifiesto: dict) -> None:
    st.markdown("## Calidad: datos ensuciados a propósito")
    st.write(
        "Los datos se ensucian a propósito con **8 tipos de error** para que la limpieza (Maitane, con pandas en "
        "Jupyter) tenga trabajo real. Hay además un error sistemático: las puntuaciones de TheFork van en escala 2–10."
    )

    archivos = manifiesto["archivos"]
    definiciones = manifiesto["definicion_errores"]

    # Total de cada tipo de error sumando los 8 archivos
    totales = {clave: sum(a.get(clave, 0) for a in archivos.values()) for clave, _ in TIPOS_ERROR}

    # Gráfica de barras horizontales: el tipo más frecuente arriba
    ordenados = sorted(TIPOS_ERROR, key=lambda t: totales[t[0]])
    figura = go.Figure(
        go.Bar(
            x=[totales[clave] for clave, _ in ordenados],
            y=[nombre for _, nombre in ordenados],
            orientation="h",
            marker_color=AZUL_PETROLEO,
            text=[formato_numero(totales[clave]) for clave, _ in ordenados],
            textposition="outside",
        )
    )
    estilo_figura(figura, "Errores inyectados por tipo (8 archivos)")
    figura.update_xaxes(gridcolor="#EAF2F4", title=None)
    figura.update_layout(margin=dict(t=60, b=30, l=10, r=60))
    st.plotly_chart(figura, width="stretch")

    # Tabla: qué significa cada tipo de error
    tabla_tipos = pd.DataFrame(
        [(nombre, definiciones[clave], formato_numero(totales[clave])) for clave, nombre in TIPOS_ERROR],
        columns=["Tipo de error", "Qué es", "Total"],
    )
    tabla_marca(tabla_tipos)

    # Tabla: resumen por archivo
    filas = []
    for nombre, info in archivos.items():
        originales = info["filas_originales"]
        con_error = info["filas_con_error_de_campo"]
        filas.append(
            (
                nombre,
                formato_numero(originales),
                formato_numero(info.get("duplicado", 0)),
                formato_numero(con_error),
                porcentaje(100 * con_error / originales),
            )
        )
    st.markdown("**Resumen por archivo**")
    tabla_marca(
        pd.DataFrame(
            filas,
            columns=["Archivo", "Filas originales", "Duplicados añadidos", "Filas con error de campo", "% sobre originales"],
        )
    )
    st.caption("Filas del CSV = filas originales + duplicados. Cada fila tiene como máximo un error aleatorio de campo.")


# ---------------------------------------------------------------
# Bloque 4: drift
# ---------------------------------------------------------------
def cambio(historico: float, drift: float, tipo: str, decimales: int) -> str:
    """Diferencia con signo: en puntos porcentuales (pp) o en la unidad del indicador."""
    diferencia = drift - historico
    signo = "+" if diferencia > 0 else "−"
    sufijo = " pp" if tipo == "pct" else ""
    return f"{signo}{formato_decimal(abs(diferencia), decimales)}{sufijo}"


def bloque_drift(manifiesto: dict) -> None:
    periodos = manifiesto["periodos"]
    st.markdown("## Drift: qué cambia entre lotes")
    st.write(
        f"El lote drift ({periodos['lote_drift']['desde']} a {periodos['lote_drift']['hasta']}) se genera con "
        "**data drift** y **concept drift**: cambian las entradas y también la relación con lo que queremos predecir. "
        "Sirve para estudiar cuánto se degradan los modelos entrenados con el histórico."
    )

    datos = indicadores_drift()
    if datos is None:
        st.info(
            f"Para calcular los indicadores necesito los CSV en `{DATA_DIR}`. "
            "Ejecuta el dashboard con la carpeta del repositorio montada."
        )
        return
    h, d = datos["historico"], datos["lote_drift"]

    # Dos cifras destacadas
    c1, c2 = st.columns(2)
    with c1:
        tarjeta("Reservas que no se cumplen", f"{porcentaje(h['fallan'])} → {porcentaje(d['fallan'])}", "cancelada + no_show")
    with c2:
        tarjeta("Reseñas positivas", f"{porcentaje(h['positiva'])} → {porcentaje(d['positiva'])}", "histórico → lote drift")
    st.write("")

    # Gráfica de los cuatro indicadores porcentuales
    etiquetas = ["Reservas que fallan", "Reservas por web", "Reseñas positivas", "Reseñas negativas"]
    claves = ["fallan", "web", "positiva", "negativa"]
    figura = go.Figure()
    for lote, color in (("historico", AZUL_PETROLEO), ("lote_drift", NARANJA)):
        valores = [datos[lote][c] for c in claves]
        figura.add_bar(
            name=LOTES[lote],
            x=etiquetas,
            y=valores,
            marker_color=color,
            text=[porcentaje(v) for v in valores],
            textposition="outside",
        )
    estilo_figura(figura, "Indicadores en porcentaje: histórico frente a lote drift")
    figura.update_layout(barmode="group", legend=dict(orientation="h", y=-0.15))
    figura.update_yaxes(gridcolor="#EAF2F4", title="%")
    st.plotly_chart(figura, width="stretch")

    # Tabla completa de indicadores: (nombre, clave, tipo, decimales, unidad)
    indicadores = [
        ("Reservas que no se cumplen (cancelada + no_show)", "fallan", "pct", 1, ""),
        ("Reservas hechas por web", "web", "pct", 1, ""),
        ("Reseñas positivas", "positiva", "pct", 1, ""),
        ("Reseñas negativas", "negativa", "pct", 1, ""),
        ("Clientes medios por restaurante y día", "clientes", "num", 1, ""),
        ("Temperatura media prevista", "temperatura", "num", 1, " °C"),
        ("Lluvia media prevista", "lluvia", "num", 2, " mm"),
        ("Coste sobre precio de los platos", "ratio", "pct", 1, ""),
        ("Unidades vendidas por plato y día", "unidades", "num", 2, ""),
    ]
    filas = []
    for nombre, clave, tipo, decimales, unidad in indicadores:
        if tipo == "pct":
            texto_h, texto_d = porcentaje(h[clave]), porcentaje(d[clave])
        else:
            texto_h = formato_decimal(h[clave], decimales) + unidad
            texto_d = formato_decimal(d[clave], decimales) + unidad
        filas.append((nombre, texto_h, texto_d, cambio(h[clave], d[clave], tipo, decimales)))
    tabla_marca(pd.DataFrame(filas, columns=["Indicador", "Histórico", "Lote drift", "Cambio"]))
    st.caption(
        "Calculado en vivo sobre los CSV. Se descartan duplicados y valores erróneos o extremos, se normalizan "
        "mayúsculas y espacios y la puntuación de TheFork se divide entre 2. Reseña positiva: 4–5; neutra: 3; "
        "negativa: 1–2. Los cambios de porcentajes van en puntos porcentuales (pp)."
    )


# ---------------------------------------------------------------
# Bloque 5: validación y avisos
# ---------------------------------------------------------------
def bloque_validacion() -> None:
    st.markdown("## ¿Hay señal para aprender?")
    st.write(
        "Al generar los datos se comprobó con modelos de prueba que existe señal que aprender. "
        "No son los modelos finales."
    )
    validacion = pd.DataFrame(
        [
            ("Clasificador de asistencia a reservas", "AUC 0,77 (0,61 sin el historial del cliente)"),
            ("Regresión de clientes: calendario + clima", "R² 0,64 · MAE 12,4"),
            ("+ reservas a la fecha de corte", "R² 0,83 · MAE 8,5"),
            ("+ asistencia esperada (la cadena)", "R² 0,86 · MAE 7,6"),
        ],
        columns=["Comprobación", "Resultado"],
    )
    tabla_marca(validacion)
    st.warning(
        "**Datos sintéticos.** Los resultados no demuestran nada sobre restaurantes reales. En las reseñas, un "
        "clasificador TF-IDF + regresión logística obtiene F1 = 1,0 porque los comentarios salen de plantillas: "
        "ese resultado no es realista y hay que decirlo en el informe."
    )


# ---------------------------------------------------------------
# Punto de entrada de la página
# ---------------------------------------------------------------
def mostrar() -> None:
    """Dibuja la página completa. La llama app.py."""
    st.title("Datos para el ML")
    st.write(
        "Estos son los datos con los que vamos a entrenar los modelos: de dónde salen, "
        "qué contienen, qué problemas traen y cómo cambian entre lotes."
    )

    manifiesto, _ = cargar_manifiesto()
    if manifiesto is None:
        st.error("No se encuentra el manifiesto `resumen_ensuciado.json` de la carpeta `data/`.")
        return

    bloque_objetivos()
    bloque_fuentes(manifiesto)
    bloque_calidad(manifiesto)
    bloque_drift(manifiesto)
    bloque_validacion()
