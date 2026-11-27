// =====================================================================
// Hotel Soluna: tablero de habitaciones (panel del personal, etapa 2)
// Muestra cada habitación hoy, por piso: libre, ocupada, llega hoy, sale
// hoy, llegada atrasada o fuera de servicio, con su estado de limpieza y
// el código de la reserva activa, que abre la gestión de esa reserva
// (gestion.js). Usa las utilidades de app.js y se carga después de él.
//
// Consumo de la base: el tablero se pide una vez por minuto y solo
// mientras la pestaña está visible y el tablero en pantalla. Cada pedido
// cuesta tres consultas, sin importar cuántas reservas haya.
// =====================================================================
'use strict';

const INTERVALO_TABLERO = 60 * 1000;

// Nombre, orden y descripción de cada situación (el color lo da la clase CSS sit-<situación>)
const SITUACIONES = {
  libre: 'Libre',
  llega_hoy: 'Llega hoy',
  llegada_atrasada: 'Llegada atrasada',
  ocupada: 'Ocupada',
  sale_hoy: 'Sale hoy',
  fuera_de_servicio: 'Fuera de servicio',
};

// Momento de la última carga y situación elegida en la leyenda (filtro)
let ultimaCargaTablero = 0;
let filtroTablero = null;

const fechaDiaMes = (iso) => iso.split('-').reverse().slice(0, 2).join('/');   // AAAA-MM-DD a DD/MM
const horaCorta = (fecha) => fecha.toLocaleTimeString('es-CR', { hour: '2-digit', minute: '2-digit' });

/** El tablero se actualiza por sí mismo solo si hay sesión, la tarjeta está visible y la pestaña también. */
function tableroVisible() {
  return Boolean(sesion.token) && !$('#sec-tablero').hidden && document.visibilityState === 'visible';
}

// ---------------------------------------------------------------------
// Carga y dibujo
// ---------------------------------------------------------------------
/** Pide el tablero a la API y dibuja los indicadores, la leyenda y los pisos. */
async function cargarTablero() {
  const datos = await api('/api/gestion/tablero');
  ultimaCargaTablero = Date.now();
  $('#fecha-tablero').textContent = fechaCorta(datos.fecha);
  $('#actualizado-tablero').textContent = `Actualizado a las ${horaCorta(new Date())}`;
  mostrarIndicadores(datos.resumen);
  mostrarLeyenda(datos.habitaciones);
  mostrarPisos(datos.habitaciones, datos.fecha);
}

/** Indicadores del día: ocupación, llegadas, salidas, habitaciones listas, por limpiar y fuera de servicio. */
function mostrarIndicadores(r) {
  const indicadores = [
    ['Ocupación', `${Number(r.ocupacion).toLocaleString('es-CR', { minimumFractionDigits: 1 })} %`,
      `${r.ocupadas} de ${r.en_servicio} en servicio`],
    ['Llegadas pendientes', r.llegadas, 'hoy o atrasadas'],
    ['Salidas pendientes', r.salidas, 'hoy o atrasadas'],
    ['Libres y listas', r.libres_listas, 'para recibir huéspedes'],
    ['Por limpiar', r.por_limpiar, 'sucias o en limpieza'],
    ['Fuera de servicio', r.fuera_de_servicio, `de ${r.habitaciones} habitaciones`],
  ];
  $('#resumen-tablero').replaceChildren(...indicadores.map(([titulo, valor, detalle]) =>
    el('div', { clase: 'indicador' },
      el('dt', {}, titulo),
      el('dd', {}, el('strong', {}, String(valor)), el('small', {}, detalle)))));
}

/**
 * Leyenda con la cantidad de habitaciones en cada situación. Cada elemento es un botón que deja
 * resaltadas solo las habitaciones de esa situación; pulsarlo de nuevo quita el filtro.
 */
function mostrarLeyenda(habitaciones) {
  const cuenta = {};
  for (const h of habitaciones) cuenta[h.situacion] = (cuenta[h.situacion] || 0) + 1;
  $('#leyenda-tablero').replaceChildren(...Object.entries(SITUACIONES).map(([clave, nombre]) =>
    el('li', {},
      el('button', {
        type: 'button', clase: `sit-${clave}`, 'aria-pressed': String(filtroTablero === clave),
        onclick: () => filtrarTablero(clave),
      }, el('span', { clase: 'muestra', 'aria-hidden': 'true' }), `${nombre} (${cuenta[clave] || 0})`))));
}

