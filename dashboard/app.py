"""
Dashboard Smart Restaurant - Proyecto Final 1 (Big Data e IA)
Paso 2: identidad corporativa + estructura de navegación.
"""
from pathlib import Path

import streamlit as st

# Módulos propios: componentes visuales compartidos y una página por archivo
import pagina_arquitectura
import pagina_datos_ml
from componentes import tarjeta

# ---------------------------------------------------------------
# Rutas: todo se calcula respecto a este archivo, así funciona
# aunque ejecutes streamlit desde otra carpeta.
# ---------------------------------------------------------------
BASE_DIR = Path(__file__).parent
ASSETS = BASE_DIR / "assets"

# ---------------------------------------------------------------
# Configuración de la página (debe ser la PRIMERA llamada a st.*)
# El favicon de 32 px sale en la pestaña del navegador.
# ---------------------------------------------------------------
st.set_page_config(
    page_title="Smart Restaurant · Datos para ML",
    page_icon=str(ASSETS / "smart-restaurant_favicon_32.png"),
    layout="wide",
)

# ---------------------------------------------------------------
# Estilos: variables CSS con la paleta del SKILL y Montserrat.
# Se aplica la fuente a .stApp (no a todos los elementos) para no
# romper los iconos internos de Streamlit.
# ---------------------------------------------------------------
CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Montserrat:wght@400;600;700&display=swap');

:root {
    --azul-petroleo: #1F3A44;
    --naranja: #F28C38;
    --melocoton: #FFE0C2;
    --azul-claro: #EAF2F4;
    --blanco: #FFFFFF;
    --gris-oscuro: #162930;
    --font-main: 'Montserrat', Arial, sans-serif;
}

.stApp { font-family: var(--font-main); background-color: var(--azul-claro); }

/* H1 azul petróleo y H2 naranja, ambos en negrita (regla del SKILL) */
.stApp h1 { font-family: var(--font-main); color: var(--azul-petroleo); font-weight: 700; }
.stApp h2 { font-family: var(--font-main); color: var(--naranja); font-weight: 700; }
.stApp h3 { font-family: var(--font-main); color: var(--azul-petroleo); font-weight: 600; }

/* Barra lateral oscura: texto blanco para que contraste */
[data-testid="stSidebar"] { background-color: var(--azul-petroleo); }
[data-testid="stSidebar"] p,
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] span { color: var(--blanco); }

/* ---------- Menú de navegación: botones en lugar de radio ---------- */
/* Rótulo pequeño sobre el menú */
[data-testid="stSidebar"] .menu-titulo {
    color: var(--melocoton);
    font-size: 0.7rem;
    font-weight: 700;
    letter-spacing: 0.12em;
    margin: 1.2rem 0 0.4rem 0.4rem;
}

/* Base común de los botones del menú */
[data-testid="stSidebar"] [data-testid="stBaseButton-secondary"],
[data-testid="stSidebar"] [data-testid="stBaseButton-primary"] {
    justify-content: flex-start;
    border: none;
    border-radius: 10px;
    padding: 0.65rem 1rem;
    font-weight: 600;
    transition: background-color 0.15s ease;
}

/* Página no seleccionada: transparente con texto blanco */
[data-testid="stSidebar"] [data-testid="stBaseButton-secondary"] {
    background: transparent;
}
[data-testid="stSidebar"] [data-testid="stBaseButton-secondary"]:hover {
    background: rgba(255, 255, 255, 0.12);
}
[data-testid="stSidebar"] [data-testid="stBaseButton-secondary"]:hover p,
[data-testid="stSidebar"] [data-testid="stBaseButton-secondary"]:hover span {
    color: var(--melocoton);
}

/* Página activa: naranja de marca con texto azul petróleo */
[data-testid="stSidebar"] [data-testid="stBaseButton-primary"] {
    background: var(--naranja);
}
[data-testid="stSidebar"] [data-testid="stBaseButton-primary"] p,
[data-testid="stSidebar"] [data-testid="stBaseButton-primary"] span {
    color: var(--azul-petroleo);
}

/* Pie de la barra lateral */
[data-testid="stSidebar"] .pie {
    color: var(--melocoton);
    font-size: 0.72rem;
    margin-top: 2rem;
    padding-left: 0.4rem;
    opacity: 0.85;
}

/* Tarjeta blanca reutilizable para KPIs y bloques */
.card {
    background: var(--blanco);
    border-radius: 12px;
    padding: 20px 24px;
    border-left: 6px solid var(--naranja);
    box-shadow: 0 2px 8px rgba(31, 58, 68, 0.08);
}
.card .titulo { color: var(--azul-petroleo); font-weight: 600; font-size: 0.9rem; }
.card .valor  { color: var(--azul-petroleo); font-weight: 700; font-size: 2.2rem; }
.card .nota   { color: var(--gris-oscuro);  font-size: 0.8rem; }

