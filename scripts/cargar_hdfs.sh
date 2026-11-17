#!/usr/bin/env bash
# ------------------------------------------------------------------
# Carga los CSV originales (carpeta data/) en la zona raw de HDFS.
# Se ejecuta DENTRO del contenedor namenode, donde:
#   /datos   = carpeta data/ del repositorio (solo lectura)
#   /scripts = carpeta scripts/ del repositorio
# Uso (desde cualquier terminal, con el Docker en marcha):
#   docker exec namenode bash /scripts/cargar_hdfs.sh
# Es repetible: ANTES de subir vacía la zona raw (así no quedan CSV antiguos
# de una versión anterior de los datos). La zona /datalake/clean NO se toca.
# ------------------------------------------------------------------
set -euo pipefail

echo "== 1. Creando zonas en HDFS =="
hdfs dfs -mkdir -p /datalake/raw/historico /datalake/raw/lote_drift /datalake/clean

echo "== 1b. Vaciando la zona raw (archivos antiguos) =="
for lote in historico lote_drift; do
  hdfs dfs -rm -r -f -skipTrash "/datalake/raw/${lote}/*" 2>&1 | grep -v "SASL" || true
done

echo "== 2. Subiendo los CSV =="
for lote in historico lote_drift; do
  # Cada lote va a su carpeta: *_historico.csv -> raw/historico, *_lote_drift.csv -> raw/lote_drift
  hdfs dfs -put -f /datos/*_"${lote}".csv /datalake/raw/"${lote}"/ 2>&1 | grep -v "SASL" || true
done

echo "== 3. Verificando que los tamaños coinciden =="
errores=0
for lote in historico lote_drift; do
  for f in /datos/*_"${lote}".csv; do
    nombre=$(basename "$f")
    local_bytes=$(stat -c%s "$f")                                   # tamaño del archivo original
    hdfs_bytes=$(hdfs dfs -stat %b /datalake/raw/"${lote}"/"$nombre") # tamaño en HDFS
    if [ "$local_bytes" = "$hdfs_bytes" ]; then
      echo "OK    $nombre ($hdfs_bytes bytes)"
    else
      echo "ERROR $nombre: local=$local_bytes HDFS=$hdfs_bytes"
      errores=$((errores+1))
    fi
  done
done

echo "== 4. Contenido de /datalake =="
hdfs dfs -ls -R /datalake

if [ "$errores" -ne 0 ]; then
  echo "Hay $errores archivo(s) con tamaño distinto. Revisa la carga."
  exit 1
fi
echo "Carga completada correctamente."
