"""
generar_pedidos_realistas.py
============================
Regenera 02_pedidos_tiempos_preparacion.csv (OBJETIVO 2: regresión del tiempo
de preparación de un pedido) con una demanda realista.

Qué cambia respecto al CSV anterior
-----------------------------------
1. `id_pedido` crece con el tiempo: se asigna DESPUÉS de ordenar todos los
   pedidos por fecha y hora reales (PED-0000001 es el primero de 2023-01-01).
   El orden se fija antes del ensuciado, así que una fila con la fecha vacía
   o en otro formato conserva su posición y se puede reconstruir al limpiar.
2. La demanda depende del calendario:
   - el restaurante CIERRA LOS LUNES (no hay pedidos; con CERRAR_LUNES_FESTIVOS
     = False abriría los lunes festivos);
   - fin de semana: más pedidos (sábado x1,45; domingo x1,50);
   - festivos de Donostia (Euskadi + locales 20-ene y 31-jul): como mínimo x1,40;
   - eventos locales: Tamborrada, Semana Grande y Navidad (fechas aproximadas);
   - horas punta: comida (13:00-15:00) y cena (20:30-22:30), con un valle por
     la tarde; el fin de semana los picos son más altos y duran más.
3. La carga de cocina sale de esa demanda: en hora punta hay más pedidos
   pendientes (`pedido_pendiente`) y se refuerza el personal solo en parte
   (`cocineros_disponibles`), así que la cocina se satura y el tiempo sube.
4. Columnas nuevas que pueden influir en el tiempo de preparación (se conocen
   antes de cocinar, no hay fuga de información): es_fin_de_semana,
   es_festivo, franja, es_hora_punta, mes, ocupacion_local, comensales,
   num_platos_complejos, temperatura_c, precipitacion_mm, evento_local e
   ingrediente_agotado.
5. Se mantiene el mismo ensuciado del CSV anterior (vacíos, dia_semana
   inválido, fechas MM-DD-AAAA, tiempo en HH:MM y 600 duplicados exactos).

`complejidad_pedido` se calcula como en generar_complejidad_pedidos.py (media
de `dificultad_elaboracion` de la carta). NO hay que ejecutar ese script
después de este: volvería a sortear la columna y rompería su relación con el
tiempo de preparación.

El clima está SIMULADO (climatología aproximada de Donostia, igual para todos
los locales). Es un dato sintético: sirve para practicar, no demuestra nada
sobre restaurantes reales.

Reproducible (semilla fija).

Uso (desde la raíz del repo):
  python data/generar_pedidos_realistas.py
  python data/generar_pedidos_realistas.py --entrada data --salida data/ampliado
"""
import argparse
import csv
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

# Reutilizamos la lectura y la dificultad por plato del script de complejidad
sys.path.insert(0, str(Path(__file__).resolve().parent))
from generar_complejidad_pedidos import dificultad_por_plato, leer  # noqa: E402

# ----------------------------------------------------------------------------
# Parámetros
# ----------------------------------------------------------------------------
SEMILLA = 20261119
N_PEDIDOS = 115_000          # pedidos distintos (aprox., sale de un Poisson)
N_DUPLICADOS = 600           # copias exactas que se añaden al final (ensuciado)
FECHA_INI, FECHA_FIN = date(2023, 1, 1), date(2025, 12, 31)
N_LOCALES = 12
MAX_PLATOS = 8
UMBRAL_COMPLEJO = 7          # un plato con dificultad >= 7 cuenta como complejo
ARCHIVO_PEDIDOS = "02_pedidos_tiempos_preparacion.csv"
ARCHIVO_CARTA = "03_carta_platos.csv"

# Factor de demanda por día de la semana (1 = lunes ... 7 = domingo)
FACTOR_DIA = np.array([0.0, 0.0, 0.85, 0.90, 0.95, 1.15, 1.45, 1.50])  # lunes cerrado
FACTOR_FESTIVO_MIN = 1.40    # un festivo vende al menos como un domingo flojo
CERRAR_LUNES_FESTIVOS = True  # True: cierra TODOS los lunes; False: abre si es festivo

