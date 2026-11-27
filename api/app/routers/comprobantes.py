"""Pagos por SINPE Móvil o transferencia con comprobante que recepción revisa (etapa 6).

Ninguna pasarela confirma un SINPE o una transferencia: la confirma una
persona que revisa la cuenta del hotel. Recorrido:
  1. El cliente paga por su cuenta a los datos del hotel y sube el
     comprobante: método, número, monto y, si quiere, una imagen o un PDF
     que el navegador comprime. La reserva sigue pendiente de pago.
  2. El cliente recibe un acuse por correo y el buzón de recepción, un aviso.
  3. Recepción revisa. Al aceptar, se registra el pago, se confirma la
     reserva y se emite la factura (correo de confirmación con la factura).
     Al rechazar, se anota el motivo (correo con el motivo) y el cliente
     puede enviar otro comprobante.
Cada paso queda en la bitácora y en el historial de la reserva.

Rutas:
  GET  /api/reservas/{codigo}/comprobantes      datos para pagar y comprobantes enviados (titular)
  POST /api/reservas/{codigo}/comprobantes      envía un comprobante (titular)
  GET  /api/gestion/comprobantes                bandeja: pendientes o revisados (recepción, gerencia)
  GET  /api/gestion/comprobantes/{id}/archivo   la imagen o el PDF (recepción, gerencia)
  POST /api/gestion/comprobantes/{id}/aceptar   registra el pago, confirma la reserva y la factura
  POST /api/gestion/comprobantes/{id}/rechazar  rechaza con un motivo
"""
import base64
import binascii
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased

from .. import config, correo, facturacion
from ..db import obtener_sesion
from ..dependencias import registrar, requiere_rol, usuario_actual
from ..esquemas import (ComprobanteEnBandeja, ComprobanteSalida, DatosPagoComprobante, NuevoComprobante,
                        RechazoComprobante)
from ..modelos import Comprobante, Habitacion, Pago, Reserva, Usuario
from .reservas import buscar_reserva, correo_confirmacion

router = APIRouter(tags=["comprobantes"])
RECEPCION = requiere_rol("recepcionista", "gerente")

MAX_ARCHIVO = 1_572_864   # 1,5 MB, igual que la restricción de la base
# Firma de los primeros bytes de cada tipo aceptado: el tipo se deduce del contenido, no de lo que diga el cliente
FIRMAS = ((b"\xff\xd8\xff", "image/jpeg"), (b"\x89PNG\r\n\x1a\n", "image/png"), (b"%PDF-", "application/pdf"))
EXTENSION = {"image/jpeg": "jpg", "image/png": "png", "application/pdf": "pdf"}
NOMBRE_METODO = {"sinpe": "SINPE Móvil", "transferencia": "Transferencia bancaria"}


def conflicto(mensaje: str) -> HTTPException:
    """Error 409 con un mensaje para la persona que hizo la acción."""
    return HTTPException(status.HTTP_409_CONFLICT, mensaje)


def total_con_iva(reserva: Reserva):
    """Lo que se paga por la reserva: el hospedaje más el IVA del 13 %."""
    return reserva.total + facturacion.impuesto_de(reserva.total)


