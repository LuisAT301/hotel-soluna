// =====================================================================
// Hotel Soluna: recepción (panel del personal, etapa 1)
// Llegadas, salidas y huéspedes en casa; detalle de cada reserva con
// check-in, check-out, cambios de habitación o fechas, cancelación e
// historial. Usa las utilidades de app.js (api, el, tabla, avisar...),
// que se carga antes. Como en app.js, todo dato de la API se inserta como
// texto, nunca como HTML.
// =====================================================================
'use strict';

const PUEDEN_GESTIONAR = ['recepcionista', 'gerente'];
const CANALES = { web: 'Sitio web', recepcion: 'Recepción', ota: 'Agencia en línea (OTA)' };

// Nombre legible de cada acción de la bitácora que aparece en el historial
const ACCIONES_BITACORA = {
  crear_reserva: 'Reserva creada',
  reserva_ota: 'Reserva recibida de la agencia en línea',
  pago_aprobado: 'Pago aprobado',
  pago_rechazado: 'Pago rechazado',
  reembolso: 'Pago reembolsado',
  cancelar_reserva: 'Reserva cancelada',
  check_in: 'Ingreso del huésped (check-in)',
  check_out: 'Salida del huésped (check-out)',
  modificar_reserva: 'Reserva modificada',
  publicar_resena: 'Reseña publicada',
};

// Texto cuando una vista no tiene reservas
const SIN_RESULTADOS = {
  llegadas: 'No hay llegadas pendientes para hoy.',
  salidas: 'No hay salidas pendientes para hoy.',
  en_casa: 'No hay huéspedes alojados en este momento.',
  activas: 'No hay reservas activas.',
  todas: 'No hay reservas.',
};

// Vista elegida en los botones de Recepción y reserva abierta en el diálogo de gestión
let vistaRecepcion = 'llegadas';
let gestionActual = null;

const hoyISO = () => fechaISO(new Date());
const noches = (r) => Math.round((new Date(r.fecha_salida) - new Date(r.fecha_entrada)) / 86400000);

// ---------------------------------------------------------------------
// Lista de recepción
// ---------------------------------------------------------------------
/**
 * Carga la vista elegida (llegadas, salidas, en casa, activas o todas), filtrada por el texto de búsqueda.
 * Una llegada cuya fecha de entrada ya pasó se marca como atrasada.
 */
async function cargarRecepcion() {
  const texto = $('#form-recepcion').q.value.trim();
  const parametros = new URLSearchParams({ vista: vistaRecepcion });
  if (texto) parametros.set('q', texto);
  const reservas = await api(`/api/gestion/reservas?${parametros}`);

  const hoy = hoyISO();
  $('#resumen-recepcion').textContent = reservas.length
    ? `${reservas.length} ${reservas.length === 1 ? 'reserva' : 'reservas'}${texto ? ' coinciden con la búsqueda' : ''}.`
    : '';
  $('#lista-recepcion').replaceChildren(tabla(
    ['Código', 'Huésped', 'Habitación', 'Entrada', 'Salida', 'Estado', ''],
    reservas.map((r) => [
      el('code', {}, r.codigo),
      r.nombre_huesped,
      `${r.habitacion} (${r.tipo})`,
      fechaCorta(r.fecha_entrada),
      fechaCorta(r.fecha_salida),
      el('span', {},
        etiquetaEstado(r.estado, ESTADOS),
        r.estado === 'confirmada' && r.fecha_entrada < hoy ? el('span', { clase: 'estado atrasada' }, 'Llegada atrasada') : null,
        r.estado === 'en_curso' && r.fecha_salida <= hoy ? el('span', { clase: 'estado sale-hoy' }, 'Sale hoy') : null),
      el('button', { clase: 'boton pequeno', type: 'button', onclick: () => intentar(() => abrirGestion(r.codigo)) }, 'Gestionar'),
    ]),
    texto ? 'Ninguna reserva coincide con la búsqueda.' : SIN_RESULTADOS[vistaRecepcion]));
}

/** Marca el botón de la vista elegida y recarga la lista. */
function elegirVista(vista) {
  vistaRecepcion = vista;
  for (const boton of document.querySelectorAll('#sec-recepcion [data-vista]')) {
    boton.setAttribute('aria-pressed', String(boton.dataset.vista === vista));
  }
  return cargarRecepcion();
}

