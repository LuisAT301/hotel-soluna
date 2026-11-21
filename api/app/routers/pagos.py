"""Pago en línea de una reserva y su factura electrónica (RF-06, RF-07).

Recorrido de un pago:
  1. El navegador envía la tarjeta a la pasarela (/pasarela/tokens) y recibe un token.
  2. El navegador envía solo el token a la API (POST /api/reservas/{codigo}/pago).
  3. La API cobra con el token, confirma la reserva y crea la factura en una
     sola transacción.
  4. Después envía la factura a Hacienda y el correo de confirmación.

Rutas:
  POST /api/reservas/{codigo}/pago      cobra con el token y confirma la reserva.
  GET  /api/reservas/{codigo}/factura   la factura de la reserva (reintenta Hacienda si está pendiente).
"""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import facturacion, servicios_externos
from ..db import obtener_sesion
from ..dependencias import registrar, usuario_actual
from ..esquemas import FacturaSalida, PagoSalida, SolicitudPago
from ..modelos import Pago, Usuario
from .reservas import buscar_reserva, correo_confirmacion, salida_reserva

router = APIRouter(prefix="/api/reservas", tags=["pagos"])


@router.post("/{codigo}/pago", response_model=PagoSalida)
def pagar(
    codigo: str,
    datos: SolicitudPago,
    tareas: BackgroundTasks,
    sesion: Session = Depends(obtener_sesion),
    usuario: Usuario = Depends(usuario_actual),
):
    """RF-06: cobra la reserva con el token de la tarjeta y emite la factura (RF-07).

    Resultados posibles:
      200  cobro aprobado: reserva confirmada, factura creada y correo enviado.
      402  la tarjeta fue rechazada: el intento queda registrado y la reserva sigue pendiente.
      409  la reserva no está pendiente de pago (por ejemplo, ya se pagó).
      422  la pasarela rechazó el token o la respuesta no corresponde a la reserva.
      503  la pasarela no responde: no se cobró nada y se puede reintentar.
    La fila de la reserva queda bloqueada durante el pago, así que dos pagos
    simultáneos de la misma reserva no pueden cobrarse dos veces.
    """
    reserva = buscar_reserva(sesion, codigo, usuario, bloquear=True)
    if reserva.estado != "pendiente_pago":
        raise HTTPException(status.HTTP_409_CONFLICT, "La reserva no está pendiente de pago")

    # Se cobra el hospedaje más el IVA del 13 %
    monto = reserva.total + facturacion.impuesto_de(reserva.total)
    try:
        resultado = servicios_externos.cobrar(
            datos.token, monto, referencia=reserva.codigo,
            descripcion=f"Hotel Soluna, reserva {reserva.codigo}")
    except servicios_externos.SolicitudRechazada as error:
        raise HTTPException(422, str(error))
    except servicios_externos.ServicioNoDisponible:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "La pasarela de pago no responde. La reserva sigue pendiente; "
                            "intente de nuevo en unos minutos.")

    # Defensa adicional: la pasarela debe confirmar que cobró para esta reserva
    # y no reutilizó un cobro anterior de otra (por ejemplo, con el mismo token).
    if resultado.get("referencia") != reserva.codigo:
        raise HTTPException(422, "La respuesta de la pasarela no corresponde a esta reserva")

    pago = Pago(reserva_id=reserva.id, tipo="cobro", estado=resultado["estado"],
                transaccion=resultado["transaccion"], monto=monto, marca=resultado.get("marca"),
                ultimos4=resultado.get("ultimos4"), motivo=resultado.get("motivo"))
    sesion.add(pago)

    if pago.estado != "aprobado":
        # El rechazo también se guarda: queda constancia de cada intento de cobro
        registrar(sesion, usuario, "pago_rechazado", "reserva", reserva.codigo,
                  transaccion=pago.transaccion, motivo=pago.motivo)
        sesion.commit()
        raise HTTPException(status.HTTP_402_PAYMENT_REQUIRED,
                            f"La tarjeta fue rechazada ({pago.motivo}). Puede intentar con otra.")

    # Pago aprobado: confirmar la reserva, crear la factura y registrar la
    # bitácora en una sola transacción, para que no quede ninguna a medias.
    reserva.estado = "confirmada"
    reserva.actualizada_en = func.now()
    factura = facturacion.crear(sesion, reserva)
    registrar(sesion, usuario, "pago_aprobado", "reserva", reserva.codigo,
              transaccion=pago.transaccion, monto=str(monto), factura=factura.consecutivo)
    sesion.commit()

    # El pago ya quedó guardado; si Hacienda no responde, la factura queda pendiente
    facturacion.enviar_a_hacienda(sesion, factura)
    sesion.refresh(reserva)
    correo_confirmacion(
        tareas, reserva,
        f"\nPago recibido: USD {monto} con {pago.marca} terminada en {pago.ultimos4}.\n"
        f"Factura electrónica {factura.consecutivo}\nClave: {factura.clave}\n"
        f"Subtotal USD {factura.subtotal} + IVA 13 % USD {factura.impuesto} = USD {factura.total}\n")
    return PagoSalida(reserva=salida_reserva(reserva), transaccion=pago.transaccion, marca=pago.marca,
                      ultimos4=pago.ultimos4, monto=monto, factura=FacturaSalida.model_validate(factura))


@router.get("/{codigo}/factura", response_model=FacturaSalida)
def ver_factura(codigo: str, sesion: Session = Depends(obtener_sesion),
                usuario: Usuario = Depends(usuario_actual)):
    """RF-07: la factura de una reserva pagada. Si sigue pendiente ante Hacienda, se reenvía antes de responder."""
    reserva = buscar_reserva(sesion, codigo, usuario)
    if reserva.factura is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "La reserva no tiene factura")
    if reserva.factura.estado == "pendiente":
        facturacion.enviar_a_hacienda(sesion, reserva.factura)   # reintento
    return reserva.factura
