"""Factura electrónica con el formato de Costa Rica, enviada al simulador de Hacienda.

  Consecutivo (20 dígitos): establecimiento (3) + terminal (5) + tipo de
      comprobante (2, "01" = factura electrónica) + número (10).
  Clave (50 dígitos): país "506" (3) + fecha DDMMAA (6) + cédula del emisor (12)
      + consecutivo (20) + situación "1" = normal (1) + código de seguridad (8).
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
    return (subtotal * config.IVA).quantize(CENTIMOS, rounding=ROUND_HALF_UP)


def consecutivo(numero: int) -> str:
    establecimiento, terminal, tipo = "001", "00001", "01"
    return f"{establecimiento}{terminal}{tipo}{numero:010d}"


def clave_numerica(fecha: datetime, consec: str) -> str:
    seguridad = f"{secrets.randbelow(10**8):08d}"
    return f"506{fecha:%d%m%y}{config.EMISOR_CEDULA:0>12}{consec}1{seguridad}"


def crear(sesion: Session, reserva: Reserva) -> Factura:
    """Registra la factura en la misma transacción que confirma el pago."""
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
        "subtotal": str(factura.subtotal),
        "impuesto": str(factura.impuesto),
        "total": str(factura.total),
    }
    try:
        respuesta = servicios_externos.enviar_comprobante(comprobante)
    except (servicios_externos.ServicioNoDisponible, servicios_externos.SolicitudRechazada):
        return
    factura.estado = respuesta["estado"]
    factura.mensaje = respuesta["mensaje"]
    factura.respondida_en = datetime.now(timezone.utc)
    sesion.commit()
