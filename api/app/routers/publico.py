"""Información pública del sitio web: catálogo de habitaciones y suscripción por correo."""
from fastapi import APIRouter, BackgroundTasks, Depends, status
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from .. import correo
from ..db import obtener_sesion
from ..dependencias import registrar, requiere_rol
from ..esquemas import NuevaSuscripcion, SuscriptorSalida, TipoHabitacionSalida
from ..modelos import Habitacion, Suscriptor, Tarifa, TipoHabitacion, Usuario

router = APIRouter(prefix="/api", tags=["sitio web"])


@router.get("/tipos-habitacion", response_model=list[TipoHabitacionSalida])
def tipos_habitacion(sesion: Session = Depends(obtener_sesion)):
    """Los tres tipos de habitación con su precio más bajo, para la página de inicio."""
    filas = sesion.execute(
        select(TipoHabitacion,
               select(func.min(Tarifa.precio_noche)).where(Tarifa.tipo_id == TipoHabitacion.id)
               .scalar_subquery(),
               select(func.count(Habitacion.id))
               .where(Habitacion.tipo_id == TipoHabitacion.id, Habitacion.fuera_de_servicio.is_(False))
               .scalar_subquery())
        .order_by(TipoHabitacion.capacidad)
    ).all()
    return [TipoHabitacionSalida(nombre=t.nombre, capacidad=t.capacidad, descripcion=t.descripcion,
                                 precio_desde=precio, habitaciones=cantidad)
            for t, precio, cantidad in filas]


@router.post("/suscripciones", status_code=status.HTTP_202_ACCEPTED)
def suscribirse(datos: NuevaSuscripcion, tareas: BackgroundTasks,
                sesion: Session = Depends(obtener_sesion)):
    """Guarda el correo para enviarle ofertas y novedades.

    La respuesta es la misma si el correo ya estaba suscrito: así nadie puede
    averiguar qué correos están en la lista.
    """
    nuevo = sesion.execute(
        insert(Suscriptor).values(correo=datos.correo, origen="sitio_web")
        .on_conflict_do_nothing(index_elements=["correo"])
        .returning(Suscriptor.id)
    ).scalar_one_or_none()
    if nuevo is not None:
        registrar(sesion, None, "suscripcion", "suscriptor", nuevo)
    sesion.commit()

    if nuevo is not None:
        tareas.add_task(
            correo.enviar, datos.correo, "Bienvenida a las novedades del Hotel Soluna",
            "Hola:\n\nGracias por suscribirse. Le escribiremos con ofertas de temporada, "
            "eventos en Playa Sámara y novedades del hotel.\n\n"
            "Si no pidió esta suscripción, puede ignorar este mensaje.")
    return {"mensaje": "Gracias. Le escribiremos con nuestras novedades."}


@router.get("/suscripciones", response_model=list[SuscriptorSalida])
def listar_suscripciones(sesion: Session = Depends(obtener_sesion),
                         _: Usuario = Depends(requiere_rol("gerente"))):
    """Lista para enviar campañas de correo. Solo gerencia."""
    return sesion.scalars(select(Suscriptor).order_by(Suscriptor.creado_en.desc())).all()
