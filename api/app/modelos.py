"""Carga y uso de los dos modelos registrados en MLflow.

Cada modelo se busca en el Model Registry por su NOMBRE y su ALIAS (`actual`). Así, cuando alguien reentrena y
registra una versión nueva en los notebooks, la API puede coger la nueva sin cambiar nada (ver `/modelos/recargar`).

Decisiones de diseño:
- La API ARRANCA aunque MLflow esté caído o todavía no haya modelos; entonces contesta 503 con un mensaje claro.
- La carga es "perezosa": se intenta al arrancar y, si falló, se reintenta cuando llega una petición
  (pero no más de una vez cada pocos segundos, para no saturar a MLflow).
- Si una recarga falla y ya había una versión cargada, se MANTIENE la antigua (la API sigue funcionando).
"""
from __future__ import annotations

import logging
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone

import mlflow
import mlflow.sklearn
import numpy as np
import pandas as pd
from mlflow.exceptions import MlflowException
from mlflow.tracking import MlflowClient

from .config import Ajustes
from .errores import DatosNoDisponibles, ErrorPrediccion, ModeloNoDisponible
from .esquemas import InfoModelo

log = logging.getLogger("api.modelos")

# Variables de entrada de cada modelo, en el orden en que se entrenaron (notebooks 04 y 06)
VARIABLES_CLUSTERING = ["popularidad", "margen_medio"]
VARIABLES_REGRESION = ["n_platos", "num_platos_complejos", "complejidad_pedido", "cola_pedidos", "cocineros_disponibles",
                       "precipitacion_mm", "hora_dec", "dia_semana", "ingrediente_agotado", "canal", "prioridad_aux"]

# Rango de los datos con los que se entrenó el modelo de regresión (notebook 05). Fuera de él, se avisa.
RANGO_ENTRENAMIENTO = {
    "n_platos": (1, 8), "num_platos_complejos": (0, 6), "cola_pedidos": (0, 20),
    "cocineros_disponibles": (1, 7), "precipitacion_mm": (0, 38.2), "hora_dec": (10, 23),
}

# Qué hacer con cada tipo de plato (ingeniería de menú clásica). Es orientativo.
SUGERENCIAS = {
    "Estrella": "Mantenerlo y darle visibilidad en la carta: es popular y deja buen margen.",
    "Popular pero poco rentable": "Revisar precio o coste de los ingredientes: se vende mucho pero deja poco margen.",
    "Rentable pero poco popular": "Promocionarlo (recomendación del camarero, mejor posición en la carta): deja margen pero se pide poco.",
    "Bajo rendimiento": "Valorar reformularlo, cambiar su precio o retirarlo de la carta: ni se vende ni deja margen.",
}


def nombrar_grupos(centroides_z: np.ndarray) -> dict[int, str]:
    """Pone nombre a cada grupo según si su centroide queda por encima o por debajo de la media (misma regla que el notebook 04).

    `centroides_z`: una fila por grupo, columnas popularidad y margen ya estandarizadas (0 = media de la carta).
    """
    nombres: dict[int, str] = {}
    for g, (pop_z, margen_z) in enumerate(centroides_z):
        if pop_z > 0 and margen_z > 0:
            nombres[g] = "Estrella (popular y rentable)"
        elif pop_z > 0:
            nombres[g] = "Popular pero poco rentable"
        elif margen_z > 0:
            nombres[g] = "Rentable pero poco popular"
        else:
            nombres[g] = "Bajo rendimiento (poco popular y poco rentable)"
    # Si dos grupos cayeran en el mismo cuadrante, se distinguen con su número
    repetidos = {n for n in nombres.values() if list(nombres.values()).count(n) > 1}
    return {g: (f"{n} · grupo {g}" if n in repetidos else n) for g, n in nombres.items()}


def sugerencia_de(nombre_grupo: str) -> str:
    for clave, texto in SUGERENCIAS.items():
        if nombre_grupo.startswith(clave):
            return texto
    return "Sin sugerencia para este tipo de grupo."


