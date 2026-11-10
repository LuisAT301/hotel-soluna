"""Reservas que llegan desde una agencia de viajes en línea (OTA), RF-08.

La OTA no inicia sesión: cada aviso viaja firmado con HMAC-SHA256 y un
secreto que solo conocen la OTA y el hotel. La firma cubre la fecha y el
cuerpo completo, así que un aviso alterado o repetido horas después se rechaza.
"""
import hashlib
import hmac
import time

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request, Response, status
from psycopg import errors as pg_errores
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import config
from ..db import obtener_sesion
from ..dependencias import registrar
from ..esquemas import ReservaOTA, ReservaSalida
from ..modelos import Reserva, TipoHabitacion
from .reservas import (calcular_total, correo_confirmacion, habitaciones_libres, nuevo_codigo,
                       salida_reserva, validar_fechas)

router = APIRouter(prefix="/api/integraciones/ota", tags=["integraciones"])

_FIRMA_INVALIDA = HTTPException(status.HTTP_401_UNAUTHORIZED, "Firma del aviso no válida")


async def verificar_firma(
    request: Request,
    x_ota_fecha: str = Header(description="Segundos desde 1970 (hora UNIX) en que se firmó el aviso"),
    x_ota_firma: str = Header(description='"sha256=" + HMAC-SHA256 de "fecha.cuerpo"'),
) -> None:
    try:
        fecha = int(x_ota_fecha)
    except ValueError:
        raise _FIRMA_INVALIDA
    if abs(time.time() - fecha) > config.OTA_TOLERANCIA_SEGUNDOS:
        raise _FIRMA_INVALIDA
    cuerpo = await request.body()
    esperada = "sha256=" + hmac.new(config.OTA_SECRETO.encode(), f"{fecha}.".encode() + cuerpo,
                                    hashlib.sha256).hexdigest()
    # compare_digest tarda lo mismo acierte o no: no da pistas para adivinar la firma
    if not hmac.compare_digest(esperada, x_ota_firma):
        raise _FIRMA_INVALIDA


@router.post("/reservas", response_model=ReservaSalida, status_code=201,
             dependencies=[Depends(verificar_firma)])
def recibir_reserva(datos: ReservaOTA, respuesta: Response, tareas: BackgroundTasks,
                    sesion: Session = Depends(obtener_sesion)):
    """Asigna la primera habitación libre del tipo pedido y confirma la reserva.

    Si la OTA reenvía la misma referencia, se devuelve la reserva ya creada (200)
    en lugar de duplicarla.
    """
    existente = sesion.scalar(select(Reserva).where(Reserva.referencia_externa == datos.referencia))
    if existente is not None:
        respuesta.status_code = status.HTTP_200_OK
        return salida_reserva(existente)

    validar_fechas(datos.fecha_entrada, datos.fecha_salida)
    tipo = sesion.scalar(select(TipoHabitacion).where(TipoHabitacion.nombre == datos.tipo))
    if datos.personas > tipo.capacidad:
        raise HTTPException(422, f"El tipo {tipo.nombre} admite como máximo {tipo.capacidad} personas")
    total = calcular_total(sesion, tipo.id, datos.fecha_entrada, datos.fecha_salida)

    # Se prueba habitación por habitación. Si otra solicitud gana una al mismo
    # tiempo, la regla "sin_traslape" de la base la rechaza y se sigue con la próxima.
    reserva = None
    for habitacion in habitaciones_libres(sesion, datos.fecha_entrada, datos.fecha_salida,
                                          datos.personas, tipo.id):
        candidata = Reserva(
            codigo=nuevo_codigo(), habitacion_id=habitacion.id, cliente_id=None,
            nombre_huesped=datos.nombre_huesped, correo_huesped=datos.correo_huesped.lower(),
            personas=datos.personas, fecha_entrada=datos.fecha_entrada, fecha_salida=datos.fecha_salida,
            canal="ota", estado="confirmada", total=total, creada_por=None,
            referencia_externa=datos.referencia,
        )
        try:
            with sesion.begin_nested():   # punto de guardado: un fallo no deshace lo anterior
                sesion.add(candidata)
        except IntegrityError as error:
            if isinstance(error.orig, pg_errores.ExclusionViolation):
                continue
            if isinstance(error.orig, pg_errores.UniqueViolation):
                # La misma referencia llegó dos veces al mismo tiempo: gana la primera
                sesion.rollback()
                existente = sesion.scalar(select(Reserva).where(Reserva.referencia_externa == datos.referencia))
                if existente is not None:
                    respuesta.status_code = status.HTTP_200_OK
                    return salida_reserva(existente)
            raise
        reserva = candidata
        break

    if reserva is None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"No hay habitaciones {datos.tipo} libres en esas fechas")

    registrar(sesion, None, "reserva_ota", "reserva", reserva.codigo, referencia=datos.referencia,
              habitacion=reserva.habitacion_id, entrada=str(datos.fecha_entrada), salida=str(datos.fecha_salida))
    sesion.commit()
    sesion.refresh(reserva)
    correo_confirmacion(tareas, reserva, f"\nReservó a través de una agencia en línea "
                                         f"(referencia {datos.referencia}). El pago se gestiona con la agencia.")
    return salida_reserva(reserva)
