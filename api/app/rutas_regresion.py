"""Objetivo 2 · Regresión: ¿cuántos minutos tardará en estar listo un pedido?"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from .dependencias import ERR_INTERNO, ERR_LOTE, ERR_MODELO, ERR_VALIDACION, Modelos, comprobar_lote, obtener_modelos
from .esquemas import (ModeloResumen, PedidoEntrada, PedidoLoteEntrada, PrediccionPedido, RespuestaPedido,
                       RespuestaPedidoLote)

router = APIRouter(prefix="/regresion", tags=["Objetivo 2 · Tiempo de preparación"])


def _resumen(modelos: Modelos) -> ModeloResumen:
    info = modelos.regresion.info
    return ModeloResumen(nombre=info.nombre, version=info.version)


@router.post("/predecir", response_model=RespuestaPedido, summary="Estimar el tiempo de un pedido",
             responses={422: ERR_VALIDACION, 503: ERR_MODELO, 500: ERR_INTERNO})
def predecir_pedido(pedido: PedidoEntrada, modelos: Modelos = Depends(obtener_modelos)):
    """Estima **cuántos minutos tardará en prepararse** un pedido a partir de sus datos y del estado de la cocina.

    El modelo es el que se registró con el alias `actual` (ahora mismo, el ganador del notebook 06). La respuesta incluye
    el error medio que tuvo con pedidos que no había visto, como orden de magnitud, y **avisos** si algún dato queda
    fuera de lo que el modelo vio al entrenar (por ejemplo, un lunes, o más de 20 pedidos en cola).
    """
    resultado = modelos.regresion.predecir([pedido.model_dump()])[0]
    return RespuestaPedido(modelo=_resumen(modelos), **resultado)


@router.post("/predecir-lote", response_model=RespuestaPedidoLote, summary="Estimar el tiempo de varios pedidos",
             responses={413: ERR_LOTE, 422: ERR_VALIDACION, 503: ERR_MODELO, 500: ERR_INTERNO})
def predecir_lote(lote: PedidoLoteEntrada, modelos: Modelos = Depends(obtener_modelos)):
    """Igual que `/regresion/predecir`, pero con una lista de pedidos. Los resultados salen **en el mismo orden** que la lista enviada."""
    comprobar_lote(len(lote.pedidos), modelos.ajustes)
    resultados = modelos.regresion.predecir([p.model_dump() for p in lote.pedidos])
    return RespuestaPedidoLote(modelo=_resumen(modelos), n=len(resultados),
                               resultados=[PrediccionPedido(**r) for r in resultados])
