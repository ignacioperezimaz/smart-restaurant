"""Almacén permanente de los platos que se añaden desde la interfaz: un CSV (`platos_nuevos.csv`).

Por qué un CSV y no la base de datos de MLflow: es lo que el equipo puede abrir, revisar y subir a Git. En Docker la carpeta
`data/` del repositorio se monta en la API (ver docker-compose.yml), así que lo guardado sobrevive a reiniciar o reconstruir el contenedor.

IMPORTANTE: este archivo NO se mezcla con los datos originales (`01_ventas_diarias_platos.csv`, HDFS…) ni reentrena el modelo.
Los platos guardados se clasifican con el modelo que ya existe.
"""
from __future__ import annotations

import csv
import io
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .errores import ErrorAPI

log = logging.getLogger("api.almacen")

COLUMNAS = ["id_plato", "nombre", "categoria", "precio_medio", "coste_medio", "margen_medio", "dificultad", "popularidad",
            "popularidad_estimada", "grupo", "nombre_grupo", "fecha_alta_utc"]
COLUMNAS_ANTIGUAS_OPCIONALES = {"popularidad_estimada": False}      # archivos guardados antes de existir esta columna siguen valiendo
PRIMER_ID_NUEVO = 81          # la carta original usa del 1 al 80


class AlmacenNoDisponible(ErrorAPI):
    """No se puede leer o escribir el CSV (carpeta sin montar, sin permisos, disco lleno…)."""
    estado = 503
    codigo = "almacen_no_disponible"


class PlatoDuplicado(ErrorAPI):
    """Ya existe un plato con ese nombre."""
    estado = 409
    codigo = "plato_duplicado"


class AlmacenPlatos:
    def __init__(self, ruta: str | Path, nombres_carta: list[str]):
        self.ruta = Path(ruta)
        self._nombres_carta = {n.casefold() for n in nombres_carta}      # no se puede repetir el nombre de un plato de la carta
        self._cerrojo = threading.Lock()                                 # dos guardados a la vez no se pisan

    # ------------------------------------------------------------------ lectura
    def leer(self) -> pd.DataFrame:
        """Todos los platos guardados (tabla vacía si todavía no hay ninguno)."""
        if not self.ruta.exists():
            return pd.DataFrame(columns=COLUMNAS).astype({"popularidad_estimada": bool})
        try:
            tabla = pd.read_csv(self.ruta)
        except (OSError, pd.errors.ParserError, UnicodeDecodeError) as error:
            log.exception("No se pudo leer %s", self.ruta)
            raise AlmacenNoDisponible(f"No se puede leer el archivo de platos nuevos ({self.ruta}). Comprueba que no esté corrupto "
                                      "ni abierto por otro programa.") from error
        for columna, por_defecto in COLUMNAS_ANTIGUAS_OPCIONALES.items():
            if columna not in tabla.columns:
                tabla[columna] = por_defecto
        tabla["popularidad_estimada"] = tabla["popularidad_estimada"].astype(str).str.lower().isin(["true", "1"])
        faltan = [c for c in COLUMNAS if c not in tabla.columns]
        if faltan:
            raise AlmacenNoDisponible(f"El archivo {self.ruta} no tiene las columnas esperadas (faltan: {', '.join(faltan)}).")
        return tabla[COLUMNAS]

    # ------------------------------------------------------------------ escritura
    def anadir(self, datos: dict) -> dict:
        """Guarda un plato (con su grupo ya calculado) y devuelve el registro, con su `id_plato` nuevo."""
        with self._cerrojo:
            tabla = self.leer()
            nombre = datos["nombre"]
            if nombre.casefold() in self._nombres_carta or nombre.casefold() in {str(n).casefold() for n in tabla["nombre"]}:
                raise PlatoDuplicado(f"Ya existe un plato llamado «{nombre}». Usa otro nombre.")
            nuevo_id = max([PRIMER_ID_NUEVO - 1, *[int(i) for i in tabla["id_plato"]]]) + 1
            registro = {**datos, "id_plato": nuevo_id,
                        "fecha_alta_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}
            nuevo = pd.DataFrame([*tabla.to_dict("records"), registro], columns=COLUMNAS)
            self._escribir(nuevo)
            return registro

    def actualizar(self, id_plato: int, cambios: dict) -> dict | None:
        """Cambia campos de un plato guardado (por ejemplo, su popularidad real). Devuelve el registro nuevo, o None si no existe."""
        with self._cerrojo:
            tabla = self.leer()
            fila = tabla.index[tabla["id_plato"] == id_plato]
            if len(fila) == 0:
                return None
            for campo, valor in cambios.items():
                tabla[campo] = tabla[campo].astype(object)
                tabla.loc[fila[0], campo] = valor
            self._escribir(tabla)
            return tabla.loc[fila[0]].to_dict()

    def eliminar(self, id_plato: int) -> bool:
        """Borra un plato guardado. Devuelve False si no existía."""
        with self._cerrojo:
            tabla = self.leer()
            resto = tabla[tabla["id_plato"] != id_plato]
            if len(resto) == len(tabla):
                return False
            self._escribir(resto)
            return True

    def _escribir(self, tabla: pd.DataFrame) -> None:
        """Escribe el CSV entero de una vez (así nunca queda a medias si algo falla a mitad)."""
        texto = io.StringIO()
        tabla.to_csv(texto, index=False, quoting=csv.QUOTE_MINIMAL)
        try:
            self.ruta.parent.mkdir(parents=True, exist_ok=True)
            self.ruta.write_text(texto.getvalue(), encoding="utf-8", newline="")
        except OSError as error:
            log.exception("No se pudo escribir %s", self.ruta)
            raise AlmacenNoDisponible(
                f"No se ha podido guardar el plato en {self.ruta}. Si usas Docker, comprueba que la carpeta data/ esté montada "
                "en la API (docker-compose.yml) y que tenga permisos de escritura.") from error
