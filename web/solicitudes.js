// =====================================================================
// Hotel Soluna: solicitudes de huéspedes (panel del personal, etapa 3)
// Dos pantallas que comparten el mismo modelo de mensajes:
//   - Personal: bandeja de solicitudes de su área y la conversación elegida,
//     para responder, tomar, reasignar o resolver. Recepción y gerencia
//     pueden simular el pedido de un huésped alojado.
//   - Huésped: chat con el hotel durante su estadía, desde "Mis reservas".
// Usa las utilidades de app.js (api, el, avisar...) y abre la gestión de
// reservas de gestion.js. Todo texto se inserta como texto, nunca como HTML.
//
// Consumo de la base: las pantallas preguntan solo mientras están visibles
// y piden únicamente lo nuevo. El personal, cada 10 s con una conversación
// abierta y cada 30 s con solo la bandeja; el huésped, cada 10 s con el
// chat abierto. Cada 10 consultas, la bandeja se recarga completa para
// descartar lo que otra persona pasó a otra área.
// =====================================================================
'use strict';

const AREAS = { recepcion: 'Recepción', limpieza: 'Limpieza', mantenimiento: 'Mantenimiento' };
const ESTADOS_SOLICITUD = { abierta: 'Abierta', en_atencion: 'En atención', resuelta: 'Resuelta' };
const AREA_DEL_ROL = { limpieza: 'limpieza', mantenimiento: 'mantenimiento' };   // los demás ven todas
const CADA_CONVERSACION = 10 * 1000;
const CADA_BANDEJA = 30 * 1000;
const CADA_CHAT_HUESPED = 10 * 1000;
const RECARGA_COMPLETA_CADA = 10;

const horaMensaje = (iso) => new Date(iso).toLocaleTimeString('es-CR', { hour: '2-digit', minute: '2-digit' });

/** Tiempo transcurrido desde una fecha, en palabras cortas: "3 min", "2 h", "1 día". */
function haceCuanto(iso) {
  const minutos = Math.max(0, Math.round((Date.now() - new Date(iso)) / 60000));
  if (minutos < 1) return 'menos de 1 min';
  if (minutos < 60) return `${minutos} min`;
  const horas = Math.round(minutos / 60);
  return horas < 24 ? `${horas} h` : `${Math.round(horas / 24)} d`;
}

/**
 * Un mensaje del chat como globo. `propio` indica si lo escribió quien mira la pantalla (va a la
 * derecha); `quien` es el nombre que se muestra arriba del texto.
 */
function globoMensaje(m, propio, quien) {
  return el('li', { clase: propio ? 'propio' : 'ajeno', 'data-id': String(m.id) },
    el('span', { clase: 'meta' }, `${quien} · ${horaMensaje(m.creado_en)}`),
    el('span', { clase: 'texto' }, m.texto));
}

/** Baja la lista hasta el último mensaje. */
function alFinal(lista) {
  lista.scrollTop = lista.scrollHeight;
}

// =====================================================================
// Personal: bandeja y conversación
// =====================================================================
const solicitudes = new Map();      // id -> solicitud, tal como la devuelve la API
let cursorSolicitudes = null;       // "ahora" de la última consulta: la siguiente pide solo lo cambiado
let solicitudAbierta = null;        // id de la conversación en pantalla
let ultimoMensaje = 0;              // id del último mensaje mostrado
let filtroSolicitudes = 'activas';
let ultimaConsultaSolicitudes = 0;
let consultasDesdeRecarga = 0;

/** La tarjeta de solicitudes está a la vista (sesión del personal, tarjeta visible y pestaña activa). */
function solicitudesVisibles() {
  return Boolean(sesion.token) && !$('#sec-solicitudes').hidden && document.visibilityState === 'visible';
}

/**
 * Consulta la bandeja. Completa (al entrar, con "Actualizar" y cada 10 consultas) reemplaza todo;
 * si no, pide solo lo que cambió desde la consulta anterior y los mensajes nuevos de la conversación
 * abierta, y lo combina con lo que ya hay en pantalla.
 */