@dataclass
class Cargado:
    """Lo que hay en memoria de un modelo ya cargado: el pipeline, su información y datos auxiliares."""
    pipeline: object
    info: InfoModelo
    extra: dict


class ModeloRegistrado:
    """Un modelo del Model Registry de MLflow, con carga perezosa y a prueba de fallos."""

    etiqueta = "modelo"             # cómo se llama en los mensajes
    notebook = "04/06"              # qué notebook lo entrena (para el mensaje de ayuda)

    def __init__(self, ajustes: Ajustes, nombre_modelo: str):
        self.ajustes = ajustes
        self.nombre = nombre_modelo
        self._estado: Cargado | None = None
        self._ultimo_error: str | None = None
        self._ultimo_fallo: float = 0.0
        self._lock = threading.RLock()      # evita que dos peticiones carguen el modelo a la vez

    # ---------------------------------------------------------------- estado
    @property
    def cargado(self) -> bool:
        return self._estado is not None

    @property
    def problema(self) -> str | None:
        """Motivo del último fallo al cargar o recargar (None si la última carga fue bien)."""
        return self._ultimo_error

    @property
    def info(self) -> InfoModelo | None:
        return self._estado.info if self._estado else None

    # ---------------------------------------------------------------- carga
    def obtener(self) -> Cargado:
        """Devuelve el modelo listo para usar; si no estaba cargado, lo intenta cargar. Lanza ModeloNoDisponible si no puede."""
        if self._estado is not None:
            return self._estado
        with self._lock:
            if self._estado is not None:
                return self._estado
            reciente = time.monotonic() - self._ultimo_fallo < self.ajustes.espera_reintento_s
            if self._ultimo_error and reciente:
                raise ModeloNoDisponible(self._ultimo_error)     # no martilleamos a MLflow con cada petición
            return self.recargar()

    def recargar(self) -> Cargado:
        """Busca en MLflow la versión con el alias vigente y la carga. Si falla, conserva la que hubiera."""
        with self._lock:
            try:
                self._estado = self._cargar()
                self._ultimo_error = None
                return self._estado
            except ModeloNoDisponible as error:
                mensaje = error.mensaje
            except Exception as error:                              # cualquier otro fallo al leer/deserializar el modelo
                log.exception("Fallo inesperado cargando %s", self.nombre)
                mensaje = (f"No se pudo cargar el modelo '{self.nombre}' ({type(error).__name__}). "
                           "Puede ser un problema de versiones de librerías; mira el log de la API.")
            self._ultimo_error, self._ultimo_fallo = mensaje, time.monotonic()
            if self._estado is not None:                           # había una versión buena: la mantenemos
                mensaje += f" Se sigue usando la versión {self._estado.info.version} ya cargada."
            raise ModeloNoDisponible(mensaje)

    def _cargar(self) -> Cargado:
        cliente = MlflowClient(tracking_uri=self.ajustes.mlflow_uri, registry_uri=self.ajustes.mlflow_uri)
        try:
            version = cliente.get_model_version_by_alias(self.nombre, self.ajustes.alias)
        except MlflowException as error:
            if error.error_code == "RESOURCE_DOES_NOT_EXIST":
                raise ModeloNoDisponible(
                    f"En MLflow no hay ninguna versión de '{self.nombre}' con el alias '{self.ajustes.alias}'. "
                    f"Ejecuta el notebook {self.notebook} para entrenarla y registrarla.") from error
            raise ModeloNoDisponible(
                f"No se puede consultar MLflow en {self.ajustes.mlflow_uri}. ¿Está arrancado el servicio (docker compose up -d)?") from error

        mlflow.set_tracking_uri(self.ajustes.mlflow_uri)
        mlflow.set_registry_uri(self.ajustes.mlflow_uri)
        pipeline = mlflow.sklearn.load_model(f"models:/{self.nombre}/{version.version}")

        metricas, fecha = {}, None
        try:                                                        # notas y fecha de la ejecución (si no están, no pasa nada)
            ejecucion = cliente.get_run(version.run_id)
            metricas = {k: round(float(v), 4) for k, v in ejecucion.data.metrics.items()}
            fecha = ejecucion.data.tags.get("fecha_ejecucion")
        except MlflowException:
            log.warning("No se pudieron leer las métricas de la ejecución %s", version.run_id)

        info = InfoModelo(nombre=self.nombre, version=int(version.version), alias=self.ajustes.alias, run_id=version.run_id,
                          fecha_entrenamiento=fecha, descripcion=version.description or None, metricas=metricas,
                          cargado_en=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"))
        extra = self._preparar(pipeline, cliente, version)
        log.info("Modelo %s cargado: versión %s", self.nombre, version.version)
        return Cargado(pipeline=pipeline, info=info, extra=extra)

    def instalar(self, pipeline, info: InfoModelo, extra: dict | None = None) -> None:
        """Pone un modelo ya construido en memoria, sin pasar por MLflow (lo usan los tests)."""
        self._estado = Cargado(pipeline=pipeline, info=info, extra=extra if extra is not None else self._preparar(pipeline, None, None))
        self._ultimo_error = None

    def _preparar(self, pipeline, cliente, version) -> dict:
        """Gancho para que cada modelo calcule lo que necesite tras cargarse."""
        return {}


# ==============================================================================================
# Objetivo 1 · Clustering
# ==============================================================================================
class ModeloClustering(ModeloRegistrado):
    etiqueta = "clustering de platos"
    notebook = "04_modelo_clustering_platos"

    def _preparar(self, pipeline, cliente, version) -> dict:
        """Saca del pipeline los centroides y los nombres de grupo, y descarga la tabla de platos con su grupo."""
        try:
            escalador, kmeans = pipeline.named_steps["estandarizar"], pipeline.named_steps["kmeans"]
        except (AttributeError, KeyError) as error:
            raise ModeloNoDisponible("El modelo registrado no tiene la estructura esperada (estandarizar + kmeans). "
                                     "Vuelve a registrarlo con el notebook 04.") from error
        centroides_z = np.asarray(kmeans.cluster_centers_)
        extra = {
            "centroides_z": centroides_z,
            "centroides": escalador.inverse_transform(centroides_z),       # en unidades reales (popularidad, euros)
            "nombres": nombrar_grupos(centroides_z),
            "platos": None, "rango": None,
        }
        if cliente is not None and version is not None:                    # tabla de platos (la guarda el notebook 04 en MLflow)
            try:
                with tempfile.TemporaryDirectory() as carpeta:
                    ruta = cliente.download_artifacts(version.run_id, "platos_con_grupo.csv", carpeta)
                    platos = pd.read_csv(ruta)
                extra["platos"] = platos
                extra["rango"] = {v: (float(platos[v].min()), float(platos[v].max())) for v in VARIABLES_CLUSTERING}
            except Exception:                                              # sin esa tabla, el resto de la API funciona igual
                log.warning("No se pudo descargar platos_con_grupo.csv de la ejecución %s", version.run_id)
        return extra

    def predecir(self, platos: pd.DataFrame) -> list[dict]:
        """Asigna grupo a cada fila (columnas popularidad y margen_medio). Devuelve un diccionario por plato."""
        estado = self.obtener()
        try:
            X = platos[VARIABLES_CLUSTERING]
            grupos = estado.pipeline.predict(X)
            z = estado.pipeline.named_steps["estandarizar"].transform(X)
            distancias = np.linalg.norm(z - estado.extra["centroides_z"][grupos], axis=1)
        except Exception as error:
            log.exception("Fallo al predecir el clustering")
            raise ErrorPrediccion("No se pudo calcular el grupo de los platos enviados.") from error
        rango, nombres, salida = estado.extra["rango"], estado.extra["nombres"], []
        for fila, g, d in zip(platos.itertuples(index=False), grupos, distancias):
            avisos = []
            if rango:
                for v in VARIABLES_CLUSTERING:
                    minimo, maximo = rango[v]
                    if not minimo <= getattr(fila, v) <= maximo:
                        avisos.append(f"{v}={getattr(fila, v):g} queda fuera del rango de la carta actual "
                                      f"({minimo:.3g}–{maximo:.3g}): el grupo es menos fiable.")
            nombre = nombres[int(g)]
            salida.append({"grupo": int(g), "nombre_grupo": nombre, "distancia_al_centroide": round(float(d), 3),
                           "sugerencia": sugerencia_de(nombre), "avisos": avisos})
        return salida

    def grupos(self) -> list[dict]:
        """Descripción de los grupos: centroide, nombre, nº de platos y sugerencia."""
        estado = self.obtener()
        platos = estado.extra["platos"]
        cuentas = platos["grupo"].value_counts().to_dict() if platos is not None else {}
        return [{"grupo": g, "nombre_grupo": nombre,
                 "centroide": {"popularidad": round(float(c[0]), 4), "margen_medio": round(float(c[1]), 4)},
                 "n_platos": int(cuentas[g]) if platos is not None and g in cuentas else (0 if platos is not None else None),
                 "sugerencia": sugerencia_de(nombre)}
                for (g, nombre), c in zip(estado.extra["nombres"].items(), estado.extra["centroides"])]

    def platos(self, grupo: int | None = None) -> pd.DataFrame:
        """Platos de la carta con su grupo (de la tabla guardada al entrenar). Opcionalmente, solo los de un grupo."""
        tabla = self.obtener().extra["platos"]
        if tabla is None:
            raise DatosNoDisponibles("La tabla de platos con su grupo no está disponible en MLflow para esta versión del modelo "
                                     "(se guarda como `platos_con_grupo.csv` al ejecutar el notebook 04).")
        return tabla if grupo is None else tabla[tabla["grupo"] == grupo]


# ==============================================================================================
# Objetivo 2 · Regresión
# ==============================================================================================
def avisos_pedido(p: dict) -> list[str]:
    """Advertencias de un pedido: datos fuera de lo que el modelo vio al entrenar (la estimación es menos fiable)."""
    avisos = []
    for campo, (minimo, maximo) in RANGO_ENTRENAMIENTO.items():
        if not minimo <= p[campo] <= maximo:
            avisos.append(f"{campo}={p[campo]:g} queda fuera del rango con el que se entrenó el modelo ({minimo:g}–{maximo:g}): "
                          "la estimación es menos fiable.")
    if p["dia_semana"] == 1:
        avisos.append("dia_semana=1 (lunes): el restaurante cierra ese día y el modelo no tiene datos de él.")
    return avisos


class ModeloRegresion(ModeloRegistrado):
    etiqueta = "tiempo de preparación"
    notebook = "06_modelo_regresion_tiempos"

    def predecir(self, pedidos: list[dict]) -> list[dict]:
        """Estima los minutos de cada pedido (lista de diccionarios con los campos de PedidoEntrada)."""
        estado = self.obtener()
        try:
            tabla = pd.DataFrame(pedidos)[VARIABLES_REGRESION]
            tabla["ingrediente_agotado"] = tabla["ingrediente_agotado"].astype(int)    # el modelo se entrenó con 0/1
            minutos = np.asarray(estado.pipeline.predict(tabla), dtype=float)
            if minutos.shape != (len(pedidos),) or not np.all(np.isfinite(minutos)):
                raise ValueError("el modelo devolvió valores no válidos")
        except Exception as error:
            log.exception("Fallo al predecir el tiempo de preparación")
            raise ErrorPrediccion("No se pudo calcular el tiempo de preparación de los pedidos enviados.") from error
        mae = estado.info.metricas.get("test_mae")
        return [{"tiempo_estimado_minutos": round(float(max(m, 0.0)), 1),      # un tiempo no puede ser negativo
                 "error_medio_orientativo_minutos": round(mae, 2) if mae is not None else None,
                 "avisos": avisos_pedido(p)}
                for m, p in zip(minutos, pedidos)]
