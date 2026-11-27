// =====================================================================
// Hotel Soluna: cuenta de la habitación (etapa 5)
//   - En la gestión de una reserva (recepción y gerencia): estado de cuenta,
//     cargar consumos del catálogo o libres, anular con motivo y registrar
//     pagos. "Registrar salida" cobra el saldo con el método elegido.
//   - Catálogo de servicios para gerencia.
//   - "Mi cuenta" para el huésped, desde Mis reservas (solo lectura).
// Usa las utilidades de app.js y la gestión de gestion.js; todo texto se
// inserta como texto, nunca como HTML.
// =====================================================================
'use strict';

const CATEGORIAS_SERVICIO = {
  room_service: 'Room service', restaurante: 'Restaurante', bar: 'Bar', minibar: 'Minibar', spa: 'Spa',
  lavanderia: 'Lavandería', transporte: 'Transporte', tours: 'Tours', otros: 'Otros',
};
const METODOS_PAGO = { tarjeta: 'Tarjeta', efectivo: 'Efectivo', sinpe: 'SINPE Móvil', transferencia: 'Transferencia' };
const MODALIDADES = {
  en_linea: 'Pagado en línea al reservar', agencia: 'Lo paga la agencia de viajes', cancelada: 'No aplica',
};

let catalogoServicios = null;   // catálogo activo, se pide una vez por sesión
let cuentaGestion = null;       // cuenta de la reserva abierta en el diálogo de gestión

const usd = (monto) => dinero.format(Number(monto));
const fechaHora = (iso) => new Date(iso).toLocaleString('es-CR', { dateStyle: 'short', timeStyle: 'short' });

// ---------------------------------------------------------------------
// Dibujo del estado de cuenta (común al personal y al huésped)
// ---------------------------------------------------------------------
/**
 * Totales, consumos, pagos y factura final. Con `anular`, cada cargo vigente tiene su botón para
 * anularlo (solo el personal y solo con el huésped alojado).
 */
function dibujarCuenta(c, { anular = null } = {}) {
  const filas = [
    ['Hospedaje', c.hospedaje_modalidad === 'en_hotel' ? usd(c.hospedaje) : MODALIDADES[c.hospedaje_modalidad]],
    ['Consumos', usd(c.consumos)],
    ['IVA (13 %)', usd(c.impuesto)],
    ['Total en el hotel', usd(c.total)],
    ['Pagado', usd(c.pagado)],
  ];
  const totales = el('dl', { clase: 'cuenta-totales' },
    ...filas.flatMap(([dt, dd]) => [el('dt', {}, dt), el('dd', {}, dd)]),
    el('dt', { clase: 'por-pagar' }, 'Por pagar a la salida'), el('dd', { clase: 'por-pagar' }, usd(c.por_pagar)),
    ...(Number(c.a_favor) > 0 ? [el('dt', {}, 'A favor del huésped'), el('dd', {}, usd(c.a_favor))] : []));

  const consumos = c.cargos.length
    ? tabla(['Fecha', 'Concepto', 'Cant.', 'Precio', 'Total', ''], c.cargos.map((x) => [
      fechaHora(x.creado_en),
      el('span', { clase: x.anulado ? 'anulado' : '' }, x.descripcion,
        el('br'), el('small', {}, CATEGORIAS_SERVICIO[x.categoria]
          + (x.creado_por ? ` · cargó ${x.creado_por}` : '')
          + (x.anulado ? ` · anulado: ${x.motivo_anulacion}` : ''))),
      String(x.cantidad),
      usd(x.precio_unitario),
      el('span', { clase: x.anulado ? 'anulado' : '' }, usd(x.total)),
      anular && !x.anulado
        ? el('button', { clase: 'boton claro pequeno', type: 'button', onclick: () => anular(x) }, 'Anular') : '',
    ]), '')
    : el('p', { clase: 'vacio' }, 'Sin consumos cargados.');

  const pagos = c.pagos.length
    ? el('ul', { clase: 'pagos-caja' }, ...c.pagos.map((p) => el('li', {},
      `${fechaHora(p.creado_en)} · ${METODOS_PAGO[p.metodo]} · ${usd(p.monto)}`
      + (p.referencia ? ` · ref. ${p.referencia}` : '') + (p.recibido_por ? ` · recibió ${p.recibido_por}` : ''))))
    : null;

  const factura = c.factura_final
    ? el('p', { clase: 'nota sin-margen' }, `Factura electrónica final ${c.factura_final.consecutivo} por `
      + `${usd(c.factura_final.total)}: ${c.factura_final.estado === 'aceptada' ? 'aceptada por Hacienda'
        : c.factura_final.estado}.`)
    : null;

  return [totales, el('h4', {}, 'Consumos'), consumos,
    pagos ? el('h4', {}, 'Pagos recibidos') : null, pagos, factura].filter(Boolean);
}