# Peso relativo de cada hora (10:00 ... 22:00) en un día laborable y en un
# fin de semana / festivo. Dos picos: comida (13-15) y cena (20-22).
HORAS = np.arange(10, 23)
PESO_LABORABLE = np.array([0.15, 0.35, 0.90, 2.60, 3.00, 1.40, 0.45,
                           0.40, 0.60, 1.10, 2.20, 2.60, 1.00])
PESO_FINDE = np.array([0.20, 0.50, 1.20, 3.00, 3.60, 2.20, 0.70,
                       0.50, 0.70, 1.30, 2.80, 3.40, 1.60])

# Intercepto del modelo del tiempo, calibrado para que la media global quede
# cerca de la del CSV anterior (25,4 min)
INTERCEPTO_TIEMPO = 4.9

COLUMNAS_ORIGINALES = [
    "id_pedido", "fecha", "hora", "dia_semana", "n_platos", "complejidad_pedido",
    "pedido_pendiente", "cocineros_disponibles", "tiempo_prep_min", "canal",
    "prioridad_aux", "id_local", "estado_captura",
]
COLUMNAS_NUEVAS = [
    "es_fin_de_semana", "es_festivo", "franja", "es_hora_punta", "mes",
    "ocupacion_local", "comensales", "num_platos_complejos", "temperatura_c",
    "precipitacion_mm", "evento_local", "ingrediente_agotado",
]


# ----------------------------------------------------------------------------
# Calendario: festivos, eventos, clima y factor de demanda por día
# ----------------------------------------------------------------------------
# Festivos de Donostia / San Sebastián (calendario laboral oficial).
# - Euskadi: decretos 56/2022 (2023), 71/2023 (2024) y 49/2024 (2025), BOPV.
#   Un festivo que cae en domingo no se lista en el decreto (por eso en 2024
#   falta el 8-dic y en 2025 el 12-oct); el 1-ene se incluye siempre.
# - Locales de Donostia: 20-ene (San Sebastián) y 31-jul (San Ignacio, festivo
#   en todo Gipuzkoa; confirmado en la resolución de 2025 y supuesto en 2023-24).
FESTIVOS_DONOSTIA = {
    2023: [(1, 1), (1, 6), (4, 6), (4, 7), (4, 10), (5, 1), (7, 25), (8, 15),
           (10, 12), (11, 1), (12, 6), (12, 8), (12, 25)],
    2024: [(1, 1), (1, 6), (3, 28), (3, 29), (4, 1), (5, 1), (7, 25), (8, 15),
           (10, 12), (11, 1), (12, 6), (12, 25)],
    2025: [(1, 1), (1, 6), (4, 17), (4, 18), (4, 21), (5, 1), (7, 25), (8, 15),
           (11, 1), (12, 6), (12, 8), (12, 25)],
}
LOCALES_DONOSTIA = [(1, 20), (7, 31)]
FESTIVOS = {date(a, m, d) for a, lista in FESTIVOS_DONOSTIA.items()
            for m, d in lista + LOCALES_DONOSTIA}


