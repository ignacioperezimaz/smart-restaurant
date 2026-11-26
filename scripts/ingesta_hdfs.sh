#!/usr/bin/env bash
# =============================================================================
# ingesta_hdfs.sh — Ingesta AUTOMÁTICA de datos CSV en la zona raw de HDFS
# =============================================================================
# Es el proceso de ENTRADA (input) del flujo de datos de Smart-Restaurant.
# Se ejecuta DENTRO del contenedor namenode (que ya tiene el cliente `hdfs`):
#
#   docker exec namenode bash /scripts/ingesta_hdfs.sh              # una pasada
#   docker exec namenode bash /scripts/ingesta_hdfs.sh --vigilar    # se queda vigilando
#   docker exec namenode bash /scripts/ingesta_hdfs.sh --esquema    # muestra las columnas exigidas
#   docker exec namenode bash /scripts/ingesta_hdfs.sh --ayuda
#
# QUÉ AUTOMATIZA (en vez de hacer `hdfs dfs -put` a mano para cada fichero):
#   1. DETECTA qué fuente es cada CSV mirando sus columnas (no importa cómo se llame el fichero).
#   2. VALIDA que tiene las columnas de nuestro contrato de datos (ver FUENTES más abajo).
#   3. LO COLOCA en la estructura de HDFS de Smart-Restaurant, con el nombre estándar.
#   4. VERIFICA bytes y MD5 contra el original y deja un REGISTRO en HDFS de lo ingerido.
#   5. Es IDEMPOTENTE: si el fichero no ha cambiado, no vuelve a subirlo.
#
# ESTRUCTURA RESULTANTE (la misma para cualquiera que use nuestro modelo):
#   /datalake/raw/<fuente>/<archivo estándar>                 <- lote principal (histórico)
#   /datalake/raw/<fuente>/lote=<nombre>/<archivo estándar>   <- lotes adicionales (p. ej. drift)
#   /datalake/raw/_ingesta/registro.csv                       <- qué se ingirió, cuándo y con qué MD5
#   /datalake/clean/                                          <- aquí se escriben los datos limpios
#
# DÓNDE DEJAR LOS FICHEROS (carpeta data/ del repositorio, visible aquí como /datos):
#   data/*.csv                       -> lote principal
#   data/entrada/*.csv               -> lote principal (bandeja de entrada)
#   data/entrada/<nombre_lote>/*.csv -> lote adicional llamado <nombre_lote>
#                                       (p. ej. data/entrada/lote_drift/ para el segundo lote del drift)
#
# SEGURIDAD DEL DATO ORIGINAL: la zona raw no se modifica. Si en el lote principal ya
# existe un fichero DISTINTO, el script se niega a sobrescribirlo (usa --lote o --forzar).
# Las fuentes marcadas como "sobrescribir" (p. ej. platos_nuevos) sí se actualizan.
# =============================================================================

set -uo pipefail   # variable sin definir o fallo en un pipe = error. (Sin -e: los errores se cuentan y se informan.)

# --- Configuración (se puede cambiar con variables de entorno) ---------------
HDFS="${HDFS_CMD:-hdfs}"            # comando del cliente HDFS (HDFS_CMD solo se cambia en pruebas)
DATOS_DIR="${DATOS_DIR:-/datos}"    # carpeta local con los CSV (data/ del repo, montada en el contenedor)
RAW="${RAW:-/datalake/raw}"         # zona de datos originales
CLEAN="${CLEAN:-/datalake/clean}"   # zona de datos limpios
REGISTRO="${RAW}/_ingesta/registro.csv"

# --- CONTRATO DE DATOS: una línea por fuente -----------------------------------
# clave | carpeta en HDFS | nombre estándar del fichero | modo | columnas obligatorias
#   modo "inmutable"   -> raw no se sobrescribe si el contenido cambia (salvo --forzar)
#   modo "sobrescribir"-> se actualiza el fichero cuando cambia (datos vivos)
FUENTES=(
  "ventas|ventas_diarias_platos|01_ventas_diarias_platos.csv|inmutable|fecha,id_plato,precio_unidad,coste_unidad,unidades_vendidas,clientes_dia,nombre_plato_aux,franja,ciudad,moneda,categoria,valoracion,dificultad_elaboracion,popularidad,margen_unitario"
  "pedidos|pedidos_tiempos_preparacion|02_pedidos_tiempos_preparacion.csv|inmutable|id_pedido,fecha,hora,dia_semana,n_platos,complejidad_pedido,cola_pedidos,cocineros_disponibles,canal,prioridad_aux,id_local,estado_captura,es_fin_de_semana,es_festivo,franja,es_hora_punta,mes,ocupacion_local,comensales,num_platos_complejos,temperatura_c,precipitacion_mm,evento_local,ingrediente_agotado,tiempo_prep_minutos"
  "platos_nuevos|platos_nuevos|platos_nuevos.csv|sobrescribir|id_plato,nombre,categoria,precio_medio,coste_medio,margen_medio,dificultad,popularidad,popularidad_estimada,grupo,nombre_grupo,fecha_alta_utc"
)

