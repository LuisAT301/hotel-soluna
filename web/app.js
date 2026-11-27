// =====================================================================
// Hotel Soluna: interfaz web del prototipo
// JavaScript sin librerías. Todo el texto que viene de la API se inserta
// con textContent (nunca con innerHTML) para evitar inyección de código.
// =====================================================================
'use strict';

// Nombres visibles de los valores que usa la API
const ROLES = {
  cliente: 'Cliente',
  recepcionista: 'Recepción',
  limpieza: 'Limpieza',
  mantenimiento: 'Mantenimiento',
  gerente: 'Gerencia',
};
const ESTADOS = {
  pendiente_pago: 'Pendiente de pago',
  confirmada: 'Confirmada',
  en_curso: 'En curso',
  finalizada: 'Finalizada',
  cancelada: 'Cancelada',
};
const LIMPIEZA = { sucia: 'Sucia', en_limpieza: 'En limpieza', limpia: 'Limpia', inspeccionada: 'Inspeccionada' };

// El público y los clientes ven el sitio completo del hotel; el personal
// entra directo a su panel de trabajo, sin la página de inicio.
const PERSONAL = ['recepcionista', 'limpieza', 'mantenimiento', 'gerente'];

// Qué secciones ve cada rol
const VISTAS = {
  publico: ['buscar'],
  cliente: ['buscar', 'reservas'],
  recepcionista: ['tablero', 'solicitudes', 'recepcion', 'buscar', 'reservas', 'habitaciones'],
  limpieza: ['solicitudes', 'habitaciones'],
  mantenimiento: ['solicitudes', 'habitaciones'],
  gerente: ['tablero', 'solicitudes', 'recepcion', 'buscar', 'reservas', 'habitaciones', 'usuarios', 'servicios',
    'bitacora', 'suscriptores'],
};

// Formato de dinero en dólares con convenciones de Costa Rica, y atajo para buscar elementos
const dinero = new Intl.NumberFormat('es-CR', { style: 'currency', currency: 'USD' });
const $ = (selector) => document.querySelector(selector);

// ---------------------------------------------------------------------
// Sesión (se guarda solo en esta pestaña y se borra al cerrarla)
// ---------------------------------------------------------------------
// Al cargar la página se recupera la sesión de la pestaña, si existía
let sesion = { token: null, rol: null, nombre: null };
try { sesion = { ...sesion, ...JSON.parse(sessionStorage.getItem('soluna') || '{}') }; } catch { /* sin almacenamiento */ }

/** Guarda la sesión en sessionStorage: sobrevive a recargar la página, pero se borra al cerrar la pestaña. */
function guardarSesion() {
  try { sessionStorage.setItem('soluna', JSON.stringify(sesion)); } catch { /* sin almacenamiento */ }
}

/** Olvida el token y vuelve a mostrar la vista pública. */
function cerrarSesion() {
  sesion = { token: null, rol: null, nombre: null };
  try { sessionStorage.removeItem('soluna'); } catch { /* sin almacenamiento */ }
  mostrarVista();
}

// ---------------------------------------------------------------------
// Llamadas a la API (siempre por la misma dirección: Nginx las reparte)
// ---------------------------------------------------------------------
/**
 * Llama a la API y devuelve el JSON de la respuesta, o lanza un Error con un mensaje legible.
 * - Agrega el token de sesión si lo hay y envía el cuerpo como JSON o como formulario.
 * - Muestra en el pie la réplica que respondió (cabecera X-Replica).
 * - Un 401 con sesión abierta significa que el token venció: cierra la sesión.
 * - Un 429 viene del límite de solicitudes de Nginx.
 * @param {string} ruta Ruta relativa (/api/... o /pasarela/...): siempre el mismo origen del sitio.
 * @param {{metodo?: string, json?: object, formulario?: object}} opciones
 */
async function api(ruta, { metodo = 'GET', json, formulario } = {}) {
  const opciones = { method: metodo, headers: {} };
  if (sesion.token) opciones.headers.Authorization = `Bearer ${sesion.token}`;
  if (json) {
    opciones.headers['Content-Type'] = 'application/json';
    opciones.body = JSON.stringify(json);
  }
  if (formulario) opciones.body = new URLSearchParams(formulario);

  const respuesta = await fetch(ruta, opciones);
  const replica = respuesta.headers.get('X-Replica');
  if (replica) $('#replica').textContent = replica;

  const esJson = (respuesta.headers.get('Content-Type') || '').includes('application/json');
  const datos = esJson ? await respuesta.json() : null;

  if (respuesta.status === 401 && sesion.token && !ruta.endsWith('/login')) {
    cerrarSesion();
    throw new Error('La sesión venció. Inicie sesión de nuevo.');
  }
  if (respuesta.status === 429) throw new Error('Demasiados intentos. Espere un minuto y vuelva a intentarlo.');
  if (!respuesta.ok) throw new Error(textoError(datos, respuesta.status));
  return datos;
}

