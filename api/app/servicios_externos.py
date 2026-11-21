"""Clientes de los servicios externos: pasarela de pago y Hacienda.

Las llamadas tienen tiempos de espera cortos: si un proveedor no responde,
la API devuelve un error claro en lugar de quedarse bloqueada, y la reserva
o la factura quedan en un estado desde el que se puede reintentar.

Los errores del proveedor se traducen a dos excepciones propias, para que
las rutas no dependan de los detalles de HTTP:
- ``ServicioNoDisponible``: falla técnica (sin respuesta o error 5xx); se informa como 502 o 503.
- ``SolicitudRechazada``: el proveedor rechazó los datos (4xx); su mensaje se muestra al usuario.
"""
from decimal import Decimal

import httpx

from . import config


class ServicioNoDisponible(Exception):
    """El proveedor no respondió o respondió con un error propio (5xx)."""


class SolicitudRechazada(Exception):
    """El proveedor rechazó los datos enviados (4xx); el mensaje es para el usuario."""


# Cliente HTTP compartido: reutiliza conexiones entre solicitudes y se
# identifica ante el proveedor con la llave de comercio (SERVICIOS_LLAVE).
# Espera 2 s para conectar y 10 s en total por respuesta.
_cliente = httpx.Client(
    base_url=config.SIMULADOR_URL,
    timeout=httpx.Timeout(10, connect=2),
    headers={"Authorization": f"Bearer {config.SERVICIOS_LLAVE}"},
)


def _enviar(metodo: str, ruta: str, **opciones) -> dict:
    """Hace la solicitud al proveedor y clasifica el resultado.

    Devuelve el JSON de una respuesta correcta (2xx). Convierte un error de
    red o un 5xx en ``ServicioNoDisponible``, y un 4xx en ``SolicitudRechazada``
    con el mensaje del proveedor (o uno genérico si no lo trae).
    """
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
    """Cobra ``monto`` (en USD) con el token de la tarjeta.

    ``referencia`` es el código de la reserva; la pasarela la asocia al cobro
    y rechaza que el mismo token se use para otra reserva.
    """
    # El token es de un solo uso, así que sirve como llave de idempotencia:
    # si la API reintenta el mismo cobro, la pasarela no cobra dos veces.
    return _enviar(
        "POST", "/pasarela/cobros",
        json={"token": token, "monto": str(monto), "moneda": "USD",
              "referencia": referencia, "descripcion": descripcion},
        headers={"Idempotency-Key": token},
    )


def reembolsar(transaccion: str) -> dict:
    """Pide a la pasarela devolver el cobro ``transaccion`` completo."""
    return _enviar("POST", f"/pasarela/cobros/{transaccion}/reembolso")


# ---------------------------------------------------------------------
# Hacienda
# ---------------------------------------------------------------------
def enviar_comprobante(comprobante: dict) -> dict:
    """Envía la factura electrónica y devuelve la respuesta (estado y mensaje)."""
    return _enviar("POST", "/hacienda/recepcion", json=comprobante)
