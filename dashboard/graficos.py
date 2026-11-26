"""
graficos.py — Gráficas Plotly reutilizables con la identidad de Smart Restaurant (colores de estilo.py).

Cada función recibe datos YA preparados (agregados con pandas) y devuelve una figura; la página decide dónde ponerla.
Así las gráficas pesan poco aunque los datos tengan cientos de miles de filas.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go

import estilo

AZUL, NARANJA, GRIS, MELOCOTON = estilo.AZUL_PETROLEO, estilo.NARANJA, estilo.AZUL_GRISACEO, estilo.MELOCOTON
ROJO = "#C0392B"        # solo para alarmas
VERDE = "#6FA8A0"       # solo para «todo bien» (el mismo verde azulado de los notebooks)
ESCALA = [[0.0, "#FFFFFF"], [0.35, MELOCOTON], [0.7, NARANJA], [1.0, AZUL]]                      # de poco a mucho
ESCALA_DIV = [[0.0, AZUL], [0.5, "#FFFFFF"], [1.0, NARANJA]]                                      # negativo - 0 - positivo
COLOR_DECISION = {"mantener": VERDE, "vigilar": NARANJA, "reentrenar": ROJO}
COLOR_NIVEL = {"estable": VERDE, "vigilar": NARANJA, "alerta": ROJO}


def _base(fig: go.Figure, titulo: str = "", alto: int = 380) -> go.Figure:
    fig.update_layout(title=titulo, height=alto, margin=dict(t=90))
    return fig


def histograma(serie: pd.Series, titulo: str, etiqueta_x: str, bins: int = 50, color: str = AZUL, alto: int = 340) -> go.Figure:
    """Histograma preparado con numpy (solo viajan los tramos, no las filas)."""
    cuentas, bordes = np.histogram(serie.dropna(), bins=bins)
    centros = (bordes[:-1] + bordes[1:]) / 2
    fig = go.Figure(go.Bar(x=centros, y=cuentas, width=np.diff(bordes) * 0.95, marker_color=color,
                           hovertemplate=f"{etiqueta_x}: %{{x:.1f}}<br>pedidos: %{{y:,}}<extra></extra>"))
    fig.update_layout(xaxis_title=etiqueta_x, yaxis_title="nº de filas", bargap=0)
    return _base(fig, titulo, alto)


def histograma_doble(ref: pd.Series, nuevo: pd.Series, nombre_ref: str, nombre_nuevo: str, titulo: str,
                     etiqueta_x: str, bins: int = 30, alto: int = 340) -> go.Figure:
    """Dos distribuciones en % (no en filas, porque los lotes tienen tamaños distintos): entrenamiento frente a lote nuevo."""
    union = pd.concat([ref, nuevo]).dropna()
    bordes = np.histogram_bin_edges(union, bins=bins)
    centros = (bordes[:-1] + bordes[1:]) / 2
    fig = go.Figure()
    for serie, nombre, color in ((ref, nombre_ref, AZUL), (nuevo, nombre_nuevo, NARANJA)):
        cuentas, _ = np.histogram(serie.dropna(), bins=bordes)
        fig.add_bar(x=centros, y=cuentas / cuentas.sum() * 100, name=nombre, marker_color=color, opacity=0.7,
                    width=np.diff(bordes) * 0.95, hovertemplate=f"{nombre}<br>{etiqueta_x}: %{{x:.1f}}<br>%{{y:.1f}} %<extra></extra>")
    fig.update_layout(barmode="overlay", xaxis_title=etiqueta_x, yaxis_title="% de pedidos", bargap=0,
                      legend=dict(orientation="h", y=1.12))
    return _base(fig, titulo, alto)


def barras_categorias_doble(ref: pd.Series, nuevo: pd.Series, nombre_ref: str, nombre_nuevo: str, titulo: str, alto: int = 340) -> go.Figure:
    """% de cada categoría en el entrenamiento y en el lote nuevo."""
    cats = sorted(set(ref.astype(str)) | set(nuevo.astype(str)))
    fig = go.Figure()
    for serie, nombre, color in ((ref, nombre_ref, AZUL), (nuevo, nombre_nuevo, NARANJA)):
        pc = serie.astype(str).value_counts(normalize=True).reindex(cats).fillna(0) * 100
        fig.add_bar(x=cats, y=pc.values, name=nombre, marker_color=color, hovertemplate="%{x}: %{y:.1f} %<extra></extra>")
    fig.update_layout(barmode="group", yaxis_title="% de pedidos", legend=dict(orientation="h", y=1.12))
    return _base(fig, titulo, alto)


def linea_media(tabla: pd.DataFrame, x: str, y: str, n: str, titulo: str, etiqueta_x: str, etiqueta_y: str,
                banda: tuple[str, str] | None = None, alto: int = 340) -> go.Figure:
    """Tiempo medio según el valor de una variable. El tamaño del punto indica cuántos pedidos hay (más pedidos = más fiable)."""
    fig = go.Figure()
    if banda:
        fig.add_scatter(x=tabla[x], y=tabla[banda[1]], mode="lines", line=dict(width=0), showlegend=False, hoverinfo="skip")
        fig.add_scatter(x=tabla[x], y=tabla[banda[0]], mode="lines", line=dict(width=0), fill="tonexty",
                        fillcolor="rgba(242,140,56,0.18)", name="25 %-75 % de los pedidos", hoverinfo="skip")
    tam = 7 + 22 * np.sqrt(tabla[n] / tabla[n].max())
    fig.add_scatter(x=tabla[x], y=tabla[y], mode="lines+markers", name="media", line=dict(color=AZUL, width=2),
                    marker=dict(color=NARANJA, size=tam, line=dict(color=AZUL, width=1)), customdata=tabla[n],
                    hovertemplate=f"{etiqueta_x}: %{{x}}<br>{etiqueta_y}: %{{y:.1f}}<br>pedidos: %{{customdata:,}}<extra></extra>")
    fig.update_layout(xaxis_title=etiqueta_x, yaxis_title=etiqueta_y, legend=dict(orientation="h", y=1.12))
    return _base(fig, titulo, alto)


def mapa_calor(matriz: pd.DataFrame, titulo: str, etiqueta_x: str, etiqueta_y: str, etiqueta_z: str, decimales: int = 1,
               divergente: bool = False, alto: int = 400, texto: bool = True, zmin=None, zmax=None) -> go.Figure:
    """Mapa de calor: filas = eje y, columnas = eje x. `divergente` centra la escala en 0 (para correlaciones)."""
    fig = go.Figure(go.Heatmap(
        z=matriz.values, x=[str(c) for c in matriz.columns], y=[str(i) for i in matriz.index],
        colorscale=ESCALA_DIV if divergente else ESCALA, zmin=-1 if divergente else zmin, zmax=1 if divergente else zmax,
        zmid=0 if divergente else None, colorbar=dict(title=etiqueta_z),
        text=np.round(matriz.values, decimales) if texto else None, texttemplate=f"%{{text:.{decimales}f}}" if texto else None,
        hovertemplate=f"{etiqueta_x}: %{{x}}<br>{etiqueta_y}: %{{y}}<br>{etiqueta_z}: %{{z:.{decimales + 1}f}}<extra></extra>"))
    fig.update_layout(xaxis_title=etiqueta_x, yaxis_title=etiqueta_y, yaxis_autorange="reversed")
    return _base(fig, titulo, alto)


def barras_h(tabla: pd.DataFrame, x: str, y: str, titulo: str, etiqueta_x: str, colores=None, texto: str | None = None,
             alto: int = 360) -> go.Figure:
    """Barras horizontales ordenadas (la primera fila de la tabla queda arriba)."""
    fig = go.Figure(go.Bar(x=tabla[x], y=tabla[y], orientation="h", marker_color=colores or AZUL,
                           text=tabla[texto] if texto else None, textposition="outside"))
    # margen a la derecha (15 %) para que la etiqueta de la barra más larga no se recorte
    maximo = float(pd.to_numeric(tabla[x], errors="coerce").max() or 0)
    fig.update_layout(xaxis_title=etiqueta_x, yaxis_title=None, yaxis_autorange="reversed",
                      xaxis_range=[min(0, float(pd.to_numeric(tabla[x], errors="coerce").min() or 0)), maximo * 1.15 if maximo > 0 else 1])
    fig.update_traces(cliponaxis=False)
    return _base(fig, titulo, alto)


def barras(tabla: pd.DataFrame, x: str, y: str, titulo: str, etiqueta_y: str, colores=None, formato: str = ".2f", alto: int = 340) -> go.Figure:
    fig = go.Figure(go.Bar(x=tabla[x], y=tabla[y], marker_color=colores or AZUL, text=tabla[y], texttemplate=f"%{{text:{formato}}}",
                           textposition="outside"))
    fig.update_layout(yaxis_title=etiqueta_y, xaxis_title=None)
    return _base(fig, titulo, alto)