# --- Opciones de línea de comandos ---------------------------------------------
LOTE_ARG=""; FUENTE_ARG=""; FORZAR=0; SIMULAR=0; VIGILAR=0; SEGUNDOS=30; ARCHIVOS=()

ayuda() { sed -n '2,36p' "$0" | sed 's/^# \{0,1\}//'; exit 0; }

mostrar_esquema() {
  echo "Contrato de datos (columnas obligatorias; el orden da igual, pueden sobrar otras):"
  local f
  for f in "${FUENTES[@]}"; do
    IFS='|' read -r clave carpeta archivo modo cols <<< "$f"
    echo
    echo "  fuente: ${clave}   ->   ${RAW}/${carpeta}/${archivo}   (${modo})"
    echo "  columnas: ${cols//,/, }"
  done
  exit 0
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --lote)     LOTE_ARG="${2:-}"; shift 2 ;;
    --fuente)   FUENTE_ARG="${2:-}"; shift 2 ;;
    --forzar)   FORZAR=1; shift ;;
    --simular)  SIMULAR=1; shift ;;
    --vigilar)  VIGILAR=1; if [[ "${2:-}" =~ ^[0-9]+$ ]]; then SEGUNDOS="$2"; shift; fi; shift ;;
    --esquema)  mostrar_esquema ;;
    -h|--ayuda) ayuda ;;
    -*)         echo "Opción desconocida: $1 (usa --ayuda)"; exit 2 ;;
    *)          ARCHIVOS+=("$1"); shift ;;
  esac
done

if [[ -n "${LOTE_ARG}" && ! "${LOTE_ARG}" =~ ^[A-Za-z0-9_-]+$ ]]; then
  echo "ERROR: el nombre del lote solo puede tener letras, números, _ y -  (recibido: '${LOTE_ARG}')"; exit 2
fi

# --- Utilidades -----------------------------------------------------------------
ahora() { date -u +%Y-%m-%dT%H:%M:%SZ; }

# Primera línea del CSV sin BOM, sin \r (finales de línea de Windows) y sin comillas.
cabecera() { head -n 1 "$1" | tr -d '\r"' | sed '1s/^\xEF\xBB\xBF//'; }

# Devuelve en columnas_que_faltan las columnas obligatorias de la fuente $2 que no aparecen en el fichero $1.
faltan_columnas() {
  local archivo="$1" cols_req="$2" c
  local -A presentes=()
  local -a lista
  IFS=',' read -ra lista <<< "$(cabecera "${archivo}")"
  for c in "${lista[@]}"; do presentes["${c}"]=1; done
  FALTAN=""
  IFS=',' read -ra lista <<< "${cols_req}"
  for c in "${lista[@]}"; do [[ -z "${presentes[${c}]:-}" ]] && FALTAN+="${c}, "; done
  FALTAN="${FALTAN%, }"
  [[ -z "${FALTAN}" ]]
}

# Averigua qué fuente es un CSV por sus columnas. Pone FUENTE_DETECTADA (línea completa de FUENTES) o "".
detectar_fuente() {
  local archivo="$1" f clave carpeta nombre modo cols mejor="" max_presentes=-1 total faltan presentes
  FUENTE_DETECTADA=""; DETALLE_RECHAZO=""
  for f in "${FUENTES[@]}"; do
    IFS='|' read -r clave carpeta nombre modo cols <<< "${f}"
    [[ -n "${FUENTE_ARG}" && "${FUENTE_ARG}" != "${clave}" ]] && continue
    if faltan_columnas "${archivo}" "${cols}"; then FUENTE_DETECTADA="${f}"; return 0; fi
    total=$(awk -F, '{print NF}' <<< "${cols}")
    faltan=$(awk -F', ' '{print NF}' <<< "${FALTAN}")
    presentes=$(( total - faltan ))
    if (( presentes > max_presentes )); then max_presentes=${presentes}; mejor="${clave} (tiene ${presentes} de ${total} columnas; faltan: ${FALTAN})"; fi
  done
  DETALLE_RECHAZO="${mejor}"      # la fuente que más se le parece, para orientar al usuario
  return 1
}

md5_local() { md5sum "$1" | cut -d' ' -f1; }
md5_hdfs()  { ${HDFS} dfs -cat "$1" | md5sum | cut -d' ' -f1; }