/** Recarga todo lo que cambia después de una acción de recepción. */
async function refrescarPanel() {
  const tareas = [cargarRecepcion(), cargarHabitaciones()];
  if (!$('#sec-tablero').hidden) tareas.push(cargarTablero());   // definida en tablero.js
  if (!$('#sec-reservas').hidden) tareas.push(cargarReservas());
  if (ultimaBusqueda) tareas.push(buscar(ultimaBusqueda));
  await Promise.all(tareas);
}

// ---------------------------------------------------------------------
// Diálogo de gestión de una reserva
// ---------------------------------------------------------------------
/** Ejecuta una acción del diálogo y muestra el error dentro del diálogo, no detrás de él. */
async function intentarEnDialogo(accion) {
  const error = $('#error-gestion');
  error.hidden = true;
  try {
    await accion();
  } catch (e) {
    error.textContent = e.message;
    error.hidden = false;
  }
}

/** Abre el diálogo con los datos, las acciones posibles hoy y el historial de la reserva. */
async function abrirGestion(codigo) {
  gestionActual = await api(`/api/gestion/reservas/${encodeURIComponent(codigo)}`);
  const { reserva: r } = gestionActual;
  $('#gestion-codigo').textContent = r.codigo;
  $('#gestion-estado').replaceChildren(etiquetaEstado(r.estado, ESTADOS));
  $('#error-gestion').hidden = true;
  $('#form-modificar').hidden = true;
  mostrarFicha();
  mostrarAcciones();
  mostrarHistorial();
  const dialogo = $('#dlg-gestion');
  if (!dialogo.open) dialogo.showModal();
}

/** Datos de la reserva: huésped, habitación con su estado de limpieza, estadía y pago. */
function mostrarFicha() {
  const { reserva: r, piso, estado_limpieza: limpieza, fuera_de_servicio: fuera, pagada_en_linea: pagada } = gestionActual;
  let pago = 'Se paga en el hotel';
  if (pagada) pago = 'Pagado en línea';
  else if (r.estado === 'pendiente_pago') pago = 'Pendiente de pago en línea';
  const filas = [
    ['Huésped', el('span', {}, r.nombre_huesped, el('br'), el('small', {}, r.correo_huesped))],
    ['Habitación', el('span', {}, `${r.habitacion} · ${r.tipo} · piso ${piso} `,
      etiquetaEstado(limpieza, LIMPIEZA), fuera ? el('span', { clase: 'estado cancelada' }, 'Fuera de servicio') : null)],
    ['Estadía', `${fechaCorta(r.fecha_entrada)} al ${fechaCorta(r.fecha_salida)} · ${noches(r)} ${noches(r) === 1 ? 'noche' : 'noches'}`],
    ['Personas', String(r.personas)],
    ['Canal', CANALES[r.canal] || r.canal],
    ['Total con IVA', `${dinero.format(Number(r.total_con_impuesto))} · ${pago}`],
  ];
  $('#gestion-datos').replaceChildren(...filas.flatMap(([dt, dd]) => [el('dt', {}, dt), el('dd', {}, dd)]));
}

/** Botones de las acciones que la API indicó como posibles hoy para esta reserva. */
function mostrarAcciones() {
  const { acciones } = gestionActual;
  const botones = [];
  if (acciones.includes('check_in')) {
    botones.push(el('button', { clase: 'boton', type: 'button', onclick: () => intentarEnDialogo(registrarIngreso) }, 'Registrar ingreso'));
  }
  if (acciones.includes('check_out')) {
    botones.push(el('button', { clase: 'boton', type: 'button', onclick: () => intentarEnDialogo(registrarSalida) }, 'Registrar salida'));
  }
  if (acciones.includes('modificar')) {
    botones.push(el('button', { clase: 'boton claro', type: 'button', onclick: () => intentarEnDialogo(abrirModificar) }, 'Modificar'));
  }
  if (acciones.includes('cancelar')) {
    botones.push(el('button', { clase: 'boton peligro', type: 'button', onclick: () => intentarEnDialogo(cancelarDesdeGestion) }, 'Cancelar reserva'));
  }
  $('#gestion-acciones').replaceChildren(...(botones.length
    ? botones : [el('p', { clase: 'vacio' }, 'Esta reserva ya no admite cambios.')]));
}

