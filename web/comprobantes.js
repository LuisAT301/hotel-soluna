// =====================================================================
// Hotel Soluna: pagos por SINPE Móvil o transferencia con comprobante (etapa 6)
//   - Cliente: desde Mis reservas abre "SINPE o transferencia", ve el monto
//     y los datos del hotel, y envía el número del comprobante con una
//     imagen o un PDF opcional. Las imágenes se comprimen aquí, en el
//     navegador, antes de enviarse (JPEG de 1600 px como máximo).
//   - Recepción y gerencia: bandeja "Comprobantes de pago" para ver cada
//     comprobante con su archivo y aceptarlo o rechazarlo con un motivo.
// Usa las utilidades de app.js y de cuenta.js (usd, fechaHora); todo texto
// se inserta como texto, nunca como HTML.
// =====================================================================
'use strict';

const MAX_ARCHIVO = 1572864;          // 1,5 MB, igual que la API
const LADO_MAXIMO = 1600;             // píxeles del lado mayor de la imagen comprimida
const INTERVALO_COMPROBANTES = 60000; // la bandeja se actualiza cada minuto mientras está a la vista
const METODOS_COMPROBANTE = { sinpe: 'SINPE Móvil', transferencia: 'Transferencia bancaria' };
const ESTADOS_COMPROBANTE = { pendiente: 'En revisión', aceptado: 'Aceptado', rechazado: 'Rechazado' };

let reservaComprobante = null;   // reserva que se está pagando en el diálogo
let archivoPreparado = null;     // { base64, tipo, tamano } listo para enviar
let vistaComprobantes = 'pendientes';
let urlArchivoAbierto = null;    // URL temporal de la imagen o PDF que se está viendo

const kb = (bytes) => `${Math.max(1, Math.round(bytes / 1024)).toLocaleString('es-CR')} KB`;

// ---------------------------------------------------------------------
// Archivo: lectura y compresión en el navegador
// ---------------------------------------------------------------------
/** Lee un archivo o un blob y devuelve su contenido en base64, sin el prefijo "data:". */
function aBase64(blob) {
  return new Promise((resolver, rechazar) => {
    const lector = new FileReader();
    lector.onload = () => resolver(String(lector.result).split(',')[1]);
    lector.onerror = () => rechazar(new Error('No se pudo leer el archivo.'));
    lector.readAsDataURL(blob);
  });
}

/**
 * Prepara el archivo para enviarlo. Un PDF va tal cual si no pasa de 1,5 MB.
 * Una imagen se redibuja en un lienzo con su lado mayor de 1600 px como
 * máximo, sobre fondo blanco (un PNG transparente no queda negro), y se
 * guarda como JPEG; si aún pesa más de 1,5 MB, se baja la calidad.
 */
async function prepararArchivo(archivo) {
  if (archivo.type === 'application/pdf') {
    if (archivo.size > MAX_ARCHIVO) throw new Error('El PDF supera 1,5 MB. Adjunte una captura de pantalla.');
    return { base64: await aBase64(archivo), tipo: archivo.type, tamano: archivo.size };
  }
  if (!['image/jpeg', 'image/png'].includes(archivo.type)) {
    throw new Error('Adjunte una imagen JPG o PNG, o un PDF.');
  }
  const imagen = await createImageBitmap(archivo);
  const escala = Math.min(1, LADO_MAXIMO / Math.max(imagen.width, imagen.height));
  const lienzo = document.createElement('canvas');
  lienzo.width = Math.round(imagen.width * escala);
  lienzo.height = Math.round(imagen.height * escala);
  const contexto = lienzo.getContext('2d');
  contexto.fillStyle = '#ffffff';
  contexto.fillRect(0, 0, lienzo.width, lienzo.height);
  contexto.drawImage(imagen, 0, 0, lienzo.width, lienzo.height);
  imagen.close();
  let calidad = 0.8;
  let blob = await new Promise((resolver) => lienzo.toBlob(resolver, 'image/jpeg', calidad));
  while (blob.size > MAX_ARCHIVO && calidad > 0.35) {
    calidad -= 0.15;
    blob = await new Promise((resolver) => lienzo.toBlob(resolver, 'image/jpeg', calidad));
  }
  if (blob.size > MAX_ARCHIVO) throw new Error('La imagen sigue pesando más de 1,5 MB. Adjunte una captura más pequeña.');
  return { base64: await aBase64(blob), tipo: 'image/jpeg', tamano: blob.size };
}

