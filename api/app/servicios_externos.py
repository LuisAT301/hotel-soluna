"""Clientes de los servicios externos: pasarela de pago y Hacienda.

Las llamadas tienen tiempos de espera cortos: si un proveedor no responde,
la API devuelve un error claro en lugar de quedarse bloqueada, y la reserva
o la factura quedan en un estado desde el que se puede reintentar.
"""
from decimal import Decimal

import httpx

from . import config


class ServicioNoDisponible(Exception):
    """El proveedor no respondió o respondió con un error propio (5xx)."""


class SolicitudRechazada(Exception):
    """El proveedor rechazó los datos enviados (4xx); el mensaje es para el usuario."""


_cliente = httpx.Client(
    base_url=config.SIMULADOR_URL,
    timeout=httpx.Timeout(10, connect=2),
    headers={"Authorization": f"Bearer {config.SERVICIOS_LLAVE}"},
)


def _enviar(metodo: str, ruta: str, **opciones) -> dict:
    try:
        respuesta = _cliente.request(metodo, ruta, **opciones)
    except httpx.HTTPError as error:
        raise ServicioNoDisponible(str(error)) from error
    if respuesta.status_code >= 500:
        raise ServicioNoDisponible(f"{ruta}: {respuesta.status_code}")
    if respuesta.status_code >= 400:
        try:
            detalle = respuesta.json().get("detail")
        except ValueError:
            detalle = None
        raise SolicitudRechazada(detalle if isinstance(detalle, str) else "Datos de pago no válidos")
    return respuesta.json()


# ---------------------------------------------------------------------
# Pasarela de pago
# ---------------------------------------------------------------------
def cobrar(token: str, monto: Decimal, referencia: str, descripcion: str) -> dict:
    # El token es de un solo uso, así que sirve como llave de idempotencia:
    # si la API reintenta el mismo cobro, la pasarela no cobra dos veces.
    return _enviar(
        "POST", "/pasarela/cobros",
        json={"token": token, "monto": str(monto), "moneda": "USD",
              "referencia": referencia, "descripcion": descripcion},
        headers={"Idempotency-Key": token},
    )


def reembolsar(transaccion: str) -> dict:
    return _enviar("POST", f"/pasarela/cobros/{transaccion}/reembolso")


# ---------------------------------------------------------------------
# Hacienda
# ---------------------------------------------------------------------
def enviar_comprobante(comprobante: dict) -> dict:
    return _enviar("POST", "/hacienda/recepcion", json=comprobante)