/**
 * Convierte la respuesta de error de la API en un texto para el usuario.
 * FastAPI envía un texto en `detail`, o una lista de errores de validación (422) que se resume campo por campo.
 */
function textoError(datos, codigo) {
  if (datos && typeof datos.detail === 'string') return datos.detail;
  if (datos && Array.isArray(datos.detail)) {
    return datos.detail.map((e) => `${e.loc[e.loc.length - 1]}: ${e.msg}`).join(' · ');
  }
  return codigo >= 500 ? 'El servicio no está disponible en este momento.' : `Error ${codigo}`;
}

// ---------------------------------------------------------------------
// Utilidades de interfaz
// ---------------------------------------------------------------------
/**
 * Crea un elemento HTML con atributos e hijos, sin usar innerHTML.
 * `clase` se asigna a className, los atributos `on...` se registran como eventos y los hijos
 * que no son nodos se insertan como texto, así ningún dato de la API se interpreta como HTML.
 */
function el(etiqueta, atributos = {}, ...hijos) {
  const nodo = document.createElement(etiqueta);
  for (const [clave, valor] of Object.entries(atributos)) {
    if (clave === 'clase') nodo.className = valor;
    else if (clave.startsWith('on')) nodo.addEventListener(clave.slice(2), valor);
    else nodo.setAttribute(clave, valor);
  }
  for (const hijo of hijos) {
    if (hijo !== null && hijo !== undefined) nodo.append(hijo instanceof Node ? hijo : String(hijo));
  }
  return nodo;
}

/** Arma una tabla con encabezados y filas; si no hay filas, muestra `textoVacio`. */
function tabla(columnas, filas, textoVacio) {
  if (!filas.length) return el('p', { clase: 'vacio' }, textoVacio);
  return el('div', { clase: 'tabla-contenedor' },
    el('table', {},
      el('thead', {}, el('tr', {}, ...columnas.map((c) => el('th', {}, c)))),
      el('tbody', {}, ...filas.map((fila) => el('tr', {}, ...fila.map((celda) => el('td', {}, celda)))))));
}

/** Etiqueta de color para un estado; el color lo da la clase CSS con el mismo nombre. */
function etiquetaEstado(valor, nombres) {
  return el('span', { clase: `estado ${valor}` }, nombres[valor] || valor);
}

let temporizadorAviso;
/** Muestra un aviso arriba de la página durante siete segundos (`tipo`: exito o error). */
function avisar(mensaje, tipo = 'exito') {
  const aviso = $('#aviso');
  aviso.textContent = mensaje;
  aviso.className = `aviso ${tipo}`;
  aviso.hidden = false;
  clearTimeout(temporizadorAviso);
  temporizadorAviso = setTimeout(() => { aviso.hidden = true; }, 7000);
}

// Conversión de fechas: el formulario usa AAAA-MM-DD y la interfaz muestra DD/MM/AAAA
const fechaISO = (fecha) => fecha.toLocaleDateString('en-CA'); // AAAA-MM-DD en hora local
const fechaCorta = (iso) => iso.split('-').reverse().join('/');

// Ejecuta una acción mostrando cualquier error en el aviso
/** Ejecuta una acción asíncrona y muestra cualquier error en el aviso, en vez de perderlo en la consola. */
async function intentar(accion) {
  try { await accion(); } catch (error) { avisar(error.message, 'error'); }
}

// ---------------------------------------------------------------------
// Vista según el rol
// ---------------------------------------------------------------------
/**
 * Muestra solo las secciones del rol actual y recarga sus datos.
 * El personal ve el modo "panel" (sin la página de inicio); el público y los clientes, el sitio completo.
 * Ocultar secciones es solo comodidad: los permisos reales los aplica la API en cada ruta.
 */
function mostrarVista() {
  const vista = VISTAS[sesion.rol] || VISTAS.publico;
  document.body.dataset.modo = PERSONAL.includes(sesion.rol) ? 'panel' : 'sitio';
  for (const nombre of ['tablero', 'solicitudes', 'recepcion', 'buscar', 'reservas', 'habitaciones', 'usuarios',
    'servicios', 'bitacora', 'suscriptores']) {
    $(`#sec-${nombre}`).hidden = !vista.includes(nombre);
  }
  $('#btn-entrar').hidden = Boolean(sesion.token);
  $('#btn-salir').hidden = !sesion.token;
  $('#usuario-actual').textContent = sesion.token ? `${sesion.nombre} · ${ROLES[sesion.rol]}` : '';
  $('#titulo-reservas').textContent = sesion.rol === 'cliente' ? 'Mis reservas' : 'Reservas';
  $('#btn-contactar').hidden = sesion.rol !== 'cliente';

  if (vista.includes('tablero')) intentar(cargarTablero);       // definida en tablero.js
  if (vista.includes('solicitudes')) intentar(iniciarSolicitudes);   // definida en solicitudes.js
  if (vista.includes('recepcion')) intentar(cargarRecepcion);   // definida en gestion.js
  if (vista.includes('reservas')) intentar(cargarReservas);
  if (vista.includes('habitaciones')) intentar(cargarHabitaciones);
  if (vista.includes('usuarios')) intentar(cargarUsuarios);
  if (vista.includes('servicios')) intentar(cargarCatalogoGerencia);   // definida en cuenta.js
  if (vista.includes('bitacora')) intentar(cargarBitacora);
  if (vista.includes('suscriptores')) intentar(cargarSuscriptores);
  if (vista.includes('buscar') && ultimaBusqueda) intentar(() => buscar(ultimaBusqueda));
}