async function cargarSolicitudes(completa = false) {
  if (completa) consultasDesdeRecarga = 0;
  const parametros = new URLSearchParams();
  if (!completa && cursorSolicitudes) parametros.set('desde', cursorSolicitudes);
  if (solicitudAbierta) {
    parametros.set('abierta', solicitudAbierta);
    parametros.set('despues', ultimoMensaje);
  }
  let datos;
  try {
    datos = await api(`/api/solicitudes?${parametros}`);
  } catch (error) {
    // La conversación abierta pasó a otra área: se cierra y se vuelve a pedir la bandeja
    if (solicitudAbierta && error.message === 'Solicitud no encontrada') {
      cerrarConversacion('La solicitud pasó a otra área.');
      return cargarSolicitudes(true);
    }
    throw error;
  }
  if (!parametros.has('desde')) solicitudes.clear();   // consulta completa: se reemplaza todo
  for (const s of datos.solicitudes) solicitudes.set(s.id, s);
  cursorSolicitudes = datos.ahora;
  ultimaConsultaSolicitudes = Date.now();
  consultasDesdeRecarga += 1;

  if (solicitudAbierta) agregarMensajesPersonal(datos.mensajes);
  mostrarBandeja();
  if (solicitudAbierta) mostrarEncabezadoConversacion();
  $('#actualizado-solicitudes').textContent = `Actualizado a las ${horaMensaje(new Date().toISOString())}`;
}

/** Cuántas solicitudes esperan respuesta: el número rojo junto al título. */
function mostrarPendientes() {
  const pendientes = [...solicitudes.values()].filter((s) => s.pendiente_desde && s.estado !== 'resuelta').length;
  const contador = $('#pendientes-solicitudes');
  contador.textContent = `${pendientes} sin responder`;
  contador.hidden = pendientes === 0;
}

/**
 * Dibuja la bandeja según el filtro. Primero las que esperan respuesta (la que más espera arriba),
 * después las demás, de la más reciente a la más antigua.
 */
function mostrarBandeja() {
  mostrarPendientes();
  const lista = [...solicitudes.values()]
    .filter((s) => (filtroSolicitudes === 'resueltas') === (s.estado === 'resuelta'))
    .sort((a, b) => {
      if (Boolean(a.pendiente_desde) !== Boolean(b.pendiente_desde)) return a.pendiente_desde ? -1 : 1;
      if (a.pendiente_desde) return a.pendiente_desde.localeCompare(b.pendiente_desde);
      return b.actualizada_en.localeCompare(a.actualizada_en);
    });
  const bandeja = $('#bandeja-solicitudes');
  if (!lista.length) {
    bandeja.replaceChildren(el('li', { clase: 'vacio' }, filtroSolicitudes === 'resueltas'
      ? 'No hay solicitudes resueltas hoy.' : 'No hay solicitudes activas. Cuando un huésped escriba, aparecerá aquí.'));
    return;
  }
  bandeja.replaceChildren(...lista.map((s) => el('li', {},
    el('button', {
      type: 'button', clase: `solicitud area-${s.categoria}`,
      'aria-current': String(s.id === solicitudAbierta),
      onclick: () => intentar(() => abrirConversacion(s.id)),
    },
    el('span', { clase: 'linea' },
      el('strong', {}, `Hab. ${s.habitacion}`), ` ${s.nombre_huesped}`),
    el('span', { clase: 'linea' },
      el('span', { clase: `estado area ${s.categoria}` }, AREAS[s.categoria]),
      etiquetaEstado(s.estado, ESTADOS_SOLICITUD),
      s.simulada ? el('span', { clase: 'estado simulada' }, 'Simulada') : null,
      s.pendiente_desde ? el('span', { clase: 'espera' }, `Espera ${haceCuanto(s.pendiente_desde)}`) : null),
    s.ultimo_mensaje ? el('span', { clase: 'vista-previa' }, s.ultimo_mensaje) : null))));
}

/** Elige el filtro de la bandeja (activas o resueltas hoy). */
function filtrarSolicitudes(filtro) {
  filtroSolicitudes = filtro;
  for (const boton of document.querySelectorAll('[data-filtro-solicitudes]')) {
    boton.setAttribute('aria-pressed', String(boton.dataset.filtroSolicitudes === filtro));
  }
  mostrarBandeja();
}

/** Abre una conversación: muestra su encabezado y pide todos sus mensajes. */
async function abrirConversacion(id) {
  solicitudAbierta = id;
  ultimoMensaje = 0;
  $('#conv-mensajes').replaceChildren();
  $('#conversacion-vacia').hidden = true;
  $('#conversacion-activa').hidden = false;
  mostrarEncabezadoConversacion();
  mostrarBandeja();
  await cargarSolicitudes();
  $('#respuesta-texto').focus();
}

