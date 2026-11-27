"""Solicitudes de huéspedes: chat entre el huésped alojado y el personal (etapa 3).

Rutas del personal (cada área ve lo suyo: limpieza solo lo de limpieza,
mantenimiento solo lo de mantenimiento; recepción y gerencia, todo):
  GET   /api/solicitudes                  bandeja; con ``desde``, solo lo que cambió.
  POST  /api/solicitudes/{id}/mensajes    responde al huésped.
  PATCH /api/solicitudes/{id}             la toma, la reasigna a otra área o cambia su estado.
  POST  /api/solicitudes/simular          un huésped simulado pide algo (recepción y gerencia).

Rutas del huésped (cuenta de cliente; la reserva debe ser suya, por la
cuenta o por el mismo correo, como en las reseñas):
  GET   /api/reservas/{codigo}/solicitudes    su conversación con el hotel.
  POST  /api/reservas/{codigo}/solicitudes    escribe; solo mientras está alojado.

Ciclo de una solicitud:

    abierta --el personal responde o la toma--> en_atencion --resolver--> resuelta
       ^                                                                     |
       +-----------------------------reabrir---------------------------------+

Si el huésped escribe con una solicitud abierta, el mensaje se suma a ella;
si no, abre una nueva. Al registrar la salida (check-out), las solicitudes
abiertas de esa reserva se resuelven solas.

Consumo de la base: las pantallas preguntan solo mientras están visibles y
piden únicamente lo nuevo (solicitudes cambiadas desde la última consulta y
mensajes posteriores al último que tienen). Cada consulta de la bandeja
cuesta como máximo cuatro sentencias SQL, sin importar cuántas solicitudes
o mensajes haya.
"""
import random
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from psycopg import errors as pg_errores
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, lazyload

from ..db import obtener_sesion
from ..dependencias import registrar, requiere_rol
from ..esquemas import (BandejaSolicitudes, CambioSolicitud, ChatHuesped, MensajeSalida, NuevoMensaje,
                        NuevoMensajeHuesped, SolicitudBreve, SolicitudSalida)
from ..modelos import Habitacion, Mensaje, Reserva, Solicitud, Usuario

router = APIRouter(tags=["solicitudes"])

PERSONAL_CHAT = requiere_rol("recepcionista", "gerente", "limpieza", "mantenimiento")
PUEDEN_SIMULAR = requiere_rol("recepcionista", "gerente")
HUESPED = requiere_rol("cliente")

# Área que ve cada rol del personal; los que no están aquí (recepción y gerencia) ven todas
AREA_DEL_ROL = {"limpieza": "limpieza", "mantenimiento": "mantenimiento"}
# Margen de la consulta incremental: cubre diferencias de reloj entre la API y la base,
# y transacciones que confirman unos instantes después de marcar su hora
SOLAPE = timedelta(seconds=10)
RESUELTAS_VISIBLES = timedelta(hours=24)     # la bandeja inicial muestra también las resueltas de hoy
MAX_BANDEJA = 100
MAX_MENSAJES = 200
MAX_POR_MINUTO = 5                           # mensajes de un huésped por minuto, contra el abuso
LARGO_VISTA_PREVIA = 140

# Pedidos del huésped simulado: área y texto, como los que llegan a un hotel de playa
PEDIDOS_SIMULADOS = [
    ("limpieza", "¿Podrían traernos dos toallas más, por favor?"),
    ("limpieza", "Se nos acabó el papel higiénico."),
    ("limpieza", "¿Pueden limpiar la habitación después de las 2 p. m.? Vamos a la playa en la mañana."),
    ("limpieza", "Necesitamos una almohada extra."),
    ("mantenimiento", "El aire acondicionado no enfría."),
    ("mantenimiento", "La ducha casi no tiene presión de agua."),
    ("mantenimiento", "El televisor no enciende."),
    ("mantenimiento", "La luz del baño parpadea."),
    ("recepcion", "¿A qué hora sirven el desayuno?"),
    ("recepcion", "¿Podríamos hacer la salida a las 2 p. m.?"),
    ("recepcion", "¿Nos recomiendan un tour para ver tortugas en Ostional?"),
    ("recepcion", "Quisiéramos un taxi para mañana a las 6 a. m. hacia el aeropuerto de Liberia."),
]


