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
const CANALES = { web: 'Sitio web', recepcion: 'Recepción (mostrador)', telefono: 'Teléfono', ota: 'Agencia en línea (OTA)' };
// Hora del día de llegada hasta la que se garantizan habitación y tarifa (igual que HORA_GARANTIA en la API)
const HORA_GARANTIA = 17;

// Nombre legible de cada acción de la bitácora que aparece en el historial
const ACCIONES_BITACORA = {
  crear_reserva: 'Reserva creada',
  reserva_ota: 'Reserva recibida de la agencia en línea',
  pago_aprobado: 'Pago aprobado',
  pago_rechazado: 'Pago rechazado',
  reembolso: 'Pago reembolsado',
  comprobante_enviado: 'Comprobante de pago enviado por el huésped',
  comprobante_aceptado: 'Comprobante aceptado: pago registrado y reserva confirmada',
  comprobante_rechazado: 'Comprobante de pago rechazado',
  cancelar_reserva: 'Reserva cancelada',
  check_in: 'Ingreso del huésped (check-in)',
  check_out: 'Salida del huésped (check-out)',
  modificar_reserva: 'Reserva modificada',
  publicar_resena: 'Reseña publicada',
  cargar_consumo: 'Consumo cargado a la habitación',
  anular_cargo: 'Cargo anulado',
  pago_caja: 'Pago recibido en recepción',
  liberar_no_presentado: 'Liberada: no se presentó antes de la hora de garantía',
};
const METODOS_BITACORA = { efectivo: 'efectivo', tarjeta: 'tarjeta', sinpe: 'SINPE Móvil', transferencia: 'transferencia' };

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
const horaGarantia = (h = HORA_GARANTIA) => `${h % 12 || 12}:00 ${h < 12 ? 'a. m.' : 'p. m.'}`;

/** Etiqueta de la garantía de una reserva que se paga al llegar: vencida, o hasta qué hora de hoy. */
function etiquetaGarantia(r) {
  if (!r.garantia_hasta) return null;
  if (Date.now() >= new Date(r.garantia_hasta)) return el('span', { clase: 'estado atrasada' }, 'Garantía vencida');
  if (r.fecha_entrada === hoyISO()) return el('span', { clase: 'estado pendiente' }, `Garantía hasta las ${horaGarantia()}`);
  return null;
}
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
        r.estado === 'en_curso' && r.fecha_salida <= hoy ? el('span', { clase: 'estado sale-hoy' }, 'Sale hoy') : null,
        etiquetaGarantia(r)),
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
  cuentaGestion = null;   // cuenta.js la carga enseguida
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
  await cargarCuentaGestion(r.codigo);   // cuenta de la habitación (cuenta.js)
}