// ---------------------------------------------------------------------
// Cliente: diálogo de pago con comprobante
// ---------------------------------------------------------------------
/** Botones y avisos de Mis reservas para una reserva pendiente de pago (los usa cargarReservas de app.js). */
function accionesDePago(r) {
  if (r.comprobante_estado === 'pendiente') {
    return [el('span', { clase: 'estado pendiente' }, 'Comprobante en revisión')];
  }
  const partes = [
    el('button', { clase: 'boton pequeno', type: 'button', onclick: () => abrirPago(r) }, 'Pagar con tarjeta'),
    el('button', { clase: 'boton claro pequeno', type: 'button', onclick: () => intentar(() => abrirComprobante(r)) },
      'SINPE o transferencia'),
  ];
  if (r.comprobante_estado === 'rechazado') {
    partes.push(el('small', { clase: 'nota-rechazo' }, `Comprobante rechazado: ${r.comprobante_motivo}`));
  }
  return partes;
}

/** Abre el diálogo con el monto, los datos de la cuenta del hotel y los comprobantes ya enviados. */
async function abrirComprobante(reserva) {
  const datos = await api(`/api/reservas/${encodeURIComponent(reserva.codigo)}/comprobantes`);
  reservaComprobante = reserva;
  archivoPreparado = null;
  const formulario = $('#form-comprobante');
  formulario.reset();
  formulario.monto.value = Number(datos.monto).toFixed(2);
  $('#error-comprobante').hidden = true;
  $('#comp-archivo-info').textContent = '';
  $('#comp-codigo').textContent = datos.codigo;
  $('#comp-monto').textContent = usd(datos.monto);
  $('#comp-sinpe').textContent = datos.sinpe;
  $('#comp-cuenta').textContent = datos.cuenta;
  $('#comp-titular').textContent = datos.titular;
  const anteriores = datos.comprobantes.filter((c) => c.estado === 'rechazado');
  $('#comp-anteriores').replaceChildren(...anteriores.map((c) => el('li', {},
    `${METODOS_COMPROBANTE[c.metodo]} ${c.numero} (${fechaHora(c.enviado_en)}): rechazado. ${c.motivo}`)));
  $('#comp-anteriores-titulo').hidden = !anteriores.length;
  $('#dlg-comprobante').showModal();
}

/** Comprime el archivo en cuanto se elige y muestra cuánto pesará. */
async function alElegirArchivo(entrada) {
  archivoPreparado = null;
  const info = $('#comp-archivo-info');
  const archivo = entrada.files[0];
  if (!archivo) {
    info.textContent = '';
    return;
  }
  info.textContent = 'Preparando el archivo…';
  try {
    archivoPreparado = await prepararArchivo(archivo);
    info.textContent = archivoPreparado.tipo === 'application/pdf'
      ? `PDF de ${kb(archivoPreparado.tamano)}.`
      : `Imagen lista para enviar: ${kb(archivoPreparado.tamano)} (el original pesa ${kb(archivo.size)}).`;
  } catch (error) {
    entrada.value = '';
    info.textContent = '';
    throw error;
  }
}