/** Cierra la conversación en pantalla, con una nota opcional. */
function cerrarConversacion(nota = 'Elija una solicitud para ver la conversación.') {
  solicitudAbierta = null;
  ultimoMensaje = 0;
  $('#conversacion-activa').hidden = true;
  $('#conversacion-vacia').hidden = false;
  $('#conversacion-vacia').textContent = nota;
}

/** Encabezado de la conversación: habitación, huésped, reserva, estado y los botones que aplican. */
function mostrarEncabezadoConversacion() {
  const s = solicitudes.get(solicitudAbierta);
  if (!s) return;
  $('#conv-titulo').textContent = `Habitación ${s.habitacion} · ${s.nombre_huesped}`;
  const reserva = ['recepcionista', 'gerente'].includes(sesion.rol)
    ? el('button', { type: 'button', clase: 'codigo-reserva', onclick: () => intentar(() => abrirGestion(s.codigo_reserva)) },
      s.codigo_reserva)
    : el('code', {}, s.codigo_reserva);
  const partes = [reserva, ` · ${ESTADOS_SOLICITUD[s.estado]}`,
    s.asignada_a ? ` · atiende ${s.asignada_a}` : ' · sin asignar'];
  if (s.pendiente_desde) partes.push(el('span', { clase: 'espera' }, ` · espera ${haceCuanto(s.pendiente_desde)}`));
  $('#conv-detalle').replaceChildren(...partes);
  $('#conv-area').value = s.categoria;
  const resuelta = s.estado === 'resuelta';
  $('#conv-tomar').hidden = resuelta || s.asignada_a === sesion.nombre;
  $('#conv-resolver').hidden = resuelta;
  $('#conv-reabrir').hidden = !resuelta;
  $('#respuesta-texto').disabled = resuelta;
  $('#form-respuesta button[type=submit]').disabled = resuelta;
  $('#respuesta-texto').placeholder = resuelta
    ? 'La solicitud está resuelta. Reábrala para seguir conversando.' : 'Escriba la respuesta al huésped';
}

/** Agrega a la conversación los mensajes que aún no se muestran. */
function agregarMensajesPersonal(lista) {
  const nuevos = lista.filter((m) => m.id > ultimoMensaje);
  if (!nuevos.length) return;
  const s = solicitudes.get(solicitudAbierta);
  const conversacion = $('#conv-mensajes');
  conversacion.append(...nuevos.map((m) => globoMensaje(m, m.autor === 'personal',
    m.autor === 'personal' ? (m.nombre || 'Personal') : (s ? s.nombre_huesped : 'Huésped'))));
  ultimoMensaje = nuevos[nuevos.length - 1].id;
  alFinal(conversacion);
}

/** Envía la respuesta del personal y actualiza la bandeja. */
async function responderSolicitud(formulario) {
  const texto = formulario.texto.value.trim();
  if (!texto) return;
  const mensaje = await api(`/api/solicitudes/${solicitudAbierta}/mensajes`, { metodo: 'POST', json: { texto } });
  formulario.reset();
  agregarMensajesPersonal([mensaje]);
  // La bandeja refleja la respuesta enseguida (la API hace lo mismo); la consulta siguiente lo confirma
  const s = solicitudes.get(solicitudAbierta);
  if (s) {
    if (s.estado === 'abierta') s.estado = 'en_atencion';
    s.asignada_a = s.asignada_a || sesion.nombre;
    s.pendiente_desde = null;
    s.ultimo_mensaje = texto;
    mostrarBandeja();
    mostrarEncabezadoConversacion();
  }
  await cargarSolicitudes();
}

/** Toma, reasigna, resuelve o reabre la solicitud abierta. */
async function cambiarSolicitud(cambios, aviso) {
  const s = await api(`/api/solicitudes/${solicitudAbierta}`, { metodo: 'PATCH', json: cambios });
  const area = AREA_DEL_ROL[sesion.rol];
  if (area && s.categoria !== area) {
    solicitudes.delete(s.id);
    cerrarConversacion(`La solicitud pasó a ${AREAS[s.categoria].toLowerCase()}.`);
  } else {
    solicitudes.set(s.id, s);
    mostrarEncabezadoConversacion();
  }
  mostrarBandeja();
  avisar(aviso(s));
}