// ---------------------------------------------------------------------
// Disponibilidad y reservas
// ---------------------------------------------------------------------
// Última búsqueda hecha, para repetirla después de reservar, cancelar o cambiar de sesión
let ultimaBusqueda = null;

/**
 * Consulta la disponibilidad y muestra una tarjeta por tipo de habitación.
 * La API devuelve cada habitación libre; aquí se agrupan por tipo y se guardan sus ids,
 * para reservar la primera libre del tipo elegido. Se recuerda la búsqueda para repetirla
 * después de reservar o cancelar.
 */
async function buscar(parametros) {
  ultimaBusqueda = parametros;
  const lista = await api(`/api/disponibilidad?${new URLSearchParams(parametros)}`);

  // Agrupa las habitaciones libres por tipo
  const grupos = new Map();
  for (const h of lista) {
    if (!grupos.has(h.tipo)) grupos.set(h.tipo, { ...h, ids: [] });
    grupos.get(h.tipo).ids.push(h.habitacion_id);
  }

  const contenedor = $('#resultados');
  contenedor.replaceChildren();
  if (!grupos.size) {
    contenedor.append(el('p', { clase: 'vacio' }, 'No hay habitaciones disponibles para esas fechas.'));
    return;
  }
  const puedeReservar = !sesion.token || ['cliente', 'recepcionista', 'gerente'].includes(sesion.rol);
  contenedor.append(el('div', { clase: 'opciones' }, ...[...grupos.values()].map((g) =>
    el('article', { clase: 'opcion' },
      el('h3', {}, g.tipo),
      el('span', { clase: 'detalle' }, `Hasta ${g.capacidad} personas · ${g.ids.length} disponibles`),
      el('span', { clase: 'precio' }, dinero.format(Number(g.total))),
      el('span', { clase: 'detalle' }, `${g.noches} ${g.noches === 1 ? 'noche' : 'noches'}, impuestos no incluidos`),
      puedeReservar ? el('button', { clase: 'boton', type: 'button', onclick: () => iniciarReserva(g, parametros) }, 'Reservar') : null,
    ))));
}

/**
 * Empieza una reserva desde el botón "Reservar".
 * Sin sesión pide iniciarla; un cliente reserva de inmediato a su nombre; el personal abre el
 * formulario de nueva reserva (gestion.js) con las fechas y el tipo ya elegidos, para completar
 * los datos del huésped, su teléfono y si llegó por teléfono o al mostrador.
 */
function iniciarReserva(grupo, parametros) {
  const datos = {
    habitacion_id: grupo.ids[0],
    fecha_entrada: parametros.entrada,
    fecha_salida: parametros.salida,
    personas: Number(parametros.personas),
  };
  if (!sesion.token) {
    abrirEntrar('Inicie sesión o cree una cuenta para reservar.');
    return;
  }
  if (sesion.rol === 'cliente') {
    intentar(() => confirmarReserva(datos));
    return;
  }
  // Personal del hotel: el mismo formulario de "Nueva reserva" de Recepción
  abrirNuevaReserva({ entrada: parametros.entrada, salida: parametros.salida, personas: parametros.personas, tipo: grupo.tipo });
}

/** Crea la reserva, actualiza la búsqueda y la lista, y abre el pago si quedó pendiente. */
async function confirmarReserva(datos) {
  const reserva = await api('/api/reservas', { metodo: 'POST', json: datos });
  avisar(`Reserva ${reserva.codigo} creada: habitación ${reserva.habitacion}, ${ESTADOS[reserva.estado].toLowerCase()}.`);
  await Promise.all([buscar(ultimaBusqueda), cargarReservas()]);
  // Una reserva en línea se paga enseguida para confirmarla
  if (reserva.estado === 'pendiente_pago') abrirPago(reserva);
}

