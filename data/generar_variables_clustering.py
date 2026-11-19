"""
generar_variables_clustering.py
===============================
Añade a los CSV las variables de entrada del OBJETIVO 1 (clustering de platos
por rendimiento) sin tocar ninguna columna ni fila original:

  01_ventas_diarias_platos.csv  ->  + margen_unitario, + popularidad   (CALCULADAS)
  03_carta_platos.csv           ->  + categoria, + dificultad_elaboracion,
                                    + valoracion                       (INVENTADAS)
  02_pedidos_tiempos_preparacion.csv no se modifica (es del objetivo 2, regresión).

Definiciones (cada fórmula, por fila):
  margen_unitario = precio_unidad - coste_unidad            [EUR por unidad]
      (NO es margen porcentual ni beneficio total; esos se calculan al agregar).
  popularidad     = unidades_vendidas / clientes_dia        [unidades por cliente]
      (mide qué parte de la clientela del día pide ese plato; en la limpieza
       se agrega por plato y periodo, p. ej. la media).

Variables inventadas (datos SINTÉTICOS, semilla fija -> reproducibles):
  Se generan UNA VEZ POR id_plato (valor estable): así, al consolidar la carta
  por identificador antes de unirla con las ventas, cada plato conserva su
  valor y no se multiplican las filas de ventas.
    categoria              entrante | principal | postre | bebida
    dificultad_elaboracion entero 1-10 (depende de la categoría + ruido)
    valoracion             1.0-5.0 (media 4; sube un poco con la dificultad)

Reglas sobre datos sucios (se respeta el RAW tal cual):
  - Precio con formato '12,5 €' se interpreta como 12.5 al calcular.
  - Si un valor falta o no es numérico ('muchos', vacío) el campo calculado
    queda VACÍO (no se imputa; la imputación se decide en la limpieza).
  - clientes_dia = 0 -> popularidad vacía (división por cero).
  - id_plato con prefijo ('PL-147') se interpreta como 147; id vacío -> vacío.

Uso (desde la raíz del repo):
  python data/generar_variables_clustering.py
  python data/generar_variables_clustering.py --entrada data --salida data/ampliado

Es idempotente: si el CSV de entrada ya trae las columnas nuevas, las
recalcula (nunca se duplican).
"""
import argparse
import csv
from pathlib import Path

import numpy as np
import pandas as pd

SEMILLA = 20261119          # semilla fija: mismos datos inventados en cada ejecución
MAX_ID_CATALOGO = 500       # ids 1..500; se genera siempre la misma tabla

ARCHIVO_VENTAS = "01_ventas_diarias_platos.csv"
ARCHIVO_CARTA = "03_carta_platos.csv"

COLS_VENTAS = ["margen_unitario", "popularidad"]
COLS_CARTA = ["categoria", "dificultad_elaboracion", "valoracion"]

# Categorías, su peso en la carta y su dificultad media de elaboración (1-10)
CATEGORIAS = ["entrante", "principal", "postre", "bebida"]
PESOS = [0.28, 0.34, 0.20, 0.18]
DIFICULTAD_BASE = {"entrante": 3.5, "principal": 6.5, "postre": 5.0, "bebida": 1.8}


# ----------------------------------------------------------------------------
# Lectura / escritura (se conserva el formato original: UTF-8 con BOM y CRLF)
# ----------------------------------------------------------------------------
def leer(ruta: Path) -> pd.DataFrame:
    """Lee el CSV todo como texto y sin convertir vacíos en NaN (fidelidad al RAW)."""
    return pd.read_csv(ruta, dtype=str, encoding="utf-8-sig", keep_default_na=False)


def escribir(df: pd.DataFrame, ruta: Path) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(ruta, index=False, encoding="utf-8-sig", lineterminator="\r\n",
              quoting=csv.QUOTE_MINIMAL)