/** Envía el comprobante y actualiza Mis reservas. */
async function enviarComprobante(formulario) {
  const datos = Object.fromEntries(new FormData(formulario));
  if (formulario.archivo.files.length && !archivoPreparado) {
    throw new Error('Espere a que el archivo termine de prepararse.');
  }
  await api(`/api/reservas/${encodeURIComponent(reservaComprobante.codigo)}/comprobantes`, {
    metodo: 'POST',
    // El monto se acepta con coma decimal (192,10) y se envía con punto, como lo espera la API
    json: { metodo: datos.metodo, numero: datos.numero, monto: datos.monto.replace(',', '.'),
      archivo: archivoPreparado?.base64 || null },
  });
  $('#dlg-comprobante').close();
  avisar(`Comprobante enviado. La reserva ${reservaComprobante.codigo} queda en revisión; `
    + 'le escribiremos al correo en cuanto recepción la confirme.');
  await cargarReservas();
}

/** Muestra el error dentro del diálogo (no detrás de él) para que la persona lo vea. */
async function intentarEnComprobante(accion) {
  const error = $('#error-comprobante');
  error.hidden = true;
  try {
    await accion();
  } catch (e) {
    error.textContent = e.message;
    error.hidden = false;
  }
}

// ---------------------------------------------------------------------
// Recepción: bandeja de comprobantes
// ---------------------------------------------------------------------
function bandejaComprobantesVisible() {
  return Boolean(sesion.token) && !$('#sec-comprobantes').hidden && document.visibilityState === 'visible';
}

/** Lista los comprobantes por revisar (o los revisados en los últimos 7 días) con sus acciones. */
async function cargarComprobantes() {
  const lista = await api(`/api/gestion/comprobantes?vista=${vistaComprobantes}`);
  if (vistaComprobantes === 'pendientes') {
    const contador = $('#pendientes-comprobantes');
    contador.textContent = lista.length;
    contador.hidden = !lista.length;
  }
  const revisar = vistaComprobantes === 'pendientes';
  $('#lista-comprobantes').replaceChildren(tabla(
    ['Recibido', 'Reserva', 'Comprobante', 'Monto', 'Archivo', revisar ? '' : 'Revisión'],
    lista.map((c) => [
      fechaHora(c.enviado_en),
      el('span', {}, el('code', {}, c.codigo), el('br'),
        el('small', {}, `${c.nombre_huesped} · hab. ${c.habitacion} · ${fechaCorta(c.fecha_entrada)}`)),
      el('span', {}, METODOS_COMPROBANTE[c.metodo], el('br'), el('code', {}, c.numero)),
      el('span', { clase: Number(c.monto) === Number(c.monto_esperado) ? '' : 'alerta' },
        usd(c.monto), el('br'), el('small', {}, `esperado ${usd(c.monto_esperado)}`)),
      archivoDe(c),
      revisar ? accionesRevision(c) : revisionHecha(c),
    ]),
    revisar ? 'No hay comprobantes por revisar.' : 'No se revisaron comprobantes en los últimos 7 días.'));
}

/** Botón para ver el archivo, o por qué no hay. */
function archivoDe(c) {
  if (c.tiene_archivo) {
    return el('button', { clase: 'boton claro pequeno', type: 'button', onclick: () => intentar(() => verArchivo(c)) },
      c.tipo_archivo === 'application/pdf' ? 'Ver PDF' : 'Ver imagen');
  }
  return el('small', {}, c.tipo_archivo ? 'Borrado por retención' : 'Sin archivo');
}

function accionesRevision(c) {
  return el('div', { clase: 'botones-fila' },
    el('button', { clase: 'boton pequeno', type: 'button', onclick: () => intentar(() => aceptarComprobante(c)) }, 'Aceptar'),
    el('button', { clase: 'boton peligro pequeno', type: 'button', onclick: () => intentar(() => rechazarComprobante(c)) },
      'Rechazar'));
}

function revisionHecha(c) {
  return el('span', {},
    etiquetaEstado(c.estado, ESTADOS_COMPROBANTE),
    el('br'), el('small', {}, `${c.revisado_por || ''} · ${fechaHora(c.revisado_en)}`),
    c.motivo ? el('small', { clase: 'nota-rechazo' }, c.motivo) : '');
}