/** Lista las reservas con los botones que permite su estado: gestionar (personal), pagar, ver factura y cancelar. */
async function cargarReservas() {
  const reservas = await api('/api/reservas');
  const cancelable = (r) => ['pendiente_pago', 'confirmada'].includes(r.estado);
  const acciones = (r) => {
    const botones = [];
    // Recepción y gerencia abren la reserva en el diálogo de gestión (gestion.js)
    if (PUEDEN_GESTIONAR.includes(sesion.rol)) {
      botones.push(el('button', { clase: 'boton pequeno', type: 'button', onclick: () => intentar(() => abrirGestion(r.codigo)) }, 'Gestionar'));
    }
    if (r.estado === 'pendiente_pago') {
      botones.push(el('button', { clase: 'boton pequeno', type: 'button', onclick: () => abrirPago(r) }, 'Pagar'));
    }
    if (r.tiene_factura) {
      botones.push(el('button', { clase: 'boton claro pequeno', type: 'button', onclick: () => intentar(() => verFactura(r)) }, 'Factura'));
    }
    if (cancelable(r)) {
      botones.push(el('button', { clase: 'boton peligro pequeno', type: 'button', onclick: () => intentar(() => cancelar(r)) }, 'Cancelar'));
    }
    // Durante la estadía, el huésped puede escribir al hotel (solicitudes.js)
    if (sesion.rol === 'cliente' && r.estado === 'en_curso') {
      botones.push(el('button', { clase: 'boton pequeno', type: 'button', onclick: () => abrirChat(r.codigo) }, 'Contactar al hotel'));
    }
    // Consumos cargados a la habitación y lo que queda por pagar al salir (cuenta.js)
    if (sesion.rol === 'cliente' && ['en_curso', 'finalizada'].includes(r.estado)) {
      botones.push(el('button', { clase: 'boton claro pequeno', type: 'button', onclick: () => abrirMiCuenta(r.codigo) }, 'Mi cuenta'));
    }
    if (sesion.rol === 'cliente' && estadiaCumplida(r)) {
      botones.push(el('button', { clase: 'boton claro pequeno', type: 'button', onclick: () => abrirResena(r.codigo) }, 'Opinar'));
    }
    return el('div', { clase: 'botones-fila' }, ...botones);
  };
  $('#lista-reservas').replaceChildren(tabla(
    ['Código', 'Huésped', 'Habitación', 'Entrada', 'Salida', 'Canal', 'Estado', 'Total con IVA', ''],
    reservas.map((r) => [
      el('code', {}, r.codigo),
      r.nombre_huesped,
      `${r.habitacion} (${r.tipo})`,
      fechaCorta(r.fecha_entrada),
      fechaCorta(r.fecha_salida),
      r.canal,
      etiquetaEstado(r.estado, ESTADOS),
      dinero.format(Number(r.total_con_impuesto)),
      acciones(r),
    ]),
    'Todavía no hay reservas.'));
}

/** Pide confirmación y cancela la reserva; si estaba pagada, la API hace el reembolso. */
async function cancelar(reserva) {
  const { codigo } = reserva;
  const pregunta = reserva.tiene_factura
    ? `¿Cancelar la reserva ${codigo}? Se reembolsará el pago a la tarjeta.`
    : `¿Cancelar la reserva ${codigo}?`;
  if (!window.confirm(pregunta)) return;
  await api(`/api/reservas/${encodeURIComponent(codigo)}/cancelar`, { metodo: 'POST' });
  avisar(reserva.tiene_factura ? `Reserva ${codigo} cancelada y pago reembolsado.` : `Reserva ${codigo} cancelada.`);
  await cargarReservas();
  if (ultimaBusqueda) await buscar(ultimaBusqueda);
}

// ---------------------------------------------------------------------
// Pago en línea y factura
// La tarjeta se envía a la pasarela (/pasarela/tokens), que devuelve un
// token de un solo uso; a la API del hotel solo llega ese token.
// ---------------------------------------------------------------------
// Reserva que se está pagando en el diálogo de pago
let reservaPorPagar = null;

/** Abre el diálogo de pago con el desglose de subtotal, IVA y total. */
function abrirPago(reserva) {
  reservaPorPagar = reserva;
  $('#form-pago').reset();
  $('#error-pago').hidden = true;
  $('#pago-codigo').textContent = reserva.codigo;
  $('#pago-subtotal').textContent = dinero.format(Number(reserva.total));
  $('#pago-impuesto').textContent = dinero.format(Number(reserva.impuesto));
  $('#pago-total').textContent = dinero.format(Number(reserva.total_con_impuesto));
  $('#dlg-pago').showModal();
}

/**
 * Paga una reserva en dos pasos, sin que la tarjeta pase por la API del hotel:
 * 1. envía la tarjeta a la pasarela (/pasarela/tokens) y recibe un token de un solo uso;
 * 2. envía solo ese token a la API, que cobra, confirma la reserva y emite la factura.
 */
async function pagar(formulario) {
  const tarjeta = Object.fromEntries(new FormData(formulario));
  const { token } = await api('/pasarela/tokens', { metodo: 'POST', json: tarjeta });
  const pago = await api(`/api/reservas/${encodeURIComponent(reservaPorPagar.codigo)}/pago`,
    { metodo: 'POST', json: { token } });
  $('#dlg-pago').close();
  avisar(`Pago aprobado: ${dinero.format(Number(pago.monto))} con ${pago.marca} terminada en ${pago.ultimos4}. `
    + `Reserva ${pago.reserva.codigo} confirmada; la factura se envió a su correo.`);
  await cargarReservas();
}