def construir_calendario(rng: np.random.Generator) -> pd.DataFrame:
    """Una fila por día con calendario, clima simulado y factor de demanda."""
    cal = pd.DataFrame({"fecha": pd.date_range(FECHA_INI, FECHA_FIN, freq="D")})
    f = cal["fecha"]
    cal["dia_semana"] = f.dt.dayofweek + 1            # 1 = lunes ... 7 = domingo
    cal["mes"] = f.dt.month
    cal["es_festivo"] = f.dt.date.isin(FESTIVOS).astype(int)
    cal["es_fin_de_semana"] = (cal["dia_semana"] >= 6).astype(int)

    # Eventos locales (fechas aproximadas) y su efecto en la demanda
    cal["evento_local"] = "ninguno"
    cal["factor_evento"] = 1.0
    eventos = [
        ("tamborrada", (f.dt.month == 1) & (f.dt.day == 20), 1.25),
        ("semana_grande", (f.dt.month == 8) & f.dt.day.between(10, 16), 1.30),
        ("navidad", (f.dt.month == 12) & f.dt.day.between(22, 30), 1.15),
    ]
    for nombre, mascara, factor in eventos:
        cal.loc[mascara, "evento_local"] = nombre
        cal.loc[mascara, "factor_evento"] = factor

    # Clima simulado: temperatura estacional y lluvia más frecuente en invierno
    doy = f.dt.dayofyear.to_numpy()
    cal["temperatura_c"] = np.round(
        14.5 - 6.5 * np.cos(2 * np.pi * (doy - 20) / 365) + rng.normal(0, 2.5, len(cal)), 1)
    p_lluvia = 0.38 + 0.12 * np.cos(2 * np.pi * (doy - 15) / 365)
    llueve = rng.random(len(cal)) < p_lluvia
    cal["precipitacion_mm"] = np.where(
        llueve, np.round(rng.exponential(6.0, len(cal)) + 0.2, 1), 0.0)

    # Factor de demanda del día = día de la semana (o festivo) x evento x
    # verano x tendencia suave de crecimiento (+3 % al año)
    factor = FACTOR_DIA[cal["dia_semana"].to_numpy()]
    factor = np.where(cal["es_festivo"] == 1, np.maximum(factor, FACTOR_FESTIVO_MIN), factor)
    cierra = (cal["dia_semana"] == 1) & ((cal["es_festivo"] == 0) | CERRAR_LUNES_FESTIVOS)
    factor = np.where(cierra, 0.0, factor)             # lunes: sin pedidos
    verano = np.where(cal["mes"].isin([7, 8]), 1.10, 1.0)
    tendencia = 1 + 0.03 * (f.dt.year.to_numpy() - FECHA_INI.year)
    cal["factor_dia"] = factor * cal["factor_evento"] * verano * tendencia
    return cal


