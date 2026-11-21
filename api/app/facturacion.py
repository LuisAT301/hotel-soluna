"""Factura electrónica con el formato de Costa Rica, enviada al simulador de Hacienda.

  Consecutivo (20 dígitos): establecimiento (3) + terminal (5) + tipo de
      comprobante (2, "01" = factura electrónica) + número (10).
  Clave (50 dígitos): país "506" (3) + fecha DDMMAA (6) + cédula del emisor (12)
      + consecutivo (20) + situación "1" = normal (1) + código de seguridad (8).

Flujo: ``crear`` registra la factura en la base dentro de la transacción del
pago; después ``enviar_a_hacienda`` la manda al simulador y guarda la
respuesta. Si Hacienda no contesta, la factura queda pendiente y el pago no
se pierde.
"""
import secrets
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session

from . import config, servicios_externos
from .modelos import Factura, Reserva

CENTIMOS = Decimal("0.01")


def impuesto_de(subtotal: Decimal) -> Decimal:
    """IVA del subtotal, redondeado a céntimos con redondeo comercial (0,005 sube).

    Se usa Decimal y no float: los montos de dinero deben ser exactos.
    """
    return (subtotal * config.IVA).quantize(CENTIMOS, rounding=ROUND_HALF_UP)


def consecutivo(numero: int) -> str:
    """Arma el consecutivo de 20 dígitos a partir del número correlativo.

    Ejemplo: el número 7 produce "00100001010000000007" (establecimiento 001,
    terminal 00001, tipo 01 y el número con ceros a la izquierda).
    """
    establecimiento, terminal, tipo = "001", "00001", "01"
    return f"{establecimiento}{terminal}{tipo}{numero:010d}"


def clave_numerica(fecha: datetime, consec: str) -> str:
    """Arma la clave numérica de 50 dígitos que identifica la factura ante Hacienda.

    Los últimos 8 dígitos son un código de seguridad al azar, generado con
    ``secrets`` (apto para criptografía), para que la clave no sea predecible.
    """
    seguridad = f"{secrets.randbelow(10**8):08d}"
    return f"506{fecha:%d%m%y}{config.EMISOR_CEDULA:0>12}{consec}1{seguridad}"


def crear(sesion: Session, reserva: Reserva) -> Factura:
    """Registra la factura en la misma transacción que confirma el pago.

    El número sale de la secuencia ``consecutivo_factura`` de PostgreSQL, que
    nunca entrega el mismo valor dos veces, aunque varias réplicas facturen
    al mismo tiempo. ``flush`` envía el INSERT sin confirmar la transacción,
    para obtener el id de la factura antes del commit.
    """
    numero = sesion.execute(text("SELECT nextval('consecutivo_factura')")).scalar_one()
    consec = consecutivo(numero)
    subtotal = reserva.total
    impuesto = impuesto_de(subtotal)
    factura = Factura(
        reserva_id=reserva.id,
        clave=clave_numerica(datetime.now(config.ZONA_HORARIA), consec),
        consecutivo=consec,
        subtotal=subtotal,
        impuesto=impuesto,
        total=subtotal + impuesto,
    )
    sesion.add(factura)
    sesion.flush()
    return factura


def enviar_a_hacienda(sesion: Session, factura: Factura) -> None:
    """Envía la factura y guarda la respuesta. Si Hacienda no responde, queda
    "pendiente" y se reintenta la próxima vez que alguien la consulte."""
    reserva = factura.reserva
    noches = (reserva.fecha_salida - reserva.fecha_entrada).days
    # Una sola línea por la estadía completa: la tarifa por noche puede
    # cambiar de temporada a mitad de la reserva.
    comprobante = {
        "clave": factura.clave,
        "consecutivo": factura.consecutivo,
        "fecha_emision": factura.emitida_en.isoformat(),
        "emisor": {"nombre": config.EMISOR_NOMBRE, "identificacion": config.EMISOR_CEDULA},
        "receptor": {"nombre": reserva.nombre_huesped, "correo": reserva.correo_huesped},
        "lineas": [{
            "detalle": (f"Hospedaje en habitación {reserva.habitacion.tipo.nombre}, {noches} "
                        f"{'noche' if noches == 1 else 'noches'}, del {reserva.fecha_entrada:%d/%m/%Y} "
                        f"al {reserva.fecha_salida:%d/%m/%Y} (reserva {reserva.codigo})"),
            "cantidad": 1,
            "precio_unitario": str(factura.subtotal),
            "subtotal": str(factura.subtotal),
        }],
        # Los montos viajan como texto para no perder precisión decimal en JSON
        "subtotal": str(factura.subtotal),
        "impuesto": str(factura.impuesto),
        "total": str(factura.total),
    }
    try:
        respuesta = servicios_externos.enviar_comprobante(comprobante)
    except (servicios_externos.ServicioNoDisponible, servicios_externos.SolicitudRechazada):
        # La factura ya está guardada como "pendiente": no se interrumpe el pago
        return
    factura.estado = respuesta["estado"]
    factura.mensaje = respuesta["mensaje"]
    factura.respondida_en = datetime.now(timezone.utc)
    sesion.commit()
