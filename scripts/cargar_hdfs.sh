#!/usr/bin/env bash
# =============================================================================
# cargar_hdfs.sh — Carga los 3 CSV originales en la zona raw de HDFS
# =============================================================================
# Se ejecuta DENTRO del contenedor namenode:
#
#   docker exec namenode bash /scripts/cargar_hdfs.sh
#
# Requisitos:
#   - Los 3 CSV están en la carpeta data/ del repo (montada como /datos).
#   - La carpeta scripts/ del repo está montada como /scripts en el namenode.
#
# Qué hace:
#   1. Espera a que HDFS salga del modo seguro y comprueba que los CSV existen.
#   2. Crea las carpetas de /datalake (si ya existen, no pasa nada).
#   3. Sube cada CSV a su carpeta (-f: si ya estaba, lo sobrescribe).
#   4. Compara los bytes de cada archivo en HDFS con el original.
#   5. Lanza un fsck final.
#
# NO borra nada de HDFS. Si hay carpetas antiguas en /datalake/raw, hay que
# eliminarlas a mano antes (ver README). Se puede ejecutar varias veces.
# =============================================================================

set -euo pipefail   # parar ante cualquier error, variable sin definir o fallo en pipes

# --- Configuración -----------------------------------------------------------
DATOS_DIR="${DATOS_DIR:-/datos}"   # carpeta local (dentro del contenedor) con los CSV
RAW="/datalake/raw"                # zona de datos originales (no se modifican después)
CLEAN="/datalake/clean"            # zona de datos limpios (aquí escribe Maitane)

# Cada entrada es "carpeta_en_hdfs:archivo_csv".
# Una carpeta por fuente para poder leerla como tabla (Spark/Hive) más adelante.
FUENTES=(
  "ventas_diarias_platos:01_ventas_diarias_platos.csv"
  "pedidos_tiempos_preparacion:02_pedidos_tiempos_preparacion.csv"
  "carta_platos:03_carta_platos.csv"
)

# --- 1. Comprobaciones previas -----------------------------------------------
echo "==> Esperando a que HDFS salga del modo seguro..."
hdfs dfsadmin -safemode wait

echo "==> Comprobando que los CSV existen en ${DATOS_DIR}..."
faltan=0
for entrada in "${FUENTES[@]}"; do
  archivo="${entrada#*:}"            # parte derecha de "carpeta:archivo"
  if [[ ! -f "${DATOS_DIR}/${archivo}" ]]; then
    echo "    ERROR: no encuentro ${DATOS_DIR}/${archivo}"
    faltan=1
  fi
done
if [[ "${faltan}" -eq 1 ]]; then
  echo "Faltan archivos. Copia los CSV a la carpeta data/ del repo y repite."
  echo "(Si ya están ahí: docker compose up -d --force-recreate, desde docker/)"
  exit 1
fi

# --- 2. Crear estructura -----------------------------------------------------
echo "==> Creando carpetas..."
for entrada in "${FUENTES[@]}"; do
  carpeta="${entrada%%:*}"           # parte izquierda de "carpeta:archivo"
  hdfs dfs -mkdir -p "${RAW}/${carpeta}"
done
hdfs dfs -mkdir -p "${CLEAN}"        # -p: si ya existe, no pasa nada

# --- 3. Subir los CSV --------------------------------------------------------
echo "==> Subiendo CSV a HDFS..."
for entrada in "${FUENTES[@]}"; do
  carpeta="${entrada%%:*}"
  archivo="${entrada#*:}"
  echo "    ${archivo} -> ${RAW}/${carpeta}/"
  hdfs dfs -put -f "${DATOS_DIR}/${archivo}" "${RAW}/${carpeta}/"
done

# --- 4. Verificar tamaños (bytes) --------------------------------------------
echo "==> Verificando bytes (local vs HDFS)..."
errores=0
for entrada in "${FUENTES[@]}"; do
  carpeta="${entrada%%:*}"
  archivo="${entrada#*:}"
  local_bytes=$(stat -c %s "${DATOS_DIR}/${archivo}")
  hdfs_bytes=$(hdfs dfs -stat "%b" "${RAW}/${carpeta}/${archivo}")
  if [[ "${local_bytes}" == "${hdfs_bytes}" ]]; then
    printf "    OK    %-40s %12s bytes\n" "${archivo}" "${hdfs_bytes}"
  else
    printf "    ERROR %-40s local=%s hdfs=%s\n" "${archivo}" "${local_bytes}" "${hdfs_bytes}"
    errores=1
  fi
done

# --- 5. Resumen final --------------------------------------------------------
echo "==> Contenido de /datalake:"
hdfs dfs -ls -R /datalake

echo "==> Estado de salud (fsck):"
hdfs fsck /datalake 2>/dev/null | grep -E "Status|Total files|Total size" || true

if [[ "${errores}" -ne 0 ]]; then
  echo "CARGA INCORRECTA: algún archivo no coincide en tamaño."
  exit 1
fi
echo "CARGA CORRECTA: 3 CSV en ${RAW}."