def leer_archivo(contenido_base64: str) -> tuple[bytes, str]:
    """Decodifica el archivo y deduce su tipo por su firma.

    Rechaza (422) lo que no sea base64 válido, lo que pase de 1,5 MB y lo que
    no sea una imagen JPG o PNG ni un PDF, aunque el nombre o el navegador
    digan otra cosa.
    """
    try:
        datos = base64.b64decode(contenido_base64, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(422, "El archivo no llegó completo; vuelva a adjuntarlo")
    if len(datos) > MAX_ARCHIVO:
        raise HTTPException(422, "El archivo supera 1,5 MB; adjunte una imagen más liviana o un PDF más pequeño")
    for firma, tipo in FIRMAS:
        if datos.startswith(firma):
            return datos, tipo
    raise HTTPException(422, "Adjunte una imagen JPG o PNG, o un PDF")


def salida(c: Comprobante, tiene_archivo: bool, revisor: str | None = None) -> ComprobanteSalida:
    """Comprobante sin el archivo, como lo devuelve la API."""
    return ComprobanteSalida(id=c.id, metodo=c.metodo, numero=c.numero, monto=c.monto, tiene_archivo=tiene_archivo,
                             tipo_archivo=c.tipo_archivo, estado=c.estado, motivo=c.motivo, enviado_en=c.enviado_en,
                             revisado_en=c.revisado_en, revisado_por=revisor)


def comprobantes_de(sesion: Session, reserva: Reserva) -> list[ComprobanteSalida]:
    """Comprobantes de la reserva, del más reciente al más antiguo, sin cargar los archivos."""
    filas = sesion.execute(select(Comprobante, Comprobante.archivo.is_not(None))
                           .where(Comprobante.reserva_id == reserva.id).order_by(Comprobante.id.desc()))
    return [salida(c, tiene) for c, tiene in filas]


def datos_para_pagar(sesion: Session, reserva: Reserva) -> DatosPagoComprobante:
    """Monto y datos de la cuenta del hotel, con los comprobantes ya enviados."""
    return DatosPagoComprobante(codigo=reserva.codigo, monto=total_con_iva(reserva), sinpe=config.SINPE_HOTEL,
                                cuenta=config.CUENTA_HOTEL, titular=config.TITULAR_CUENTA_HOTEL,
                                comprobantes=comprobantes_de(sesion, reserva))


# ---------------------------------------------------------------------
# Cliente
# ---------------------------------------------------------------------
@router.get("/api/reservas/{codigo}/comprobantes", response_model=DatosPagoComprobante)
def ver_comprobantes(codigo: str, sesion: Session = Depends(obtener_sesion),
                     usuario: Usuario = Depends(usuario_actual)):
    """Lo que el cliente necesita para pagar por SINPE Móvil o transferencia, y lo que ya envió."""
    return datos_para_pagar(sesion, buscar_reserva(sesion, codigo, usuario))


@router.post("/api/reservas/{codigo}/comprobantes", response_model=DatosPagoComprobante,
             status_code=status.HTTP_201_CREATED)
def enviar_comprobante(codigo: str, datos: NuevoComprobante, tareas: BackgroundTasks,
                       sesion: Session = Depends(obtener_sesion), usuario: Usuario = Depends(usuario_actual)):
    """El titular sube el comprobante de su pago; la reserva queda en revisión.

    Algoritmo:
      1. Solo el cliente titular (el personal registra los pagos en la cuenta
         de la habitación). Bloquea la reserva para que dos envíos simultáneos
         no se crucen.
      2. Exige que la reserva siga pendiente de pago, que no tenga otro
         comprobante en revisión, que el monto sea el total con IVA y que el
         número no respalde ya otro pago.
      3. Valida el archivo por su contenido y guarda el comprobante.
      4. Avisa por correo al cliente (acuse) y al buzón de recepción.
    """
    if usuario.rol != "cliente":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "El personal registra los pagos en la cuenta de la "
                                                       "habitación; el comprobante lo envía el huésped")
    reserva = buscar_reserva(sesion, codigo, usuario, bloquear=True)
    if reserva.estado != "pendiente_pago":
        raise conflicto("La reserva no está pendiente de pago")
    if sesion.scalar(select(Comprobante.id).where(Comprobante.reserva_id == reserva.id,
                                                  Comprobante.estado == "pendiente")):
        raise conflicto("Ya envió un comprobante que recepción está revisando; espere la respuesta")
    esperado = total_con_iva(reserva)
    if datos.monto != esperado:
        raise HTTPException(422, f"El monto pagado debe ser USD {esperado}, el total de la reserva con IVA")
    if sesion.scalar(select(Comprobante.id).where(Comprobante.metodo == datos.metodo,
                                                  Comprobante.numero == datos.numero,
                                                  Comprobante.estado != "rechazado")):
        raise conflicto("Ese número de comprobante ya se registró para otro pago")
    archivo, tipo = leer_archivo(datos.archivo) if datos.archivo else (None, None)

    comprobante = Comprobante(reserva_id=reserva.id, metodo=datos.metodo, numero=datos.numero, monto=datos.monto,
                              archivo=archivo, tipo_archivo=tipo, estado="pendiente", enviado_por=usuario.id)
    sesion.add(comprobante)
    registrar(sesion, usuario, "comprobante_enviado", "reserva", reserva.codigo, metodo=datos.metodo,
              numero=datos.numero, monto=str(datos.monto), archivo=tipo)
    sesion.commit()

    metodo = NOMBRE_METODO[datos.metodo]
    correo.programar(
        tareas, reserva.correo_huesped, f"Recibimos su comprobante de pago ({reserva.codigo})",
        f"Hola, {reserva.nombre_huesped}:\n\nRecibimos el comprobante de su pago por {metodo}:\n\n"
        f"Reserva: {reserva.codigo}\nComprobante: {datos.numero}\nMonto: USD {datos.monto}\n\n"
        f"La recepción lo revisará y le escribiremos en cuanto la reserva quede confirmada. Mientras tanto, la "
        f"reserva sigue pendiente de pago. Si tiene dudas, llámenos al {config.TELEFONO_HOTEL}.\n")
    if config.CORREO_RECEPCION:
        correo.programar(
            tareas, config.CORREO_RECEPCION, f"Comprobante por revisar: {reserva.codigo}",
            f"{reserva.nombre_huesped} ({reserva.correo_huesped}) envió un comprobante de pago.\n\n"
            f"Reserva: {reserva.codigo}, habitación {reserva.habitacion.numero}, del "
            f"{reserva.fecha_entrada:%d/%m/%Y} al {reserva.fecha_salida:%d/%m/%Y}\n"
            f"Método: {metodo}\nComprobante: {datos.numero}\nMonto declarado: USD {datos.monto} "
            f"(total esperado: USD {esperado})\nArchivo adjunto: {'sí' if archivo else 'no'}\n\n"
            f"Revíselo en el panel del personal, sección Comprobantes de pago.\n")
    return datos_para_pagar(sesion, reserva)