/** Recepción o gerencia simulan el pedido de un huésped alojado, elegido al azar. */
async function simularPedido() {
  const s = await api('/api/solicitudes/simular', { metodo: 'POST' });
  solicitudes.set(s.id, s);
  filtrarSolicitudes('activas');
  avisar(`Pedido simulado de la habitación ${s.habitacion}: "${s.ultimo_mensaje}"`);
  await abrirConversacion(s.id);
}

/** Consulta automática sin avisos emergentes; si falla, lo indica junto a la hora. */
async function actualizarSolicitudesEnSilencio() {
  try {
    await cargarSolicitudes(consultasDesdeRecarga >= RECARGA_COMPLETA_CADA);
  } catch {
    $('#actualizado-solicitudes').textContent = `No se pudo actualizar a las ${horaMensaje(new Date().toISOString())}.`;
  }
}

/** Primera carga al mostrar la tarjeta (la llama mostrarVista en app.js). */
function iniciarSolicitudes() {
  cursorSolicitudes = null;
  cerrarConversacion();
  $('#btn-simular-solicitud').hidden = !['recepcionista', 'gerente'].includes(sesion.rol);
  return cargarSolicitudes(true);
}

// =====================================================================
// Huésped: chat con el hotel
// =====================================================================
let chatCodigo = null;
let chatUltimo = 0;
let chatSolicitud = null;           // solicitud del último mensaje mostrado, para separar conversaciones
let chatUltimaConsulta = 0;

/**
 * Abre el chat de una estadía. Desde "Mis reservas" llega con el código; desde el botón general,
 * primero pide el código (sirve también para reservas hechas en recepción a nombre de su correo).
 */
function abrirChat(codigo = '') {
  if (!sesion.token) {
    abrirEntrar('Inicie sesión para escribir al hotel.', () => abrirChat(codigo));
    return;
  }
  chatCodigo = null;
  chatUltimo = 0;
  chatSolicitud = null;
  $('#chat-mensajes').replaceChildren();
  $('#chat-habitacion').textContent = '';
  $('#error-chat').hidden = true;
  $('#form-chat').hidden = true;
  $('#chat-cerrado').hidden = true;
  $('#form-chat-codigo').hidden = Boolean(codigo);
  $('#form-chat-codigo').reset();
  $('#dlg-chat').showModal();
  if (codigo) intentarEnChat(() => entrarAlChat(codigo));
}

/** Ejecuta una acción del chat y muestra el error dentro del diálogo. */
async function intentarEnChat(accion) {
  $('#error-chat').hidden = true;
  try {
    await accion();
  } catch (error) {
    $('#error-chat').textContent = error.message;
    $('#error-chat').hidden = false;
  }
}

/** Carga la conversación de una reserva y, si se pudo, deja el código fijo para las consultas siguientes. */
async function entrarAlChat(codigo) {
  const limpio = codigo.trim().toUpperCase();
  await cargarChat(limpio);
  chatCodigo = limpio;
  $('#form-chat-codigo').hidden = true;
}

/**
 * Pide los mensajes nuevos del chat y los agrega. Entre dos solicitudes distintas pone un separador.
 * Muestra el formulario solo durante la estadía, y el tema solo si no hay una solicitud abierta.
 */
async function cargarChat(codigo = chatCodigo) {
  const datos = await api(`/api/reservas/${encodeURIComponent(codigo)}/solicitudes?despues=${chatUltimo}`);
  chatUltimaConsulta = Date.now();
  $('#chat-habitacion').textContent = `Habitación ${datos.habitacion} · ${datos.codigo}`;
  const lista = $('#chat-mensajes');
  for (const m of datos.mensajes.filter((x) => x.id > chatUltimo)) {
    if (chatSolicitud !== null && m.solicitud_id !== chatSolicitud) {
      lista.append(el('li', { clase: 'separador' }, 'Nueva solicitud'));
    }
    lista.append(globoMensaje(m, m.autor === 'huesped', m.autor === 'huesped' ? 'Usted' : 'Hotel Soluna'));
    chatSolicitud = m.solicitud_id;
    chatUltimo = m.id;
  }
  if (!lista.children.length) {
    lista.append(el('li', { clase: 'separador' }, 'Aún no hay mensajes. ¿En qué le podemos ayudar?'));
  }
  alFinal(lista);
  $('#form-chat').hidden = !datos.puede_escribir;
  $('#chat-cerrado').hidden = datos.puede_escribir;
  $('#chat-tema').hidden = Boolean(datos.abierta);
}

