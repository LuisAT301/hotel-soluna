"""Reseñas verificadas de huéspedes.

Rutas:
  GET  /api/resenas   promedio, total y las reseñas más recientes (pública).
  POST /api/resenas   publica una reseña (requiere iniciar sesión).

Una reseña no es libre: para publicarla hay que cumplir las cuatro reglas.
  1. Tener una cuenta activa (sin sesión, 401).
  2. Indicar el código de una reservación propia: hecha con esa cuenta, o a
     nombre del mismo correo (por ejemplo, la registró recepción o llegó de
     una agencia y el huésped creó su cuenta después). Si no, 404.
  3. Que la estadía esté cumplida: la reservación no fue cancelada ni quedó
     sin pagar, y su fecha de salida ya llegó. Si no, 409.
  4. Que esa reservación no tenga ya una reseña (una por estadía). Si no, 409.
"""
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from psycopg import errors as pg_errores
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db import obtener_sesion
from ..dependencias import registrar, usuario_actual
from ..esquemas import NuevaResena, ResenaSalida, ResumenResenas
from ..modelos import Resena, Reserva, Usuario
from .reservas import hoy

router = APIRouter(prefix="/api/resenas", tags=["reseñas"])

# Estados de una reservación que llegó a hospedarse (pagada o confirmada)
ESTADOS_CUMPLIDOS = ("confirmada", "en_curso", "finalizada")
# Cuántas reseñas recientes muestra la página de inicio
MAX_PUBLICADAS = 12
_ESTADO_LEGIBLE = {"pendiente_pago": "pendiente de pago", "cancelada": "cancelada"}


def autor_visible(nombre: str) -> str:
    """Nombre y la inicial del apellido ("Ana Mora Solís" da "Ana S."): reconocible, pero discreto."""
    partes = nombre.split()
    return partes[0] if len(partes) == 1 else f"{partes[0]} {partes[-1][0].upper()}."


def salida_resena(r: Resena) -> ResenaSalida:
    """Convierte la reseña al formato público, sin datos personales del autor."""
    return ResenaSalida(
        autor=autor_visible(r.usuario.nombre),
        calificacion=r.calificacion,
        comentario=r.comentario,
        tipo_habitacion=r.reserva.habitacion.tipo.nombre,
        creada_en=r.creada_en,
    )


@router.get("", response_model=ResumenResenas)
def listar(sesion: Session = Depends(obtener_sesion)):
    """Promedio y total de todas las reseñas, y las más recientes primero.

    El promedio se redondea a un decimal (por ejemplo, 4,7 de 5).
    """
    promedio, total = sesion.execute(select(func.avg(Resena.calificacion), func.count(Resena.id))).one()
    recientes = sesion.scalars(select(Resena).order_by(Resena.creada_en.desc()).limit(MAX_PUBLICADAS)).all()
    return ResumenResenas(
        promedio=Decimal(promedio).quantize(Decimal("0.1")) if promedio is not None else None,
        total=total,
        resenas=[salida_resena(r) for r in recientes],
    )


@router.post("", response_model=ResenaSalida, status_code=status.HTTP_201_CREATED)
def publicar(datos: NuevaResena, sesion: Session = Depends(obtener_sesion),
             usuario: Usuario = Depends(usuario_actual)):
    """Publica la reseña si se cumplen las reglas del módulo, y la deja en la bitácora."""
    reserva = sesion.scalar(select(Reserva).where(Reserva.codigo == datos.codigo_reserva))
    # Regla 2. Misma respuesta para un código inexistente y uno ajeno: así no
    # se puede usar este formulario para averiguar qué códigos existen.
    propia = reserva is not None and (reserva.cliente_id == usuario.id
                                      or reserva.correo_huesped.lower() == usuario.correo)
    if not propia:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "No encontramos una reservación suya con ese código. "
                            "Revise el código que recibió por correo.")

    # Regla 3: la estadía debe haber ocurrido
    if reserva.estado not in ESTADOS_CUMPLIDOS:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"Solo se puede opinar sobre una estadía realizada; esta reservación está "
                            f"{_ESTADO_LEGIBLE.get(reserva.estado, reserva.estado)}.")
    if reserva.fecha_salida > hoy():
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"Podrá escribir su reseña a partir del {reserva.fecha_salida:%d/%m/%Y}, "
                            f"cuando termine su estadía.")

    resena = Resena(reserva_id=reserva.id, usuario_id=usuario.id,
                    calificacion=datos.calificacion, comentario=datos.comentario)
    sesion.add(resena)
    try:
        # Regla 4: la restricción UNIQUE de la base decide, aun con dos envíos simultáneos
        sesion.flush()
    except IntegrityError as error:
        sesion.rollback()
        if isinstance(error.orig, pg_errores.UniqueViolation):
            raise HTTPException(status.HTTP_409_CONFLICT, "Esa reservación ya tiene una reseña.")
        raise
    registrar(sesion, usuario, "publicar_resena", "reserva", reserva.codigo, calificacion=datos.calificacion)
    sesion.commit()
    sesion.refresh(resena)
    return salida_resena(resena)