// ---------------------------------------------------------------------
// Personal: cuenta en el diálogo de gestión
// ---------------------------------------------------------------------
/** Pide el catálogo activo una sola vez y llena el selector de consumos, agrupado por categoría. */
async function prepararCatalogo() {
  if (!catalogoServicios) catalogoServicios = await api('/api/servicios');
  const grupos = new Map();
  for (const s of catalogoServicios) {
    if (!grupos.has(s.categoria)) grupos.set(s.categoria, []);
    grupos.get(s.categoria).push(s);
  }
  $('#form-cargo').servicio_id.replaceChildren(
    ...[...grupos.entries()].map(([categoria, lista]) => el('optgroup', { label: CATEGORIAS_SERVICIO[categoria] },
      ...lista.map((s) => el('option', { value: String(s.id) }, `${s.nombre} · ${usd(s.precio)}`)))),
    el('option', { value: 'otro' }, 'Otro (fuera del catálogo)…'));
  ajustarCargoLibre();
}

/** Muestra los campos de descripción, categoría y precio solo para un cargo fuera del catálogo. */
function ajustarCargoLibre() {
  const formulario = $('#form-cargo');
  const libre = formulario.servicio_id.value === 'otro';
  for (const campo of formulario.querySelectorAll('.solo-libre')) campo.hidden = !libre;
  formulario.descripcion.required = libre;
  formulario.precio_unitario.required = libre;
}

/** Carga la cuenta de la reserva abierta en la gestión y la dibuja con sus formularios. */
async function cargarCuentaGestion(codigo) {
  cuentaGestion = await api(`/api/gestion/reservas/${encodeURIComponent(codigo)}/cuenta`);
  mostrarCuentaGestion();
}

/** Dibuja la cuenta, el "por pagar" de la ficha y los formularios que aplican al estado de la reserva. */
function mostrarCuentaGestion() {
  const c = cuentaGestion;
  $('#cuenta-contenido').replaceChildren(...dibujarCuenta(c, { anular: c.puede_cargar ? anularCargo : null }));
  const porPagar = $('#ficha-por-pagar');
  if (porPagar) porPagar.replaceChildren(el('strong', {}, usd(c.por_pagar)), c.por_pagar > 0 ? ' (se cobra al registrar la salida)' : '');
  $('#form-cargo').hidden = !c.puede_cargar;
  const puedePagar = Number(c.por_pagar) > 0 && ['confirmada', 'en_curso'].includes(c.estado);
  $('#form-pago-caja').hidden = !puedePagar;
  if (puedePagar) $('#form-pago-caja').monto.value = c.por_pagar;
  if (c.puede_cargar) intentarEnDialogo(prepararCatalogo);
  mostrarAcciones();   // "Registrar salida" indica si hay saldo que cobrar
}

