#!/usr/bin/env bash
# =============================================================================
# cargar_hdfs.sh — Carga inicial de los CSV de data/ en la zona raw de HDFS
# =============================================================================
#   docker exec namenode bash /scripts/cargar_hdfs.sh
#
# Ahora delega en ingesta_hdfs.sh, que reconoce cada CSV por sus columnas, comprueba
# el contrato de datos, verifica bytes y MD5 y no vuelve a subir lo que no ha cambiado.
# Se admiten sus mismas opciones (por ejemplo --forzar para reemplazar un CSV que se
# ha regenerado, o --esquema para ver las columnas exigidas).
# =============================================================================
exec bash "$(dirname "$0")/ingesta_hdfs.sh" "$@"