/** Pide el archivo con la sesión (una etiqueta img no puede enviar la cabecera) y lo muestra en un diálogo. */
async function verArchivo(c) {
  const respuesta = await fetch(`/api/gestion/comprobantes/${c.id}/archivo`,
    { headers: { Authorization: `Bearer ${sesion.token}` } });
  if (!respuesta.ok) throw new Error(respuesta.status === 404 ? 'El comprobante ya no tiene archivo.' : 'No se pudo abrir el archivo.');
  cerrarArchivo();
  urlArchivoAbierto = URL.createObjectURL(await respuesta.blob());
  const vista = c.tipo_archivo === 'application/pdf'
    ? el('iframe', { src: urlArchivoAbierto, title: `Comprobante ${c.numero}` })
    : el('img', { src: urlArchivoAbierto, alt: `Comprobante ${c.numero} de la reserva ${c.codigo}` });
  $('#archivo-titulo').textContent = `${METODOS_COMPROBANTE[c.metodo]} ${c.numero} · ${c.codigo} · ${usd(c.monto)}`;
  $('#archivo-vista').replaceChildren(vista);
  $('#archivo-abrir').href = urlArchivoAbierto;
  $('#dlg-archivo').showModal();
}

/** Libera la URL temporal del archivo que se estaba viendo. */
function cerrarArchivo() {
  if (urlArchivoAbierto) URL.revokeObjectURL(urlArchivoAbierto);
  urlArchivoAbierto = null;
  $('#archivo-vista').replaceChildren();
}

async function aceptarComprobante(c) {
  if (!window.confirm(`¿Aceptar el comprobante ${c.numero} por ${usd(c.monto)}? Se registrará el pago, se confirmará `
    + `la reserva ${c.codigo} y se emitirá la factura; el huésped recibirá la confirmación por correo.`)) return;
  await api(`/api/gestion/comprobantes/${c.id}/aceptar`, { metodo: 'POST' });
  avisar(`Comprobante aceptado: reserva ${c.codigo} confirmada y facturada.`);
  await Promise.all([cargarComprobantes(), refrescarPanel()]);
}

async function rechazarComprobante(c) {
  const motivo = window.prompt(`Motivo del rechazo del comprobante ${c.numero} (se le enviará al huésped):`);
  if (motivo === null) return;
  await api(`/api/gestion/comprobantes/${c.id}/rechazar`, { metodo: 'POST', json: { motivo } });
  avisar(`Comprobante ${c.numero} rechazado; el huésped recibió el motivo por correo.`);
  await cargarComprobantes();
}

// ---------------------------------------------------------------------
// Eventos
// ---------------------------------------------------------------------
document.addEventListener('DOMContentLoaded', () => {
  $('#form-comprobante').archivo.addEventListener('change', (e) => intentarEnComprobante(() => alElegirArchivo(e.target)));
  $('#form-comprobante').addEventListener('submit', (e) => {
    e.preventDefault();
    intentarEnComprobante(() => enviarComprobante(e.target));
  });
  $('#dlg-archivo').addEventListener('close', cerrarArchivo);
  $('#btn-recargar-comprobantes').addEventListener('click', () => intentar(cargarComprobantes));
  for (const boton of document.querySelectorAll('[data-vista-comprobantes]')) {
    boton.addEventListener('click', () => {
      vistaComprobantes = boton.dataset.vistaComprobantes;
      for (const otro of document.querySelectorAll('[data-vista-comprobantes]')) {
        otro.setAttribute('aria-pressed', String(otro === boton));
      }
      intentar(cargarComprobantes);
    });
  }
  // Mientras la bandeja está a la vista se actualiza sola, sin avisar errores pasajeros
  setInterval(() => { if (bandejaComprobantesVisible()) cargarComprobantes().catch(() => {}); }, INTERVALO_COMPROBANTES);
});