/** Envía el mensaje del huésped y muestra la conversación actualizada. */
async function enviarChat(formulario) {
  const texto = formulario.texto.value.trim();
  if (!texto) return;
  await api(`/api/reservas/${encodeURIComponent(chatCodigo)}/solicitudes`, {
    metodo: 'POST', json: { texto, categoria: formulario.categoria.value },
  });
  formulario.texto.value = '';
  // El primer mensaje reemplaza la nota de "Aún no hay mensajes"
  for (const nota of document.querySelectorAll('#chat-mensajes .separador')) {
    if (nota.textContent.startsWith('Aún no hay')) nota.remove();
  }
  await cargarChat();
}

// =====================================================================
// Eventos y actualización automática
// =====================================================================
document.addEventListener('DOMContentLoaded', () => {
  // Personal
  for (const boton of document.querySelectorAll('[data-filtro-solicitudes]')) {
    boton.addEventListener('click', () => filtrarSolicitudes(boton.dataset.filtroSolicitudes));
  }
  $('#btn-simular-solicitud').addEventListener('click', () => intentar(simularPedido));
  $('#form-respuesta').addEventListener('submit', (evento) => {
    evento.preventDefault();
    intentar(() => responderSolicitud(evento.target));
  });
  // Enter envía; Mayúsculas+Enter agrega una línea
  for (const [area, formulario] of [['#respuesta-texto', '#form-respuesta'], ['#chat-texto', '#form-chat']]) {
    $(area).addEventListener('keydown', (evento) => {
      if (evento.key === 'Enter' && !evento.shiftKey) {
        evento.preventDefault();
        $(formulario).requestSubmit();
      }
    });
  }
  $('#conv-tomar').addEventListener('click', () => intentar(() =>
    cambiarSolicitud({ tomar: true }, (s) => `Usted atiende la solicitud de la habitación ${s.habitacion}.`)));
  $('#conv-resolver').addEventListener('click', () => intentar(() =>
    cambiarSolicitud({ estado: 'resuelta' }, (s) => `Solicitud de la habitación ${s.habitacion} resuelta.`)));
  $('#conv-reabrir').addEventListener('click', () => intentar(() =>
    cambiarSolicitud({ estado: 'en_atencion' }, (s) => `Solicitud de la habitación ${s.habitacion} reabierta.`)));
  $('#conv-area').addEventListener('change', (evento) => {
    const actual = solicitudes.get(solicitudAbierta);
    if (actual && actual.categoria === evento.target.value) return;   // misma área: nada que cambiar
    intentar(() => cambiarSolicitud({ categoria: evento.target.value },
      (s) => `Solicitud enviada a ${AREAS[s.categoria].toLowerCase()}.`));
  });

  // Huésped
  $('#btn-contactar').addEventListener('click', () => abrirChat());
  $('#form-chat-codigo').addEventListener('submit', (evento) => {
    evento.preventDefault();
    intentarEnChat(() => entrarAlChat(evento.target.codigo.value));
  });
  $('#form-chat').addEventListener('submit', (evento) => {
    evento.preventDefault();
    const boton = evento.target.querySelector('button[type=submit]');
    boton.disabled = true;
    intentarEnChat(() => enviarChat(evento.target)).finally(() => { boton.disabled = false; });
  });

  // Un solo reloj revisa cada 5 s si toca consultar, según lo que esté a la vista
  setInterval(() => {
    if (solicitudesVisibles()) {
      const cada = solicitudAbierta ? CADA_CONVERSACION : CADA_BANDEJA;
      if (Date.now() - ultimaConsultaSolicitudes >= cada) actualizarSolicitudesEnSilencio();
    }
    if (chatCodigo && $('#dlg-chat').open && document.visibilityState === 'visible'
        && Date.now() - chatUltimaConsulta >= CADA_CHAT_HUESPED) {
      cargarChat().catch(() => { /* se reintenta en la próxima vuelta */ });
    }
  }, 5000);
  // Al volver a la pestaña, se consulta enseguida si los datos quedaron viejos
  document.addEventListener('visibilitychange', () => {
    if (solicitudesVisibles() && Date.now() - ultimaConsultaSolicitudes >= CADA_CONVERSACION) {
      actualizarSolicitudesEnSilencio();
    }
  });
  // Al cerrar el chat del huésped, deja de consultar
  $('#dlg-chat').addEventListener('close', () => { chatCodigo = null; });
});
