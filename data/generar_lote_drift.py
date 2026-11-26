"""
generar_lote_drift.py
=====================
Genera el SEGUNDO LOTE de pedidos (enero-junio de 2026) para demostrar el drift.

Idea: el modelo de regresión se entrenó con pedidos de 2023-2025 (lote 1). Seis meses
después llegan datos nuevos. ¿Siguen "pareciéndose" a los de entrenamiento? ¿El modelo
sigue acertando? Para poder responderlo de forma controlada fabricamos DOS versiones
del lote 2 con el MISMO generador y las mismas fechas, y solo cambia el escenario:

  control : el restaurante sigue funcionando igual que en 2023-2025.
            Sirve para comprobar que la monitorización NO da falsas alarmas.
  drift   : el restaurante ha cambiado (ver CAMBIOS_DRIFT). Sirve para comprobar que la
            monitorización SÍ detecta el cambio y el modelo empeora.

Se reutiliza `generar_pedidos_realistas.py` (calendario, festivos, horas punta, ensuciado
y formato RAW idénticos a los del lote 1). Solo se parametriza lo que cambia.

Qué cambia en el escenario `drift` a partir del 1 de marzo de 2026 (enero y febrero son normales, así
se puede ver en la monitorización MES A MES cuándo salta la alarma). Todo es SINTÉTICO e inventado:
  1. Más demanda (+15 %): cocina más cargada (cola_pedidos sube).               -> data drift
  2. Carta renovada: platos más difíciles (+1,2 puntos de dificultad).          -> data drift
  3. Más delivery (+15 puntos) y pedidos más grandes (+0,4 comensales).         -> data drift
  4. Menos personal (-1 cocinero de base en cada local).                        -> data drift
  5. La relación entrada->tiempo cambia: cada plato tarda más, el delivery
     tarda más (app de reparto saturada) y la saturación de cocina penaliza
     más.                                                                       -> concept drift
Los puntos 1-4 cambian las ENTRADAS (data drift / covariate shift). El 5 cambia la
RELACIÓN entre entradas y tiempo (concept drift): es el que hace que el modelo falle
aunque las entradas parecieran normales.

Reproducible (semilla fija). Uso (desde la raíz del repo):
  python data/generar_lote_drift.py --escenario drift   --entrada data --salida data/entrada/2026h1_drift
  python data/generar_lote_drift.py --escenario control --entrada data --salida data/entrada/2026h1_control
La carta se toma de 01_ventas_diarias_platos.csv (columna dificultad_elaboracion), porque
03_carta_platos.csv no está en el repositorio.
"""
import argparse
import csv
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import generar_pedidos_realistas as gen            # noqa: E402  (lote 1: se reutiliza casi todo)
from generar_complejidad_pedidos import dificultad_por_plato, leer  # noqa: E402

SEMILLA_LOTE = 20260701
FECHA_INI, FECHA_FIN = date(2026, 1, 1), date(2026, 6, 30)
# Festivos de Donostia en el primer semestre de 2026 (aproximados; Semana Santa: 2, 3 y 6 de abril)
FESTIVOS_2026 = [(1, 1), (1, 6), (1, 20), (4, 2), (4, 3), (4, 6), (5, 1)]
ID_INICIAL = 200_000        # los id_pedido del lote 2 empiezan en PED-0200001 (no chocan con el lote 1)
MAX_DIFICULTAD = 10

# Parámetros de cada escenario. `control` = valores del lote 1 (los mismos números que
# hay dentro de generar_pedidos_realistas.generar_pedidos).
BASE = dict(                       # valores del lote 1 (los mismos números que hay en generar_pedidos_realistas)
    mas_dificultad=0.0, mas_comensales=0.0, mas_delivery=0.0, menos_cocineros=0, demanda=1.0,
    c_platos=1.9, c_compl=1.2, c_complejos=0.9, c_carga=3.2, c_carga2=0.5,
    extra_delivery=3.0, extra_agotado=3.5,
)
CAMBIO = dict(                     # valores a partir del cambio de funcionamiento
    mas_dificultad=1.2, mas_comensales=0.4, mas_delivery=0.15, menos_cocineros=1, demanda=1.15,
    c_platos=2.3, c_compl=1.2, c_complejos=0.9, c_carga=3.2, c_carga2=0.8,
    extra_delivery=5.0, extra_agotado=3.5,
)
N_PEDIDOS_LOTE = 19_500            # ~ lo que daría el ritmo del lote 1 en 6 meses
INICIO_CAMBIO = {"control": None, "drift": date(2026, 3, 1)}
ESCENARIOS = tuple(INICIO_CAMBIO)