# ----------------------------------------------------------------------------
# Generación de los pedidos (valores reales, sin ensuciar)
# ----------------------------------------------------------------------------
def generar_pedidos(cal: pd.DataFrame, dificultades: np.ndarray,
                    rng: np.random.Generator) -> pd.DataFrame:
    # --- 1. Cuántos pedidos hay en cada local y día (Poisson) ----------------
    tam_local = rng.uniform(0.7, 1.3, N_LOCALES)       # locales grandes y pequeños
    mu0 = N_PEDIDOS / (tam_local.sum() * cal["factor_dia"].sum())
    cuentas = rng.poisson(mu0 * tam_local[None, :] * cal["factor_dia"].to_numpy()[:, None])
    pares = np.repeat(np.arange(cuentas.size), cuentas.ravel())
    dia_idx, local_idx = pares // N_LOCALES, pares % N_LOCALES
    n = len(pares)

    # --- 2. Hora de cada pedido según el perfil del día ----------------------
    finde = ((cal["es_fin_de_semana"] == 1) | (cal["es_festivo"] == 1)).to_numpy()[dia_idx]
    hora = np.empty(n, dtype=int)
    for es_finde, pesos in ((True, PESO_FINDE), (False, PESO_LABORABLE)):
        m = finde == es_finde
        hora[m] = rng.choice(HORAS, size=m.sum(), p=pesos / pesos.sum())
    minuto = rng.integers(0, 60, n)

    # --- 3. Orden cronológico (día, hora, minuto; empates al azar) -----------
    orden = np.lexsort((rng.random(n), hora * 60 + minuto, dia_idx))
    dia_idx, local_idx, hora, minuto, finde = (
        a[orden] for a in (dia_idx, local_idx, hora, minuto, finde))
    h_dec = hora + minuto / 60

    # --- 4. Variables de calendario y franja ---------------------------------
    c = cal.iloc[dia_idx].reset_index(drop=True)
    comida_punta = (h_dec >= 13) & (h_dec < 15)
    cena_punta = (h_dec >= 20.5) & (h_dec < 22.5)
    es_punta = comida_punta | cena_punta
    franja = np.select([h_dec < 12, h_dec < 16, h_dec < 19.5],
                       ["manana", "comida", "tarde"], default="cena")
    lluvia = c["precipitacion_mm"].to_numpy() > 1.0

    # --- 5. Ocupación del local: perfil horario x día x ruido ----------------
    perfil = np.where(finde, np.interp(h_dec, HORAS + 0.5, PESO_FINDE) / 3.6,
                      np.interp(h_dec, HORAS + 0.5, PESO_LABORABLE) / 3.6)
    dia_norm = np.clip(c["factor_dia"].to_numpy() / 1.5, 0, 1.4)
    ocupacion = np.clip(perfil * dia_norm * rng.lognormal(0, 0.12, n), 0, 1.3)

    # --- 6. Cocina: pedidos pendientes y personal -----------------------------
    pendiente = np.clip(rng.poisson(0.5 + 14 * ocupacion), 0, 20)
    base = np.round(2 + 3 * (tam_local - 0.7) / 0.6)[local_idx]   # 2..5 cocineros
    cocineros = base + es_punta + (es_punta & finde) - (rng.random(n) < 0.08)
    cocineros = np.clip(cocineros, 1, 8).astype(int)

    # --- 7. El pedido: comensales, platos y complejidad ----------------------
    lam = 0.8 + 0.7 * finde + 0.5 * es_punta + 0.3 * lluvia
    comensales = np.clip(1 + rng.poisson(lam), 1, MAX_PLATOS)
    n_platos = np.clip(comensales + rng.poisson(0.9, n), 1, MAX_PLATOS)
    elegidos = dificultades[rng.integers(0, len(dificultades), size=(n, MAX_PLATOS))]
    cuenta = np.arange(MAX_PLATOS)[None, :] < n_platos[:, None]
    complejidad = (elegidos * cuenta).sum(axis=1) / n_platos
    n_complejos = ((elegidos >= UMBRAL_COMPLEJO) & cuenta).sum(axis=1)

    # --- 8. Canal, prioridad e ingrediente agotado ----------------------------
    p_del = np.clip(0.20 + 0.08 * (franja == "cena") + 0.05 * finde + 0.08 * lluvia, 0, 0.6)
    p_tak = 0.22 - 0.05 * (finde & es_punta)
    u = rng.random(n)
    canal = np.where(u < p_del, "delivery", np.where(u < p_del + p_tak, "takeaway", "mesa"))
    prioridad = rng.choice(["normal", "prioridad", "VIP"], size=n, p=[0.75, 0.18, 0.07])
    agotado = (rng.random(n) < 0.02 + 0.03 * (es_punta & finde)).astype(int)

    # --- 9. Tiempo de preparación (variable objetivo) -------------------------
    carga = pendiente / cocineros                       # pedidos por cocinero
    tiempo = (INTERCEPTO_TIEMPO
              + 1.9 * n_platos + 1.2 * complejidad + 0.9 * n_complejos
              + 3.2 * carga + 0.5 * carga ** 2          # la cocina se satura
              + np.select([canal == "delivery", canal == "takeaway"], [3.0, 1.2], 0.0)
              + 1.5 * ((canal == "delivery") & lluvia)
              + np.select([prioridad == "VIP", prioridad == "prioridad"], [-4.0, -2.5], 0.0)
              + 3.5 * agotado)
    tiempo = tiempo * rng.lognormal(0, 0.08, n) + rng.normal(0, 1.2, n)
    tiempo = np.round(np.clip(tiempo, 2, 60), 1)

    return pd.DataFrame({
        "fecha": c["fecha"], "hora": [f"{h:02d}:{m:02d}:00" for h, m in zip(hora, minuto)],
        "dia_semana": c["dia_semana"], "n_platos": n_platos, "complejidad_pedido": complejidad,
        "pedido_pendiente": pendiente, "cocineros_disponibles": cocineros,
        "tiempo_prep_min": tiempo, "canal": canal, "prioridad_aux": prioridad,
        "id_local": local_idx + 1, "estado_captura": "registrado",
        "es_fin_de_semana": c["es_fin_de_semana"], "es_festivo": c["es_festivo"],
        "franja": franja, "es_hora_punta": es_punta.astype(int), "mes": c["mes"],
        "ocupacion_local": np.round(ocupacion, 2), "comensales": comensales,
        "num_platos_complejos": n_complejos, "temperatura_c": c["temperatura_c"],
        "precipitacion_mm": c["precipitacion_mm"], "evento_local": c["evento_local"],
        "ingrediente_agotado": agotado,
    })