# Añade una línea al registro de ingestas en HDFS (lo crea con su cabecera si no existe).
# OJO: no se usa `hdfs dfs -appendToFile`: con un solo datanode suele fallar ("Failed to replace a datanode").
# En su lugar se baja el registro, se añade la línea y se vuelve a subir entero (es un fichero diminuto).
registrar() {
  local linea="$1" tmp
  (( SIMULAR )) && return 0
  tmp=$(mktemp)
  if ${HDFS} dfs -test -e "${REGISTRO}" 2>/dev/null; then
    ${HDFS} dfs -cat "${REGISTRO}" > "${tmp}" 2>/dev/null
  else
    ${HDFS} dfs -mkdir -p "$(dirname "${REGISTRO}")" >/dev/null 2>&1
    echo "fecha_utc,fuente,lote,archivo_origen,archivo_hdfs,bytes,md5,filas,estado" > "${tmp}"
  fi
  echo "${linea}" >> "${tmp}"
  if ! ${HDFS} dfs -put -f "${tmp}" "${REGISTRO}" >/dev/null 2>&1; then
    echo "    ?? aviso: no se pudo actualizar el registro ${REGISTRO} (la ingesta en sí está bien)"
  fi
  rm -f "${tmp}"
}

# Ingiere UN fichero: ingerir <ruta local> <línea de FUENTES> <lote ("" = principal)>.  0 = bien, 1 = error.
ingerir() {
  local origen="$1" fuente="$2" lote="$3"
  local clave carpeta nombre modo cols destino destino_dir bytes md5 filas bytes_h md5_h estado
  IFS='|' read -r clave carpeta nombre modo cols <<< "${fuente}"

  destino_dir="${RAW}/${carpeta}"
  [[ -n "${lote}" ]] && destino_dir="${destino_dir}/lote=${lote}"
  destino="${destino_dir}/${nombre}"

  bytes=$(stat -c %s "${origen}")
  md5=$(md5_local "${origen}")
  filas=$(( $(awk 'END{print NR}' "${origen}") - 1 ))      # líneas menos la cabecera
  (( filas < 0 )) && filas=0

  if ${HDFS} dfs -test -e "${destino}" 2>/dev/null; then
    bytes_h=$(${HDFS} dfs -stat "%b" "${destino}" 2>/dev/null)
    md5_h=$(md5_hdfs "${destino}")
    if [[ "${bytes_h}" == "${bytes}" && "${md5_h}" == "${md5}" ]]; then
      printf "    =  %-34s sin cambios (ya está en %s)\n" "$(basename "${origen}")" "${destino}"
      return 0
    fi
    if [[ "${modo}" == "inmutable" && ${FORZAR} -eq 0 ]]; then
      printf "    !! %-34s ya existe en %s y es DISTINTO.\n" "$(basename "${origen}")" "${destino}"
      echo "       La zona raw no se sobrescribe. Opciones: --lote <nombre> (otro lote) o --forzar (reemplazar)."
      registrar "$(ahora),${clave},${lote:-principal},$(basename "${origen}"),${destino},${bytes},${md5},${filas},rechazado_conflicto"
      return 1
    fi
    estado="actualizado"
  else
    estado="nuevo"
  fi

  if (( SIMULAR )); then
    printf "    ~  %-34s -> %s  (%s, %s filas) [simulación: no se sube nada]\n" "$(basename "${origen}")" "${destino}" "${estado}" "${filas}"
    return 0
  fi

  ${HDFS} dfs -mkdir -p "${destino_dir}" >/dev/null 2>&1
  if ! ${HDFS} dfs -put -f "${origen}" "${destino}" >/dev/null 2>&1; then
    printf "    !! %-34s no se pudo subir a %s\n" "$(basename "${origen}")" "${destino}"
    return 1
  fi

  bytes_h=$(${HDFS} dfs -stat "%b" "${destino}" 2>/dev/null)
  md5_h=$(md5_hdfs "${destino}")
  if [[ "${bytes_h}" != "${bytes}" || "${md5_h}" != "${md5}" ]]; then
    printf "    !! %-34s subido pero NO coincide (local %s bytes / HDFS %s bytes)\n" "$(basename "${origen}")" "${bytes}" "${bytes_h}"
    registrar "$(ahora),${clave},${lote:-principal},$(basename "${origen}"),${destino},${bytes},${md5},${filas},error_verificacion"
    return 1
  fi
  printf "    +  %-34s -> %s  (%s, %s filas, %s bytes, md5 %s)\n" "$(basename "${origen}")" "${destino}" "${estado}" "${filas}" "${bytes}" "${md5:0:8}…"
  registrar "$(ahora),${clave},${lote:-principal},$(basename "${origen}"),${destino},${bytes},${md5},${filas},${estado}"
  return 0
}