/** Muestra la factura electrónica de la reserva con su estado ante Hacienda. */
async function verFactura(reserva) {
  const f = await api(`/api/reservas/${encodeURIComponent(reserva.codigo)}/factura`);
  $('#factura-reserva').textContent = reserva.codigo;
  $('#factura-consecutivo').textContent = f.consecutivo;
  $('#factura-estado').replaceChildren(etiquetaEstado(f.estado, { aceptada: 'Aceptada', rechazada: 'Rechazada', pendiente: 'Pendiente de envío' }));
  $('#factura-fecha').textContent = new Date(f.emitida_en).toLocaleString('es-CR');
  $('#factura-subtotal').textContent = dinero.format(Number(f.subtotal));
  $('#factura-impuesto').textContent = dinero.format(Number(f.impuesto));
  $('#factura-total').textContent = dinero.format(Number(f.total));
  $('#factura-clave').textContent = f.clave;
  $('#dlg-factura').showModal();
}

// ---------------------------------------------------------------------
// Habitaciones y limpieza
// ---------------------------------------------------------------------
/** Lista las habitaciones; quien puede cambiar la limpieza ve un selector en lugar de la etiqueta. */
async function cargarHabitaciones() {
  const habitaciones = await api('/api/habitaciones');
  const editable = ['limpieza', 'recepcionista', 'gerente'].includes(sesion.rol);
  $('#lista-habitaciones').replaceChildren(tabla(
    ['Número', 'Tipo', 'Piso', 'Capacidad', 'Limpieza'],
    habitaciones.map((h) => [
      h.numero,
      h.tipo,
      h.piso,
      h.capacidad,
      editable ? selectorLimpieza(h) : etiquetaEstado(h.estado_limpieza, LIMPIEZA),
    ]),
    'No hay habitaciones registradas.'));
}

/** Selector del estado de limpieza que guarda el cambio en cuanto se elige otra opción. */
function selectorLimpieza(h) {
  const selector = el('select', { 'aria-label': `Estado de limpieza de la habitación ${h.numero}` },
    ...Object.entries(LIMPIEZA).map(([valor, texto]) => el('option', { value: valor }, texto)));
  selector.value = h.estado_limpieza;
  selector.addEventListener('change', () => intentar(async () => {
    await api(`/api/habitaciones/${h.id}/limpieza`, { metodo: 'PATCH', json: { estado: selector.value } });
    avisar(`Habitación ${h.numero}: ${LIMPIEZA[selector.value].toLowerCase()}.`);
    // El tablero muestra la limpieza de cada habitación: se actualiza si está a la vista
    if (!$('#sec-tablero').hidden) await cargarTablero();
  }));
  return selector;
}

// ---------------------------------------------------------------------
// Gerencia: usuarios y bitácora
// ---------------------------------------------------------------------
/** Lista las cuentas (gerencia) con el botón para desactivar las demás. */
async function cargarUsuarios() {
  const usuarios = await api('/api/usuarios');
  $('#lista-usuarios').replaceChildren(tabla(
    ['Nombre', 'Correo', 'Rol', 'Estado', ''],
    usuarios.map((u) => [
      u.nombre,
      u.correo,
      ROLES[u.rol],
      u.activo ? 'Activa' : 'Desactivada',
      u.activo && u.nombre !== sesion.nombre
        ? el('button', { clase: 'boton claro pequeno', type: 'button', onclick: () => intentar(() => desactivar(u)) }, 'Desactivar')
        : '',
    ]),
    'No hay cuentas.'));
}

/** Pide confirmación y desactiva una cuenta. */
async function desactivar(usuario) {
  if (!window.confirm(`¿Desactivar la cuenta de ${usuario.nombre}?`)) return;
  await api(`/api/usuarios/${usuario.id}/desactivar`, { metodo: 'POST' });
  avisar(`Cuenta de ${usuario.nombre} desactivada.`);
  await cargarUsuarios();
}

/** Muestra los últimos 50 registros de la bitácora, con la réplica que atendió cada acción. */
async function cargarBitacora() {
  const registros = await api('/api/bitacora?limite=50');
  $('#lista-bitacora').replaceChildren(tabla(
    ['Fecha', 'Usuario', 'Acción', 'Elemento', 'Réplica'],
    registros.map((r) => [
      new Date(r.fecha).toLocaleString('es-CR'),
      r.usuario_id ?? '',
      r.accion.replaceAll('_', ' '),
      `${r.entidad} ${r.entidad_id ?? ''}`,
      el('code', {}, r.detalle.replica ?? ''),
    ]),
    'Sin registros.'));
}