# ---------------------------------------------------------------------
# Funciones de apoyo
# ---------------------------------------------------------------------
def consulta_bandeja(area: str | None):
    """Consulta base de la bandeja: solicitud, reserva, habitación, quién la tomó y su último mensaje.

    Todo en una sola sentencia: el último mensaje sale de una subconsulta
    correlacionada que usa el índice (solicitud_id, id). ``area`` limita la
    consulta al área del rol (None: todas).
    """
    ultimo = (select(Mensaje.texto).where(Mensaje.solicitud_id == Solicitud.id)
              .order_by(Mensaje.id.desc()).limit(1).correlate(Solicitud).scalar_subquery())
    consulta = (select(Solicitud, Reserva.codigo, Reserva.nombre_huesped, Habitacion.numero,
                       Usuario.nombre.label("asignada_nombre"), ultimo.label("ultimo_mensaje"))
                .join(Reserva, Solicitud.reserva_id == Reserva.id)
                .join(Habitacion, Reserva.habitacion_id == Habitacion.id)
                .outerjoin(Usuario, Solicitud.asignada_a == Usuario.id))
    if area:
        consulta = consulta.where(Solicitud.categoria == area)
    return consulta


def salida_solicitud(fila) -> SolicitudSalida:
    """Convierte una fila de ``consulta_bandeja`` al formato de respuesta."""
    s = fila.Solicitud
    vista_previa = fila.ultimo_mensaje
    if vista_previa and len(vista_previa) > LARGO_VISTA_PREVIA:
        vista_previa = vista_previa[:LARGO_VISTA_PREVIA - 1] + "…"
    return SolicitudSalida(
        id=s.id, codigo_reserva=fila.codigo, habitacion=fila.numero, nombre_huesped=fila.nombre_huesped,
        categoria=s.categoria, estado=s.estado, asignada_a=fila.asignada_nombre, simulada=s.simulada,
        creada_en=s.creada_en, actualizada_en=s.actualizada_en, pendiente_desde=s.pendiente_desde,
        resuelta_en=s.resuelta_en, ultimo_mensaje=vista_previa)


def solicitud_visible(sesion: Session, solicitud_id: int, usuario: Usuario, bloquear: bool = False) -> Solicitud:
    """La solicitud, si el rol puede verla; si no, 404 (lo mismo que si no existiera).

    Con ``bloquear`` la fila queda reservada hasta el final de la
    transacción, para que dos personas no la cambien al mismo tiempo.
    """
    if bloquear:
        sesion.execute(select(Solicitud.id).where(Solicitud.id == solicitud_id).with_for_update())
    solicitud = sesion.get(Solicitud, solicitud_id, populate_existing=bloquear)
    area = AREA_DEL_ROL.get(usuario.rol)
    if solicitud is None or (area and solicitud.categoria != area):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Solicitud no encontrada")
    return solicitud


def mensajes(sesion: Session, condicion, despues: int, para_huesped: bool) -> list[MensajeSalida]:
    """Mensajes que cumplen ``condicion`` con id mayor que ``despues``, en orden.

    Al huésped no se le muestra el nombre de quien respondió: ve "Hotel
    Soluna". El personal sí ve quién respondió cada mensaje.
    """
    filas = sesion.execute(
        select(Mensaje, Usuario.nombre)
        .join(Solicitud, Mensaje.solicitud_id == Solicitud.id)
        .outerjoin(Usuario, Mensaje.usuario_id == Usuario.id)
        .where(condicion, Mensaje.id > despues)
        .order_by(Mensaje.id).limit(MAX_MENSAJES))
    return [MensajeSalida(id=m.id, solicitud_id=m.solicitud_id, autor=m.autor,
                          nombre=None if para_huesped or m.autor == "huesped" else nombre,
                          texto=m.texto, creado_en=m.creado_en)
            for m, nombre in filas]


