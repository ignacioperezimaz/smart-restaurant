"""Esquemas de entrada y salida (Pydantic). FastAPI los usa para VALIDAR lo que llega y para generar la documentación.

Regla general: los límites "duros" (que dan error 422) son de sentido común (no tiene sentido -3 pedidos en cola).
Lo que simplemente queda fuera de lo que el modelo vio al entrenar NO es error: se responde, pero con un `aviso`.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Base(BaseModel):
    """Todos los esquemas de entrada rechazan campos desconocidos: así una errata (`cola_pedido`) no pasa desapercibida."""
    model_config = ConfigDict(extra="forbid")


# ==============================================================================================
# Comunes
# ==============================================================================================
class ModeloResumen(BaseModel):
    nombre: str = Field(description="Nombre del modelo en el Model Registry de MLflow.")
    version: int = Field(description="Versión del modelo que ha contestado.")


class InfoModelo(BaseModel):
    nombre: str
    version: int
    alias: str = Field(description="Alias del Registry que apunta a esta versión (normalmente `actual`).")
    run_id: str = Field(description="Ejecución de MLflow en la que se entrenó.")
    fecha_entrenamiento: str | None = Field(default=None, description="Fecha y hora de la ejecución (`AAAA-MM-DD_HH-MM`).")
    descripcion: str | None = None
    metricas: dict[str, float] = Field(default_factory=dict, description="Notas registradas en MLflow al entrenarlo.")
    cargado_en: str = Field(description="Cuándo cargó la API esta versión (UTC).")


class EstadoModelo(BaseModel):
    disponible: bool
    modelo: InfoModelo | None = None
    problema: str | None = Field(default=None, description="Motivo del último fallo al cargar o recargar el modelo, si lo hubo (puede haber un modelo cargado y aun así un fallo de recarga).")


class Salud(BaseModel):
    estado: Literal["ok", "degradado"] = Field(description="`ok` si los dos modelos están cargados; `degradado` si falta alguno.")
    version_api: str
    mlflow_uri: str
    clustering: EstadoModelo
    regresion: EstadoModelo


# ==============================================================================================
# Objetivo 1 · Clustering de platos
# ==============================================================================================
class PlatoEntrada(Base):
    """Un plato descrito con las dos variables con las que se agrupó la carta (notebook 04)."""
    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [
        {"id_plato": "plato-nuevo-1", "popularidad": 0.52, "margen_medio": 10.1},
        {"id_plato": "plato-nuevo-2 (sin ventas aún)", "margen_medio": 9.9}]})

    id_plato: str | None = Field(default=None, max_length=50,
                                 description="Etiqueta opcional para reconocer el plato en la respuesta.")
    popularidad: float | None = Field(default=None, ge=0, le=100, allow_inf_nan=False,
                                      description="Unidades vendidas por cliente (en la carta actual, entre 0,47 y 0,52). "
                                                  "OPCIONAL: un plato nuevo aún no tiene ventas. Si se omite (o es `null`) el grupo "
                                                  "que se devuelve es provisional y se añade el reparto de grupos posibles.")
    margen_medio: float = Field(ge=-1000, le=1000, allow_inf_nan=False,
                                description="Margen medio por unidad, en euros (en la carta actual, entre 9,6 y 10,2).")


class NuevoPlatoEntrada(Base):
    """Un plato que se quiere AÑADIR (guardar para siempre) a la carta del gráfico.

    Si ya tiene ventas se envía su `popularidad`. Si todavía no, se envía `estimar_popularidad: true` y la API usa la
    **media de la popularidad de los platos de su misma categoría** (queda marcado como estimado)."""
    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [
        {"nombre": "Tarta de la abuela", "categoria": "postre", "precio_medio": 6.5, "coste_medio": 2.1, "dificultad": 4, "popularidad": 0.51},
        {"nombre": "Flan de la casa", "categoria": "postre", "precio_medio": 5.0, "coste_medio": 1.6, "dificultad": 3, "estimar_popularidad": True}]})

    nombre: str = Field(min_length=2, max_length=60, description="Nombre del plato (no puede repetirse).")
    categoria: Literal["entrante", "principal", "postre"]
    precio_medio: float = Field(ge=0, le=1000, allow_inf_nan=False, description="Precio de venta, en euros.")
    coste_medio: float = Field(ge=0, le=1000, allow_inf_nan=False, description="Coste de los ingredientes, en euros.")
    dificultad: int = Field(ge=1, le=10, description="Dificultad de elaboración, de 1 (fácil) a 10 (difícil).")
    popularidad: float | None = Field(default=None, ge=0, le=100, allow_inf_nan=False,
                                      description="Unidades vendidas por cliente. Obligatoria salvo que `estimar_popularidad` sea `true`.")
    estimar_popularidad: bool = Field(default=False, description="`true` = el plato aún no tiene ventas: se usa la media de popularidad de su categoría.")

    @field_validator("nombre")
    @classmethod
    def _limpiar_nombre(cls, v: str) -> str:
        v = " ".join(v.split())                      # sin espacios de más ni saltos de línea
        if len(v) < 2:
            raise ValueError("El nombre debe tener al menos 2 caracteres.")
        if v[0] in "=+-@":                           # una celda que empieza así se ejecutaría como fórmula al abrir el CSV en Excel
            raise ValueError("El nombre no puede empezar por =, +, - ni @.")
        return v

    @model_validator(mode="after")
    def _popularidad_o_estimacion(self):
        if self.estimar_popularidad and self.popularidad is not None:
            raise ValueError("Envía `popularidad` o `estimar_popularidad: true`, pero no las dos cosas.")
        if not self.estimar_popularidad and self.popularidad is None:
            raise ValueError("Falta la popularidad. Si el plato aún no tiene ventas, envía `estimar_popularidad: true`.")
        return self

    @property
    def margen_medio(self) -> float:
        """Margen unitario = precio − coste (como en los datos de ventas)."""
        return round(self.precio_medio - self.coste_medio, 2)


class PopularidadReal(Base):
    """Para sustituir la popularidad estimada de un plato añadido por la real, cuando ya tenga ventas."""
    popularidad: float = Field(ge=0, le=100, allow_inf_nan=False, description="Unidades vendidas por cliente.")


class MediaCategoria(BaseModel):
    categoria: str
    popularidad_media: float = Field(description="Media de la popularidad de los platos de esa categoría (con ventas reales).")
    n_platos: int = Field(description="Platos que entran en la media.")


class PlatoLoteEntrada(Base):
    platos: list[PlatoEntrada] = Field(min_length=1, description="Platos a clasificar (el máximo lo fija `MAX_LOTE`, 500 por defecto).")


class GrupoPosible(BaseModel):
    grupo: int
    nombre_grupo: str
    porcentaje: float = Field(description="De todas las popularidades probadas (las de la carta actual), % en las que el plato caería en este grupo.")


class PrediccionPlato(BaseModel):
    id_plato: str | None = Field(default=None, description="La etiqueta que se envió, si se envió.")
    grupo: int = Field(description="Número del grupo (0, 1, 2…). Cambia si se reentrena; mejor usar `nombre_grupo`.")
    nombre_grupo: str = Field(description="Tipo de plato según su popularidad y su margen frente a la media de la carta.")
    distancia_al_centroide: float | None = Field(
        description="Lo lejos que está el plato del centro de su grupo, en desviaciones típicas. 0 = justo en el centro; "
                    "valores altos (más de 2) = plato atípico dentro de su grupo. `null` si no se indicó la popularidad.")
    popularidad_conocida: bool = Field(default=True, description="`false` si no se envió la popularidad: el grupo es entonces PROVISIONAL.")
    grupos_posibles: list[GrupoPosible] = Field(
        default_factory=list,
        description="Solo si falta la popularidad: en qué grupos puede caer el plato y con qué frecuencia, de más a menos probable.")
    sugerencia: str = Field(description="Idea orientativa de qué hacer con este tipo de plato.")
    avisos: list[str] = Field(default_factory=list, description="Advertencias (por ejemplo, plato fuera del rango de la carta).")


class RespuestaPlato(PrediccionPlato):
    modelo: ModeloResumen


class RespuestaPlatoLote(BaseModel):
    modelo: ModeloResumen
    n: int = Field(description="Número de platos clasificados.")
    resultados: list[PrediccionPlato] = Field(description="Un resultado por plato, en el MISMO orden que la petición.")


class Centroide(BaseModel):
    popularidad: float
    margen_medio: float


class GrupoInfo(BaseModel):
    grupo: int
    nombre_grupo: str
    centroide: Centroide = Field(description="El plato \"medio\" del grupo, en unidades reales.")
    n_platos: int | None = Field(default=None, description="Platos de la carta en este grupo (si los datos están disponibles).")
    sugerencia: str


class PlatoCarta(BaseModel):
    """Un plato de la carta actual con el grupo que le asignó el modelo."""
    id_plato: int
    nombre: str = Field(description="Nombre del plato (ensalada, croquetas…). Ojo: los datos solo traen el id; los nombres son de ejemplo.")
    categoria: str | None = Field(default=None, description="`entrante`, `principal` o `postre` (asignada por nosotros, como el nombre).")
    es_nuevo: bool = Field(default=False, description="`true` si lo añadió alguien desde la interfaz (está en `platos_nuevos.csv`); `false` si es de la carta original.")
    popularidad_estimada: bool = Field(default=False, description="`true` si el plato se guardó sin ventas y su popularidad es la MEDIA de su categoría (un supuesto, no un dato real).")
    grupo: int
    nombre_grupo: str
    popularidad: float
    margen_medio: float
    precio_medio: float | None = None
    coste_medio: float | None = None
    valoracion: float | None = None
    dificultad: float | None = None
    unidades_medias: float | None = None
    sugerencia: str


# ==============================================================================================
# Objetivo 2 · Regresión del tiempo de preparación
# ==============================================================================================
Canal = Literal["mesa", "delivery", "takeaway"]
Prioridad = Literal["normal", "prioridad", "VIP"]


class PedidoEntrada(Base):
    """Un pedido en el momento en que entra en cocina. Los nombres de los campos son los de la tabla de pedidos."""
    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [{
        "n_platos": 3, "num_platos_complejos": 1, "complejidad_pedido": 4.5, "cola_pedidos": 8,
        "cocineros_disponibles": 5, "precipitacion_mm": 0.0, "hora_dec": 20.5, "dia_semana": 6,
        "ingrediente_agotado": False, "canal": "delivery", "prioridad_aux": "normal"}]})

    n_platos: int = Field(ge=1, le=50, description="Platos del pedido. (El modelo se entrenó con pedidos de 1 a 8.)")
    num_platos_complejos: int = Field(ge=0, le=50, description="Cuántos de esos platos son complejos (no puede superar `n_platos`).")
    complejidad_pedido: float = Field(ge=1, le=10, allow_inf_nan=False, description="Complejidad global del pedido, de 1 (sencillo) a 10.")
    cola_pedidos: int = Field(ge=0, le=500, description="Pedidos esperando en cocina. (Entrenado con 0 a 20.)")
    cocineros_disponibles: int = Field(ge=1, le=50, description="Cocineros disponibles. (Entrenado con 1 a 7.)")
    precipitacion_mm: float = Field(ge=0, le=500, allow_inf_nan=False, description="Lluvia en mm.")
    hora_dec: float = Field(ge=0, lt=24, allow_inf_nan=False,
                            description="Hora del día en decimal: las 20:30 son 20.5. (Entrenado con horas de 10 a 23.)")
    dia_semana: int = Field(ge=1, le=7, description="1 = lunes … 7 = domingo. (Los lunes el restaurante está cerrado: no hay datos.)")
    ingrediente_agotado: bool = Field(default=False, description="`true` (o 1) si falta algún ingrediente del pedido.")
    canal: Canal = Field(description="Cómo se consume el pedido.")
    prioridad_aux: Prioridad = Field(default="normal", description="Prioridad del pedido.")

    @model_validator(mode="after")
    def _complejos_no_superan_platos(self):
        """Comprobación entre campos: no puede haber más platos complejos que platos."""
        if self.num_platos_complejos > self.n_platos:
            raise ValueError(f"num_platos_complejos ({self.num_platos_complejos}) no puede ser mayor que n_platos ({self.n_platos}).")
        return self


class PedidoLoteEntrada(Base):
    pedidos: list[PedidoEntrada] = Field(min_length=1, description="Pedidos a estimar (el máximo lo fija `MAX_LOTE`, 500 por defecto).")


class PrediccionPedido(BaseModel):
    tiempo_estimado_minutos: float = Field(description="Minutos estimados hasta que el pedido está listo.")
    error_medio_orientativo_minutos: float | None = Field(
        default=None, description="Lo que se equivocó de media el modelo con pedidos que no había visto (MAE de prueba). "
                                  "Sirve de orden de magnitud: no es un intervalo garantizado.")
    avisos: list[str] = Field(default_factory=list, description="Advertencias: datos fuera de lo visto al entrenar, lunes, etc.")


class RespuestaPedido(PrediccionPedido):
    modelo: ModeloResumen


class RespuestaPedidoLote(BaseModel):
    modelo: ModeloResumen
    n: int
    resultados: list[PrediccionPedido] = Field(description="Un resultado por pedido, en el MISMO orden que la petición.")