// ---------------------------------------------------------------------
// Página de inicio: tipos de habitación y suscripción por correo
// ---------------------------------------------------------------------
// Ola decorativa de las tarjetas de habitación (SVG fijo, sin datos de la API)
function olaDecorativa() {
  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('viewBox', '0 0 400 46');
  svg.setAttribute('preserveAspectRatio', 'none');
  svg.setAttribute('aria-hidden', 'true');
  const camino = document.createElementNS(ns, 'path');
  camino.setAttribute('d', 'M0 24c50-16 100-16 150 0s100 16 150 0 70-14 100-6v28H0z');
  camino.setAttribute('fill', '#FFFFFF');
  svg.append(camino);
  return svg;
}

/** Arma las tarjetas de tipos de habitación de la página de inicio con los datos de la API. */
async function cargarTiposHabitacion() {
  const tipos = await api('/api/tipos-habitacion');
  if (!tipos.length) return;
  $('#tipos-habitacion').replaceChildren(...tipos.map((t) => el('article', { clase: 'tipo' },
    el('div', { clase: `tipo-cabecera ${t.nombre === 'estándar' ? '' : t.nombre}` }, olaDecorativa()),
    el('div', { clase: 'tipo-cuerpo' },
      el('h3', {}, t.nombre),
      el('p', {}, t.descripcion || ''),
      el('div', { clase: 'tipo-datos' },
        el('span', {}, `Hasta ${t.capacidad} personas`),
        el('span', {}, `${t.habitaciones} habitaciones`)),
      el('div', { clase: 'tipo-precio' },
        el('span', {}, 'Desde ', el('strong', {}, dinero.format(Number(t.precio_desde))), ' por noche'),
        el('a', { clase: 'boton pequeno', href: '#reservar', onclick: () => prepararBusqueda(t.capacidad) }, 'Ver fechas'))))));
}

// Lleva al buscador con una cantidad de personas que quepa en ese tipo de habitación
function prepararBusqueda(capacidad) {
  const personas = $('#buscar-personas');
  if (Number(personas.value) > capacidad) personas.value = capacidad;
  setTimeout(() => $('#buscar-entrada').focus({ preventScroll: true }), 400);
}

/**
 * Envía el correo del formulario de novedades.
 * Valida el formato en el navegador antes de enviarlo y desactiva el botón mientras
 * espera, para evitar envíos repetidos.
 */
async function suscribir(formulario) {
  const mensaje = $('#msg-suscripcion');
  const campo = $('#suscripcion-correo');
  mensaje.className = 'novedades-mensaje';
  if (!campo.checkValidity()) {
    mensaje.textContent = 'Escriba un correo válido, por ejemplo nombre@ejemplo.com.';
    mensaje.classList.add('error');
    campo.focus();
    return;
  }
  const boton = $('#btn-suscribir');
  boton.disabled = true;
  try {
    const respuesta = await api('/api/suscripciones', { metodo: 'POST', json: { correo: campo.value.trim() } });
    mensaje.textContent = respuesta.mensaje;
    mensaje.classList.add('exito');
    formulario.reset();
  } catch (error) {
    mensaje.textContent = error.message;
    mensaje.classList.add('error');
  } finally {
    boton.disabled = false;
  }
}

// Gerencia: correos suscritos desde la página de inicio
/** Lista los correos suscritos (gerencia). */
async function cargarSuscriptores() {
  const lista = await api('/api/suscripciones');
  $('#total-suscriptores').textContent = lista.length
    ? `${lista.length} ${lista.length === 1 ? 'correo suscrito' : 'correos suscritos'}` : '';
  $('#lista-suscriptores').replaceChildren(tabla(
    ['Correo', 'Desde', 'Estado'],
    lista.map((s) => [s.correo, new Date(s.creado_en).toLocaleString('es-CR'), s.activo ? 'Activo' : 'De baja']),
    'Todavía no hay correos suscritos.'));
}

// ---------------------------------------------------------------------
// Reseñas verificadas
// Solo opina quien inició sesión y tiene una reservación propia ya cumplida;
// la API comprueba esas reglas y aquí solo se muestran sus mensajes.
// ---------------------------------------------------------------------
const ESTADOS_CUMPLIDOS = ['confirmada', 'en_curso', 'finalizada'];

/** Indica si una reserva ya terminó y se puede reseñar (la API vuelve a comprobarlo). */
function estadiaCumplida(reserva) {
  return ESTADOS_CUMPLIDOS.includes(reserva.estado) && reserva.fecha_salida <= fechaISO(new Date());
}

/** Cinco estrellas de texto: llenas según la calificación y vacías el resto. */
function textoEstrellas(calificacion) {
  return '★'.repeat(calificacion) + '☆'.repeat(5 - calificacion);
}

/** Tarjeta de una reseña real, con el distintivo de estadía verificada. */
function tarjetaResena(r) {
  const fecha = new Date(r.creada_en).toLocaleDateString('es-CR', { month: 'long', year: 'numeric' });
  return el('figure', { clase: 'resena' },
    el('div', { clase: 'estrellas', 'aria-label': `${r.calificacion} de 5 estrellas` }, textoEstrellas(r.calificacion)),
    el('blockquote', {}, r.comentario),
    el('figcaption', {},
      el('strong', {}, r.autor), ` · Habitación ${r.tipo_habitacion} · ${fecha}`,
      el('span', { clase: 'verificada' }, 'Estadía verificada')));
}