def mensaje_del_huesped(sesion: Session, reserva_id: int, texto: str, categoria: str,
                        usuario_id: int | None, simulada: bool) -> tuple[Solicitud, Mensaje]:
    """Agrega un mensaje del huésped a su solicitud abierta, o abre una nueva.

    Bloquea la fila de la reserva: dos mensajes simultáneos del mismo huésped
    se atienden uno tras otro y no abren dos solicitudes. La base lo
    garantiza además con el índice único de una solicitud abierta por reserva.
    """
    sesion.execute(select(Reserva.id).where(Reserva.id == reserva_id).with_for_update())
    solicitud = sesion.scalar(select(Solicitud).where(Solicitud.reserva_id == reserva_id,
                                                      Solicitud.estado != "resuelta"))
    if solicitud is None:
        solicitud = Solicitud(reserva_id=reserva_id, categoria=categoria, simulada=simulada,
                              pendiente_desde=func.now())
        sesion.add(solicitud)
    elif solicitud.pendiente_desde is None:
        solicitud.pendiente_desde = func.now()   # el huésped vuelve a esperar respuesta
    solicitud.actualizada_en = func.now()
    sesion.flush()
    mensaje = Mensaje(solicitud_id=solicitud.id, autor="huesped", usuario_id=usuario_id, texto=texto)
    sesion.add(mensaje)
    sesion.flush()
    return solicitud, mensaje


def una_solicitud(sesion: Session, solicitud_id: int) -> SolicitudSalida:
    """Una solicitud con los datos de la bandeja, sin filtrar por área (después de cambiarla)."""
    return salida_solicitud(sesion.execute(consulta_bandeja(None).where(Solicitud.id == solicitud_id)).one())


# ---------------------------------------------------------------------
# Personal
# ---------------------------------------------------------------------
@router.get("/api/solicitudes", response_model=BandejaSolicitudes)
def bandeja(
    desde: datetime | None = Query(None, description="Valor de 'ahora' de la consulta anterior"),
    abierta: int | None = Query(None, description="Solicitud cuya conversación tiene abierta la pantalla"),
    despues: int = Query(0, ge=0, description="Último mensaje que ya tiene la pantalla"),
    sesion: Session = Depends(obtener_sesion),
    usuario: Usuario = Depends(PERSONAL_CHAT),
):
    """Bandeja del personal y, si se indica, los mensajes nuevos de la conversación abierta.

    Sin ``desde``: las solicitudes abiertas y en atención, más las resueltas
    en las últimas 24 horas. Con ``desde``: solo las que cambiaron desde
    entonces (con un margen de 10 s), que la pantalla combina con lo que ya
    tiene. Así, una consulta sin novedades devuelve una lista vacía.
    """
    ahora = datetime.now(timezone.utc)
    consulta = consulta_bandeja(AREA_DEL_ROL.get(usuario.rol))
    if desde is None:
        consulta = consulta.where(or_(Solicitud.estado != "resuelta",
                                      Solicitud.resuelta_en > func.now() - RESUELTAS_VISIBLES))
    else:
        consulta = consulta.where(Solicitud.actualizada_en > desde - SOLAPE)
    consulta = consulta.order_by(Solicitud.actualizada_en.desc()).limit(MAX_BANDEJA)
    solicitudes = [salida_solicitud(f) for f in sesion.execute(consulta)]

    nuevos = []
    if abierta is not None:
        solicitud_visible(sesion, abierta, usuario)
        nuevos = mensajes(sesion, Mensaje.solicitud_id == abierta, despues, para_huesped=False)
    return BandejaSolicitudes(ahora=ahora, solicitudes=solicitudes, mensajes=nuevos)


@router.post("/api/solicitudes/{solicitud_id}/mensajes", response_model=MensajeSalida,
             status_code=status.HTTP_201_CREATED)