# ---------------------------------------------------------------------
# Recepción
# ---------------------------------------------------------------------
@router.get("/api/gestion/comprobantes", response_model=list[ComprobanteEnBandeja])
def bandeja(vista: Literal["pendientes", "revisados"] = Query("pendientes"),
            sesion: Session = Depends(obtener_sesion), _: Usuario = Depends(RECEPCION)):
    """Comprobantes por revisar (del más antiguo al más reciente) o revisados en los últimos 7 días.

    Una sola consulta con la reserva, la habitación y quién lo revisó; los
    archivos no se cargan (solo se indica si hay uno).
    """
    revisor = aliased(Usuario)
    consulta = (select(Comprobante, Comprobante.archivo.is_not(None), Reserva, Habitacion.numero, revisor.nombre)
                .join(Reserva, Reserva.id == Comprobante.reserva_id)
                .join(Habitacion, Habitacion.id == Reserva.habitacion_id)
                .outerjoin(revisor, revisor.id == Comprobante.revisado_por))
    if vista == "pendientes":
        consulta = consulta.where(Comprobante.estado == "pendiente").order_by(Comprobante.enviado_en)
    else:
        consulta = (consulta.where(Comprobante.estado != "pendiente",
                                   Comprobante.revisado_en > func.now() - timedelta(days=7))
                    .order_by(Comprobante.revisado_en.desc()))
    return [ComprobanteEnBandeja(**salida(c, tiene, nombre).model_dump(), codigo=r.codigo,
                                 nombre_huesped=r.nombre_huesped, correo_huesped=r.correo_huesped, habitacion=numero,
                                 fecha_entrada=r.fecha_entrada, fecha_salida=r.fecha_salida, estado_reserva=r.estado,
                                 monto_esperado=total_con_iva(r))
            for c, tiene, r, numero, nombre in sesion.execute(consulta)]


@router.get("/api/gestion/comprobantes/{comprobante_id}/archivo")
def ver_archivo(comprobante_id: int, sesion: Session = Depends(obtener_sesion), _: Usuario = Depends(RECEPCION)):
    """La imagen o el PDF del comprobante, para verlo en el panel; nunca se guarda en caché."""
    fila = sesion.execute(select(Comprobante.archivo, Comprobante.tipo_archivo)
                          .where(Comprobante.id == comprobante_id)).one_or_none()
    if fila is None or fila.archivo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "El comprobante no tiene archivo")
    return Response(content=fila.archivo, media_type=fila.tipo_archivo, headers={
        "Content-Disposition": f'inline; filename="comprobante-{comprobante_id}.{EXTENSION[fila.tipo_archivo]}"',
        "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
    })


def comprobante_para_revisar(sesion: Session, comprobante_id: int) -> Comprobante:
    """Bloquea la reserva y el comprobante, y exige que siga pendiente (409 si ya se revisó).

    Primero la reserva y después el comprobante, el mismo orden que la
    cancelación y el envío: así dos operaciones simultáneas nunca se esperan
    mutuamente. Después del bloqueo se leen de nuevo, con el estado posterior.
    """
    reserva_id = sesion.scalar(select(Comprobante.reserva_id).where(Comprobante.id == comprobante_id))
    if reserva_id is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Comprobante no encontrado")
    sesion.execute(select(Reserva.id).where(Reserva.id == reserva_id).with_for_update())
    sesion.scalar(select(Reserva).where(Reserva.id == reserva_id).execution_options(populate_existing=True))
    comprobante = sesion.scalar(select(Comprobante).where(Comprobante.id == comprobante_id).with_for_update()
                                .execution_options(populate_existing=True))
    if comprobante.estado != "pendiente":
        raise conflicto(f"Este comprobante ya fue {comprobante.estado}")
    return comprobante


