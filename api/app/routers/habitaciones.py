"""Habitaciones y estado de limpieza (RF-12 en lectura, RF-13)."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import obtener_sesion
from ..dependencias import PERSONAL, registrar, requiere_rol
from ..esquemas import CambioLimpieza, HabitacionSalida
from ..modelos import Habitacion, Usuario

router = APIRouter(prefix="/api/habitaciones", tags=["habitaciones"])


def _salida(h: Habitacion) -> HabitacionSalida:
    return HabitacionSalida(
        id=h.id,
        numero=h.numero,
        piso=h.piso,
        tipo=h.tipo.nombre,
        capacidad=h.tipo.capacidad,
        estado_limpieza=h.estado_limpieza,
        fuera_de_servicio=h.fuera_de_servicio,
    )


@router.get("", response_model=list[HabitacionSalida])
def listar(sesion: Session = Depends(obtener_sesion), _: Usuario = Depends(requiere_rol(*PERSONAL))):
    habitaciones = sesion.scalars(select(Habitacion).order_by(Habitacion.numero)).all()
    return [_salida(h) for h in habitaciones]


@router.patch("/{habitacion_id}/limpieza", response_model=HabitacionSalida)
def cambiar_limpieza(
    habitacion_id: int,
    cambio: CambioLimpieza,
    sesion: Session = Depends(obtener_sesion),
    usuario: Usuario = Depends(requiere_rol("limpieza", "recepcionista", "gerente")),
):
    habitacion = sesion.get(Habitacion, habitacion_id)
    if habitacion is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Habitación no encontrada")
    anterior = habitacion.estado_limpieza
    habitacion.estado_limpieza = cambio.estado
    registrar(sesion, usuario, "cambiar_limpieza", "habitacion", habitacion.numero,
              de=anterior, a=cambio.estado)
    sesion.commit()
    return _salida(habitacion)