def generar_pedidos_lote(cal, dificultades, rng, inicio_cambio, tam_local):
    """Misma lógica que gen.generar_pedidos, con los parámetros del escenario `p`."""
    N_LOC = gen.N_LOCALES
    # El ritmo base se calcula SIN el cambio; después la demanda sube un 15 % desde el cambio
    mu0 = N_PEDIDOS_LOTE / (tam_local.sum() * cal["factor_dia"].sum())
    if inicio_cambio is not None:
        cal = cal.copy()
        cal.loc[cal["fecha"].dt.date >= inicio_cambio, "factor_dia"] *= CAMBIO["demanda"]
    cuentas = rng.poisson(mu0 * tam_local[None, :] * cal["factor_dia"].to_numpy()[:, None])
    pares = np.repeat(np.arange(cuentas.size), cuentas.ravel())
    dia_idx, local_idx = pares // N_LOC, pares % N_LOC
    n = len(pares)

    finde = ((cal["es_fin_de_semana"] == 1) | (cal["es_festivo"] == 1)).to_numpy()[dia_idx]
    hora = np.empty(n, dtype=int)
    for es_finde, pesos in ((True, gen.PESO_FINDE), (False, gen.PESO_LABORABLE)):
        m = finde == es_finde
        hora[m] = rng.choice(gen.HORAS, size=m.sum(), p=pesos / pesos.sum())
    minuto = rng.integers(0, 60, n)

    orden = np.lexsort((rng.random(n), hora * 60 + minuto, dia_idx))
    dia_idx, local_idx, hora, minuto, finde = (a[orden] for a in (dia_idx, local_idx, hora, minuto, finde))
    h_dec = hora + minuto / 60

    c = cal.iloc[dia_idx].reset_index(drop=True)
    es_punta = ((h_dec >= 13) & (h_dec < 15)) | ((h_dec >= 20.5) & (h_dec < 22.5))
    franja = np.select([h_dec < 12, h_dec < 16, h_dec < 19.5], ["manana", "comida", "tarde"], default="cena")
    lluvia = c["precipitacion_mm"].to_numpy() > 1.0
    # Parámetros de cada pedido: los de BASE antes del cambio y los de CAMBIO después
    activo = np.zeros(n, bool) if inicio_cambio is None else (c["fecha"].dt.date >= inicio_cambio).to_numpy()
    p = {k: np.where(activo, CAMBIO[k], BASE[k]) for k in BASE}

    perfil = np.where(finde, np.interp(h_dec, gen.HORAS + 0.5, gen.PESO_FINDE) / 3.6,
                      np.interp(h_dec, gen.HORAS + 0.5, gen.PESO_LABORABLE) / 3.6)
    dia_norm = np.clip(c["factor_dia"].to_numpy() / 1.5, 0, 1.4)
    ocupacion = np.clip(perfil * dia_norm * rng.lognormal(0, 0.12, n), 0, 1.3)

    pendiente = np.clip(rng.poisson(0.5 + 14 * ocupacion), 0, 20)
    base = np.round(2 + 3 * (tam_local - 0.7) / 0.6)[local_idx] - p["menos_cocineros"]
    cocineros = base + es_punta + (es_punta & finde) - (rng.random(n) < 0.08)
    cocineros = np.clip(cocineros, 1, 8).astype(int)

    lam = 0.8 + 0.7 * finde + 0.5 * es_punta + 0.3 * lluvia + p["mas_comensales"]
    comensales = np.clip(1 + rng.poisson(lam), 1, gen.MAX_PLATOS)
    n_platos = np.clip(comensales + rng.poisson(0.9, n), 1, gen.MAX_PLATOS)
    elegidos = np.clip(dificultades[rng.integers(0, len(dificultades), size=(n, gen.MAX_PLATOS))]
                       + p["mas_dificultad"][:, None], 1, MAX_DIFICULTAD)      # carta renovada
    cuenta = np.arange(gen.MAX_PLATOS)[None, :] < n_platos[:, None]
    complejidad = (elegidos * cuenta).sum(axis=1) / n_platos
    n_complejos = ((elegidos >= gen.UMBRAL_COMPLEJO) & cuenta).sum(axis=1)

    p_del = np.clip(0.20 + 0.08 * (franja == "cena") + 0.05 * finde + 0.08 * lluvia + p["mas_delivery"], 0, 0.7)
    p_tak = 0.22 - 0.05 * (finde & es_punta)
    u = rng.random(n)
    canal = np.where(u < p_del, "delivery", np.where(u < p_del + p_tak, "takeaway", "mesa"))
    prioridad = rng.choice(["normal", "prioridad", "VIP"], size=n, p=[0.75, 0.18, 0.07])
    agotado = (rng.random(n) < 0.02 + 0.03 * (es_punta & finde)).astype(int)

    carga = pendiente / cocineros
    tiempo = (gen.INTERCEPTO_TIEMPO
              + p["c_platos"] * n_platos + p["c_compl"] * complejidad + p["c_complejos"] * n_complejos
              + p["c_carga"] * carga + p["c_carga2"] * carga ** 2
              + np.select([canal == "delivery", canal == "takeaway"], [p["extra_delivery"], 1.2], 0.0)
              + 1.5 * ((canal == "delivery") & lluvia)
              + np.select([prioridad == "VIP", prioridad == "prioridad"], [-4.0, -2.5], 0.0)
              + p["extra_agotado"] * agotado)
    tiempo = tiempo * rng.lognormal(0, 0.08, n) + rng.normal(0, 1.2, n)
    tiempo = np.round(np.clip(tiempo, 2, 60), 1)

    return pd.DataFrame({
        "fecha": c["fecha"], "hora": [f"{h:02d}:{m:02d}:00" for h, m in zip(hora, minuto)],
        "dia_semana": c["dia_semana"], "n_platos": n_platos, "complejidad_pedido": complejidad,
        "cola_pedidos": pendiente, "cocineros_disponibles": cocineros,
        "tiempo_prep_minutos": tiempo, "canal": canal, "prioridad_aux": prioridad,
        "id_local": local_idx + 1, "estado_captura": "registrado",
        "es_fin_de_semana": c["es_fin_de_semana"], "es_festivo": c["es_festivo"],
        "franja": franja, "es_hora_punta": es_punta.astype(int), "mes": c["mes"],
        "ocupacion_local": np.round(ocupacion, 2), "comensales": comensales,
        "num_platos_complejos": n_complejos, "temperatura_c": c["temperatura_c"],
        "precipitacion_mm": c["precipitacion_mm"], "evento_local": c["evento_local"],
        "ingrediente_agotado": agotado,
    })


