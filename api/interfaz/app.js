/* ==========================================================================
   Smart-Restaurant · Panel de predicciones
   JavaScript sin librerías: habla con la API del proyecto (mismo servidor, rutas /regresion y /clustering).
   Índice:  1) Utilidades   2) Cliente de la API   3) Pestañas   4) Estimar tiempo   5) Grupos de platos
   ========================================================================== */
"use strict";

/* ============================== 1) UTILIDADES ============================== */
// Si la página se abre desde el servidor de la API (http://localhost:8000/interfaz/), las rutas son relativas.
// Si se abriera como archivo suelto, apuntamos a la API local.
const API = location.protocol.startsWith("http") ? "" : "http://localhost:8000";

const $ = (selector, raiz = document) => raiz.querySelector(selector);
const $$ = (selector, raiz = document) => [...raiz.querySelectorAll(selector)];
const reducirMovimiento = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

const formato = (n, decimales = 1) =>
  Number(n).toLocaleString("es-ES", { minimumFractionDigits: decimales, maximumFractionDigits: decimales });

/** Escapa texto antes de meterlo en HTML (todo lo que viene de la API pasa por aquí). */
function esc(texto) {
  return String(texto ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

/** Ejecuta `funcion` solo cuando pasan `ms` milisegundos sin nuevas llamadas (para no preguntar a la API en cada tecla). */
function retrasar(funcion, ms) {
  let temporizador;
  return (...args) => { clearTimeout(temporizador); temporizador = setTimeout(() => funcion(...args), ms); };
}

/* ============================== 2) CLIENTE DE LA API ============================== */
/** Error de la API ya "traducido": lleva el estado HTTP, el código y los detalles por campo. */
class ErrorApi extends Error {
  constructor(mensaje, { estado = 0, codigo = "error", detalles = [], idPeticion = null } = {}) {
    super(mensaje);
    Object.assign(this, { estado, codigo, detalles, idPeticion });
  }
}

/** Llama a la API. Devuelve el JSON si todo va bien y lanza ErrorApi (con mensaje en español) si no. */
async function llamarApi(ruta, { metodo = "GET", cuerpo = null, senal = null } = {}) {
  const control = new AbortController();
  const limite = setTimeout(() => control.abort(), 20000);                    // si en 20 s no contesta, se corta
  if (senal) senal.addEventListener("abort", () => control.abort());
  let respuesta;
  try {
    respuesta = await fetch(API + ruta, {
      method: metodo, signal: control.signal,
      headers: cuerpo ? { "Content-Type": "application/json" } : undefined,
      body: cuerpo ? JSON.stringify(cuerpo) : undefined,
    });
  } catch (error) {
    if (senal?.aborted) throw error;                                          // la cancelamos nosotros: se ignora más arriba
    throw new ErrorApi(control.signal.aborted
      ? "La API tarda demasiado en responder. Inténtalo de nuevo en unos segundos."
      : "No se puede conectar con la API. Comprueba que está arrancada (docker compose up -d api).", { codigo: "sin_conexion" });
  } finally {
    clearTimeout(limite);
  }
  let datos = null;
  try { datos = await respuesta.json(); } catch { /* respuesta sin JSON */ }
  if (!respuesta.ok) {
    const e = datos?.error;
    throw new ErrorApi(e?.mensaje || `La API respondió con el error ${respuesta.status}.`,
      { estado: respuesta.status, codigo: e?.codigo || "error", detalles: e?.detalles || [], idPeticion: e?.id_peticion || null });
  }
  return datos;
}

/* ---------- Estado de la API (chip de la cabecera) ---------- */
async function comprobarSalud() {
  const chip = $("#estado-api"), texto = $("#estado-api-texto");
  const poner = (clase, mensaje, ayuda = "") => { chip.className = `estado estado--${clase}`; texto.textContent = mensaje; chip.title = ayuda; };
  poner("cargando", "Comprobando la API…");
  try {
    const s = await llamarApi("/salud");
    if (s.estado === "ok") {
      poner("ok", `Modelos listos · tiempo v${s.regresion.modelo.version} · platos v${s.clustering.modelo.version}`);
    } else {
      const falta = [!s.regresion.disponible && "tiempo", !s.clustering.disponible && "platos"].filter(Boolean).join(" y ");
      poner("degradado", `Falta el modelo de ${falta}`, [s.regresion.problema, s.clustering.problema].filter(Boolean).join(" · "));
    }
  } catch (error) {
    poner("caido", "Sin conexión con la API", error.message);
  }
}

/* ============================== 3) PESTAÑAS ============================== */
const pestanas = $$(".pestana");
function mostrarSeccion(nombre, { enfocar = false } = {}) {
  for (const p of pestanas) {
    const activa = p.dataset.seccion === nombre;
    p.setAttribute("aria-selected", activa);
    p.tabIndex = activa ? 0 : -1;
    $(`#panel-${p.dataset.seccion}`).hidden = !activa;
    if (activa && enfocar) p.focus();
  }
  if (location.hash !== `#${nombre}`) history.replaceState(null, "", `#${nombre}`);
  if (nombre === "platos") cargarPlatos();                                   // se carga la primera vez que se abre
}
pestanas.forEach((p) => p.addEventListener("click", () => mostrarSeccion(p.dataset.seccion)));
$("[role=tablist]").addEventListener("keydown", (e) => {                       // flechas izquierda/derecha entre pestañas
  const i = pestanas.findIndex((p) => p === document.activeElement);
  if (i < 0 || !["ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key)) return;
  e.preventDefault();
  const siguiente = e.key === "Home" ? 0 : e.key === "End" ? pestanas.length - 1 : (i + (e.key === "ArrowRight" ? 1 : -1) + pestanas.length) % pestanas.length;
  mostrarSeccion(pestanas[siguiente].dataset.seccion, { enfocar: true });
});

/* ============================== 4) ESTIMAR TIEMPO (objetivo 2) ============================== */
const formPedido = $("#form-pedido");
const salidaTiempo = $("#resultado-tiempo");
const DIAS = ["", "Lunes (el restaurante cierra: no hay datos)", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"];
const CAMPOS_NUMERICOS = {                    // campos de la COCINA: nombre -> [mínimo, máximo, entero?, nombre para el mensaje]
  cocineros_disponibles: [1, 7, true, "Los cocineros"],
  precipitacion_mm: [0, 500, false, "La lluvia"],
};
const HORA_APERTURA = "10:00", HORA_CIERRE = "23:00";   // el restaurante solo abre en este horario: fuera de él no se deja poner hora
const MAX_PLATOS = 50;                        // la API admite hasta 50 platos por pedido
const MAX_UDS_PLATO = 20;                     // tope de unidades de un mismo plato en la interfaz
const TEXTO_BOTON_ESTIMAR = "Estimar tiempo de preparación";
// Los datos de muestra rellenan la cocina y eligen platos de la carta según su dificultad (fáciles ≤ 4, medios 5-6, complejos ≥ 7).
const EJEMPLOS = {
  tranquilo: { cesta: { faciles: 2, medios: 0, complejos: 0 }, cola: 2, cocineros_disponibles: 5, precipitacion_mm: 0, hora: "15:30", dia_semana: 3, canal: "mesa", prioridad_aux: "normal", ingrediente_agotado: false },
  punta: { cesta: { faciles: 2, medios: 1, complejos: 1 }, cola: 12, cocineros_disponibles: 4, precipitacion_mm: 0, hora: "21:00", dia_semana: 6, canal: "delivery", prioridad_aux: "normal", ingrediente_agotado: false },
  saturada: { cesta: { faciles: 2, medios: 1, complejos: 2 }, cola: 20, cocineros_disponibles: 3, precipitacion_mm: 5, hora: "21:30", dia_semana: 7, canal: "delivery", prioridad_aux: "normal", ingrediente_agotado: false },
};
const VALORES_INICIALES = { cesta: null, cola: 0, cocineros_disponibles: 5, precipitacion_mm: 0, hora: "20:30", dia_semana: 6, canal: "delivery", prioridad_aux: "normal", ingrediente_agotado: false };

/* ---------- Carta y cesta del cliente ---------- */
const NOMBRES_CATEGORIA = { entrante: "Entrantes", principal: "Principales", postre: "Postres" };
const menu = { platos: [], uds: new Map(), filtro: "" };   // uds: id_plato -> unidades elegidas
let pedidosRecibidos = [];
let siguienteNumeroPedido = 1;                              // los números no se reutilizan aunque se marquen pedidos como listos
let pedidoEnEstimacion = null;                              // si se está estimando un pedido ya recibido: solo cuentan los que van antes que él                                  // pedidos "enviados" desde Cliente (solo en esta sesión del navegador)
let menuPromesa = null;

/** Cola que ve el modelo: solo depende de los pedidos recibidos (no se ajusta a mano). Si se está estimando un pedido ya recibido,
 *  cuentan únicamente los que van antes que él. */
function colaParaModelo() {
  return pedidoEnEstimacion == null ? pedidosRecibidos.length : pedidosRecibidos.filter((p) => p.numero < pedidoEnEstimacion).length;
}

function actualizarResumenCola() {
  $("#cola-numero").textContent = pedidosRecibidos.length;
  const caja = $("#resumen-cola");
  caja.hidden = pedidoEnEstimacion == null;
  if (pedidoEnEstimacion != null) caja.innerHTML = `Para el pedido nº ${pedidoEnEstimacion} el modelo ve <strong>${colaParaModelo()}</strong> ${colaParaModelo() === 1 ? "pedido delante" : "pedidos delante"} en la cola.`;
}

/** Los ejemplos de muestra «preparan» la cola con N pedidos de ejemplo (2 platos cada uno), ya que la cola solo sale de los pedidos. */
function simularCola(n) {
  const platos = [...menu.platos].sort((a, b) => a.id_plato - b.id_plato);
  const hora = new Date().toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit" });
  siguienteNumeroPedido = n + 1;
  return Array.from({ length: n }, (_, i) => {
    const elegidos = platos.length ? [...new Set([platos[((i + 1) * 7) % platos.length], platos[((i + 1) * 13 + 3) % platos.length]])] : [];
    return { numero: n - i, hora, simulado: true, platos: elegidos.length, lineas: elegidos.map((p) => ({ id: p.id_plato, uds: 1, nombre: p.nombre })) };
  });                                                                          // el más reciente arriba, como en la lista real
}

const unidadesTotales = () => [...menu.uds.values()].reduce((a, b) => a + b, 0);
const platoPorId = (id) => menu.platos.find((p) => p.id_plato === id);

/** Resume la cesta con lo que necesita el modelo: nº de platos, platos complejos y dificultad media (por unidad). */
function resumirCesta() {
  let n = 0, complejos = 0, suma = 0, conDificultad = 0;
  for (const [id, uds] of menu.uds) {
    const plato = platoPorId(id);
    if (!plato) continue;
    n += uds;
    if (plato.dificultad != null) { suma += plato.dificultad * uds; conDificultad += uds; if (plato.dificultad >= 7) complejos += uds; }
  }
  const media = conDificultad ? Math.round((suma / conDificultad) * 100) / 100 : 5;
  return { n, complejos, complejidad: Math.min(10, Math.max(1, media)) };
}
let ultimaEstimacion = null;                  // minutos de la estimación anterior (para mostrar el cambio)
let hayResultado = false;                     // true tras la primera estimación: a partir de ahí se actualiza solo
let contadorPeticion = 0;                     // para ignorar respuestas antiguas si llegan tarde
let cancelarAnterior = null;

/* ---------- Leer el formulario y validarlo en el navegador (la API vuelve a validar igualmente) ---------- */
function ponerError(campo, mensaje) {
  const caja = $(`#error-${campo}`);
  const entrada = campo === "n_platos" ? $("#menu") : ($(`#${campo}`) || $("#hora"));
  if (caja) caja.textContent = mensaje || "";
  if (entrada) { if (mensaje) entrada.setAttribute("aria-invalid", "true"); else entrada.removeAttribute("aria-invalid"); }
}

function leerPedido() {
  const pedido = {}, errores = {};
  const cesta = resumirCesta();                                                // los datos del pedido salen de lo que eligió el cliente
  if (cesta.n < 1) errores.n_platos = "Elige al menos un plato de la carta.";
  else if (cesta.n > MAX_PLATOS) errores.n_platos = `Un pedido admite como máximo ${MAX_PLATOS} platos.`;
  else Object.assign(pedido, { n_platos: cesta.n, num_platos_complejos: cesta.complejos, complejidad_pedido: cesta.complejidad });
  for (const [campo, [min, max, entero, nombre]] of Object.entries(CAMPOS_NUMERICOS)) {
    const texto = $(`#${campo}`).value.trim();
    const valor = Number(texto);
    if (texto === "" || Number.isNaN(valor)) errores[campo] = `${nombre}: escribe un número.`;
    else if (entero && !Number.isInteger(valor)) errores[campo] = `${nombre}: debe ser un número entero.`;
    else if (valor < min || valor > max) errores[campo] = `${nombre}: debe estar entre ${min} y ${max}.`;
    else pedido[campo] = valor;
  }
  pedido.cola_pedidos = colaParaModelo();                                         // la cola sale de los pedidos recibidos
  const hora = $("#hora").value;                                              // "20:30" -> 20.5
  if (!/^\d{2}:\d{2}$/.test(hora)) errores.hora_dec = "Indica la hora de entrada del pedido.";
  else if (hora < HORA_APERTURA || hora > HORA_CIERRE) errores.hora_dec = `El restaurante solo abre de ${HORA_APERTURA} a ${HORA_CIERRE}.`;
  else { const [h, m] = hora.split(":").map(Number); pedido.hora_dec = Math.round((h + m / 60) * 100) / 100; }
  pedido.dia_semana = Number($("input[name=dia_semana]:checked").value);
  pedido.canal = $("input[name=canal]:checked").value;
  pedido.prioridad_aux = $("input[name=prioridad_aux]:checked").value;
  pedido.ingrediente_agotado = $("#ingrediente_agotado").checked;
  return { pedido, errores };
}

function mostrarErroresPedido(errores) {
  const delPedido = errores.n_platos || errores.num_platos_complejos || errores.complejidad_pedido;   // los tres salen de la cesta
  ponerError("n_platos", delPedido);
  for (const campo of [...Object.keys(CAMPOS_NUMERICOS), "hora_dec"]) ponerError(campo, errores[campo]);
}

/* ---------- Dibujo del resultado ---------- */
const ICONO_COCINA = `<svg viewBox="0 0 64 64" fill="none" aria-hidden="true"><circle cx="32" cy="32" r="28" stroke="#5C808E" stroke-width="3"/><path d="M32 16v16l10 6" stroke="#F28C38" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
const ICONO_ALERTA = `<svg viewBox="0 0 64 64" fill="none" aria-hidden="true"><path d="M32 8 58 54H6L32 8Z" stroke="#C4621A" stroke-width="3.5" stroke-linejoin="round"/><path d="M32 26v14" stroke="#C4621A" stroke-width="4" stroke-linecap="round"/><circle cx="32" cy="47" r="2.6" fill="#C4621A"/></svg>`;

function pintarVacio() {
  salidaTiempo.innerHTML = `<div class="estado-vacio">${ICONO_COCINA}<strong>Aún no hay estimación</strong>
    Rellena los datos del pedido y pulsa «Estimar tiempo». También puedes probar un ejemplo de muestra.</div>`;
}
function pintarCarga() {
  if (hayResultado && $(".minutos__numero", salidaTiempo)) { salidaTiempo.style.opacity = ".55"; return; }   // si ya hay número, solo se atenúa
  salidaTiempo.innerHTML = `<div class="cargando-barras" aria-label="Calculando la estimación"><div class="esqueleto" style="height:64px;width:60%"></div>
    <div class="esqueleto" style="height:18px"></div><div class="esqueleto" style="height:60px"></div></div>`;
}
function pintarError(error, reintentar) {
  salidaTiempo.style.opacity = "";
  const id = error.idPeticion ? `<br><small>Código de la petición: ${esc(error.idPeticion)}</small>` : "";
  salidaTiempo.innerHTML = `<div class="estado-error" role="alert">${ICONO_ALERTA}<strong>No se ha podido estimar el tiempo</strong>${esc(error.message)}${id}<br>
    <button type="button" class="boton boton--secundario" id="boton-reintentar">Reintentar</button></div>`;
  $("#boton-reintentar").addEventListener("click", reintentar);
}

function tramoDe(minutos) {                                                   // los mismos tramos que usamos en el notebook 06
  if (minutos < 20) return "menos de 20 min";
  if (minutos < 30) return "de 20 a 30 min";
  if (minutos < 40) return "de 30 a 40 min";
  return "más de 40 min";
}

/** Anima el número de 0 (o del valor anterior) hasta el nuevo. */
function animarNumero(elemento, desde, hasta) {
  if (reducirMovimiento) { elemento.textContent = formato(hasta); return; }
  const inicio = performance.now(), duracion = 550;
  const paso = (ahora) => {
    const t = Math.min((ahora - inicio) / duracion, 1), suave = 1 - Math.pow(1 - t, 3);
    elemento.textContent = formato(desde + (hasta - desde) * suave);
    if (t < 1) requestAnimationFrame(paso);
  };
  requestAnimationFrame(paso);
}

function pintarResultado(r) {
  salidaTiempo.style.opacity = "";
  const minutos = r.tiempo_estimado_minutos;
  const posicion = Math.min(Math.max(minutos, 0), 60) / 60 * 100;
  const yaHabia = $(".minutos__numero", salidaTiempo);
  const desde = yaHabia ? ultimaEstimacion ?? 0 : 0;

  let cambio = "";
  if (ultimaEstimacion !== null && Math.abs(minutos - ultimaEstimacion) >= 0.05) {
    const dif = minutos - ultimaEstimacion;
    cambio = `<span class="minutos__cambio ${dif > 0 ? "minutos__cambio--sube" : ""}">${dif > 0 ? "+" : "−"}${formato(Math.abs(dif))} min respecto a la anterior</span>`;
  }
  const avisos = r.avisos?.length ? `<ul class="avisos">${r.avisos.map((a) => `<li>${esc(a)}</li>`).join("")}</ul>` : "";
  const error = r.error_medio_orientativo_minutos != null
    ? `<div><dt>Error medio del modelo</dt><dd>${formato(r.error_medio_orientativo_minutos)} min</dd></div>` : "";

  salidaTiempo.innerHTML = `
    <div class="minutos"><span class="minutos__numero" id="numero-minutos">${formato(desde)}</span><span class="minutos__unidad">min</span>${cambio}</div>
    <p class="resultado__texto">Tiempo estimado hasta que el pedido esté listo.</p>
    <div class="medidor" role="img" aria-label="Escala de 0 a 60 minutos. El pedido está en el tramo ${tramoDe(minutos)}.">
      <div class="medidor__pista"><span class="medidor__tramo"></span><span class="medidor__tramo"></span><span class="medidor__tramo"></span><span class="medidor__tramo"></span>
        <span class="medidor__marcador" id="marcador" style="left:${yaHabia ? (Math.min(ultimaEstimacion ?? 0, 60) / 60 * 100) : 0}%"></span></div>
      <div class="medidor__etiquetas"><span>menos de 20</span><span>20–30</span><span>30–40</span><span>más de 40</span></div>
      <div class="medidor__escala"><span>0</span><span>60 min</span></div>
    </div>
    <p class="tramo-actual">Tramo: <strong>${tramoDe(minutos)}</strong></p>
    ${avisos}
    <dl class="datos-modelo datos-modelo--lista">
      ${error}
      <div><dt>Modelo</dt><dd>${esc(r.modelo.nombre)} · v${esc(r.modelo.version)}</dd></div>
    </dl>
    <p class="nota">El error medio se calculó con pedidos de prueba que el modelo no había visto. Es un orden de magnitud, no una garantía para cada pedido.</p>`;

  animarNumero($("#numero-minutos"), desde, minutos);
  requestAnimationFrame(() => { $("#marcador").style.left = `${posicion}%`; });       // el marcador se desliza hasta su sitio
  ultimaEstimacion = minutos;
  hayResultado = true;
}

/* ---------- Estimar ---------- */
async function estimar({ desdeBoton = false } = {}) {
  const { pedido, errores } = leerPedido();
  mostrarErroresPedido(errores);
  if (Object.keys(errores).length) {                                           // no molestamos a la API con datos que sabemos mal
    if (desdeBoton) {
      const invalido = $("[aria-invalid=true]", formPedido);
      const subpanel = invalido?.closest(".subpanel");
      if (subpanel?.hidden) mostrarSub(subpanel.id.replace("subpanel-", ""));  // si el fallo está en la otra subsección, vamos a ella
      invalido?.focus();
    }
    return;
  }
  cancelarAnterior?.abort();
  const control = new AbortController();
  cancelarAnterior = control;
  const numero = ++contadorPeticion;
  const boton = $("#boton-estimar");
  boton.disabled = true; boton.textContent = "Estimando…";
  pintarCarga();
  try {
    const respuesta = await llamarApi("/regresion/predecir", { metodo: "POST", cuerpo: pedido, senal: control.signal });
    if (numero !== contadorPeticion) return;                                   // llegó una respuesta más nueva: esta se descarta
    pintarResultado(respuesta);
    if (desdeBoton && window.matchMedia("(max-width: 920px)").matches) salidaTiempo.scrollIntoView({ behavior: "smooth", block: "nearest" });
  } catch (error) {
    if (control.signal.aborted || numero !== contadorPeticion) return;
    if (error.estado === 422 && error.detalles.length) {                       // la API encontró campos mal: los marcamos en el formulario
      const mapa = {};
      for (const d of error.detalles) { const c = d.campo.split(/[.[]/)[0]; mapa[c] = d.mensaje; }
      mostrarErroresPedido(mapa);
      salidaTiempo.style.opacity = "";
      pintarError(new ErrorApi("Revisa los campos marcados en el formulario."), () => estimar({ desdeBoton: true }));
    } else {
      pintarError(error, () => estimar({ desdeBoton: true }));
    }
    hayResultado = false;
  } finally {
    if (numero === contadorPeticion) { boton.disabled = false; boton.textContent = TEXTO_BOTON_ESTIMAR; }
  }
}
const estimarConRetraso = retrasar(() => { if (hayResultado) estimar(); }, 400);

/* ---------- Controles del formulario ---------- */
function rellenarPedido(valores) {
  for (const campo of Object.keys(CAMPOS_NUMERICOS)) { $(`#${campo}`).value = valores[campo]; sincronizarRango(campo); }
  $("#hora").value = valores.hora;
  $(`input[name=dia_semana][value="${valores.dia_semana}"]`).checked = true;
  $(`input[name=canal][value="${valores.canal}"]`).checked = true;
  $(`input[name=prioridad_aux][value="${valores.prioridad_aux}"]`).checked = true;
  $("#ingrediente_agotado").checked = valores.ingrediente_agotado;
  actualizarNombreDia();
  pedidosRecibidos = simularCola(valores.cola); pintarPedidosRecibidos();      // la cola del ejemplo (0 al restablecer)
  ponerCesta(valores.cesta ? armarCesta(valores.cesta) : new Map());
  mostrarErroresPedido({});
}
function pintarRelleno(rango) {                                                 // parte naranja de la pista (Chrome no tiene "progress")
  const { min, max, value } = rango;
  rango.style.setProperty("--relleno", `${((value - min) / (max - min)) * 100}%`);
}
function sincronizarRango(campo) {                                              // el deslizador sigue al número
  const rango = $(`#${campo}-rango`);
  if (rango) { rango.value = $(`#${campo}`).value; pintarRelleno(rango); }
}
function actualizarNombreDia() {
  $("#dia-nombre").textContent = DIAS[$("input[name=dia_semana]:checked").value];
}

$$(".deslizador").forEach((bloque) => {                                         // deslizador -> número
  const rango = $("input[type=range]", bloque), numero = $("input[type=number]", bloque);
  rango.addEventListener("input", () => { numero.value = rango.value; pintarRelleno(rango); ponerError(numero.id, ""); estimarConRetraso(); });
});
formPedido.addEventListener("input", (e) => {
  if (e.target.id === "buscar-plato") return;
  // buscar en la carta no cambia el pedido
  if (e.target.matches("input[type=number]")) { sincronizarRango(e.target.id); ponerError(e.target.id, ""); }
  if (e.target.id === "hora") ponerError("hora_dec", "");
  if (e.target.name === "dia_semana") actualizarNombreDia();
  $$(".chip[data-ejemplo]").forEach((c) => c.setAttribute("aria-pressed", "false"));
  estimarConRetraso();
});
formPedido.addEventListener("change", (e) => {
  if (e.target.id === "hora") {                                                 // una hora fuera del horario se corrige a la más cercana abierta
    const h = e.target.value;
    if (!h || h < HORA_APERTURA || h > HORA_CIERRE) {
      e.target.value = !h || h < HORA_APERTURA ? HORA_APERTURA : HORA_CIERRE;
      ponerError("hora_dec", `El restaurante solo abre de ${HORA_APERTURA} a ${HORA_CIERRE}: se ha ajustado la hora.`);
    }
  }                                  // radios e interruptor disparan "change"
  if (e.target.matches("input[type=radio], input[type=checkbox]")) { if (e.target.name === "dia_semana") actualizarNombreDia(); estimarConRetraso(); }
});
formPedido.addEventListener("submit", (e) => { e.preventDefault(); estimar({ desdeBoton: true }); });
$("#boton-estimar").addEventListener("click", () => estimar({ desdeBoton: true }));
$("#boton-restablecer").addEventListener("click", () => {
  rellenarPedido(VALORES_INICIALES);
  $$(".chip[data-ejemplo]").forEach((c) => c.setAttribute("aria-pressed", "false"));
  $("#confirmacion-pedido").innerHTML = "";
  pedidosRecibidos = []; pintarPedidosRecibidos();                              // restablecer todo también vacía la cola de pedidos recibidos
  contadorPeticion++; cancelarAnterior?.abort();
  hayResultado = false; ultimaEstimacion = null;
  $("#boton-estimar").disabled = false; $("#boton-estimar").textContent = TEXTO_BOTON_ESTIMAR;
  pintarVacio();
});
$$(".chip[data-ejemplo]").forEach((chip) => chip.addEventListener("click", async () => {
  await menuPromesa;                                                            // los ejemplos eligen platos: necesitan la carta cargada
  rellenarPedido(EJEMPLOS[chip.dataset.ejemplo]);
  $("#confirmacion-pedido").innerHTML = "";
  $$(".chip[data-ejemplo]").forEach((c) => c.setAttribute("aria-pressed", c === chip));
  hayResultado = true;                                                          // elegir un ejemplo ya implica querer ver el resultado
  estimar();
}));

/* ---------- Subsecciones Cliente / Cocina ---------- */
const subpestanas = $$(".subpestana");
function mostrarSub(nombre, { enfocar = false } = {}) {
  for (const t of subpestanas) {
    const activa = t.dataset.sub === nombre;
    t.setAttribute("aria-selected", activa);
    t.tabIndex = activa ? 0 : -1;
    $(`#subpanel-${t.dataset.sub}`).hidden = !activa;
    if (activa && enfocar) t.focus();
  }
  $("#bloque-recibidos").hidden = nombre !== "cocina";                          // los pedidos recibidos solo se ven en Cocina
}
subpestanas.forEach((t) => t.addEventListener("click", () => mostrarSub(t.dataset.sub)));
$(".subpestanas").addEventListener("keydown", (e) => {
  if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key)) return;
  e.preventDefault();
  const i = subpestanas.findIndex((t) => t.getAttribute("aria-selected") === "true");
  const siguiente = e.key === "Home" ? 0 : e.key === "End" ? subpestanas.length - 1 : (i + (e.key === "ArrowRight" ? 1 : -1) + subpestanas.length) % subpestanas.length;
  mostrarSub(subpestanas[siguiente].dataset.sub, { enfocar: true });
});

/* ---------- Carta (Cliente) ---------- */
function pintarMenu() {
  const caja = $("#menu");
  const texto = menu.filtro.trim().toLowerCase();
  const visibles = menu.platos.filter((p) => !texto || p.nombre.toLowerCase().includes(texto));
  if (!visibles.length) { caja.innerHTML = `<p class="menu__vacio">${menu.platos.length ? "Ningún plato coincide con la búsqueda." : "La carta está vacía."}</p>`; return; }
  const orden = ["entrante", "principal", "postre"];
  const categorias = [...new Set(visibles.map((p) => p.categoria || "otros"))].sort((a, b) => (orden.indexOf(a) + 1 || 9) - (orden.indexOf(b) + 1 || 9));
  caja.innerHTML = categorias.map((c) => {
    const platos = visibles.filter((p) => (p.categoria || "otros") === c).sort((a, b) => a.nombre.localeCompare(b.nombre, "es"));
    return `<section class="menu__categoria" aria-label="${esc(NOMBRES_CATEGORIA[c] || "Otros")}">
      <h3>${esc(NOMBRES_CATEGORIA[c] || "Otros")} <small>${platos.length}</small></h3>
      <ul>${platos.map((p) => {
        const uds = menu.uds.get(p.id_plato) || 0;
        return `<li class="plato-menu${uds ? " plato-menu--elegido" : ""}" data-id="${p.id_plato}">
          <span class="plato-menu__nombre">${esc(p.nombre)}${p.dificultad != null && p.dificultad >= 7 ? ' <span class="etiqueta-compleja" title="Plato complejo (dificultad 7 o más)">complejo</span>' : ""}
            <small>${p.precio_medio != null ? formato(p.precio_medio, 2) + " € · " : ""}dificultad ${formato(p.dificultad ?? 0, 0)}</small></span>
          <span class="unidades" role="group" aria-label="Unidades de ${esc(p.nombre)}">
            <button type="button" class="unidades__boton" data-delta="-1" aria-label="Quitar una unidad de ${esc(p.nombre)}"${uds ? "" : " disabled"}>−</button>
            <output class="unidades__n" aria-live="polite">${uds}</output>
            <button type="button" class="unidades__boton" data-delta="1" aria-label="Añadir una unidad de ${esc(p.nombre)}">+</button>
          </span></li>`;
      }).join("")}</ul></section>`;
  }).join("");
}

function pintarCesta() {
  const caja = $("#cesta");
  const { n, complejos, complejidad } = resumirCesta();
  if (!n) { caja.innerHTML = `<p class="cesta__vacio">Todavía no has elegido ningún plato.</p>`; return; }
  const lineas = [...menu.uds].filter(([id]) => platoPorId(id)).map(([id, uds]) => `${uds} × ${esc(platoPorId(id).nombre)}`);
  caja.innerHTML = `<div class="cesta__cabecera"><strong>Tu pedido</strong>
      <button type="button" class="enlace" id="vaciar-cesta">Vaciar</button></div>
    <p class="cesta__lineas">${lineas.join(" · ")}</p>
    <dl class="cesta__datos">
      <div><dt>Platos</dt><dd>${n}</dd></div>
      <div><dt>Complejos</dt><dd>${complejos}</dd></div>
      <div><dt>Dificultad media</dt><dd>${formato(complejidad, 1)}</dd></div>
    </dl>`;
  if (n > 8) caja.insertAdjacentHTML("beforeend", `<p class="nota">El modelo se entrenó con pedidos de 1 a 8 platos: con más, la estimación es menos fiable.</p>`);
}

/** Sustituye la cesta entera (ejemplos, restablecer, pedir) y repinta la carta. */
function ponerCesta(nueva) {
  menu.uds = nueva;
  pedidoEnEstimacion = null; actualizarResumenCola();
  pintarMenu(); pintarCesta();
}

/** Convierte "2 fáciles, 1 medio, 2 complejos" en platos concretos de la carta (uno de cada, por orden de id). */
function armarCesta({ faciles = 0, medios = 0, complejos = 0 }) {
  const cesta = new Map();
  const grupos = [[(d) => d <= 4, faciles], [(d) => d >= 5 && d < 7, medios], [(d) => d >= 7, complejos]];
  const ordenados = [...menu.platos].sort((a, b) => a.id_plato - b.id_plato);
  for (const [cumple, cuantos] of grupos) {
    ordenados.filter((p) => p.dificultad != null && cumple(p.dificultad)).slice(0, cuantos).forEach((p) => cesta.set(p.id_plato, 1));
  }
  return cesta;
}

/** Se llama al cargar la carta y cada vez que cambia (platos añadidos o quitados en la pestaña Grupos). */
function ponerMenu(platos) {
  menu.platos = platos;
  for (const id of [...menu.uds.keys()]) if (!platoPorId(id)) menu.uds.delete(id);   // un plato que ya no existe sale de la cesta
  pintarMenu(); pintarCesta();
}

function cargarMenu() {
  $("#menu").innerHTML = `<div class="esqueleto" style="height:220px"></div>`;
  menuPromesa = llamarApi("/clustering/platos").then(ponerMenu).catch((error) => {
    $("#menu").innerHTML = `<div class="estado-error" role="alert">${ICONO_ALERTA}<strong>No se ha podido cargar la carta</strong>${esc(error.message)}<br>
      <button type="button" class="boton boton--secundario" id="reintentar-menu">Reintentar</button></div>`;
    $("#reintentar-menu").addEventListener("click", cargarMenu);
  });
  return menuPromesa;
}

function cambiarUnidades(id, delta) {
  const actual = menu.uds.get(id) || 0;
  const total = unidadesTotales();
  const nuevo = Math.min(MAX_UDS_PLATO, Math.max(0, actual + delta));
  if (delta > 0 && total >= MAX_PLATOS) { ponerError("n_platos", `Un pedido admite como máximo ${MAX_PLATOS} platos.`); return; }
  if (nuevo === actual) return;
  if (nuevo) menu.uds.set(id, nuevo); else menu.uds.delete(id);
  pedidoEnEstimacion = null; actualizarResumenCola();
  const fila = $(`.plato-menu[data-id="${id}"]`);                               // se actualiza solo esa fila: así no se pierde el foco del botón
  if (fila) {
    fila.classList.toggle("plato-menu--elegido", nuevo > 0);
    $(".unidades__n", fila).textContent = nuevo;
    $('[data-delta="-1"]', fila).disabled = nuevo === 0;
  }
  pintarCesta();
  ponerError("n_platos", "");
  $("#confirmacion-pedido").innerHTML = "";
  $$(".chip[data-ejemplo]").forEach((c) => c.setAttribute("aria-pressed", "false"));
  estimarConRetraso();
}

$("#menu").addEventListener("click", (e) => {
  const boton = e.target.closest(".unidades__boton");
  if (boton) cambiarUnidades(Number(boton.closest(".plato-menu").dataset.id), Number(boton.dataset.delta));
});
$("#cesta").addEventListener("click", (e) => {
  if (e.target.id !== "vaciar-cesta") return;
  ponerCesta(new Map()); estimarConRetraso();
  $$(".chip[data-ejemplo]").forEach((c) => c.setAttribute("aria-pressed", "false"));
});
$("#buscar-plato").addEventListener("input", (e) => { menu.filtro = e.target.value; pintarMenu(); });
$("#buscar-plato").addEventListener("keydown", (e) => { if (e.key === "Enter") e.preventDefault(); });   // Enter en el buscador no envía el formulario

/* ---------- Pedir (Cliente) y pedidos recibidos (Cocina) ---------- */
// Es una demostración: el pedido solo vive en esta página (no se guarda en servidor ni cambia la cola de la cocina).
$("#boton-pedir").addEventListener("click", () => {
  const { n } = resumirCesta();
  const confirmacion = $("#confirmacion-pedido");
  if (!n) { ponerError("n_platos", "Elige al menos un plato de la carta."); confirmacion.innerHTML = ""; $("#menu").focus(); return; }
  ponerError("n_platos", "");
  const lineas = [...menu.uds].filter(([id]) => platoPorId(id)).map(([id, uds]) => ({ id, uds, nombre: platoPorId(id).nombre }));
  const numero = siguienteNumeroPedido++;
  pedidosRecibidos.unshift({ numero, hora: new Date().toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit" }), lineas, platos: n });
  pintarPedidosRecibidos();
  confirmacion.innerHTML = `<p class="confirmacion" role="status"><strong>Pedido nº ${numero} enviado a cocina</strong> (${n} ${n === 1 ? "plato" : "platos"}). Lo verás en la pestaña Cocina, en «Pedidos recibidos».</p>`;
  ponerCesta(new Map());                                                        // la cesta queda vacía para el siguiente pedido
  $$(".chip[data-ejemplo]").forEach((c) => c.setAttribute("aria-pressed", "false"));
  estimarConRetraso();                                                          // la cola ha crecido: si ya había un resultado, se recalcula
});

function pintarPedidosRecibidos() {
  const lista = $("#pedidos-recibidos");
  actualizarResumenCola();
  if (!pedidosRecibidos.length) { lista.innerHTML = `<li class="recibidos__vacio">Todavía no ha entrado ningún pedido.</li>`; return; }
  lista.innerHTML = pedidosRecibidos.map((p) => `<li class="recibido">
      <div><strong>Pedido nº ${p.numero}</strong> <small>${esc(p.hora)}${p.simulado ? " · de ejemplo" : ""} · ${p.platos} ${p.platos === 1 ? "plato" : "platos"}</small>
        <p>${p.lineas.map((l) => `${l.uds} × ${esc(l.nombre)}`).join(" · ")}</p></div>
      <span class="recibido__botones">
        <button type="button" class="boton boton--secundario boton--pequeno" data-recibido="${p.numero}">Estimar este pedido</button>
        <button type="button" class="boton boton--secundario boton--pequeno" data-listo="${p.numero}" title="Sale de la cola de cocina">Marcar como listo</button></span></li>`).join("");
}
$("#pedidos-recibidos").addEventListener("click", (e) => {
  const listo = e.target.closest("[data-listo]");
  if (listo) {                                                                  // el pedido sale de la cola y el tiempo estimado baja
    pedidosRecibidos = pedidosRecibidos.filter((p) => p.numero !== Number(listo.dataset.listo));
    if (pedidoEnEstimacion === Number(listo.dataset.listo)) pedidoEnEstimacion = null;
    pintarPedidosRecibidos(); estimarConRetraso();
    return;
  }
  const boton = e.target.closest("[data-recibido]");
  if (!boton) return;
  const pedido = pedidosRecibidos.find((p) => p.numero === Number(boton.dataset.recibido));
  if (!pedido) return;
  ponerCesta(new Map(pedido.lineas.filter((l) => platoPorId(l.id)).map((l) => [l.id, l.uds])));   // lo carga en la cesta y lo estima con los datos de cocina actuales
  pedidoEnEstimacion = pedido.numero; actualizarResumenCola();                  // en la cola solo cuentan los pedidos que van antes que él
  $$(".chip[data-ejemplo]").forEach((c) => c.setAttribute("aria-pressed", "false"));
  hayResultado = true;
  estimar({ desdeBoton: true });
});

/* ============================== 5) GRUPOS DE PLATOS (objetivo 1) ============================== */
// Cada grupo tiene color Y forma, para que no dependa solo del color. Se reconocen por el principio de su nombre.
const ESTILOS_GRUPO = [
  { clave: "Estrella", color: "#F28C38", forma: "circulo" },
  { clave: "Popular pero poco rentable", color: "#E8B98A", forma: "cuadrado" },
  { clave: "Rentable pero poco popular", color: "#5C808E", forma: "triangulo" },
  { clave: "Bajo rendimiento", color: "#1F3A44", forma: "rombo" },
];
const estiloDe = (nombre) => ESTILOS_GRUPO.find((e) => nombre.startsWith(e.clave)) || { color: "#42636B", forma: "circulo" };

/** Dibuja la forma de un grupo como elemento SVG (para el gráfico) con centro (x, y) y tamaño r. */
function formaSvg(forma, x, y, r, atributos = "") {
  switch (forma) {
    case "cuadrado": return `<rect x="${x - r}" y="${y - r}" width="${2 * r}" height="${2 * r}" rx="2" ${atributos}/>`;
    case "triangulo": return `<polygon points="${x},${y - r * 1.2} ${x + r * 1.1},${y + r * .9} ${x - r * 1.1},${y + r * .9}" ${atributos}/>`;
    case "rombo": return `<polygon points="${x},${y - r * 1.25} ${x + r * 1.25},${y} ${x},${y + r * 1.25} ${x - r * 1.25},${y}" ${atributos}/>`;
    default: return `<circle cx="${x}" cy="${y}" r="${r}" ${atributos}/>`;
  }
}
const iconoGrupo = (nombre) => { const e = estiloDe(nombre); return `<svg viewBox="0 0 16 16" aria-hidden="true">${formaSvg(e.forma, 8, 8, 5.2, `fill="${e.color}" stroke="#1F3A44" stroke-width="1.4"`)}</svg>`; };

const estadoPlatos = { cargado: false, cargando: false, platos: [], grupos: [], filtro: new Set(), orden: { campo: "nombre", asc: true }, nuevo: null, seleccion: null, zonas: null, medias: {} };
const grafico = $("#grafico"), tooltip = $("#tooltip");

async function cargarPlatos({ forzar = false } = {}) {
  if (forzar) estadoPlatos.cargado = false;
  if (estadoPlatos.cargado || estadoPlatos.cargando) return;
  estadoPlatos.cargando = true;
  grafico.innerHTML = `<div class="esqueleto" style="height:320px"></div>`;
  $("#tarjetas-grupos").innerHTML = [1, 2, 3, 4].map(() => `<div class="esqueleto" style="height:170px;border-radius:14px"></div>`).join("");
  $("#leyenda").innerHTML = "";
  try {
    const [grupos, platos, medias] = await Promise.all([llamarApi("/clustering/grupos"), llamarApi("/clustering/platos"), llamarApi("/clustering/popularidad-por-categoria")]);
    estadoPlatos.medias = Object.fromEntries(medias.map((m) => [m.categoria, m]));
    const posicion = (g) => { const i = ESTILOS_GRUPO.findIndex((e) => g.nombre_grupo.startsWith(e.clave)); return i < 0 ? 99 : i; };
    grupos.sort((a, b) => posicion(a) - posicion(b));                           // mismo orden siempre: de mejor a peor rendimiento
    grupos.forEach((g) => { g.n_platos = platos.filter((p) => p.grupo === g.grupo).length; });   // cuenta también los platos añadidos
    Object.assign(estadoPlatos, { grupos, platos, cargado: true, filtro: new Set(grupos.map((g) => g.grupo)) });
    pintarPlatos();
    ponerMenu(platos);                                                          // la carta del cliente también incluye los platos añadidos
    cargarZonas();                                                              // sin bloquear: el gráfico ya se ve sin las zonas
  } catch (error) {
    const vacio = error.codigo === "datos_no_disponibles";
    grafico.innerHTML = `<div class="estado-error" role="alert">${ICONO_ALERTA}<strong>${vacio ? "No hay platos para mostrar" : "No se han podido cargar los grupos de platos"}</strong>${esc(error.message)}<br>
      <button type="button" class="boton boton--secundario" id="reintentar-platos">Reintentar</button></div>`;
    $("#tarjetas-grupos").innerHTML = ""; $("#resumen-tabla").textContent = "";
    $("tbody", $("#tabla-platos")).innerHTML = "";
    $("#reintentar-platos").addEventListener("click", () => { estadoPlatos.cargando = false; cargarPlatos(); });
  } finally {
    estadoPlatos.cargando = false;
  }
}

/** Pide al modelo en qué grupo caería un plato en cada punto de una rejilla, para pintar las zonas de color del fondo del gráfico. */
async function cargarZonas() {
  const { platos } = estadoPlatos, NX = 40, NY = 24, TROZO = 480;               // 960 puntos, en 2 peticiones (el lote admite 500)
  const relleno = (min, max) => { const r = (max - min) || 1; return [min - r * .08, max + r * .08]; };
  const [x0, x1] = relleno(Math.min(...platos.map((p) => p.popularidad)), Math.max(...platos.map((p) => p.popularidad)));
  const [y0, y1] = relleno(Math.min(...platos.map((p) => p.margen_medio)), Math.max(...platos.map((p) => p.margen_medio)));
  const puntos = [];
  for (let j = 0; j < NY; j++) for (let i = 0; i < NX; i++) puntos.push({ popularidad: x0 + (i + .5) / NX * (x1 - x0), margen_medio: y0 + (j + .5) / NY * (y1 - y0) });
  try {
    const trozos = [];
    for (let k = 0; k < puntos.length; k += TROZO) trozos.push(puntos.slice(k, k + TROZO));
    const respuestas = await Promise.all(trozos.map((t) => llamarApi("/clustering/predecir-lote", { metodo: "POST", cuerpo: { platos: t } })));
    const grupos = respuestas.flatMap((r) => r.resultados.map((x) => x.grupo));
    estadoPlatos.zonas = { x0, x1, y0, y1, NX, NY, grupos };
    pintarGrafico();
  } catch { /* las zonas son un extra: si falla, el gráfico sigue igual */ }
}

function pintarPlatos() {
  pintarLeyenda(); pintarGrafico(); pintarTarjetasGrupos(); pintarTabla(); ajustarAyudaRangos();
}

function ajustarAyudaRangos() {                                                 // el texto de ayuda usa los rangos reales de la carta
  const p = estadoPlatos.platos.filter((x) => !x.es_nuevo);                     // el rango "de la carta" es el de los 80 originales
  const rango = (campo, dec) => [Math.min(...p.map((x) => x[campo])), Math.max(...p.map((x) => x[campo]))].map((v) => formato(v, dec));
  const [pmin, pmax] = rango("popularidad", 3), [mmin, mmax] = rango("margen_medio", 2);
  $("#ayuda-popularidad").textContent = `En la carta actual, entre ${pmin} y ${pmax}.`;
  $("#ayuda-margen").textContent = `Precio − coste. En la carta actual, entre ${mmin} y ${mmax} €.`;
}

function pintarLeyenda() {
  const caja = $("#leyenda");
  caja.innerHTML = estadoPlatos.grupos.map((g) => `<button type="button" class="leyenda__item" data-grupo="${g.grupo}" aria-pressed="${estadoPlatos.filtro.has(g.grupo)}">
      ${iconoGrupo(g.nombre_grupo)}${esc(g.nombre_grupo)}${g.n_platos != null ? ` (${g.n_platos})` : ""}</button>`).join("");
  $$(".leyenda__item", caja).forEach((boton) => boton.addEventListener("click", () => {
    const g = Number(boton.dataset.grupo);
    estadoPlatos.filtro.has(g) ? estadoPlatos.filtro.delete(g) : estadoPlatos.filtro.add(g);
    boton.setAttribute("aria-pressed", estadoPlatos.filtro.has(g));
    pintarGrafico(); pintarTabla();
  }));
}

/* ---------- Gráfico de dispersión en SVG ---------- */
function ticks(min, max, n = 5) {
  const paso = (max - min) / (n - 1);
  return Array.from({ length: n }, (_, i) => min + paso * i);
}
function pintarGrafico() {
  const { platos, grupos, filtro, nuevo } = estadoPlatos;
  const ancho = 760, alto = 440, m = { i: 62, d: 18, s: 18, b: 56 };
  const xs = platos.map((p) => p.popularidad).concat(nuevo && nuevo.popularidad != null ? [nuevo.popularidad] : []);
  const ys = platos.map((p) => p.margen_medio).concat(nuevo ? [nuevo.margen_medio] : []);
  const relleno = (min, max) => { const r = (max - min) || 1; return [min - r * .08, max + r * .08]; };
  const [x0, x1] = relleno(Math.min(...xs), Math.max(...xs)), [y0, y1] = relleno(Math.min(...ys), Math.max(...ys));
  const X = (v) => m.i + (v - x0) / (x1 - x0) * (ancho - m.i - m.d);
  const Y = (v) => alto - m.b - (v - y0) / (y1 - y0) * (alto - m.b - m.s);
  const nombreDe = new Map(grupos.map((g) => [g.grupo, g.nombre_grupo]));

  let svg = `<svg viewBox="0 0 ${ancho} ${alto}" role="img" aria-label="Gráfico de dispersión de los platos: popularidad en el eje horizontal y margen medio en el vertical. La misma información está en la tabla de abajo.">`;
  if (estadoPlatos.zonas) {                                                     // zonas de color: dónde caería un plato nuevo según el modelo
    const z = estadoPlatos.zonas, ax = (z.x1 - z.x0) / z.NX, ay = (z.y1 - z.y0) / z.NY;
    z.grupos.forEach((g, k) => {
      const i = k % z.NX, j = Math.floor(k / z.NX), nombre = nombreDe.get(g);
      if (!nombre || !filtro.has(g)) return;
      const xa = X(z.x0 + i * ax), xb = X(z.x0 + (i + 1) * ax), yb = Y(z.y0 + j * ay), ya = Y(z.y0 + (j + 1) * ay);
      svg += `<rect class="zona" x="${xa}" y="${ya}" width="${xb - xa + .6}" height="${yb - ya + .6}" fill="${estiloDe(nombre).color}" fill-opacity=".16"/>`;
    });
  }
  for (const t of ticks(y0, y1)) svg += `<line class="rejilla-linea" x1="${m.i}" x2="${ancho - m.d}" y1="${Y(t)}" y2="${Y(t)}"/><text class="eje-texto" x="${m.i - 8}" y="${Y(t) + 4}" text-anchor="end">${formato(t, 2)}</text>`;
  for (const t of ticks(x0, x1)) svg += `<line class="rejilla-linea" y1="${m.s}" y2="${alto - m.b}" x1="${X(t)}" x2="${X(t)}"/><text class="eje-texto" x="${X(t)}" y="${alto - m.b + 18}" text-anchor="middle">${formato(t, 3)}</text>`;
  svg += `<line class="eje-linea" x1="${m.i}" x2="${ancho - m.d}" y1="${alto - m.b}" y2="${alto - m.b}"/><line class="eje-linea" x1="${m.i}" x2="${m.i}" y1="${m.s}" y2="${alto - m.b}"/>`;
  svg += `<text class="eje-titulo" x="${(m.i + ancho - m.d) / 2}" y="${alto - 12}" text-anchor="middle">Popularidad (unidades vendidas por cliente)</text>`;
  svg += `<text class="eje-titulo" transform="translate(16 ${(m.s + alto - m.b) / 2}) rotate(-90)" text-anchor="middle">Margen medio (€ por unidad)</text>`;

  const R = 6, posiciones = platos.map((p) => ({ x: X(p.popularidad), y: Y(p.margen_medio) }));
  platos.forEach((p, i) => {                                                    // un punto por plato
    const e = estiloDe(p.nombre_grupo), visible = filtro.has(p.grupo), q = posiciones[i], sel = p.id_plato === estadoPlatos.seleccion;
    svg += `<g class="punto ${visible ? "" : "punto--oculto"} ${sel ? "punto--sel" : ""}" data-i="${i}">
      <circle cx="${q.x}" cy="${q.y}" r="${R + 6}" fill="transparent"/>${sel ? `<circle class="anillo-sel" cx="${q.x}" cy="${q.y}" r="${R + 6}"/>` : ""}${p.es_nuevo ? `<circle class="anillo-nuevo" cx="${q.x}" cy="${q.y}" r="${R + 4}"/>` : ""}
      ${formaSvg(e.forma, q.x, q.y, R, `fill="${e.color}" stroke="#1F3A44" stroke-width="1.5" fill-opacity=".92"`)}</g>`;
  });
  if (nuevo && nuevo.popularidad != null) {                                     // el plato que ha clasificado la persona
    const cx = X(nuevo.popularidad), cy = Y(nuevo.margen_medio), e = estiloDe(nuevo.nombre_grupo);
    svg += `<g class="plato-nuevo"><circle class="plato-nuevo__anillo" cx="${cx}" cy="${cy}" r="14" fill="none" stroke="#1F3A44" stroke-width="2"/>
      ${formaSvg(e.forma, cx, cy, 9, `fill="${e.color}" stroke="#1F3A44" stroke-width="3"`)}
      <text x="${cx}" y="${cy - 20}" text-anchor="middle" class="eje-titulo" paint-order="stroke" stroke="#fff" stroke-width="4">Tu plato</text></g>`;
  } else if (nuevo) {                                                           // sin popularidad: no hay un punto, hay una franja de posibilidades
    const xa = X(Math.min(...platos.map((p) => p.popularidad))), xb = X(Math.max(...platos.map((p) => p.popularidad))), cy = Y(nuevo.margen_medio);
    svg += `<g class="plato-nuevo"><line x1="${xa}" x2="${xb}" y1="${cy}" y2="${cy}" stroke="#F28C38" stroke-width="9" stroke-linecap="round" opacity=".55"/>
      <line x1="${xa}" x2="${xb}" y1="${cy}" y2="${cy}" stroke="#1F3A44" stroke-width="2.5" stroke-dasharray="7 5" stroke-linecap="round"/>
      <text x="${(xa + xb) / 2}" y="${cy - 14}" text-anchor="middle" class="eje-titulo" paint-order="stroke" stroke="#fff" stroke-width="4">Tu plato (sin popularidad)</text></g>`;
  }
  grafico.innerHTML = svg + "</svg>";

  $$(".punto", grafico).forEach((nodo) => {                                      // información al pasar el ratón
    const p = platos[nodo.dataset.i];
    const mostrar = (ev) => {
      tooltip.innerHTML = `<strong>${esc(p.nombre)}</strong>${p.categoria ? ` · ${esc(p.categoria)}` : ""}${p.es_nuevo ? (p.popularidad_estimada ? " · añadido (popularidad estimada)" : " · añadido") : ""}<br>${esc(nombreDe.get(p.grupo) || p.nombre_grupo)}<br>Popularidad: ${formato(p.popularidad, 3)}<br>Margen: ${formato(p.margen_medio, 2)} €`;
      tooltip.hidden = false;
      const caja = tooltip.getBoundingClientRect();
      tooltip.style.left = `${Math.min(ev.clientX + 14, window.innerWidth - caja.width - 8)}px`;
      tooltip.style.top = `${Math.min(ev.clientY + 14, window.innerHeight - caja.height - 8)}px`;
    };
    nodo.addEventListener("pointermove", mostrar);
    nodo.addEventListener("pointerleave", () => { tooltip.hidden = true; });
    nodo.addEventListener("click", () => seleccionarPlato(p.id_plato, { desdeGrafico: true }));
  });
}

/** Cuando un plato guardado con la media de su categoría ya tiene ventas: se sustituye por su popularidad real. */
async function ponerPopularidadReal(plato) {
  const entrada = $("#popularidad-real"), error = $("#error-popularidad-real"), v = Number(entrada.value);
  error.textContent = "";
  if (entrada.value.trim() === "" || Number.isNaN(v) || v < 0 || v > 100) { error.textContent = "Escribe un número entre 0 y 100."; entrada.focus(); return; }
  $("#boton-poner-real").disabled = true;
  try {
    const nuevo = await llamarApi(`/clustering/platos-nuevos/${plato.id_plato}`, { metodo: "PATCH", cuerpo: { popularidad: v } });
    estadoPlatos.seleccion = nuevo.id_plato;
    await cargarPlatos({ forzar: true });
    $("#detalle-plato").innerHTML = `<strong>${esc(nuevo.nombre)}</strong>: popularidad real guardada (${formato(nuevo.popularidad, 3)}) · ahora es ${esc(nuevo.nombre_grupo)}.`;
  } catch (e) {
    error.textContent = e.message; $("#boton-poner-real").disabled = false;
  }
}

/** Elimina un plato añadido. Dos pasos (primer clic: "¿Seguro?", segundo: borra) para no borrar por accidente. */
let temporizadorEliminar = null;
async function eliminarPlato(plato, boton) {
  if (!boton.classList.contains("confirmar")) {
    boton.classList.add("confirmar"); boton.textContent = "¿Seguro? Pulsa otra vez";
    clearTimeout(temporizadorEliminar);
    temporizadorEliminar = setTimeout(() => { boton.classList.remove("confirmar"); boton.textContent = "Eliminar plato"; }, 4000);
    return;
  }
  boton.disabled = true;
  try {
    await llamarApi(`/clustering/platos-nuevos/${plato.id_plato}`, { metodo: "DELETE" });
    estadoPlatos.seleccion = null;
    $("#detalle-plato").textContent = `«${plato.nombre}» eliminado.`;
    await cargarPlatos({ forzar: true });
  } catch (error) {
    $("#detalle-plato").textContent = `No se ha podido eliminar: ${error.message}`;
  }
}

/** Marca un plato (o lo desmarca si ya lo estaba): se resalta en el gráfico y en la tabla, y se describe encima del gráfico. */
function seleccionarPlato(id, { desdeGrafico = false } = {}) {
  estadoPlatos.seleccion = estadoPlatos.seleccion === id ? null : id;
  const p = estadoPlatos.platos.find((x) => x.id_plato === estadoPlatos.seleccion);
  $("#detalle-plato").innerHTML = p
    ? `<strong>${esc(p.nombre)}</strong> (${esc(p.categoria ?? "–")}) · ${esc(p.nombre_grupo)} · popularidad ${formato(p.popularidad, 3)} · margen ${formato(p.margen_medio, 2)} €${p.es_nuevo ? `<button type="button" class="boton" id="boton-eliminar">Eliminar plato</button>` : ""}${p.es_nuevo && p.popularidad_estimada ? `<span class="poner-real"><label class="sr-only" for="popularidad-real">Popularidad real</label><input id="popularidad-real" type="number" step="0.001" min="0" max="100" placeholder="popularidad real"><button type="button" class="boton" id="boton-poner-real">Poner popularidad real</button><span class="poner-real__error" id="error-popularidad-real" role="alert"></span></span>` : ""}`
    : "Pasa el ratón por un punto para ver el plato.";
  $("#boton-eliminar")?.addEventListener("click", (e) => eliminarPlato(p, e.currentTarget));
  $("#boton-poner-real")?.addEventListener("click", () => ponerPopularidadReal(p));
  pintarGrafico(); pintarTabla();
  if (p && desdeGrafico) $("#tabla-platos tr.fila--sel")?.scrollIntoView({ block: "nearest", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
}

function pintarTarjetasGrupos() {
  $("#tarjetas-grupos").innerHTML = estadoPlatos.grupos.map((g) => {
    const e = estiloDe(g.nombre_grupo);
    return `<article class="grupo-tarjeta" style="border-top-color:${e.color}">
      <h3>${iconoGrupo(g.nombre_grupo)}${esc(g.nombre_grupo)}</h3>
      <p class="grupo-tarjeta__n">${g.n_platos ?? "–"} <small>platos</small></p>
      <dl><div><dt>Popularidad media</dt><dd>${formato(g.centroide.popularidad, 3)}</dd></div>
          <div><dt>Margen medio</dt><dd>${formato(g.centroide.margen_medio, 2)} €</dd></div></dl>
      <p>${esc(g.sugerencia)}</p></article>`;
  }).join("");
}

/* ---------- Tabla ordenable ---------- */
function pintarTabla() {
  const { platos, filtro, orden } = estadoPlatos;
  const filas = platos.filter((p) => filtro.has(p.grupo)).sort((a, b) => {
    const va = a[orden.campo], vb = b[orden.campo];
    const c = typeof va === "string" ? va.localeCompare(vb, "es") : (va ?? -Infinity) - (vb ?? -Infinity);
    return orden.asc ? c : -c;
  });
  $("#resumen-tabla").textContent = `Mostrando ${filas.length} de ${platos.length} platos. Pulsa el título de una columna para ordenar o una fila para verla en el gráfico.`;
  const celda = (v, dec) => (v == null ? "–" : formato(v, dec));
  $("tbody", $("#tabla-platos")).innerHTML = filas.length ? filas.map((p) => `<tr data-id="${esc(p.id_plato)}" class="${p.id_plato === estadoPlatos.seleccion ? "fila--sel" : ""}" aria-selected="${p.id_plato === estadoPlatos.seleccion}">
      <td class="celda-plato">${esc(p.nombre)}${p.es_nuevo ? `<span class="etiqueta-nuevo ${p.popularidad_estimada ? "etiqueta-nuevo--estimada" : ""}">${p.popularidad_estimada ? "Añadido · popularidad estimada" : "Añadido"}</span>` : ""}</td><td class="cap">${esc(p.categoria ?? "–")}</td><td><span class="celda-grupo">${iconoGrupo(p.nombre_grupo)}${esc(p.nombre_grupo)}</span></td>
      <td class="num">${celda(p.popularidad, 3)}</td><td class="num">${celda(p.margen_medio, 2)}</td><td class="num">${celda(p.precio_medio, 2)}</td>
      <td class="num">${celda(p.coste_medio, 2)}</td><td class="num">${celda(p.valoracion, 1)}</td><td class="num">${celda(p.dificultad, 0)}</td></tr>`).join("")
    : `<tr><td colspan="9" class="tabla-vacia">No hay platos con los grupos seleccionados. Activa algún grupo en la leyenda del gráfico.</td></tr>`;
  $$("#tabla-platos tbody tr[data-id]").forEach((fila) => fila.addEventListener("click", () => seleccionarPlato(Number(fila.dataset.id))));
  $$("#tabla-platos th").forEach((th) => {
    const campo = $("button", th).dataset.orden;
    th.setAttribute("aria-sort", campo === orden.campo ? (orden.asc ? "ascending" : "descending") : "none");
  });
}
$$("#tabla-platos th button").forEach((boton) => boton.addEventListener("click", () => {
  const campo = boton.dataset.orden, o = estadoPlatos.orden;
  estadoPlatos.orden = { campo, asc: o.campo === campo ? !o.asc : true };
  pintarTabla();
}));

/* ---------- Añadir un plato: ver dónde cae (prueba) o guardarlo (permanente) ---------- */
const formPlato = $("#form-plato"), salidaPlato = $("#resultado-plato"), sinPopularidad = $("#sin-popularidad"), botonGuardar = $("#boton-guardar");
const euros = (n) => `${formato(n, 2)} €`;
const redondear2 = (n) => Math.round(n * 100) / 100;

/** Muestra el margen (precio − coste) mientras se escribe. */
function actualizarMargen() {
  const precio = Number($("#precio_medio").value), coste = Number($("#coste_medio").value);
  const caja = $("#margen-calculado"), valido = $("#precio_medio").value.trim() !== "" && $("#coste_medio").value.trim() !== "" && !Number.isNaN(precio) && !Number.isNaN(coste);
  caja.textContent = valido ? euros(redondear2(precio - coste)) : "–";
  caja.classList.toggle("negativo", valido && precio - coste < 0);
}
/** Sin ventas: avisa de qué popularidad se usaría al guardar (la media de la categoría elegida). */
function actualizarNotaMedia() {
  const nota = $("#nota-media"), media = estadoPlatos.medias[$("#categoria").value];
  nota.hidden = !sinPopularidad.checked;
  if (!sinPopularidad.checked) return;
  nota.textContent = media
    ? `Si lo guardas ahora se usará la popularidad media de los platos de categoría «${$("#categoria").value}»: ${formato(media.popularidad_media, 3)} (media de ${media.n_platos} platos). Es un supuesto, no un dato.`
    : "Si lo guardas ahora se usará la popularidad media de su categoría (se calcula al guardar). Es un supuesto, no un dato.";
}
function actualizarBotonGuardar() {
  botonGuardar.textContent = sinPopularidad.checked ? "Guardar con la media de su categoría" : "Guardar plato";
}
$("#categoria").addEventListener("change", actualizarNotaMedia);
sinPopularidad.addEventListener("change", () => {
  $("#popularidad").disabled = sinPopularidad.checked;
  $("#ayuda-sin-popularidad").hidden = !sinPopularidad.checked;
  ponerError("popularidad", "");
  actualizarBotonGuardar(); actualizarNotaMedia();
});
["precio_medio", "coste_medio"].forEach((id) => $(`#${id}`).addEventListener("input", actualizarMargen));

/** Lee y valida el formulario. Para guardar, el nombre y la popularidad son obligatorios; para probar, no. */
function leerPlato({ guardar }) {
  const plato = {}, errores = {};
  const numero = (campo, nombre, min, max, { entero = false } = {}) => {
    const texto = $(`#${campo}`).value.trim(), v = Number(texto);
    if (texto === "" || Number.isNaN(v)) errores[campo] = `${nombre}: escribe un número.`;
    else if (entero && !Number.isInteger(v)) errores[campo] = `${nombre}: debe ser un número entero.`;
    else if (v < min || v > max) errores[campo] = `${nombre}: debe estar entre ${min} y ${max}.`;
    else plato[campo] = v;
  };
  const nombre = $("#nombre").value.trim().replace(/\s+/g, " ");
  if (nombre === "" && guardar) errores.nombre = "Escribe el nombre del plato.";
  else if (nombre !== "" && (nombre.length < 2 || nombre.length > 60)) errores.nombre = "El nombre debe tener entre 2 y 60 caracteres.";
  else if (/^[=+\-@]/.test(nombre)) errores.nombre = "El nombre no puede empezar por =, +, - ni @.";
  else plato.nombre = nombre;
  plato.categoria = $("#categoria").value;
  numero("precio_medio", "El precio", 0, 1000);
  numero("coste_medio", "El coste", 0, 1000);
  numero("dificultad", "La dificultad", 1, 10, { entero: true });
  if (!sinPopularidad.checked) numero("popularidad", "La popularidad", 0, 100);
  for (const campo of ["nombre", "precio_medio", "coste_medio", "dificultad", "popularidad"]) ponerError(campo, errores[campo]);
  if ("precio_medio" in plato && "coste_medio" in plato) plato.margen_medio = redondear2(plato.precio_medio - plato.coste_medio);
  return { plato, errores };
}
formPlato.addEventListener("input", (e) => { if (e.target.id) ponerError(e.target.id, ""); });
formPlato.addEventListener("change", (e) => { if (e.target.id) ponerError(e.target.id, ""); });

function pintarResultadoPrueba(r) {
  const avisos = r.avisos?.length ? `<ul class="avisos">${r.avisos.map((a) => `<li>${esc(a)}</li>`).join("")}</ul>` : "";
  const e2 = estiloDe(r.nombre_grupo), borde = e2.color === "#E8B98A" ? "#C4621A" : e2.color;
  const provisional = r.popularidad_conocida === false;
  const reparto = provisional ? `<div><p><strong>Dónde puede caer</strong> según su popularidad futura:</p><ul class="posibles">${r.grupos_posibles.map((g) => {
    const c = estiloDe(g.nombre_grupo);
    return `<li><span class="posibles__nombre">${iconoGrupo(g.nombre_grupo)}${esc(g.nombre_grupo)}</span><span class="posibles__valor">${formato(g.porcentaje, 0)} %</span>
      <span class="posibles__barra" aria-hidden="true"><span style="width:${g.porcentaje}%;background:${c.color}"></span></span></li>`;
  }).join("")}</ul></div>` : "";
  salidaPlato.innerHTML = `<div class="resultado-plato">
    ${provisional ? `<p class="nota" style="margin:0"><strong>Grupo provisional</strong> (el más frecuente):</p>` : `<p class="nota" style="margin:0">Prueba (todavía no está guardado):</p>`}
    <span class="insignia ${provisional ? "insignia--provisional" : ""}" style="border-color:${borde}">${iconoGrupo(r.nombre_grupo)}${esc(r.nombre_grupo)}</span>
    ${reparto}
    <p class="resultado-plato__sugerencia">${esc(r.sugerencia)}</p>
    ${provisional ? "" : `<p><strong>Distancia al centro del grupo:</strong> ${formato(r.distancia_al_centroide, 2)} (0 = justo en el centro; más de 2 = plato atípico dentro de su grupo).</p>`}
    ${provisional ? `<button type="button" class="boton boton--secundario" id="boton-ya-ventas">Ya tiene ventas: indicar su popularidad</button>` : `<p class="nota" style="margin:0">Si te convence, pulsa «Guardar plato» para dejarlo en el gráfico y en el CSV.</p>`}
    ${avisos}<p class="nota">Modelo: ${esc(r.modelo.nombre)} · v${esc(r.modelo.version)}</p></div>`;
  $("#boton-ya-ventas")?.addEventListener("click", () => {                      // pasa de "provisional" a "definitivo": hay que dar la popularidad real
    sinPopularidad.checked = false; sinPopularidad.dispatchEvent(new Event("change"));
    $("#popularidad").focus(); $("#popularidad").select();
  });
}
const mostrarErrorPlato = (titulo, error) => {
  salidaPlato.innerHTML = `<div class="estado-error" role="alert" style="margin-top:16px">${ICONO_ALERTA}<strong>${titulo}</strong>${esc(error.message)}</div>`;
  if (error.estado === 422) for (const d of error.detalles) ponerError(d.campo.split(".")[0], d.mensaje);
};

/* "Ver dónde cae": no guarda nada, solo dibuja el plato (punto o línea) en el gráfico */
formPlato.addEventListener("submit", async (e) => {
  e.preventDefault();
  const { plato, errores } = leerPlato({ guardar: false });
  if (Object.keys(errores).length) { $("[aria-invalid=true]", formPlato)?.focus(); return; }
  const boton = $("#boton-clasificar");
  boton.disabled = true; boton.textContent = "Calculando…";
  salidaPlato.innerHTML = `<div class="resultado-plato"><div class="esqueleto" style="height:28px;width:70%"></div><div class="esqueleto" style="height:48px"></div></div>`;
  try {
    const cuerpo = { margen_medio: plato.margen_medio };
    if (!sinPopularidad.checked) cuerpo.popularidad = plato.popularidad;
    const r = await llamarApi("/clustering/predecir", { metodo: "POST", cuerpo });
    pintarResultadoPrueba(r);
    estadoPlatos.nuevo = { popularidad: cuerpo.popularidad ?? null, margen_medio: plato.margen_medio, nombre_grupo: r.nombre_grupo };
    $("#boton-quitar-plato").hidden = false;
    if (estadoPlatos.cargado) pintarGrafico(); else await cargarPlatos();
  } catch (error) {
    mostrarErrorPlato("No se ha podido calcular el grupo del plato", error);
  } finally {
    boton.disabled = false; boton.textContent = "Ver dónde cae";
  }
});

/* "Guardar plato": lo añade para siempre (CSV) y pasa a ser un punto más del gráfico */
botonGuardar.addEventListener("click", async () => {
  const { plato, errores } = leerPlato({ guardar: true });
  if (Object.keys(errores).length) { $("[aria-invalid=true]", formPlato)?.focus(); return; }
  delete plato.margen_medio;                                                     // lo calcula la API (precio − coste)
  if (sinPopularidad.checked) plato.estimar_popularidad = true;                  // sin ventas: la API usa la media de la categoría
  botonGuardar.disabled = true; botonGuardar.textContent = "Guardando…";
  try {
    const guardado = await llamarApi("/clustering/platos-nuevos", { metodo: "POST", cuerpo: plato });
    estadoPlatos.nuevo = null; estadoPlatos.seleccion = guardado.id_plato;     // se queda seleccionado para verlo enseguida
    $("#boton-quitar-plato").hidden = true;
    salidaPlato.innerHTML = `<div class="guardado" role="status"><strong>«${esc(guardado.nombre)}» guardado.</strong>
      <span>Margen: ${euros(guardado.margen_medio)} · Grupo: <strong>${esc(guardado.nombre_grupo)}</strong>.</span>
      ${guardado.popularidad_estimada ? `<span>Popularidad <strong>estimada</strong>: ${formato(guardado.popularidad, 3)} (media de su categoría). Cuando tenga ventas, selecciónalo en el gráfico y pulsa «Poner popularidad real».</span>` : ""}
      <span>Ya está en el gráfico y en <code>data/platos_nuevos.csv</code>, y seguirá ahí cuando reinicies.</span></div>`;
    formPlato.reset(); actualizarMargen(); sinPopularidad.dispatchEvent(new Event("change"));      // listo para el siguiente
    await cargarPlatos({ forzar: true });
    estadoPlatos.seleccion = null; seleccionarPlato(guardado.id_plato);          // lo selecciona y escribe su detalle
  } catch (error) {
    mostrarErrorPlato("No se ha podido guardar el plato", error);
  } finally {
    botonGuardar.disabled = false; actualizarBotonGuardar();
  }
});
$("#boton-quitar-plato").addEventListener("click", () => {
  estadoPlatos.nuevo = null; salidaPlato.innerHTML = ""; $("#boton-quitar-plato").hidden = true;
  if (estadoPlatos.cargado) pintarGrafico();
});

/* ============================== ARRANQUE ============================== */
pintarVacio();
cargarMenu();
actualizarNombreDia();
actualizarResumenCola();
actualizarMargen();
$$("input[type=range]").forEach(pintarRelleno);
comprobarSalud();
setInterval(comprobarSalud, 60000);                                             // el chip de estado se refresca cada minuto
mostrarSeccion(location.hash === "#tiempo" ? "tiempo" : "platos");     // la primera pestaña (Objetivo 1) es la que se abre por defecto
