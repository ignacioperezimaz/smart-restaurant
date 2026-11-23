"""
estilo.py — Identidad corporativa Smart Restaurant para el dashboard.

Paleta, tipografía (Montserrat), logos y plantilla de gráficas Plotly.
Uso en cada página:   import estilo ; estilo.configurar("Título de la página")
"""
from pathlib import Path

import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st
from PIL import Image

ASSETS = Path(__file__).resolve().parent / "assets"

# --- Paleta oficial ---------------------------------------------------------
AZUL_PETROLEO = "#1F3A44"   # títulos principales, cabeceras, marca
NARANJA = "#F28C38"         # acentos, énfasis, subtítulos
MELOCOTON = "#FFE0C2"       # resaltados suaves, filas impares de tablas
AZUL_CLARO = "#EAF2F4"      # fondo general, paneles
BLANCO = "#FFFFFF"          # tarjetas, filas pares
GRIS_TEXTO = "#162930"      # texto extenso
AZUL_GRISACEO = "#5C808E"   # 3.ª serie de las gráficas

# Orden de series en gráficas, según la guía
SERIES = [AZUL_PETROLEO, NARANJA, AZUL_GRISACEO, MELOCOTON]

_FUENTE = "'Montserrat', Arial, 'DejaVu Sans', sans-serif"

_CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Montserrat:wght@400;600;700&display=swap');

:root {{
  --azul-petroleo: {AZUL_PETROLEO};
  --naranja: {NARANJA};
  --melocoton: {MELOCOTON};
  --azul-claro: {AZUL_CLARO};
  --blanco: {BLANCO};
  --texto: {GRIS_TEXTO};
  --font-main: {_FUENTE};
}}

/* Tipografía: solo en elementos de texto (no en 'span', para no romper los iconos de Streamlit) */
.stApp, .stApp p, .stApp li, .stApp label, .stApp button, .stApp input,
.stApp h1, .stApp h2, .stApp h3, .stApp h4,
[data-testid="stMetricLabel"], [data-testid="stMetricValue"],
[data-testid="stCaptionContainer"], [data-testid="stWidgetLabel"] p {{
  font-family: var(--font-main) !important;
}}

/* Títulos: H1 azul petróleo, H2 y H3 naranja, todos en negrita */
.stApp h1 {{ color: var(--azul-petroleo) !important; font-weight: 700 !important; }}
.stApp h2, .stApp h3 {{ color: var(--naranja) !important; font-weight: 700 !important; }}

/* Tarjetas de métricas: fondo blanco y acento naranja */
[data-testid="stMetric"] {{
  background: var(--blanco);
  border-left: 6px solid var(--naranja);
  border-radius: 10px;
  padding: 0.9rem 1.1rem;
  box-shadow: 0 1px 3px rgba(31, 58, 68, 0.12);
}}
[data-testid="stMetricLabel"] {{ color: var(--azul-petroleo) !important; font-weight: 600 !important; }}
[data-testid="stMetricValue"] {{ color: var(--azul-petroleo) !important; font-weight: 700 !important; }}

/* Cifras de las tarjetas: más pequeñas y sin cortar con "..." */
[data-testid="stMetricValue"], [data-testid="stMetricValue"] * {{
  font-size: 1.75rem !important; line-height: 1.25 !important;
  white-space: normal !important; overflow: visible !important; text-overflow: clip !important;
}}

/* Fondo general azul claro y barra lateral blanca */
.stApp {{ background: var(--azul-claro); }}
[data-testid="stSidebar"] {{ background: var(--blanco); border-right: 1px solid rgba(31, 58, 68, 0.15); }}
[data-testid="stHeader"] {{ background: transparent; }}

/* Cabecera: tarjeta blanca con acento naranja */
[data-testid="stVerticalBlockBorderWrapper"] {{
  background: var(--blanco); border: none !important; border-left: 8px solid var(--naranja) !important;
  border-radius: 12px; box-shadow: 0 1px 4px rgba(31, 58, 68, 0.15);
}}

/* Pestañas */
button[data-baseweb="tab"] p {{ font-weight: 600 !important; font-size: 1rem !important; color: var(--azul-petroleo) !important; }}
button[data-baseweb="tab"][aria-selected="true"] p {{ color: var(--naranja) !important; }}

/* Iconos de Streamlit: siempre con su fuente de iconos, nunca con Montserrat */
[data-testid="stIconMaterial"], span[class*="material"] {{
  font-family: "Material Symbols Rounded", "Material Symbols Outlined" !important;
}}

/* Menú lateral: opción activa en melocotón con borde naranja */
[data-testid="stSidebarNavLink"] {{ border-radius: 8px; margin-bottom: 4px; }}
[data-testid="stSidebarNavLink"] span {{ font-weight: 600; color: var(--azul-petroleo); }}
[data-testid="stSidebarNavLink"][aria-current="page"] {{
  background: var(--melocoton); border-left: 5px solid var(--naranja);
}}
[data-testid="stSidebarNavLink"][aria-current="page"] span {{ font-weight: 700; }}

/* Bloque de código (árbol de HDFS): fondo azul petróleo, texto claro y detalles en naranja */
[data-testid="stCode"] pre, [data-testid="stCode"] code {{
  background: var(--azul-petroleo) !important; color: var(--azul-claro) !important;
  font-size: 1rem !important; line-height: 1.5 !important;
}}
[data-testid="stCode"] {{ border-radius: 12px; border-left: 8px solid var(--naranja); }}
</style>
"""


def _registrar_plantilla_plotly() -> None:
    """Plantilla Plotly con la paleta de la marca (títulos en negrita, fondos claros, sin adornos)."""
    pio.templates["smart_restaurant"] = go.layout.Template(
        layout=dict(
            colorway=SERIES,
            font=dict(family="Montserrat, Arial, DejaVu Sans, sans-serif", color=GRIS_TEXTO, size=14),
            title=dict(font=dict(size=18, color=AZUL_PETROLEO)),
            paper_bgcolor=BLANCO,
            plot_bgcolor=BLANCO,
            xaxis=dict(gridcolor=AZUL_CLARO, linecolor=AZUL_PETROLEO),
            yaxis=dict(gridcolor=AZUL_CLARO, linecolor=AZUL_PETROLEO),
            margin=dict(t=60, r=20, b=40, l=50),
        )
    )
    pio.templates.default = "smart_restaurant"


def configurar(titulo_pestana: str = "Smart Restaurant") -> None:
    """Llamar al principio de la página (antes de cualquier otro st.*)."""
    st.set_page_config(
        page_title=titulo_pestana,
        page_icon=Image.open(ASSETS / "smart-restaurant_favicon_32.png"),  # favicon de navegador
        layout="wide",
    )
    # Logo a color (positivo) para barras claras; icono compacto cuando la barra está plegada
    st.logo(
        str(ASSETS / "smart-restaurant_positivo.png"),
        icon_image=str(ASSETS / "smart-restaurant_favicon_256.png"),
        size="large",
    )
    st.markdown(_CSS, unsafe_allow_html=True)
    _registrar_plantilla_plotly()