/** Resume el detalle de una acción del historial (por ejemplo, qué cambió en una modificación). */
function resumenEvento(e) {
  const d = e.detalle || {};
  if (e.accion === 'modificar_reserva' && d.antes && d.despues) {
    const nombres = { habitacion: 'habitación', entrada: 'entrada', salida: 'salida', personas: 'personas', total: 'total' };
    const formato = (campo, valor) => {
      if (campo === 'entrada' || campo === 'salida') return fechaCorta(valor);
      if (campo === 'total') return dinero.format(Number(valor));
      return String(valor);
    };
    return Object.keys(nombres)
      .filter((campo) => String(d.antes[campo]) !== String(d.despues[campo]))
      .map((campo) => `${nombres[campo]}: ${formato(campo, d.antes[campo])} → ${formato(campo, d.despues[campo])}`)
      .join('; ');
  }
  if (e.accion === 'check_out' && d.salida_prevista) {
    return `habitación ${d.habitacion}; salida anticipada (estaba prevista para el ${fechaCorta(d.salida_prevista)})`;
  }
  if (d.habitacion) return `habitación ${d.habitacion}`;
  if (d.monto) return dinero.format(Number(d.monto));
  return '';
}

/** Historial de la reserva, del más antiguo al más reciente, con quién hizo cada acción. */
function mostrarHistorial() {
  const eventos = gestionActual.historial;
  if (!eventos.length) {
    $('#gestion-historial').replaceChildren(el('li', { clase: 'vacio' }, 'Sin acciones registradas.'));
    return;
  }
  $('#gestion-historial').replaceChildren(...eventos.map((e) => {
    const resumen = resumenEvento(e);
    return el('li', {},
      el('time', { datetime: e.fecha }, new Date(e.fecha).toLocaleString('es-CR', { dateStyle: 'short', timeStyle: 'short' })),
      el('strong', {}, ACCIONES_BITACORA[e.accion] || e.accion),
      el('span', { clase: 'quien' }, e.usuario || 'Sistema externo'),
      resumen ? el('span', { clase: 'detalle' }, resumen) : null);
  }));
}

/** Registra el ingreso y deja el diálogo abierto con el nuevo estado. */
async function registrarIngreso() {
  const { codigo } = gestionActual.reserva;
  const r = await api(`/api/gestion/reservas/${encodeURIComponent(codigo)}/check-in`, { metodo: 'POST' });
  avisar(`Ingreso registrado: ${r.codigo}, habitación ${r.habitacion}.`);
  await Promise.all([abrirGestion(codigo), refrescarPanel()]);
}

/** Registra la salida; si es antes de lo previsto, explica que las noches restantes se liberan. */
async function registrarSalida() {
  const { codigo, fecha_salida: salida, habitacion } = gestionActual.reserva;
  const pregunta = salida > hoyISO()
    ? `La salida estaba prevista para el ${fechaCorta(salida)}. ¿Registrar la salida anticipada? `
      + 'Las noches restantes quedarán libres y el monto no cambia.'
    : `¿Registrar la salida de la habitación ${habitacion}?`;
  if (!window.confirm(pregunta)) return;
  await api(`/api/gestion/reservas/${encodeURIComponent(codigo)}/check-out`, { metodo: 'POST' });
  avisar(`Salida registrada: ${codigo}. La habitación ${habitacion} quedó pendiente de limpieza.`);
  await Promise.all([abrirGestion(codigo), refrescarPanel()]);
}

/** Cancela con la misma función del listado de reservas (pide confirmación y reembolsa si hubo pago). */
async function cancelarDesdeGestion() {
  await cancelar(gestionActual.reserva);
  await Promise.all([abrirGestion(gestionActual.reserva.codigo), refrescarPanel()]);
}

// ---------------------------------------------------------------------
// Modificación: fechas, personas y habitación
// ---------------------------------------------------------------------
/**
 * Muestra el formulario con los valores actuales. Si el huésped ya ingresó, la entrada no se puede
 * cambiar. Enseguida carga las habitaciones posibles para esos valores.
 */
async function abrirModificar() {
  const { reserva: r } = gestionActual;
  const formulario = $('#form-modificar');
  formulario.fecha_entrada.value = r.fecha_entrada;
  formulario.fecha_entrada.disabled = r.estado === 'en_curso';
  formulario.fecha_salida.value = r.fecha_salida;
  formulario.personas.value = r.personas;
  formulario.hidden = false;
  await cargarAlternativas();
  formulario.fecha_salida.focus();
}

/**
 * Llena el selector con las habitaciones donde cabe la reserva, con el total de cada una y la
 * diferencia respecto del actual. Si la reserva ya se pagó en línea, las que cambian el monto
 * aparecen deshabilitadas, porque la API las rechazaría.
 */
