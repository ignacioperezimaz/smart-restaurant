"""
Componentes visuales reutilizables del dashboard Smart Restaurant.

Aquí viven las piezas que se repiten en varias páginas (tarjetas KPI, tablas
con la identidad de marca y formato de números). Los estilos CSS asociados
(.card, .tabla-marca...) se definen una sola vez en app.py.
"""
import html

import pandas as pd
import streamlit as st


def formato_numero(n: int) -> str:
    """Formatea un entero con punto de millares, como en español: 1234567 -> 1.234.567."""
    return f"{int(n):,}".replace(",", ".")


def formato_decimal(x: float, decimales: int = 1) -> str:
    """Formatea un decimal a la española: 1234.5 -> 1.234,5 (coma decimal, punto de millares)."""
    texto = f"{x:,.{decimales}f}"
    # Intercambiamos separadores pasando por un marcador temporal
    return texto.replace(",", "§").replace(".", ",").replace("§", ".")


def tarjeta(titulo: str, valor: str, nota: str = "") -> None:
    """Dibuja una tarjeta KPI blanca con borde naranja."""
    st.markdown(
        f'<div class="card"><div class="titulo">{html.escape(titulo)}</div>'
        f'<div class="valor">{html.escape(valor)}</div>'
        f'<div class="nota">{html.escape(nota)}</div></div>',
        unsafe_allow_html=True,
    )


def tabla_marca(df: pd.DataFrame, ancha: bool = False) -> None:
    """
    Dibuja un DataFrame como tabla de marca:
    cabecera azul petróleo con texto blanco y filas alternas
    (primero melocotón, luego blanco), según el SKILL.

    Con ancha=True la tabla no parte el texto en varias líneas y se puede
    desplazar en horizontal: útil para muestras de CSV con muchas columnas.
    """
    # Cabecera: una celda <th> por columna
    cabecera = "".join(f"<th>{html.escape(str(c))}</th>" for c in df.columns)

    # Cuerpo: la clase "impar"/"par" decide el color de fondo de cada fila
    filas = ""
    for i, fila in enumerate(df.itertuples(index=False)):
        clase = "impar" if i % 2 == 0 else "par"
        celdas = "".join(f"<td>{html.escape(str(valor))}</td>" for valor in fila)
        filas += f'<tr class="{clase}">{celdas}</tr>'

    clase_tabla = "tabla-marca ancha" if ancha else "tabla-marca"
    tabla = (
        f'<table class="{clase_tabla}"><thead><tr>{cabecera}</tr></thead>'
        f"<tbody>{filas}</tbody></table>"
    )
    # Todo en una sola línea: así Markdown lo trata como un único bloque HTML
    if ancha:
        tabla = f'<div class="scroll-x">{tabla}</div>'
    st.markdown(tabla, unsafe_allow_html=True)