def en_bandeja(sesion: Session, comprobante: Comprobante, revisor: Usuario) -> ComprobanteEnBandeja:
    """El comprobante recién revisado, con los datos de su reserva."""
    r = comprobante.reserva
    tiene = sesion.scalar(select(Comprobante.archivo.is_not(None)).where(Comprobante.id == comprobante.id))
    return ComprobanteEnBandeja(**salida(comprobante, tiene, revisor.nombre).model_dump(), codigo=r.codigo,
                                nombre_huesped=r.nombre_huesped, correo_huesped=r.correo_huesped,
                                habitacion=r.habitacion.numero, fecha_entrada=r.fecha_entrada,
                                fecha_salida=r.fecha_salida, estado_reserva=r.estado, monto_esperado=total_con_iva(r))


@router.post("/api/gestion/comprobantes/{comprobante_id}/aceptar", response_model=ComprobanteEnBandeja)
def aceptar(comprobante_id: int, tareas: BackgroundTasks, sesion: Session = Depends(obtener_sesion),
            usuario: Usuario = Depends(RECEPCION)):
    """Acepta el comprobante: registra el pago, confirma la reserva y emite la factura, como un pago con tarjeta.

    En una sola transacción: el pago (con la transacción "comp_<id>", que
    indica que no pasó por la pasarela), la revisión, la confirmación, la
    factura y la bitácora. Después se envía la factura a Hacienda y el correo
    de confirmación. 409 si el comprobante ya se revisó o si la reserva ya no
    está pendiente de pago (por ejemplo, se canceló).
    """
    comprobante = comprobante_para_revisar(sesion, comprobante_id)
    reserva = comprobante.reserva
    if reserva.estado != "pendiente_pago":
        raise conflicto("La reserva ya no está pendiente de pago; rechace el comprobante con el motivo")
    monto = total_con_iva(reserva)
    metodo = NOMBRE_METODO[comprobante.metodo]
    sesion.add(Pago(reserva_id=reserva.id, tipo="cobro", estado="aprobado", transaccion=f"comp_{comprobante.id}",
                    monto=monto, marca=metodo))
    comprobante.estado = "aceptado"
    comprobante.revisado_por = usuario.id
    comprobante.revisado_en = func.now()
    reserva.estado = "confirmada"
    reserva.actualizada_en = func.now()
    factura = facturacion.crear(sesion, reserva)
    registrar(sesion, usuario, "comprobante_aceptado", "reserva", reserva.codigo, metodo=comprobante.metodo,
              numero=comprobante.numero, monto=str(monto), factura=factura.consecutivo)
    sesion.commit()

    # El pago ya quedó guardado; si Hacienda no responde, la factura queda pendiente y se reintenta después
    facturacion.enviar_a_hacienda(sesion, factura)
    sesion.refresh(reserva)
    sesion.refresh(comprobante)
    correo_confirmacion(
        tareas, reserva,
        f"\nPago recibido: USD {monto} por {metodo} (comprobante {comprobante.numero}), verificado por la "
        f"recepción.\nFactura electrónica {factura.consecutivo}\nClave: {factura.clave}\n"
        f"Subtotal USD {factura.subtotal} + IVA 13 % USD {factura.impuesto} = USD {factura.total}\n")
    return en_bandeja(sesion, comprobante, usuario)


@router.post("/api/gestion/comprobantes/{comprobante_id}/rechazar", response_model=ComprobanteEnBandeja)
def rechazar(comprobante_id: int, datos: RechazoComprobante, tareas: BackgroundTasks,
             sesion: Session = Depends(obtener_sesion), usuario: Usuario = Depends(RECEPCION)):
    """Rechaza el comprobante con un motivo; el cliente lo recibe por correo y puede enviar otro."""
    comprobante = comprobante_para_revisar(sesion, comprobante_id)
    reserva = comprobante.reserva
    comprobante.estado = "rechazado"
    comprobante.motivo = datos.motivo
    comprobante.revisado_por = usuario.id
    comprobante.revisado_en = func.now()
    registrar(sesion, usuario, "comprobante_rechazado", "reserva", reserva.codigo, metodo=comprobante.metodo,
              numero=comprobante.numero, motivo=datos.motivo)
    sesion.commit()
    sesion.refresh(comprobante)

    otra_vez = ("Puede enviar un nuevo comprobante desde Mis reservas, en el sitio del hotel. "
                if reserva.estado == "pendiente_pago" else "")
    correo.programar(
        tareas, reserva.correo_huesped, f"No pudimos confirmar su pago ({reserva.codigo})",
        f"Hola, {reserva.nombre_huesped}:\n\nRevisamos el comprobante {comprobante.numero} "
        f"({NOMBRE_METODO[comprobante.metodo]}) de su reserva {reserva.codigo} y no pudimos aceptarlo:\n\n"
        f"{datos.motivo}\n\n{otra_vez}Si tiene dudas, llámenos al {config.TELEFONO_HOTEL}.\n")
    return en_bandeja(sesion, comprobante, usuario)