/**
 * Carga las reseñas reales y el promedio. Mientras no exista ninguna, se quedan
 * las reseñas de ejemplo del HTML, con su nota de demostración.
 */
async function cargarResenas() {
  const { promedio, total, resenas } = await api('/api/resenas');
  if (!total) return;
  const valor = Number(promedio);
  $('#resumen-resenas').replaceChildren(
    el('span', { clase: 'estrellas', 'aria-hidden': 'true' }, textoEstrellas(Math.round(valor))),
    el('strong', {}, `${valor.toLocaleString('es-CR', { minimumFractionDigits: 1, maximumFractionDigits: 1 })} de 5`),
    ` en ${total} ${total === 1 ? 'opinión verificada' : 'opiniones verificadas'}`);
  $('#lista-resenas').replaceChildren(...resenas.map(tarjetaResena));
  $('#nota-resenas').textContent = 'Cada reseña corresponde a una estadía cumplida en el hotel.';
}

/**
 * Abre el formulario de reseña, con el código ya escrito si viene de "Mis reservas".
 * Sin sesión, primero pide iniciarla y abre el formulario en cuanto entra.
 */
function abrirResena(codigo = '') {
  if (!sesion.token) {
    abrirEntrar('Inicie sesión para escribir una reseña. Solo pueden opinar huéspedes con una estadía cumplida.',
      () => abrirResena(codigo));
    return;
  }
  const formulario = $('#form-resena');
  formulario.reset();
  formulario.codigo_reserva.value = codigo;
  $('#error-resena').hidden = true;
  $('#dlg-resena').showModal();
}

/** Envía la reseña; si la API la acepta, cierra el formulario y actualiza la sección. */
async function enviarResena(formulario) {
  const datos = Object.fromEntries(new FormData(formulario));
  await api('/api/resenas', {
    metodo: 'POST',
    json: {
      codigo_reserva: datos.codigo_reserva.trim().toUpperCase(),
      calificacion: Number(datos.calificacion),
      comentario: datos.comentario.trim(),
    },
  });
  $('#dlg-resena').close();
  avisar('Gracias por su reseña: ya está publicada en el sitio.');
  await cargarResenas();
}

// ---------------------------------------------------------------------
// Inicio de sesión y registro
// ---------------------------------------------------------------------
// false: el diálogo inicia sesión; true: crea una cuenta de cliente
let modoRegistro = false;
// Acción que se ejecuta al iniciar sesión, si se pidió entrar para hacer algo (por ejemplo, opinar)
let alEntrar = null;

/**
 * Abre el diálogo de inicio de sesión; `nota` explica por qué se pidió (por ejemplo, para reservar)
 * y `despues`, si se indica, se ejecuta en cuanto la sesión quede iniciada.
 */
function abrirEntrar(nota, despues = null) {
  alEntrar = despues;
  modoRegistro = false;
  actualizarModoEntrar();
  $('#form-entrar').reset();
  $('#nota-entrar').textContent = nota || '';
  $('#nota-entrar').hidden = !nota;
  $('#dlg-entrar').showModal();
}

/** Cambia el diálogo entre "Iniciar sesión" y "Crear cuenta de cliente". */
function actualizarModoEntrar() {
  $('#titulo-entrar').textContent = modoRegistro ? 'Crear cuenta de cliente' : 'Iniciar sesión';
  $('#campo-nombre').hidden = !modoRegistro;
  $('#campo-nombre input').required = modoRegistro;
  $('#btn-enviar-entrar').textContent = modoRegistro ? 'Crear cuenta' : 'Entrar';
  $('#btn-cambiar-modo').textContent = modoRegistro ? 'Ya tengo cuenta' : 'Crear una cuenta de cliente';
}

/**
 * Inicia sesión o, en modo registro, crea la cuenta y luego inicia sesión con ella.
 * Guarda el token, el rol y el nombre, y muestra la vista que corresponde al rol.
 */
async function enviarEntrar(formulario) {
  const datos = Object.fromEntries(new FormData(formulario));
  if (modoRegistro) {
    await api('/api/auth/registro', {
      metodo: 'POST', json: { nombre: datos.nombre, correo: datos.correo, contrasena: datos.contrasena } });
  }
  const token = await api('/api/auth/login', {
    metodo: 'POST', formulario: { username: datos.correo, password: datos.contrasena } });
  sesion = { token: token.access_token, rol: token.rol, nombre: token.nombre };
  guardarSesion();
  $('#dlg-entrar').close();
  avisar(`Bienvenido, ${token.nombre}.`);
  mostrarVista();
  // Si se pidió entrar para hacer algo, se retoma
  if (alEntrar) {
    const accion = alEntrar;
    alEntrar = null;
    accion();
  }
  // El personal pasa a su panel: se empieza desde arriba
  if (document.body.dataset.modo === 'panel') window.scrollTo({ top: 0, behavior: 'instant' });
}