# ----------------------------------------------------------------------------
# Utilidades de parseo (sobre datos sucios)
# ----------------------------------------------------------------------------
def a_numero(serie: pd.Series) -> pd.Series:
    """'12,5 €' -> 12.5 ; '34' -> 34.0 ; 'muchos' o '' -> NaN."""
    limpio = (serie.str.replace("€", "", regex=False)
                   .str.replace(",", ".", regex=False)
                   .str.strip())
    return pd.to_numeric(limpio, errors="coerce")


def id_a_entero(serie: pd.Series) -> pd.Series:
    """'147' o 'PL-147' -> 147 ; '' -> NaN."""
    return pd.to_numeric(serie.str.extract(r"(\d+)")[0], errors="coerce")


def formatear(serie: pd.Series, decimales: int) -> pd.Series:
    """Número -> texto con decimales fijos; NaN -> cadena vacía."""
    return serie.map(lambda x: "" if pd.isna(x) else f"{x:.{decimales}f}")


# ----------------------------------------------------------------------------
# Ventas: variables calculadas
# ----------------------------------------------------------------------------
def ampliar_ventas(df: pd.DataFrame) -> pd.DataFrame:
    df = df.drop(columns=[c for c in COLS_VENTAS if c in df.columns])
    precio = a_numero(df["precio_unidad"])
    coste = a_numero(df["coste_unidad"])
    unidades = a_numero(df["unidades_vendidas"])
    clientes = a_numero(df["clientes_dia"])

    margen = (precio - coste).round(2)                    # EUR por unidad
    popularidad = unidades / clientes.where(clientes > 0)  # unidades por cliente

    df["margen_unitario"] = formatear(margen, 2)
    df["popularidad"] = formatear(popularidad, 4)
    return df


# ----------------------------------------------------------------------------
# Carta: variables inventadas, estables por id_plato
# ----------------------------------------------------------------------------
def tabla_atributos() -> pd.DataFrame:
    rng = np.random.default_rng(SEMILLA)
    n = MAX_ID_CATALOGO
    categoria = rng.choice(CATEGORIAS, size=n, p=PESOS)
    base = pd.Series(categoria).map(DIFICULTAD_BASE).to_numpy()
    dificultad = np.clip(np.rint(base + rng.normal(0, 1.3, n)), 1, 10).astype(int)
    valoracion = np.clip(np.round(4.0 + 0.12 * (dificultad - 5) + rng.normal(0, 0.45, n), 1),
                         1.0, 5.0)
    return pd.DataFrame({"categoria": categoria,
                         "dificultad_elaboracion": dificultad,
                         "valoracion": valoracion},
                        index=pd.RangeIndex(1, n + 1, name="id"))


def ampliar_carta(df: pd.DataFrame) -> pd.DataFrame:
    df = df.drop(columns=[c for c in COLS_CARTA if c in df.columns])
    ids = id_a_entero(df["id_plato"])
    atributos = tabla_atributos()

    df["categoria"] = ids.map(atributos["categoria"]).fillna("")
    df["dificultad_elaboracion"] = formatear(ids.map(atributos["dificultad_elaboracion"]), 0)
    df["valoracion"] = formatear(ids.map(atributos["valoracion"]), 1)
    return df


# ----------------------------------------------------------------------------
def main() -> None:
    carpeta = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--entrada", type=Path, default=carpeta, help="carpeta con los CSV originales")
    ap.add_argument("--salida", type=Path, default=carpeta / "ampliado", help="carpeta de salida")
    args = ap.parse_args()

    ventas = ampliar_ventas(leer(args.entrada / ARCHIVO_VENTAS))
    carta = ampliar_carta(leer(args.entrada / ARCHIVO_CARTA))
    escribir(ventas, args.salida / ARCHIVO_VENTAS)
    escribir(carta, args.salida / ARCHIVO_CARTA)

    print(f"{ARCHIVO_VENTAS}: {len(ventas):,} filas  (+{', '.join(COLS_VENTAS)})")
    print(f"{ARCHIVO_CARTA}: {len(carta):,} filas  (+{', '.join(COLS_CARTA)})")
    print(f"Salida: {args.salida}")


if __name__ == "__main__":
    main()