def responder(solicitud_id: int, datos: NuevoMensaje, sesion: Session = Depends(obtener_sesion),
              usuario: Usuario = Depends(PERSONAL_CHAT)):
    """Responde al huésped: la solicitud pasa a "en atención", queda asignada a quien responde
    (si nadie la había tomado) y deja de estar pendiente de respuesta."""
    solicitud = solicitud_visible(sesion, solicitud_id, usuario, bloquear=True)
    if solicitud.estado == "resuelta":
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "La solicitud está resuelta. Reábrala para seguir conversando.")
    mensaje = Mensaje(solicitud_id=solicitud.id, autor="personal", usuario_id=usuario.id, texto=datos.texto)
    sesion.add(mensaje)
    if solicitud.estado == "abierta":
        solicitud.estado = "en_atencion"
    if solicitud.asignada_a is None:
        solicitud.asignada_a = usuario.id
    solicitud.pendiente_desde = None
    solicitud.actualizada_en = func.now()
    sesion.commit()
    sesion.refresh(mensaje)
    return MensajeSalida(id=mensaje.id, solicitud_id=solicitud.id, autor="personal", nombre=usuario.nombre,
                         texto=mensaje.texto, creado_en=mensaje.creado_en)


@router.patch("/api/solicitudes/{solicitud_id}", response_model=SolicitudSalida)
def cambiar(solicitud_id: int, datos: CambioSolicitud, sesion: Session = Depends(obtener_sesion),
            usuario: Usuario = Depends(PERSONAL_CHAT)):
    """Toma, reasigna o cambia el estado de una solicitud, y lo deja en la bitácora.

    - ``tomar``: queda asignada a quien la toma y pasa a "en atención".
    - ``categoria``: la pasa a otra área (por ejemplo, de recepción a mantenimiento).
    - ``estado``: "resuelta" la cierra; "abierta" o "en_atencion" la reabren,
      salvo que la reserva ya tenga otra abierta (409).
    """
    solicitud = solicitud_visible(sesion, solicitud_id, usuario, bloquear=True)
    cambios: dict = {}
    if datos.tomar:
        solicitud.asignada_a = usuario.id
        cambios["tomada_por"] = usuario.nombre
        if solicitud.estado == "abierta":
            solicitud.estado = "en_atencion"
    if datos.categoria and datos.categoria != solicitud.categoria:
        cambios["categoria"] = {"de": solicitud.categoria, "a": datos.categoria}
        solicitud.categoria = datos.categoria
    if datos.estado and datos.estado != solicitud.estado:
        cambios["estado"] = {"de": solicitud.estado, "a": datos.estado}
        if datos.estado == "resuelta":
            solicitud.resuelta_en = func.now()
            solicitud.pendiente_desde = None
        else:
            solicitud.resuelta_en = None
        solicitud.estado = datos.estado
    if not cambios:
        raise HTTPException(422, "No hay cambios que guardar.")
    solicitud.actualizada_en = func.now()
    try:
        sesion.flush()
    except IntegrityError as error:
        sesion.rollback()
        if isinstance(error.orig, pg_errores.UniqueViolation):
            raise HTTPException(status.HTTP_409_CONFLICT,
                                "Esta reserva ya tiene otra solicitud abierta; continúe en esa.")
        raise
    registrar(sesion, usuario, "actualizar_solicitud", "solicitud", solicitud.id, **cambios)
    sesion.commit()
    return una_solicitud(sesion, solicitud_id)


@router.post("/api/solicitudes/simular", response_model=SolicitudSalida, status_code=status.HTTP_201_CREATED)
def simular(sesion: Session = Depends(obtener_sesion), usuario: Usuario = Depends(PUEDEN_SIMULAR)):
    """Un huésped alojado, elegido al azar, envía un pedido típico (para demostraciones y pruebas).

    El mensaje entra como cualquier otro: se suma a la solicitud abierta de
    esa reserva o abre una nueva marcada como simulada.
    """
    elegida = sesion.execute(select(Reserva.id, Reserva.codigo).where(Reserva.estado == "en_curso")
                             .order_by(func.random()).limit(1)).first()
    if elegida is None:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "No hay huéspedes alojados. Registre un ingreso para simular una solicitud.")
    categoria, texto = random.choice(PEDIDOS_SIMULADOS)
    solicitud, _ = mensaje_del_huesped(sesion, elegida.id, texto, categoria, None, simulada=True)
    registrar(sesion, usuario, "simular_solicitud", "solicitud", solicitud.id, reserva=elegida.codigo)
    sesion.commit()
    return una_solicitud(sesion, solicitud.id)