def main() -> None:
    carpeta = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--escenario", choices=ESCENARIOS, default="drift")
    ap.add_argument("--entrada", type=Path, default=carpeta, help="carpeta con 01_ventas_diarias_platos.csv")
    ap.add_argument("--salida", type=Path, default=None, help="carpeta de salida (por defecto data/entrada/2026h1_<escenario>)")
    args = ap.parse_args()
    inicio_cambio = INICIO_CAMBIO[args.escenario]
    salida = args.salida or carpeta / "entrada" / f"2026h1_{args.escenario}"

    # Los 12 locales son LOS MISMOS que en el lote 1: se repite su sorteo de tamaños con la semilla original
    # (si no, el control mostraría un cambio de plantilla que no existe). Hay que consumir antes el
    # azar del calendario 2023-2025, igual que hizo el lote 1.
    rng1 = np.random.default_rng(gen.SEMILLA)
    gen.construir_calendario(rng1)
    tam_local = rng1.uniform(0.7, 1.3, gen.N_LOCALES)

    # Ajustamos el generador del lote 1 al periodo nuevo (calendario, festivos, duplicados)
    gen.FECHA_INI, gen.FECHA_FIN = FECHA_INI, FECHA_FIN
    gen.FESTIVOS.update(date(2026, m, d) for m, d in FESTIVOS_2026)
    gen.N_DUPLICADOS = 300

    rng = np.random.default_rng(SEMILLA_LOTE)      # misma semilla en los dos escenarios
    dificultades = dificultad_por_plato(leer(args.entrada / "01_ventas_diarias_platos.csv"))
    cal = gen.construir_calendario(rng)
    real = generar_pedidos_lote(cal, dificultades, rng, inicio_cambio, tam_local)
    raw = gen.ensuciar(real, rng)
    # ids propios del lote 2
    num = raw["id_pedido"].str.extract(r"(\d+)")[0].astype(int) + ID_INICIAL
    raw["id_pedido"] = num.map(lambda i: f"PED-{i:07d}")

    salida.mkdir(parents=True, exist_ok=True)
    ruta = salida / gen.ARCHIVO_PEDIDOS
    raw.to_csv(ruta, index=False, encoding="utf-8-sig", lineterminator="\r\n", quoting=csv.QUOTE_MINIMAL)
    t = real["tiempo_prep_minutos"]
    print(f"Escenario {args.escenario}: {len(real):,} pedidos reales, {len(raw):,} filas RAW "
          f"({FECHA_INI} -> {FECHA_FIN}) | tiempo medio {t.mean():.1f} min")
    print(f"Salida: {ruta}")


if __name__ == "__main__":
    main()