/** Activa o quita el filtro de una situación sin volver a pedir datos a la API. */
function filtrarTablero(situacion) {
  filtroTablero = filtroTablero === situacion ? null : situacion;
  const pisos = $('#pisos-tablero');
  if (filtroTablero) pisos.dataset.filtro = filtroTablero;
  else delete pisos.dataset.filtro;
  for (const boton of document.querySelectorAll('#leyenda-tablero button')) {
    boton.setAttribute('aria-pressed', String(boton.classList.contains(`sit-${filtroTablero}`)));
  }
}

/** Agrupa las habitaciones por piso y dibuja una cuadrícula por cada uno. */
function mostrarPisos(habitaciones, hoy) {
  const pisos = new Map();
  for (const h of habitaciones) {
    if (!pisos.has(h.piso)) pisos.set(h.piso, []);
    pisos.get(h.piso).push(h);
  }
  $('#pisos-tablero').replaceChildren(...[...pisos.entries()].map(([piso, lista]) => {
    const tipos = [...new Set(lista.map((h) => h.tipo))].join(' y ');
    return el('section', { clase: 'piso', 'aria-label': `Piso ${piso}` },
      el('h3', {}, `Piso ${piso}`, el('small', {}, ` · ${tipos} · ${lista.length} habitaciones`)),
      el('div', { clase: 'cuadricula' }, ...lista.map((h) => tarjetaHabitacion(h, hoy))));
  }));
}

/** Botón con el código de una reserva que abre su gestión (gestion.js). */
function botonReserva(reserva) {
  return el('button', {
    type: 'button', clase: 'codigo-reserva', title: `Gestionar la reserva ${reserva.codigo}`,
    onclick: () => intentar(() => abrirGestion(reserva.codigo)),
  }, reserva.codigo);
}

/**
 * Tarjeta de una habitación: número, estado de limpieza, situación y la reserva que la ocupa o que
 * llega. El texto de la situación siempre está escrito, para no depender solo del color.
 */
function tarjetaHabitacion(h, hoy) {
  let titulo = SITUACIONES[h.situacion];
  if (h.situacion === 'sale_hoy' && h.ocupante.fecha_salida < hoy) titulo = 'Salida atrasada';
  const partes = [];
  if (h.ocupante) {
    const o = h.ocupante;
    partes.push(el('div', { clase: 'reserva' }, botonReserva(o),
      el('span', {}, `${o.nombre_huesped} · sale ${fechaDiaMes(o.fecha_salida)}`)));
  }
  if (h.llegada) {
    const l = h.llegada;
    const cuando = l.fecha_entrada < hoy ? `esperada el ${fechaDiaMes(l.fecha_entrada)}` : `${l.personas} pers.`;
    partes.push(el('div', { clase: 'reserva' },
      h.ocupante || h.fuera_de_servicio ? el('span', { clase: 'etiqueta-llega' }, 'Llega:') : null,
      botonReserva(l),
      el('span', {}, `${l.nombre_huesped} · ${cuando}`),
      l.estado === 'pendiente_pago' ? el('span', { clase: 'estado pendiente_pago' }, 'Sin pagar') : null));
  }
  if (h.llegada && h.llegada.garantia_vencida) {
    partes.push(el('span', { clase: 'alerta' }, 'Garantía vencida: el precio ya no se conserva'));
  }
  if (h.situacion === 'fuera_de_servicio' && h.llegada) {
    partes.push(el('span', { clase: 'alerta' }, 'Asigne otra habitación'));
  }
  return el('article', { clase: `hab sit-${h.situacion}`, 'data-situacion': h.situacion },
    el('header', {},
      el('strong', { clase: 'numero' }, h.numero),
      etiquetaEstado(h.estado_limpieza, LIMPIEZA)),
    el('p', { clase: 'situacion' }, titulo),
    ...partes);
}

// ---------------------------------------------------------------------
// Actualización automática
// ---------------------------------------------------------------------
/**
 * Recarga el tablero sin avisos emergentes: si falla, lo indica junto a la hora de la última
 * actualización. Se usa en la actualización automática, que no debe interrumpir al personal.
 */
async function actualizarTableroEnSilencio() {
  try {
    await cargarTablero();
  } catch {
    $('#actualizado-tablero').textContent =
      `No se pudo actualizar a las ${horaCorta(new Date())}; se reintentará en un minuto.`;
  }
}

document.addEventListener('DOMContentLoaded', () => {
  $('#btn-recargar-tablero').addEventListener('click', () => intentar(cargarTablero));
  // Cada minuto, solo si el tablero está a la vista
  setInterval(() => { if (tableroVisible()) actualizarTableroEnSilencio(); }, INTERVALO_TABLERO);
  // Al volver a la pestaña, se actualiza enseguida si los datos tienen más de un minuto
  document.addEventListener('visibilitychange', () => {
    if (tableroVisible() && Date.now() - ultimaCargaTablero > INTERVALO_TABLERO) actualizarTableroEnSilencio();
  });
});