// ---------------------------------------------------------------------
// Eventos
// ---------------------------------------------------------------------
// Al terminar de cargar la página: valores iniciales, eventos de formularios y botones, y
// comprobación de la sesión guardada.
document.addEventListener('DOMContentLoaded', () => {
  // Fechas sugeridas: dentro de 7 días, por 3 noches
  const entrada = new Date();
  entrada.setDate(entrada.getDate() + 7);
  const salida = new Date(entrada);
  salida.setDate(salida.getDate() + 3);
  const formBuscar = $('#form-buscar');
  formBuscar.entrada.value = fechaISO(entrada);
  formBuscar.salida.value = fechaISO(salida);
  formBuscar.entrada.min = fechaISO(new Date());

  formBuscar.addEventListener('submit', (evento) => {
    evento.preventDefault();
    intentar(() => buscar(Object.fromEntries(new FormData(formBuscar))));
  });

  // Menú en pantallas angostas: se abre con el botón y se cierra al elegir una sección
  const menu = $('#menu-principal');
  const botonMenu = $('#btn-menu');
  botonMenu.addEventListener('click', () => {
    const abierto = menu.classList.toggle('abierto');
    botonMenu.setAttribute('aria-expanded', String(abierto));
  });
  menu.addEventListener('click', (evento) => {
    if (evento.target.closest('a')) {
      menu.classList.remove('abierto');
      botonMenu.setAttribute('aria-expanded', 'false');
    }
  });

  $('#form-suscripcion').addEventListener('submit', (evento) => {
    evento.preventDefault();
    suscribir(evento.target);
  });
  cargarTiposHabitacion().catch(() => { /* se queda el texto de respaldo del HTML */ });
  cargarResenas().catch(() => { /* se quedan las reseñas de ejemplo del HTML */ });

  $('#btn-resena').addEventListener('click', () => abrirResena());
  $('#form-resena').addEventListener('submit', (evento) => {
    evento.preventDefault();
    const boton = $('#btn-publicar-resena');
    boton.disabled = true;
    $('#error-resena').hidden = true;
    enviarResena(evento.target)
      .catch((error) => {
        $('#error-resena').textContent = error.message;
        $('#error-resena').hidden = false;
      })
      .finally(() => { boton.disabled = false; });
  });

  $('#btn-entrar').addEventListener('click', () => abrirEntrar());
  $('#btn-salir').addEventListener('click', () => { cerrarSesion(); avisar('Sesión cerrada.'); });
  $('#btn-cambiar-modo').addEventListener('click', () => { modoRegistro = !modoRegistro; actualizarModoEntrar(); });
  $('#btn-recargar-reservas').addEventListener('click', () => intentar(cargarReservas));
  $('#btn-recargar-habitaciones').addEventListener('click', () => intentar(cargarHabitaciones));
  $('#btn-recargar-bitacora').addEventListener('click', () => intentar(cargarBitacora));
  $('#btn-recargar-suscriptores').addEventListener('click', () => intentar(cargarSuscriptores));
  for (const boton of document.querySelectorAll('[data-cerrar]')) {
    boton.addEventListener('click', () => boton.closest('dialog').close());
  }

  $('#form-entrar').addEventListener('submit', (evento) => {
    evento.preventDefault();
    const boton = $('#btn-enviar-entrar');
    boton.disabled = true;
    enviarEntrar(evento.target)
      .catch((error) => {
        $('#nota-entrar').textContent = error.message;
        $('#nota-entrar').hidden = false;
      })
      .finally(() => { boton.disabled = false; });
  });

  $('#form-pago').addEventListener('submit', (evento) => {
    evento.preventDefault();
    const boton = $('#btn-pagar');
    boton.disabled = true;
    $('#error-pago').hidden = true;
    pagar(evento.target)
      .catch((error) => {
        $('#error-pago').textContent = error.message;
        $('#error-pago').hidden = false;
      })
      .finally(() => { boton.disabled = false; });
  });

  $('#form-usuario').addEventListener('submit', (evento) => {
    evento.preventDefault();
    const formulario = evento.target;
    intentar(async () => {
      const usuario = await api('/api/usuarios', { metodo: 'POST', json: Object.fromEntries(new FormData(formulario)) });
      avisar(`Cuenta creada para ${usuario.nombre} (${ROLES[usuario.rol]}).`);
      formulario.reset();
      await cargarUsuarios();
    });
  });

  // Si había una sesión guardada, se comprueba que siga vigente
  if (sesion.token) {
    api('/api/auth/yo').then(mostrarVista).catch(() => cerrarSesion());
  } else {
    mostrarVista();
  }
  api('/api/salud').catch(() => { /* solo para mostrar la réplica */ });
});