# ----------------------------------------------------------------------------
# Ensuciado (mismos problemas que el CSV anterior)
# ----------------------------------------------------------------------------
def ensuciar(real: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """Devuelve el RAW en texto: ID ya asignado por orden cronológico, con
    vacíos, formatos mezclados, valores inválidos y duplicados exactos."""
    n = len(real)
    df = pd.DataFrame(index=real.index)
    df["id_pedido"] = [f"PED-{i:07d}" for i in range(1, n + 1)]    # orden = fecha y hora
    df["fecha"] = real["fecha"].dt.strftime("%Y-%m-%d")
    df["hora"] = real["hora"]
    df["dia_semana"] = real["dia_semana"].astype(str)
    df["n_platos"] = real["n_platos"].astype(str)
    df["complejidad_pedido"] = real["complejidad_pedido"].map("{:.2f}".format)
    df["pedido_pendiente"] = real["pedido_pendiente"].astype(str)
    df["cocineros_disponibles"] = real["cocineros_disponibles"].astype(str)
    df["tiempo_prep_min"] = real["tiempo_prep_min"].map("{:.1f}".format)
    for col in ("canal", "prioridad_aux", "estado_captura"):
        df[col] = real[col]
    df["id_local"] = real["id_local"].astype(str)

    def azar(tasa):                                     # máscara aleatoria
        return rng.random(n) < tasa

    # Formatos mezclados
    m = azar(0.0151)                                    # fecha MM-DD-AAAA
    df.loc[m, "fecha"] = real.loc[m, "fecha"].dt.strftime("%m-%d-%Y")
    m = azar(0.0082)                                    # tiempo en HH:MM ('00:25')
    t = real.loc[m, "tiempo_prep_min"].astype(int)
    df.loc[m, "tiempo_prep_min"] = [f"{x // 60:02d}:{x % 60:02d}" for x in t]
    m = azar(0.0098)                                    # día de la semana inválido
    df.loc[m, "dia_semana"] = rng.choice(["0", "8", "lunes"], size=m.sum(), p=[0.37, 0.34, 0.29])

    # Vacíos (~0,43 % por columna)
    for col in ("fecha", "hora", "dia_semana", "n_platos", "pedido_pendiente",
                "cocineros_disponibles", "tiempo_prep_min"):
        df.loc[azar(0.0043), col] = ""
    # La complejidad se calcula a partir de n_platos: si falta, no se puede calcular
    df.loc[df["n_platos"] == "", "complejidad_pedido"] = ""

    # Duplicados exactos: copia pegada justo debajo de la fila original
    repeticiones = np.ones(n, dtype=int)
    repeticiones[rng.choice(n, size=N_DUPLICADOS, replace=False)] = 2
    df = df.iloc[np.repeat(np.arange(n), repeticiones)]

    # Columnas nuevas (limpias: se calculan de los valores reales)
    nuevas = real[COLUMNAS_NUEVAS].iloc[np.repeat(np.arange(n), repeticiones)]
    return pd.concat([df[COLUMNAS_ORIGINALES], nuevas], axis=1)


# ----------------------------------------------------------------------------
# Comprobaciones rápidas (se imprimen al ejecutar)
# ----------------------------------------------------------------------------
def informe(real: pd.DataFrame, raw: pd.DataFrame) -> None:
    f = real["fecha"]
    print(f"\nPedidos distintos: {len(real):,} | filas con duplicados: {len(raw):,}")
    fh = pd.to_datetime(f.dt.strftime("%Y-%m-%d") + " " + real["hora"])
    print("ID ordenado por fecha y hora:", bool(fh.is_monotonic_increasing))
    print("Pedidos en lunes:", int((real["dia_semana"] == 1).sum()),
          "| festivos distintos con pedidos:", real.loc[real["es_festivo"] == 1, "fecha"].nunique())

    dia = real.groupby(real["fecha"])["id_local"].size()
    dsem = dia.groupby(dia.index.dayofweek + 1).mean().round(1)
    print("\nPedidos por día (media) según día de la semana (1=lun ... 7=dom):")
    print(dsem.to_string())
    lab = dia[(dia.index.dayofweek < 5)].mean()
    fin = dia[(dia.index.dayofweek >= 5)].mean()
    print(f"Fin de semana / laborable: x{fin / lab:.2f}")
    fest = real.loc[real["es_festivo"] == 1].groupby("fecha").size().mean()
    print(f"Festivo entre semana: {real.loc[(real['es_festivo'] == 1) & (real['dia_semana'] < 6)].groupby('fecha').size().mean():.1f}"
          f" pedidos/día (festivos en total: {fest:.1f})")

    print("\n% de pedidos por franja y hora punta:")
    print((real["franja"].value_counts(normalize=True) * 100).round(1).to_string())
    print(f"Hora punta: {real['es_hora_punta'].mean() * 100:.1f} % de los pedidos")

    t = real["tiempo_prep_min"]
    print(f"\nTiempo de preparación: media {t.mean():.1f} | desv. {t.std():.1f} | "
          f"min {t.min():.1f} | max {t.max():.1f}")
    print("Tiempo medio según hora punta / fin de semana:")
    print(real.groupby(["es_hora_punta", "es_fin_de_semana"])["tiempo_prep_min"]
          .mean().round(1).unstack().to_string())
    print("Pedidos pendientes medios según hora punta / fin de semana:")
    print(real.groupby(["es_hora_punta", "es_fin_de_semana"])["pedido_pendiente"]
          .mean().round(1).unstack().to_string())

    # Regresión lineal rápida con las variables de entrada (solo como señal)
    X = real[["n_platos", "complejidad_pedido", "pedido_pendiente", "cocineros_disponibles",
              "num_platos_complejos", "es_hora_punta", "es_fin_de_semana", "es_festivo",
              "ingrediente_agotado", "ocupacion_local"]].astype(float).copy()
    X["delivery"] = (real["canal"] == "delivery").astype(float)
    X["vip"] = (real["prioridad_aux"] == "VIP").astype(float)
    A = np.column_stack([np.ones(len(X)), X.to_numpy()])
    coef, *_ = np.linalg.lstsq(A, t.to_numpy(), rcond=None)
    r2 = 1 - ((t.to_numpy() - A @ coef) ** 2).sum() / ((t - t.mean()) ** 2).sum()
    print(f"\nR2 de una regresión lineal con estas variables: {r2:.2f}")

    print("\nEnsuciado (filas con problema):")
    print("  vacíos por columna:", {c: int((raw[c] == "").sum()) for c in
          ("fecha", "hora", "dia_semana", "n_platos", "complejidad_pedido",
           "pedido_pendiente", "cocineros_disponibles", "tiempo_prep_min")})
    print("  dia_semana inválido:", int(raw["dia_semana"].isin(["0", "8", "lunes"]).sum()),
          "| fecha MM-DD-AAAA:", int(raw["fecha"].str.match(r"^\d{2}-\d{2}-\d{4}$").sum()),
          "| tiempo HH:MM:", int(raw["tiempo_prep_min"].str.contains(":").sum()),
          "| id repetidos:", int(raw["id_pedido"].duplicated().sum()))


def main() -> None:
    carpeta = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--entrada", type=Path, default=carpeta)
    ap.add_argument("--salida", type=Path, default=carpeta / "ampliado")
    args = ap.parse_args()

    rng = np.random.default_rng(SEMILLA)
    dificultades = dificultad_por_plato(leer(args.entrada / ARCHIVO_CARTA))
    cal = construir_calendario(rng)
    real = generar_pedidos(cal, dificultades, rng)
    raw = ensuciar(real, rng)

    args.salida.mkdir(parents=True, exist_ok=True)
    ruta = args.salida / ARCHIVO_PEDIDOS
    raw.to_csv(ruta, index=False, encoding="utf-8-sig", lineterminator="\r\n",
               quoting=csv.QUOTE_MINIMAL)
    informe(real, raw)
    print(f"\nSalida: {ruta}")


if __name__ == "__main__":
    main()
