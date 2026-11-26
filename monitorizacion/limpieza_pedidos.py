"""
limpieza_pedidos.py
===================
La limpieza del notebook 02 (EDA de pedidos), convertida en UNA función reutilizable.

Para qué sirve: el segundo lote de datos (el del drift) tiene que pasar EXACTAMENTE por
la misma limpieza que el primero; si no, las diferencias que midamos podrían venir de
cómo limpiamos y no de que los datos hayan cambiado. Por eso aquí no se inventa nada
nuevo: cada paso corresponde a una celda del notebook 02 (se indica cuál).

Uso:
    from limpieza_pedidos import limpiar_pedidos
    df_limpio, resumen = limpiar_pedidos(df_raw)   # df_raw: CSV leído con dtype=str, keep_default_na=False

`resumen` cuenta cuántas filas se descartan en cada paso: también sirve para vigilar la
CALIDAD de los datos que llegan (si de pronto se descartan muchas más filas, algo ha cambiado).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# Columnas que el notebook 02 elimina (celdas 22, 24 y 26)
COLUMNAS_SIN_INFO = ["estado_captura", "temperatura_c", "mes"]
COLUMNAS_REDUNDANTES = ["comensales", "ocupacion_local", "es_hora_punta", "es_fin_de_semana",
                        "es_festivo", "evento_local", "franja"]
HORA_APERTURA, HORA_CIERRE = 10.0, 23.0     # los pedidos van de 10:00 a 22:59 (celda 38)


def _rellenar_fecha(f: pd.Series, hd: pd.Series) -> pd.Series:
    """Celda 34. Recupera una fecha vacía mirando la fila de arriba y la de abajo (el id crece con el tiempo)."""
    f = f.copy()
    ant, sig = f.ffill(), f.bfill()
    f = f.where(f.notna(), ant.where(ant == sig))          # misma fecha arriba y abajo -> esa fecha

    ok = f.notna() & hd.notna()                            # anclas: vecinos con fecha y hora conocidas
    f_ant, h_ant = f.where(ok).ffill(), hd.where(ok).ffill()
    f_sig, h_sig = f.where(ok).bfill(), hd.where(ok).bfill()
    pend = f.isna() & hd.notna() & f_ant.notna() & f_sig.notna()
    cabe_ant = hd >= h_ant
    cabe_sig = hd <= h_sig
    d_ant, d_sig = hd - h_ant, h_sig - hd
    usa_ant = pend & cabe_ant & (~cabe_sig | (d_ant <= d_sig))
    usa_sig = pend & cabe_sig & (~cabe_ant | (d_ant > d_sig))
    f = f.where(~usa_ant, f_ant)
    f = f.where(~usa_sig, f_sig)
    return f


def _rellenar_hora(hd: pd.Series, f: pd.Series) -> pd.Series:
    """Celda 34. Una hora vacía dentro del mismo día se estima con la media de las horas vecinas."""
    ant, sig = hd.ffill(), hd.bfill()
    mismo_dia = f.eq(f.ffill()) & f.eq(f.bfill())
    return hd.where(hd.notna(), ((ant + sig) / 2).where(mismo_dia & (ant <= sig)))


def limpiar_pedidos(df_raw: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Devuelve (pedidos limpios, resumen de lo descartado). No modifica df_raw."""
    resumen = {"filas_raw": len(df_raw)}
    df = df_raw.copy()

    # 1) Quitar columnas sin información o redundantes, y el id del local (celdas 22, 24, 26)
    df = df.drop(columns=COLUMNAS_SIN_INFO + COLUMNAS_REDUNDANTES + ["id_local"])

    # 2) Duplicados exactos: mismo id_pedido (celda 30)
    n0 = len(df)
    df = df.drop_duplicates(subset="id_pedido", keep="first").reset_index(drop=True)
    resumen["duplicados_eliminados"] = n0 - len(df)

    # 3) Tipos: enteros, decimales y tiempo '00:25' (HH:MM) -> 25 minutos (celda 32)
    for c in ["n_platos", "cola_pedidos", "cocineros_disponibles", "num_platos_complejos", "ingrediente_agotado"]:
        df[c] = pd.to_numeric(df[c].str.strip(), errors="coerce").astype("Int64")
    for c in ["complejidad_pedido", "precipitacion_mm"]:
        df[c] = pd.to_numeric(df[c].str.strip(), errors="coerce")
    t = df["tiempo_prep_minutos"].str.strip()
    es_hhmm = t.str.fullmatch(r"\d{1,2}:\d{2}")
    partes = t[es_hhmm].str.split(":", expand=True).astype(int)
    tiempo = pd.to_numeric(t.where(~es_hhmm), errors="coerce")
    tiempo[es_hhmm] = partes[0] * 60 + partes[1]
    df["tiempo_prep_minutos"] = tiempo
    for c in ["canal", "prioridad_aux"]:
        df[c] = df[c].astype("category")
    resumen["tiempo_en_hhmm_convertidos"] = int(es_hhmm.sum())

    # 4) Fecha (dos formatos), hora decimal y día de la semana (celda 34)
    fe = df["fecha"].str.strip()
    iso = fe.str.fullmatch(r"\d{4}-\d{2}-\d{2}")
    mdy = fe.str.fullmatch(r"\d{2}-\d{2}-\d{4}")
    fecha = pd.Series(pd.NaT, index=df.index, dtype="datetime64[ns]")
    fecha[iso] = pd.to_datetime(fe[iso], format="%Y-%m-%d")
    fecha[mdy] = pd.to_datetime(fe[mdy], format="%m-%d-%Y")
    resumen["fechas_en_formato_mdy"] = int(mdy.sum())

    h = pd.to_datetime(df["hora"].str.strip(), format="%H:%M:%S", errors="coerce")
    hora_dec = h.dt.hour + h.dt.minute / 60

    resumen["fechas_vacias_antes"] = int(fecha.isna().sum())
    resumen["horas_vacias_antes"] = int(hora_dec.isna().sum())
    fecha = _rellenar_fecha(fecha, hora_dec)
    hora_dec = _rellenar_hora(hora_dec, fecha).round(2)
    fecha = _rellenar_fecha(fecha, hora_dec)

    dia_texto = pd.to_numeric(df["dia_semana"].str.strip(), errors="coerce")       # manda la fecha, no el texto
    valido = dia_texto.between(1, 7)
    dia_fecha = fecha.dt.dayofweek + 1
    dia = dia_fecha.where(fecha.notna(), dia_texto.where(valido))
    resumen["dia_semana_invalido"] = int((~valido).sum())

    # Primer y último pedido del día: se usa el límite del día como segundo vecino (celda 38)
    vacia = hora_dec.isna() & fecha.notna()
    mismo_arriba = fecha.eq(fecha.shift(1))
    mismo_abajo = fecha.eq(fecha.shift(-1))
    ultimo = vacia & mismo_arriba & ~mismo_abajo
    primero = vacia & ~mismo_arriba & mismo_abajo
    hora_dec = hora_dec.where(~ultimo, (hora_dec.shift(1) + HORA_CIERRE) / 2)
    hora_dec = hora_dec.where(~primero, (HORA_APERTURA + hora_dec.shift(-1)) / 2)
    hora_dec = hora_dec.round(2)

    df["fecha"], df["hora_dec"], df["dia_semana"] = fecha, hora_dec, dia.astype("Int64")
    df = df.drop(columns="hora")

    # 5) Filas sin variables imprescindibles se eliminan; no se imputan (celdas 44, 47 y 53)
    n0 = len(df); df = df[df["n_platos"].notna()].reset_index(drop=True)
    resumen["sin_n_platos"] = n0 - len(df)
    n0 = len(df); df = df[df["tiempo_prep_minutos"].notna()].reset_index(drop=True)
    resumen["sin_tiempo"] = n0 - len(df)
    n0 = len(df); df = df.dropna(subset=["cola_pedidos", "cocineros_disponibles"]).reset_index(drop=True)
    resumen["sin_carga_cocina"] = n0 - len(df)

    # 6) Esquema final (celda 57): fecha DD-MM-AAAA, sin id, y el objetivo siempre la última columna
    df["fecha"] = df["fecha"].dt.strftime("%d-%m-%Y")
    df = df.drop(columns=["id_pedido"])
    df = df[[c for c in df.columns if c != "tiempo_prep_minutos"] + ["tiempo_prep_minutos"]]

    resumen["filas_limpias"] = len(df)
    resumen["pct_descartado"] = round(100 * (1 - len(df) / max(len(df_raw), 1)), 2)
    return df, resumen


def leer_raw(origen, **opciones) -> pd.DataFrame:
    """Lee un CSV de pedidos tal como lo hace el notebook 02 (todo texto, sin convertir vacíos a NaN)."""
    return pd.read_csv(origen, dtype=str, encoding="utf-8-sig", keep_default_na=False, **opciones)