/* Tabla de marca: cabecera azul petróleo con texto blanco; filas impares
   en melocotón y pares en blanco (regla del SKILL) */
.tabla-marca { width: 100%; border-collapse: collapse; font-size: 0.88rem; margin: 0.4rem 0 1rem 0; }
.tabla-marca th { background: var(--azul-petroleo); color: var(--blanco); text-align: left;
                  padding: 10px 14px; font-weight: 700; }
.tabla-marca td { padding: 9px 14px; color: var(--gris-oscuro); }
.tabla-marca tr.impar td { background: var(--melocoton); }
.tabla-marca tr.par td   { background: var(--blanco); }

/* Diagrama de flujo de datos: pasos en tarjetas unidos por flechas */
.flujo { display: flex; flex-wrap: wrap; align-items: stretch; gap: 8px; margin: 0.5rem 0 1.2rem 0; }
.flujo .paso { flex: 1 1 140px; background: var(--blanco); border-radius: 12px; padding: 14px 16px;
               border-top: 5px solid var(--azul-petroleo); box-shadow: 0 2px 8px rgba(31, 58, 68, 0.08); }
.flujo .paso.pendiente { background: var(--melocoton); border-top-color: var(--naranja); }
.flujo .paso .t { font-weight: 700; color: var(--azul-petroleo); font-size: 0.95rem; }
.flujo .paso .d { font-size: 0.78rem; color: var(--gris-oscuro); margin-top: 4px; }
.flujo .flecha { align-self: center; color: var(--naranja); font-weight: 700; font-size: 1.5rem; }

/* Tablas anchas: scroll horizontal y texto compacto */
.scroll-x { overflow-x: auto; }
.tabla-marca.ancha th, .tabla-marca.ancha td { white-space: nowrap; font-size: 0.78rem; }
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


# ---------------------------------------------------------------
# Barra lateral: logo negativo (fondo oscuro) + menú de navegación
# ---------------------------------------------------------------
# Páginas del dashboard y su icono (iconos Material integrados en Streamlit)
PAGINAS = {
    "Inicio": ":material/home:",
    "Arquitectura": ":material/account_tree:",
    "Datos para el ML": ":material/database:",
    "Simulación": ":material/science:",
}

# La página activa se guarda en session_state para que sobreviva a cada recarga
if "pagina" not in st.session_state:
    st.session_state.pagina = "Inicio"

st.sidebar.image(str(ASSETS / "smart-restaurant_negativo.png"), width="stretch")
st.sidebar.markdown('<p class="menu-titulo">MENÚ</p>', unsafe_allow_html=True)

for nombre, icono in PAGINAS.items():
    es_activa = st.session_state.pagina == nombre
    # type="primary" pinta el botón en naranja (página activa); "secondary" en transparente
    if st.sidebar.button(
        nombre,
        icon=icono,
        key=f"nav_{nombre}",
        type="primary" if es_activa else "secondary",
        width="stretch",
    ):
        st.session_state.pagina = nombre
        st.rerun()

st.sidebar.markdown(
    '<p class="pie">Proyecto Final 1 · Big Data e IA</p>', unsafe_allow_html=True
)

pagina = st.session_state.pagina


# ---------------------------------------------------------------
# Páginas (de momento solo la portada; el resto son marcadores)
# ---------------------------------------------------------------
def pagina_inicio() -> None:
    st.title("Smart Restaurant")
    st.markdown("## De los datos en bruto al modelo de Machine Learning")
    st.write(
        "Este panel muestra el entorno Big Data que hemos montado "
        "(Docker + Hadoop/HDFS) y los datos que usaremos para entrenar los modelos."
    )
    # Cifras reales del proyecto (4 tarjetas)
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        tarjeta("Restaurantes", "24", "RST-0001 a RST-0024")
    with c2:
        tarjeta("Archivos CSV en HDFS", "8", "4 fuentes × 2 lotes")
    with c3:
        tarjeta("Contenedores Docker", "5", "namenode, datanode, YARN ×2, Jupyter")
    with c4:
        tarjeta("Objetivos de ML", "2", "regresión + clustering, cada uno con una clasificación")
    st.write("")
    st.markdown("### Qué queremos predecir")
    st.write(
        "**Objetivo 1:** estimar los clientes diarios de cada restaurante, apoyándonos en si las reservas se cumplen. "
        "**Objetivo 2:** agrupar los platos por popularidad y margen, y clasificar el sentimiento de las reseñas."
    )


def pagina_pendiente(nombre: str) -> None:
    st.title(nombre)
    st.info("Esta sección se construye en los próximos pasos.")


if pagina == "Inicio":
    pagina_inicio()
elif pagina == "Arquitectura":
    pagina_arquitectura.mostrar()
elif pagina == "Datos para el ML":
    pagina_datos_ml.mostrar()
else:
    pagina_pendiente(pagina)