# ---------------------------------------------------------------------
# Huésped
# ---------------------------------------------------------------------
def reserva_del_huesped(sesion: Session, codigo: str, usuario: Usuario) -> Reserva:
    """La reserva, si es del huésped: hecha con su cuenta o a nombre de su mismo correo.

    Un código inexistente y uno ajeno dan la misma respuesta, como en las
    reseñas, para no revelar qué códigos existen.
    """
    # lazyload: la factura de la reserva no hace falta aquí, así se ahorra una consulta
    reserva = sesion.scalar(select(Reserva).where(Reserva.codigo == codigo.strip().upper())
                            .options(lazyload(Reserva.factura)))
    propia = reserva is not None and (reserva.cliente_id == usuario.id
                                      or reserva.correo_huesped.lower() == usuario.correo)
    if not propia:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "No encontramos una reservación suya con ese código. "
                            "Revise el código que recibió por correo.")
    return reserva


@router.get("/api/reservas/{codigo}/solicitudes", response_model=ChatHuesped)
def chat_del_huesped(codigo: str, despues: int = Query(0, ge=0), sesion: Session = Depends(obtener_sesion),
                     usuario: Usuario = Depends(HUESPED)):
    """La conversación de la estadía (todas sus solicitudes, en orden) y si el huésped puede escribir."""
    reserva = reserva_del_huesped(sesion, codigo, usuario)
    abierta = sesion.scalar(select(Solicitud).where(Solicitud.reserva_id == reserva.id,
                                                    Solicitud.estado != "resuelta"))
    return ChatHuesped(
        codigo=reserva.codigo, habitacion=reserva.habitacion.numero,
        puede_escribir=reserva.estado == "en_curso",
        abierta=SolicitudBreve(id=abierta.id, categoria=abierta.categoria, estado=abierta.estado)
        if abierta else None,
        mensajes=mensajes(sesion, Solicitud.reserva_id == reserva.id, despues, para_huesped=True),
    )


@router.post("/api/reservas/{codigo}/solicitudes", response_model=MensajeSalida,
             status_code=status.HTTP_201_CREATED)
def escribir_al_hotel(codigo: str, datos: NuevoMensajeHuesped, sesion: Session = Depends(obtener_sesion),
                      usuario: Usuario = Depends(HUESPED)):
    """El huésped escribe al hotel. Solo mientras está alojado y hasta 5 mensajes por minuto."""
    reserva = reserva_del_huesped(sesion, codigo, usuario)
    if reserva.estado != "en_curso":
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Puede escribirnos durante su estadía: desde que registra su ingreso hasta su salida.")
    recientes = sesion.scalar(
        select(func.count(Mensaje.id)).join(Solicitud, Mensaje.solicitud_id == Solicitud.id)
        .where(Solicitud.reserva_id == reserva.id, Mensaje.autor == "huesped",
               Mensaje.creado_en > func.now() - timedelta(minutes=1)))
    if recientes >= MAX_POR_MINUTO:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                            "Ha enviado varios mensajes seguidos. Espere un minuto, por favor.")
    _, mensaje = mensaje_del_huesped(sesion, reserva.id, datos.texto, datos.categoria, usuario.id,
                                     simulada=False)
    sesion.commit()
    sesion.refresh(mensaje)
    return MensajeSalida(id=mensaje.id, solicitud_id=mensaje.solicitud_id, autor="huesped", nombre=None,
                         texto=mensaje.texto, creado_en=mensaje.creado_en)