/** Datos de la reserva: huésped, habitación con su estado de limpieza, estadía y pago. */
function mostrarFicha() {
  const { reserva: r, piso, estado_limpieza: limpieza, fuera_de_servicio: fuera, pagada_en_linea: pagada } = gestionActual;
  let pago = 'Se paga en el hotel';
  if (pagada) pago = 'Pagado en línea';
  else if (r.estado === 'pendiente_pago') {
    pago = r.comprobante_estado === 'pendiente'
      ? 'Pendiente de pago: comprobante de SINPE o transferencia en revisión'
      : 'Pendiente de pago en línea';
  }
  if (r.garantia_hasta) {
    const vencida = Date.now() >= new Date(r.garantia_hasta);
    pago += ` · garantía hasta las ${horaGarantia()} del ${fechaCorta(r.fecha_entrada)}${vencida ? ' (vencida)' : ''}`;
  }
  const contacto = [r.correo_huesped];
  if (r.telefono_huesped) contacto.push(r.telefono_huesped);
  const filas = [
    ['Huésped', el('span', {}, r.nombre_huesped, el('br'), el('small', {}, contacto.join(' · ')))],
    ['Habitación', el('span', {}, `${r.habitacion} · ${r.tipo} · piso ${piso} `,
      etiquetaEstado(limpieza, LIMPIEZA), fuera ? el('span', { clase: 'estado cancelada' }, 'Fuera de servicio') : null)],
    ['Estadía', `${fechaCorta(r.fecha_entrada)} al ${fechaCorta(r.fecha_salida)} · ${noches(r)} ${noches(r) === 1 ? 'noche' : 'noches'}`],
    ['Personas', String(r.personas)],
    ['Canal', CANALES[r.canal] || r.canal],
    ['Total con IVA', `${dinero.format(Number(r.total_con_impuesto))} · ${pago}`],
    // La llena cuenta.js con el saldo de la cuenta de la habitación
    ['Por pagar a la salida', el('span', { id: 'ficha-por-pagar' }, 'Calculando…')],
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
    const saldo = cuentaGestion && cuentaGestion.codigo === gestionActual.reserva.codigo ? Number(cuentaGestion.por_pagar) : 0;
    const texto = saldo > 0 ? `Cobrar ${dinero.format(saldo)} y registrar salida` : 'Registrar salida';
    botones.push(el('button', { clase: 'boton', type: 'button', onclick: () => intentarEnDialogo(registrarSalida) }, texto));
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
  const medio = { sinpe: 'SINPE Móvil', transferencia: 'transferencia' }[d.metodo] || d.metodo;
  if (e.accion === 'comprobante_enviado') {
    return `${medio} ${d.numero} por ${dinero.format(Number(d.monto))}${d.archivo ? ', con archivo' : ''}`;
  }
  if (e.accion === 'comprobante_aceptado') return `${medio} ${d.numero}; factura ${d.factura}`;
  if (e.accion === 'comprobante_rechazado') return `${medio} ${d.numero}: ${d.motivo}`;
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
  if (e.accion === 'liberar_no_presentado') {
    return `la garantía vencía a las ${horaGarantia(d.hora_garantia)} del ${fechaCorta(d.fecha_entrada)}; la habitación quedó libre`;
  }
  if (e.accion === 'cargar_consumo') return `${d.cantidad} × ${d.descripcion}: ${dinero.format(Number(d.total))} sin IVA`;
  if (e.accion === 'anular_cargo') return `${d.descripcion} (${dinero.format(Number(d.total))}); motivo: ${d.motivo}`;
  if (e.accion === 'pago_caja') return `${dinero.format(Number(d.monto))} con ${METODOS_BITACORA[d.metodo] || d.metodo}`;
  if (e.accion === 'check_out') {
    const partes = [`habitación ${d.habitacion}`];
    if (d.salida_prevista) partes.push(`salida anticipada (estaba prevista para el ${fechaCorta(d.salida_prevista)})`);
    if (d.cobrado) partes.push(`cobrados ${dinero.format(Number(d.cobrado))} con ${METODOS_BITACORA[d.metodo_pago] || d.metodo_pago}`);
    if (d.factura_final) partes.push(`factura final ${d.factura_final}`);
    return partes.join('; ');
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
      el('span', { clase: 'quien' }, e.usuario || (e.accion === 'reserva_ota' ? 'Agencia en línea' : 'Sistema (automático)')),
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
  // Si queda saldo, se cobra con el método elegido en el formulario de pago de la cuenta (cuenta.js)
  const saldo = cuentaGestion ? Number(cuentaGestion.por_pagar) : 0;
  const cobro = saldo > 0 ? cobroDeSalida() : null;
  let pregunta = salida > hoyISO()
    ? `La salida estaba prevista para el ${fechaCorta(salida)}. ¿Registrar la salida anticipada? `
      + 'Las noches restantes quedarán libres y el monto no cambia.'
    : `¿Registrar la salida de la habitación ${habitacion}?`;
  if (cobro) pregunta += `\n\nSe cobrarán ${dinero.format(saldo)} con ${METODOS_PAGO[cobro.metodo_pago].toLowerCase()} `
    + 'y se emitirá la factura electrónica final.';
  if (!window.confirm(pregunta)) return;
  await api(`/api/gestion/reservas/${encodeURIComponent(codigo)}/check-out`, { metodo: 'POST', json: cobro || {} });
  avisar(`Salida registrada: ${codigo}${cobro ? `, cobrados ${dinero.format(saldo)}` : ''}. `
    + `La habitación ${habitacion} quedó pendiente de limpieza.`);
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
// Nueva reserva tomada por recepción (por teléfono o en el mostrador)
// ---------------------------------------------------------------------
// Tipos de habitación libres para las fechas elegidas, con sus habitaciones y el total sin IVA
let opcionesNueva = [];

/**
 * Abre el formulario. Desde "Nueva reserva" empieza con entrada hoy y salida mañana; desde el botón
 * "Reservar" de Disponibilidad llega con las fechas, las personas y el tipo ya elegidos.
 */
function abrirNuevaReserva(inicial = {}) {
  const formulario = $('#form-nueva-reserva');
  formulario.reset();
  const manana = new Date();
  manana.setDate(manana.getDate() + 1);
  formulario.entrada.value = inicial.entrada || hoyISO();
  formulario.entrada.min = hoyISO();
  formulario.salida.value = inicial.salida || fechaISO(manana);
  formulario.personas.value = inicial.personas || 2;
  $('#error-nueva').hidden = true;
  ajustarCanalNueva();
  $('#dlg-nueva-reserva').showModal();
  intentarEnNueva(() => cargarOpcionesNueva(inicial.tipo));
}

/** Ejecuta una acción del formulario y muestra el error dentro del diálogo. */
async function intentarEnNueva(accion) {
  $('#error-nueva').hidden = true;
  try {
    await accion();
  } catch (error) {
    $('#error-nueva').textContent = error.message;
    $('#error-nueva').hidden = false;
  }
}

/** Por teléfono, el número de contacto es obligatorio; en el mostrador, opcional. */
function ajustarCanalNueva() {
  const formulario = $('#form-nueva-reserva');
  formulario.telefono_huesped.required = formulario.canal.value === 'telefono';
}

/**
 * Consulta la disponibilidad de las fechas y personas elegidas y muestra un tipo de habitación por
 * opción, con cuántas quedan libres y el total. Deja elegido el tipo indicado o el primero.
 */
async function cargarOpcionesNueva(tipoPreferido) {
  const formulario = $('#form-nueva-reserva');
  const parametros = new URLSearchParams({
    entrada: formulario.entrada.value, salida: formulario.salida.value, personas: formulario.personas.value,
  });
  opcionesNueva = [];
  $('#nueva-tipos').replaceChildren(el('p', { clase: 'nota sin-margen' }, 'Buscando habitaciones libres…'));
  const libres = await api(`/api/disponibilidad?${parametros}`);
  const tipos = new Map();
  for (const h of libres) {
    if (!tipos.has(h.tipo)) tipos.set(h.tipo, { tipo: h.tipo, capacidad: h.capacidad, total: Number(h.total), noches: h.noches, habitaciones: [] });
    tipos.get(h.tipo).habitaciones.push(h);
  }
  opcionesNueva = [...tipos.values()];
  if (!opcionesNueva.length) {
    $('#nueva-tipos').replaceChildren(el('p', { clase: 'vacio' }, 'No hay habitaciones libres para esas fechas y personas.'));
    formulario.habitacion_id.replaceChildren();
    mostrarResumenNueva();
    return;
  }
  const elegido = opcionesNueva.some((o) => o.tipo === tipoPreferido) ? tipoPreferido : opcionesNueva[0].tipo;
  $('#nueva-tipos').replaceChildren(...opcionesNueva.map((o) => {
    const opcion = el('input', { type: 'radio', name: 'tipo', value: o.tipo });
    opcion.checked = o.tipo === elegido;
    opcion.addEventListener('change', () => { elegirTipoNueva(); });
    return el('label', { clase: 'tipo-opcion' }, opcion,
      el('span', {},
        el('strong', {}, o.tipo),
        el('small', {}, ` · hasta ${o.capacidad} personas · ${o.habitaciones.length} libres`),
        el('br'),
        `${dinero.format(o.total)} por ${o.noches} ${o.noches === 1 ? 'noche' : 'noches'}, sin IVA`));
  }));
  elegirTipoNueva();
}

/** Llena el selector con las habitaciones libres del tipo elegido y actualiza el resumen. */
function elegirTipoNueva() {
  const formulario = $('#form-nueva-reserva');
  const opcion = opcionesNueva.find((o) => o.tipo === formulario.tipo.value);
  formulario.habitacion_id.replaceChildren(...(opcion ? opcion.habitaciones.map((h) =>
    el('option', { value: String(h.habitacion_id) }, `Habitación ${h.numero}`)) : []));
  mostrarResumenNueva();
}

/**
 * Resumen antes de confirmar: total con IVA a pagar al llegar y hasta cuándo se garantiza. Si la
 * llegada es hoy y ya pasó la hora de garantía, lo advierte.
 */
function mostrarResumenNueva() {
  const formulario = $('#form-nueva-reserva');
  const opcion = opcionesNueva.find((o) => o.tipo === formulario.tipo?.value);
  const resumen = $('#nueva-resumen');
  $('#btn-crear-reserva').disabled = !opcion;
  if (!opcion) {
    resumen.replaceChildren();
    return;
  }
  const impuesto = Math.round(opcion.total * 13) / 100;
  const entrada = formulario.entrada.value;
  const tarde = entrada === hoyISO() && new Date().getHours() >= HORA_GARANTIA;
  resumen.replaceChildren(
    el('p', {}, 'Total a pagar al llegar: ', el('strong', {}, dinero.format(opcion.total + impuesto)),
      el('small', {}, ` (${dinero.format(opcion.total)} + IVA ${dinero.format(impuesto)})`)),
    el('p', { clase: tarde ? 'alerta' : '' }, tarde
      ? `La llegada es hoy y ya pasaron las ${horaGarantia()}: la habitación queda reservada para esta noche `
        + 'y no se libera sola. Si el huésped avisa que no llega, cancélela.'
      : `La habitación y la tarifa se garantizan hasta las ${horaGarantia()} del ${fechaCorta(entrada)}. `
        + 'Si no llega antes ni paga un adelanto, la reserva se libera sola y el precio no se conserva. '
        + 'El correo de confirmación lo explica.'));
}

/** Crea la reserva, avisa a quién se envió la confirmación y la abre en el diálogo de gestión. */
async function crearNuevaReserva(formulario) {
  const datos = Object.fromEntries(new FormData(formulario));
  const reserva = await api('/api/reservas', {
    metodo: 'POST',
    json: {
      habitacion_id: Number(datos.habitacion_id),
      fecha_entrada: datos.entrada,
      fecha_salida: datos.salida,
      personas: Number(datos.personas),
      nombre_huesped: datos.nombre_huesped.trim(),
      correo_huesped: datos.correo_huesped.trim(),
      telefono_huesped: datos.telefono_huesped.trim() || null,
      canal: datos.canal,
    },
  });
  $('#dlg-nueva-reserva').close();
  avisar(`Reserva ${reserva.codigo} creada para ${reserva.nombre_huesped}: habitación ${reserva.habitacion}, `
    + `${dinero.format(Number(reserva.total_con_impuesto))} a pagar al llegar. Confirmación enviada a ${reserva.correo_huesped}.`);
  await Promise.all([refrescarPanel(), abrirGestion(reserva.codigo)]);
}

/**
 * Libera ya las reservas no presentadas (lo mismo que la tarea automática de cada hora) y avisa
 * cuáles quedaron libres.
 */
async function liberarNoPresentados() {
  if (!window.confirm(`¿Liberar las reservas que se pagan al llegar, sin ingreso ni adelanto, cuya garantía `
    + `(${horaGarantia()} del día de llegada) ya venció? El sistema lo hace solo cada hora.`)) return;
  const liberadas = await api('/api/gestion/liberar-no-presentados', { metodo: 'POST' });
  avisar(liberadas.length
    ? `Liberadas ${liberadas.length}: ${liberadas.map((r) => `${r.codigo} (habitación ${r.habitacion})`).join(', ')}.`
    : 'No había reservas con la garantía vencida para liberar.');
  await refrescarPanel();
}

// ---------------------------------------------------------------------
// Eventos
// ---------------------------------------------------------------------
document.addEventListener('DOMContentLoaded', () => {
  $('#btn-liberar').addEventListener('click', () => intentar(liberarNoPresentados));
  // Nueva reserva
  $('#btn-nueva-reserva').addEventListener('click', () => abrirNuevaReserva());
  const nueva = $('#form-nueva-reserva');
  for (const campo of [nueva.entrada, nueva.salida, nueva.personas]) {
    campo.addEventListener('change', () => intentarEnNueva(() => cargarOpcionesNueva(nueva.tipo?.value)));
  }
  for (const radio of nueva.querySelectorAll('input[name=canal]')) radio.addEventListener('change', ajustarCanalNueva);
  nueva.addEventListener('submit', (evento) => {
    evento.preventDefault();
    const boton = $('#btn-crear-reserva');
    boton.disabled = true;
    intentarEnNueva(() => crearNuevaReserva(nueva)).finally(() => { boton.disabled = !opcionesNueva.length; });
  });

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
