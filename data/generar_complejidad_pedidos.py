"""
generar_complejidad_pedidos.py
==============================
Rellena la columna `complejidad_pedido` de 02_pedidos_tiempos_preparacion.csv
a partir de la carta (03_carta_platos.csv), para que los datasets 02 y 03
queden relacionados (OBJETIVO 2: regresión del tiempo de preparación).

Método (por pedido):
  1. El pedido tiene `n_platos` platos.
  2. Se eligen al azar n_platos platos de la carta (ids distintos de la carta,
     con repetición posible, como en un pedido real donde se repite un plato).
  3. complejidad_pedido = media de la `dificultad_elaboracion` de esos platos
     (escala 1-10, 2 decimales).

Por qué `dificultad_elaboracion` y no la columna `complejidad` de la carta:
  la columna original `complejidad` de la carta es ruidosa (un mismo id_plato
  tiene hasta 14 valores distintos, y trae 'alta', 0, 11 y vacíos). En cambio
  `dificultad_elaboracion` es estable por plato (un valor por id_plato), está en
  la misma escala 1-10 y es la misma que lleva el CSV de ventas (coherencia 01-03).

Reglas sobre datos sucios (el resto de columnas del RAW no se toca):
  - n_platos vacío -> complejidad_pedido vacía (no se puede calcular).
  - Los valores previos de complejidad_pedido (incluidos 'alta' y vacíos) se
    sustituyen por el valor calculado.
  - Plato de la carta sin id o sin dificultad -> no se usa como candidato.
  - id con prefijo ('PL-147') se interpreta como 147.

Reproducible (semilla fija) e idempotente (siempre se recalcula la columna).

Uso (desde la raíz del repo):
  python data/generar_complejidad_pedidos.py
  python data/generar_complejidad_pedidos.py --entrada data --salida data/ampliado
"""
import argparse
import csv
from pathlib import Path

import numpy as np
import pandas as pd

SEMILLA = 20261120
MAX_PLATOS = 8                      # n_platos va de 1 a 8
ARCHIVO_PEDIDOS = "02_pedidos_tiempos_preparacion.csv"
ARCHIVO_CARTA = "03_carta_platos.csv"


def leer(ruta: Path) -> pd.DataFrame:
    return pd.read_csv(ruta, dtype=str, encoding="utf-8-sig", keep_default_na=False)


def escribir(df: pd.DataFrame, ruta: Path) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(ruta, index=False, encoding="utf-8-sig", lineterminator="\r\n",
              quoting=csv.QUOTE_MINIMAL)


def dificultad_por_plato(carta: pd.DataFrame) -> np.ndarray:
    """Un valor de dificultad por id_plato de la carta (ids únicos y válidos)."""
    ids = pd.to_numeric(carta["id_plato"].str.extract(r"(\d+)")[0], errors="coerce")
    dif = pd.to_numeric(carta["dificultad_elaboracion"], errors="coerce")
    tabla = pd.DataFrame({"id": ids, "dif": dif}).dropna().drop_duplicates("id").sort_values("id")
    return tabla["dif"].to_numpy()


def rellenar_complejidad(pedidos: pd.DataFrame, dificultades: np.ndarray) -> pd.DataFrame:
    rng = np.random.default_rng(SEMILLA)
    n = pd.to_numeric(pedidos["n_platos"], errors="coerce")
    valido = n.between(1, MAX_PLATOS)
    n_int = n.where(valido, 0).astype(int).to_numpy()

    # Para cada pedido, MAX_PLATOS platos al azar; solo cuentan los n_platos primeros
    elegidos = dificultades[rng.integers(0, len(dificultades), size=(len(pedidos), MAX_PLATOS))]
    cuenta = np.arange(MAX_PLATOS)[None, :] < n_int[:, None]
    suma = (elegidos * cuenta).sum(axis=1)
    media = np.where(n_int > 0, suma / np.maximum(n_int, 1), np.nan)

    pedidos = pedidos.copy()
    pedidos["complejidad_pedido"] = pd.Series(media).map(
        lambda x: "" if pd.isna(x) else f"{x:.2f}").to_numpy()
    return pedidos


def main() -> None:
    carpeta = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--entrada", type=Path, default=carpeta)
    ap.add_argument("--salida", type=Path, default=carpeta / "ampliado")
    args = ap.parse_args()

    carta = leer(args.entrada / ARCHIVO_CARTA)
    dificultades = dificultad_por_plato(carta)
    pedidos = rellenar_complejidad(leer(args.entrada / ARCHIVO_PEDIDOS), dificultades)
    escribir(pedidos, args.salida / ARCHIVO_PEDIDOS)
    print(f"{ARCHIVO_PEDIDOS}: {len(pedidos):,} filas; platos candidatos en carta: {len(dificultades)}")
    print(f"complejidad_pedido vacía en {(pedidos['complejidad_pedido'] == '').sum():,} filas (n_platos vacío)")
    print(f"Salida: {args.salida}")


if __name__ == "__main__":
    main()