/** Carga el consumo elegido (del catálogo o libre) a la cuenta. */
async function cargarConsumo(formulario) {
  const datos = Object.fromEntries(new FormData(formulario));
  const cuerpo = { cantidad: Number(datos.cantidad) };
  if (datos.servicio_id === 'otro') {
    Object.assign(cuerpo, { descripcion: datos.descripcion, categoria: datos.categoria, precio_unitario: datos.precio_unitario });
  } else {
    cuerpo.servicio_id = Number(datos.servicio_id);
  }
  cuentaGestion = await api(`/api/gestion/reservas/${encodeURIComponent(cuentaGestion.codigo)}/cargos`, { metodo: 'POST', json: cuerpo });
  const ultimo = cuentaGestion.cargos[cuentaGestion.cargos.length - 1];
  avisar(`Cargado a la habitación: ${ultimo.cantidad} × ${ultimo.descripcion} (${usd(ultimo.total)} sin IVA).`);
  formulario.reset();
  mostrarCuentaGestion();
  await refrescarHistorial();
}

/** Anula un cargo después de pedir el motivo. */
async function anularCargo(cargo) {
  const motivo = window.prompt(`¿Por qué se anula "${cargo.descripcion}" (${usd(cargo.total)})?`);
  if (motivo === null) return;
  await intentarEnDialogo(async () => {
    cuentaGestion = await api(`/api/gestion/reservas/${encodeURIComponent(cuentaGestion.codigo)}/cargos/${cargo.id}/anular`,
      { metodo: 'POST', json: { motivo } });
    avisar(`Cargo anulado: ${cargo.descripcion}.`);
    mostrarCuentaGestion();
    await refrescarHistorial();
  });
}

/** Registra un pago en caja (adelanto o saldo). */
async function registrarPagoCaja(formulario) {
  const datos = Object.fromEntries(new FormData(formulario));
  cuentaGestion = await api(`/api/gestion/reservas/${encodeURIComponent(cuentaGestion.codigo)}/pagos`, {
    metodo: 'POST', json: { monto: datos.monto, metodo: datos.metodo, referencia: datos.referencia || null },
  });
  avisar(`Pago registrado: ${usd(datos.monto)} con ${METODOS_PAGO[datos.metodo].toLowerCase()}. `
    + `Por pagar a la salida: ${usd(cuentaGestion.por_pagar)}.`);
  formulario.reset();
  mostrarCuentaGestion();
  await refrescarHistorial();
}

/** Vuelve a pedir el detalle de la reserva para actualizar el historial (cargos y pagos quedan en la bitácora). */
async function refrescarHistorial() {
  gestionActual = await api(`/api/gestion/reservas/${encodeURIComponent(gestionActual.reserva.codigo)}`);
  mostrarHistorial();
}

/** Método y referencia con que se cobra el saldo al registrar la salida (los del formulario de pago). */
function cobroDeSalida() {
  const formulario = $('#form-pago-caja');
  return { metodo_pago: formulario.metodo.value, referencia: formulario.referencia.value.trim() || null };
}

// ---------------------------------------------------------------------
// Huésped: "Mi cuenta"
// ---------------------------------------------------------------------
/** Abre la cuenta de una estadía propia, en solo lectura. */
async function abrirMiCuenta(codigo) {
  $('#mi-cuenta-codigo').textContent = codigo;
  $('#mi-cuenta-contenido').replaceChildren(el('p', { clase: 'nota' }, 'Cargando…'));
  $('#error-mi-cuenta').hidden = true;
  $('#dlg-mi-cuenta').showModal();
  try {
    const c = await api(`/api/reservas/${encodeURIComponent(codigo)}/cuenta`);
    $('#mi-cuenta-contenido').replaceChildren(...dibujarCuenta(c));
  } catch (error) {
    $('#mi-cuenta-contenido').replaceChildren();
    $('#error-mi-cuenta').textContent = error.message;
    $('#error-mi-cuenta').hidden = false;
  }
}