async function cargarAlternativas() {
  const { reserva: r, pagada_en_linea: pagada } = gestionActual;
  const formulario = $('#form-modificar');
  const parametros = new URLSearchParams({
    entrada: formulario.fecha_entrada.value,
    salida: formulario.fecha_salida.value,
    personas: formulario.personas.value,
  });
  const selector = formulario.habitacion_id;
  selector.replaceChildren(el('option', { value: '' }, 'Buscando habitaciones…'));
  let opciones;
  try {
    opciones = await api(`/api/gestion/reservas/${encodeURIComponent(r.codigo)}/alternativas?${parametros}`);
  } catch (error) {
    selector.replaceChildren(el('option', { value: '' }, 'Revise las fechas y las personas'));
    throw error;
  }
  const actual = Number(r.total);
  selector.replaceChildren(...(opciones.length ? opciones.map((o) => {
    const diferencia = Number(o.total) - actual;
    let texto = `${o.numero} · ${o.tipo} · ${LIMPIEZA[o.estado_limpieza]} · ${dinero.format(Number(o.total))} sin IVA`;
    if (o.actual) texto += ' (habitación actual)';
    if (diferencia) texto += ` (${diferencia > 0 ? '+' : '−'}${dinero.format(Math.abs(diferencia))})`;
    const bloqueada = pagada && diferencia !== 0;
    if (bloqueada) texto += ' · cambia el monto pagado';
    const opcion = el('option', { value: String(o.habitacion_id) }, texto);
    opcion.disabled = bloqueada;
    opcion.selected = o.actual;
    return opcion;
  }) : [el('option', { value: '' }, 'No hay habitaciones libres con esos datos')]));
  $('#nota-modificar').textContent = pagada
    ? 'Esta reserva ya se pagó en línea: solo se permiten cambios que no alteran el monto. '
      + 'Para noches adicionales, cree una reserva nueva.'
    : 'El total se recalcula con la tarifa de cada noche. El huésped recibe un correo si cambian las fechas o la habitación.';
}

/** Envía solo los campos que cambiaron y vuelve a mostrar la reserva actualizada. */
async function guardarModificacion(formulario) {
  const { reserva: r } = gestionActual;
  const cambios = {};
  if (!formulario.fecha_entrada.disabled && formulario.fecha_entrada.value !== r.fecha_entrada) {
    cambios.fecha_entrada = formulario.fecha_entrada.value;
  }
  if (formulario.fecha_salida.value !== r.fecha_salida) cambios.fecha_salida = formulario.fecha_salida.value;
  if (Number(formulario.personas.value) !== r.personas) cambios.personas = Number(formulario.personas.value);
  const habitacion = Number(formulario.habitacion_id.value);
  if (habitacion) cambios.habitacion_id = habitacion;
  const nueva = await api(`/api/gestion/reservas/${encodeURIComponent(r.codigo)}`, { metodo: 'PATCH', json: cambios });
  avisar(`Reserva ${nueva.codigo} actualizada: habitación ${nueva.habitacion}, del ${fechaCorta(nueva.fecha_entrada)} `
    + `al ${fechaCorta(nueva.fecha_salida)}, ${dinero.format(Number(nueva.total_con_impuesto))} con IVA.`);
  await Promise.all([abrirGestion(r.codigo), refrescarPanel()]);
}

// ---------------------------------------------------------------------
// Eventos
// ---------------------------------------------------------------------
document.addEventListener('DOMContentLoaded', () => {
  for (const boton of document.querySelectorAll('#sec-recepcion [data-vista]')) {
    boton.addEventListener('click', () => intentar(() => elegirVista(boton.dataset.vista)));
  }
  // Una búsqueda por texto revisa todas las reservas, no solo la vista elegida
  $('#form-recepcion').addEventListener('submit', (evento) => {
    evento.preventDefault();
    intentar(() => ($('#form-recepcion').q.value.trim() ? elegirVista('todas') : cargarRecepcion()));
  });
  $('#btn-recargar-recepcion').addEventListener('click', () => intentar(cargarRecepcion));

  const formulario = $('#form-modificar');
  for (const campo of [formulario.fecha_entrada, formulario.fecha_salida, formulario.personas]) {
    campo.addEventListener('change', () => intentarEnDialogo(cargarAlternativas));
  }
  formulario.addEventListener('submit', (evento) => {
    evento.preventDefault();
    const boton = formulario.querySelector('button[type=submit]');
    boton.disabled = true;
    intentarEnDialogo(() => guardarModificacion(formulario)).finally(() => { boton.disabled = false; });
  });
  $('#btn-descartar-cambios').addEventListener('click', () => { formulario.hidden = true; });
});