# Lista los CSV candidatos como "ruta|lote". Si se pasaron ficheros, solo esos.
listar_candidatos() {
  local f d
  if (( ${#ARCHIVOS[@]} > 0 )); then
    for f in "${ARCHIVOS[@]}"; do echo "${f}|${LOTE_ARG}"; done
    return
  fi
  for f in "${DATOS_DIR}"/*.csv "${DATOS_DIR}"/entrada/*.csv; do [[ -f "${f}" ]] && echo "${f}|${LOTE_ARG}"; done
  for d in "${DATOS_DIR}"/entrada/*/; do                      # cada subcarpeta de entrada/ es un lote
    [[ -d "${d}" ]] || continue
    for f in "${d}"*.csv; do [[ -f "${f}" ]] && echo "${f}|$(basename "${d}")"; done
  done
}

declare -A VISTO=()   # ruta|lote -> "tamaño:mtime" ya procesado (en modo vigilar no se repite trabajo)

# Una pasada completa sobre los candidatos. Devuelve el nº de errores en ERRORES_CICLO.
ciclo() {
  local linea ruta lote firma n_ok=0 n_ignorados=0 n_vistos=0
  ERRORES_CICLO=0
  while IFS= read -r linea; do
    [[ -z "${linea}" ]] && continue
    ruta="${linea%|*}"; lote="${linea##*|}"
    if [[ ! -f "${ruta}" ]]; then echo "    !! ${ruta}: no existe"; ERRORES_CICLO=$((ERRORES_CICLO+1)); continue; fi
    firma="$(stat -c '%s:%Y' "${ruta}")"
    if (( VIGILAR )) && [[ "${VISTO[${linea}]:-}" == "${firma}" ]]; then n_vistos=$((n_vistos+1)); continue; fi
    VISTO["${linea}"]="${firma}"

    if [[ ! -s "${ruta}" ]]; then echo "    -  $(basename "${ruta}"): fichero vacío, se ignora"; n_ignorados=$((n_ignorados+1)); continue; fi
    if ! detectar_fuente "${ruta}"; then
      if (( ${#ARCHIVOS[@]} > 0 )); then                      # lo pidieron expresamente: es un error
        echo "    !! ${ruta}: no cumple el contrato de datos (${DETALLE_RECHAZO:-sin fuente conocida})"
        ERRORES_CICLO=$((ERRORES_CICLO+1))
      else
        echo "    -  $(basename "${ruta}"): no es ninguna fuente conocida, se ignora${DETALLE_RECHAZO:+ (más cercana → ${DETALLE_RECHAZO})}"
        n_ignorados=$((n_ignorados+1))
      fi
      continue
    fi
    if ingerir "${ruta}" "${FUENTE_DETECTADA}" "${lote}"; then n_ok=$((n_ok+1)); else ERRORES_CICLO=$((ERRORES_CICLO+1)); fi
  done < <(listar_candidatos)
  (( VIGILAR )) || echo "==> Resumen: ${n_ok} correctos, ${ERRORES_CICLO} con error, ${n_ignorados} ignorados."
}

# --- Programa principal ------------------------------------------------------------
echo "==> Esperando a que HDFS salga del modo seguro..."
${HDFS} dfsadmin -safemode wait >/dev/null 2>&1 || { echo "ERROR: HDFS no responde. ¿Están namenode y datanode en marcha?"; exit 1; }

if (( ! SIMULAR )); then
  ${HDFS} dfs -mkdir -p "${RAW}" "${CLEAN}" >/dev/null 2>&1
  for f in "${FUENTES[@]}"; do IFS='|' read -r _ carpeta _ <<< "${f}"; ${HDFS} dfs -mkdir -p "${RAW}/${carpeta}" >/dev/null 2>&1; done
fi

if (( VIGILAR )); then
  echo "==> Vigilando ${DATOS_DIR} y ${DATOS_DIR}/entrada cada ${SEGUNDOS} s (Ctrl+C para parar)."
  trap 'echo; echo "==> Vigilancia detenida."; exit 0' INT TERM
  salida_tmp=$(mktemp)
  while true; do
    ciclo > "${salida_tmp}"            # (sin subshell, para que VISTO se conserve entre pasadas)
    [[ -s "${salida_tmp}" ]] && { echo "[$(ahora)]"; cat "${salida_tmp}"; }
    sleep "${SEGUNDOS}"
  done
fi

echo "==> Ingiriendo en ${RAW} ..."
ciclo

echo "==> Contenido de ${RAW}:"
${HDFS} dfs -ls -R "${RAW}" 2>/dev/null | grep -v '^Found' || true
echo "==> Estado de salud (fsck):"
${HDFS} fsck /datalake 2>/dev/null | grep -E "Status|Total files|Total size" || true

if (( ERRORES_CICLO > 0 )); then echo "INGESTA CON ERRORES: revisa los avisos de arriba."; exit 1; fi
echo "INGESTA CORRECTA."