// ---------------------------------------------------------------------
// Gerencia: catálogo de servicios
// ---------------------------------------------------------------------
/** Lista todo el catálogo, también lo inactivo, con precio editable y un interruptor de activo. */
async function cargarCatalogoGerencia() {
  const servicios = await api('/api/servicios?todos=true');
  $('#lista-servicios').replaceChildren(tabla(['Servicio', 'Categoría', 'Precio (sin IVA)', 'Activo', ''],
    servicios.map((s) => {
      const precio = el('input', { type: 'number', min: '0.01', step: '0.01', value: s.precio, 'aria-label': `Precio de ${s.nombre}`, clase: 'precio-corto' });
      const activo = el('input', { type: 'checkbox', 'aria-label': `${s.nombre} activo` });
      activo.checked = s.activo;
      const guardar = el('button', {
        clase: 'boton claro pequeno', type: 'button',
        onclick: () => intentar(() => guardarServicio(s, precio.value, activo.checked)),
      }, 'Guardar');
      return [el('span', { clase: s.activo ? '' : 'anulado' }, s.nombre), CATEGORIAS_SERVICIO[s.categoria], precio, activo, guardar];
    }), 'No hay servicios.'));
}

/** Guarda el precio o el estado de un servicio, solo si cambiaron. */
async function guardarServicio(servicio, precio, activo) {
  const cambios = {};
  if (Number(precio) !== Number(servicio.precio)) cambios.precio = precio;
  if (activo !== servicio.activo) cambios.activo = activo;
  if (!Object.keys(cambios).length) {
    avisar(`"${servicio.nombre}" no tiene cambios.`);
    return;
  }
  await api(`/api/servicios/${servicio.id}`, { metodo: 'PATCH', json: cambios });
  catalogoServicios = null;   // recepción verá el catálogo nuevo en el próximo consumo
  avisar(`"${servicio.nombre}" actualizado. Lo ya cargado a las cuentas no cambia.`);
  await cargarCatalogoGerencia();
}

/** Agrega un servicio nuevo al catálogo. */
async function agregarServicio(formulario) {
  const datos = Object.fromEntries(new FormData(formulario));
  await api('/api/servicios', { metodo: 'POST', json: { nombre: datos.nombre, categoria: datos.categoria, precio: datos.precio } });
  catalogoServicios = null;
  avisar(`"${datos.nombre.trim()}" agregado al catálogo.`);
  formulario.reset();
  await cargarCatalogoGerencia();
}

// ---------------------------------------------------------------------
// Eventos
// ---------------------------------------------------------------------
document.addEventListener('DOMContentLoaded', () => {
  const cargo = $('#form-cargo');
  cargo.categoria.replaceChildren(...Object.entries(CATEGORIAS_SERVICIO).map(([valor, texto]) => el('option', { value: valor }, texto)));
  cargo.servicio_id.addEventListener('change', ajustarCargoLibre);
  cargo.addEventListener('submit', (evento) => {
    evento.preventDefault();
    intentarEnDialogo(() => cargarConsumo(cargo));
  });
  const pago = $('#form-pago-caja');
  pago.metodo.replaceChildren(...Object.entries(METODOS_PAGO).map(([valor, texto]) => el('option', { value: valor }, texto)));
  pago.addEventListener('submit', (evento) => {
    evento.preventDefault();
    intentarEnDialogo(() => registrarPagoCaja(pago));
  });
  const servicio = $('#form-servicio');
  servicio.categoria.replaceChildren(...Object.entries(CATEGORIAS_SERVICIO).map(([valor, texto]) => el('option', { value: valor }, texto)));
  servicio.addEventListener('submit', (evento) => {
    evento.preventDefault();
    intentar(() => agregarServicio(servicio));
  });
  // Al salir de la sesión se olvida el catálogo (otro usuario puede tener otro rol)
  $('#btn-salir').addEventListener('click', () => { catalogoServicios = null; });
});
