"""Disponibilidad y reservas (RF-03, RF-04, RF-05).

Rutas:
  GET  /api/disponibilidad              habitaciones libres y precio (pública).
  POST /api/reservas                    crea una reserva (cliente, recepción o gerencia).
  GET  /api/reservas                    lista de reservas (el cliente solo ve las suyas).
  GET  /api/reservas/{codigo}           una reserva.
  POST /api/reservas/{codigo}/cancelar  cancela y, si estaba pagada, reembolsa.

Estados de una reserva: pendiente_pago (reserva en línea sin pagar),
confirmada, en_curso, finalizada y cancelada. Una reserva de recepción nace
confirmada porque el huésped paga en el hotel.

Regla contra la sobreventa: la base de datos (restricción "sin_traslape")
impide dos reservas activas de la misma habitación con fechas traslapadas,
incluso si llegan al mismo tiempo a réplicas distintas de la API.
"""
import secrets
from datetime import date, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from psycopg import errors as pg_errores
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import config, correo, servicios_externos
from ..db import obtener_sesion
from ..dependencias import registrar, requiere_rol, usuario_actual
from ..esquemas import Disponible, NuevaReserva, ReservaSalida
from ..facturacion import impuesto_de
from ..modelos import Habitacion, Pago, Reserva, Tarifa, TipoHabitacion, Usuario

router = APIRouter(prefix="/api", tags=["reservas"])

# Temporada alta en Guanacaste: de diciembre a abril (época seca)
MESES_TEMPORADA_ALTA = {12, 1, 2, 3, 4}
MAX_NOCHES = 30
# Una estadía en curso o terminada ya no se puede cancelar
ESTADOS_CANCELABLES = ("pendiente_pago", "confirmada")
PUEDEN_RESERVAR = requiere_rol("cliente", "recepcionista", "gerente")


# ---------------------------------------------------------------------
# Funciones de apoyo
# ---------------------------------------------------------------------
def hoy() -> date:
    """Fecha de hoy en Costa Rica (el servidor puede estar en otra zona horaria, como UTC)."""
    return datetime.now(config.ZONA_HORARIA).date()


def validar_fechas(entrada: date, salida: date) -> None:
    """Rechaza con 422 fechas pasadas, salidas no posteriores a la entrada o estadías largas."""
    if entrada < hoy():
        raise HTTPException(422, "La fecha de entrada ya pasó")
    if salida <= entrada:
        raise HTTPException(422, "La salida debe ser posterior a la entrada")
    if (salida - entrada).days > MAX_NOCHES:
        raise HTTPException(422, f"Máximo {MAX_NOCHES} noches por reserva")


def temporada(dia: date) -> str:
    """Temporada ("alta" o "baja") que corresponde a una noche, según su mes."""
    return "alta" if dia.month in MESES_TEMPORADA_ALTA else "baja"


def calcular_total(sesion: Session, tipo_id: int, entrada: date, salida: date) -> Decimal:
    """Suma el precio de cada noche según la temporada en que cae.

    Ejemplo: del 29 de noviembre al 2 de diciembre son tres noches; la del 29
    y la del 30 de noviembre se cobran en temporada baja y la del 1 de
    diciembre en alta. Las noches van de la entrada hasta el día anterior a la
    salida: la noche del día de salida no se cobra.
    """
    precios = {t.temporada: t.precio_noche
               for t in sesion.scalars(select(Tarifa).where(Tarifa.tipo_id == tipo_id))}
    noches = (salida - entrada).days
    return sum((precios[temporada(entrada + timedelta(days=i))] for i in range(noches)), Decimal("0"))


def nuevo_codigo() -> str:
    """Código de reserva al azar, por ejemplo SOL-7KQ2MX.

    Seis caracteres de un alfabeto de 32 dan unos mil millones de
    combinaciones: difícil de adivinar y, con ``secrets``, impredecible. Si
    por azar se repitiera, la restricción UNIQUE de la base lo rechazaría.
    """
    alfabeto = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # sin 0/O ni 1/I para evitar confusiones
    return "SOL-" + "".join(secrets.choice(alfabeto) for _ in range(6))


def salida_reserva(r: Reserva) -> ReservaSalida:
    """Arma la respuesta de una reserva, con el IVA calculado sobre el total del hospedaje."""
    return ReservaSalida(
        codigo=r.codigo,
        habitacion=r.habitacion.numero,
        tipo=r.habitacion.tipo.nombre,
        nombre_huesped=r.nombre_huesped,
        correo_huesped=r.correo_huesped,
        personas=r.personas,
        fecha_entrada=r.fecha_entrada,
        fecha_salida=r.fecha_salida,
        canal=r.canal,
        estado=r.estado,
        total=r.total,
        impuesto=impuesto_de(r.total),
        total_con_impuesto=r.total + impuesto_de(r.total),
        tiene_factura=r.factura is not None,
        creada_en=r.creada_en,
    )


def buscar_reserva(sesion: Session, codigo: str, usuario: Usuario, bloquear: bool = False) -> Reserva:
    """Busca la reserva y verifica que el usuario pueda verla.

    Con bloquear=True la fila queda reservada para esta transacción: si llegan
    dos pagos o dos cancelaciones a la vez desde réplicas distintas, el
    segundo espera a que termine el primero y luego ve el estado ya cambiado.
    """
    # El personal de limpieza y mantenimiento no trabaja con reservas
    if usuario.rol not in ("cliente", "recepcionista", "gerente"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Su rol no tiene permiso para esta acción")
    if bloquear:
        sesion.execute(select(Reserva.id).where(Reserva.codigo == codigo.upper()).with_for_update())
    # populate_existing: lee de nuevo la fila de la base aunque la sesión ya la
    # tenga en memoria, para trabajar con el estado posterior al bloqueo.
    reserva = sesion.scalar(select(Reserva).where(Reserva.codigo == codigo.upper())
                            .execution_options(populate_existing=True))
    # Un cliente solo ve sus propias reservas; para él, las ajenas "no existen"
    if reserva is None or (usuario.rol == "cliente" and reserva.cliente_id != usuario.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Reserva no encontrada")
    return reserva


def habitaciones_libres(sesion: Session, entrada: date, salida: date, personas: int,
                        tipo_id: int | None = None,
                        excluir_reserva_id: int | None = None) -> list[Habitacion]:
    """Habitaciones en servicio, con capacidad suficiente y sin reservas activas en esas fechas.

    Dos estadías se traslapan si cada una empieza antes de que termine la
    otra: entrada_existente < salida_pedida y salida_existente > entrada_pedida.
    Así, una reserva que sale el día 10 no choca con otra que entra el 10.
    Las habitaciones ocupadas se excluyen con una subconsulta, y el resultado
    se ordena de la más pequeña a la más grande para ofrecer primero la que
    mejor se ajusta al grupo.

    ``excluir_reserva_id`` ignora una reserva al buscar choques: recepción la
    usa al mover o extender una reserva, que no debe chocar consigo misma.
    """
    ocupadas = select(Reserva.habitacion_id).where(
        Reserva.estado != "cancelada",
        Reserva.fecha_entrada < salida,
        Reserva.fecha_salida > entrada,
    )
    if excluir_reserva_id is not None:
        ocupadas = ocupadas.where(Reserva.id != excluir_reserva_id)
    consulta = (
        select(Habitacion)
        .join(TipoHabitacion, Habitacion.tipo_id == TipoHabitacion.id)
        .where(
            Habitacion.fuera_de_servicio.is_(False),
            TipoHabitacion.capacidad >= personas,
            Habitacion.id.not_in(ocupadas),
        )
        .order_by(TipoHabitacion.capacidad, Habitacion.numero)
    )
    if tipo_id is not None:
        consulta = consulta.where(Habitacion.tipo_id == tipo_id)
    return list(sesion.scalars(consulta))


def correo_confirmacion(tareas: BackgroundTasks, reserva: Reserva, extra: str = "") -> None:
    """Programa el correo de confirmación; ``extra`` agrega instrucciones (pago o factura)."""
    correo.programar(
        tareas, reserva.correo_huesped, f"Reserva confirmada {reserva.codigo}",
        f"Hola, {reserva.nombre_huesped}:\n\nSu reserva en el Hotel Soluna está confirmada.\n\n"
        f"{correo.detalle_reserva(reserva)}\n{extra}")


# ---------------------------------------------------------------------
# Disponibilidad (pública: el sitio web la muestra antes de iniciar sesión)
# ---------------------------------------------------------------------
@router.get("/disponibilidad", response_model=list[Disponible])
def disponibilidad(
    entrada: date = Query(description="Fecha de entrada (AAAA-MM-DD)"),
    salida: date = Query(description="Fecha de salida (AAAA-MM-DD)"),
    personas: int = Query(1, ge=1, le=10),
    sesion: Session = Depends(obtener_sesion),
):
    """RF-03: habitaciones libres para las fechas y personas indicadas, con el precio total.

    No exige sesión: el sitio la usa para que cualquier visitante consulte.
    """
    validar_fechas(entrada, salida)
    habitaciones = habitaciones_libres(sesion, entrada, salida, personas)

    # El precio depende solo del tipo de habitación: se calcula una vez por
    # tipo y se reutiliza para todas las habitaciones de ese tipo.
    totales: dict[int, Decimal] = {}
    resultado = []
    for h in habitaciones:
        if h.tipo_id not in totales:
            totales[h.tipo_id] = calcular_total(sesion, h.tipo_id, entrada, salida)
        resultado.append(Disponible(
            habitacion_id=h.id, numero=h.numero, tipo=h.tipo.nombre, capacidad=h.tipo.capacidad,
            noches=(salida - entrada).days, total=totales[h.tipo_id],
        ))
    return resultado


# ---------------------------------------------------------------------
# Reservas
# ---------------------------------------------------------------------
@router.post("/reservas", response_model=ReservaSalida, status_code=201)
def crear_reserva(
    datos: NuevaReserva,
    tareas: BackgroundTasks,
    sesion: Session = Depends(obtener_sesion),
    usuario: Usuario = Depends(PUEDEN_RESERVAR),
):
    """RF-04: crea una reserva.

    Algoritmo:
      1. Valida fechas, habitación y capacidad.
      2. Decide canal y estado según quién reserva: un cliente reserva para sí
         mismo y queda pendiente de pago; recepción o gerencia reservan a
         nombre de un huésped y la reserva nace confirmada.
      3. Calcula el total por temporada e inserta la reserva.
      4. Si la base rechaza el INSERT por traslape (otra solicitud ganó la
         habitación), responde 409 en lugar de un error genérico.
      5. Registra la bitácora, confirma la transacción y, si ya está
         confirmada, envía el correo.
    """
    validar_fechas(datos.fecha_entrada, datos.fecha_salida)
    habitacion = sesion.get(Habitacion, datos.habitacion_id)
    if habitacion is None or habitacion.fuera_de_servicio:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Habitación no disponible")
    if datos.personas > habitacion.tipo.capacidad:
        raise HTTPException(422,
                            f"La habitación admite como máximo {habitacion.tipo.capacidad} personas")

    if usuario.rol == "cliente":
        # Reserva en línea: queda pendiente hasta que la pasarela confirme el pago
        nombre, correo, canal, estado, cliente_id = usuario.nombre, usuario.correo, "web", "pendiente_pago", usuario.id
    else:
        if not datos.nombre_huesped or not datos.correo_huesped:
            raise HTTPException(422,
                                "Indique el nombre y el correo del huésped")
        nombre, correo, canal, estado, cliente_id = (
            datos.nombre_huesped, datos.correo_huesped.lower(), "recepcion", "confirmada", None)

    reserva = Reserva(
        codigo=nuevo_codigo(),
        habitacion_id=habitacion.id,
        cliente_id=cliente_id,
        nombre_huesped=nombre,
        correo_huesped=correo,
        personas=datos.personas,
        fecha_entrada=datos.fecha_entrada,
        fecha_salida=datos.fecha_salida,
        canal=canal,
        estado=estado,
        total=calcular_total(sesion, habitacion.tipo_id, datos.fecha_entrada, datos.fecha_salida),
        creada_por=usuario.id,
    )
    sesion.add(reserva)
    try:
        # flush envía el INSERT ahora, para conocer el resultado de las restricciones antes del commit
        sesion.flush()
    except IntegrityError as error:
        sesion.rollback()
        if isinstance(error.orig, pg_errores.ExclusionViolation):
            # La regla "sin_traslape" de la base detectó otra reserva en esas fechas
            raise HTTPException(status.HTTP_409_CONFLICT,
                                "La habitación ya no está disponible en esas fechas")
        raise
    registrar(sesion, usuario, "crear_reserva", "reserva", reserva.codigo,
              habitacion=habitacion.numero, entrada=str(datos.fecha_entrada),
              salida=str(datos.fecha_salida), canal=canal)
    sesion.commit()
    sesion.refresh(reserva)   # trae los valores que puso la base, como creada_en
    if reserva.estado == "confirmada":
        correo_confirmacion(tareas, reserva, "\nEl pago se realiza en la recepción del hotel.")
    return salida_reserva(reserva)


@router.get("/reservas", response_model=list[ReservaSalida])
def listar_reservas(
    desde: date | None = None,
    hasta: date | None = None,
    estado: str | None = None,
    sesion: Session = Depends(obtener_sesion),
    usuario: Usuario = Depends(PUEDEN_RESERVAR),
):
    """RF-05: reservas filtradas por fechas y estado, hasta 500.

    ``desde`` y ``hasta`` devuelven las estadías que tocan ese periodo (con la
    misma lógica de traslape de la disponibilidad). Un cliente solo recibe las suyas.
    """
    consulta = select(Reserva).order_by(Reserva.fecha_entrada, Reserva.codigo).limit(500)
    if usuario.rol == "cliente":
        consulta = consulta.where(Reserva.cliente_id == usuario.id)
    if desde:
        consulta = consulta.where(Reserva.fecha_salida > desde)
    if hasta:
        consulta = consulta.where(Reserva.fecha_entrada < hasta)
    if estado:
        consulta = consulta.where(Reserva.estado == estado)
    return [salida_reserva(r) for r in sesion.scalars(consulta)]


@router.get("/reservas/{codigo}", response_model=ReservaSalida)
def ver_reserva(codigo: str, sesion: Session = Depends(obtener_sesion),
                usuario: Usuario = Depends(usuario_actual)):
    """Una reserva por su código; un cliente solo puede ver las suyas."""
    return salida_reserva(buscar_reserva(sesion, codigo, usuario))


@router.post("/reservas/{codigo}/cancelar", response_model=ReservaSalida)
def cancelar_reserva(codigo: str, tareas: BackgroundTasks, sesion: Session = Depends(obtener_sesion),
                     usuario: Usuario = Depends(usuario_actual)):
    """Cancela una reserva pendiente o confirmada y, si estaba pagada, reembolsa.

    El orden importa: primero se reembolsa y después se cancela. Con la fila
    bloqueada, dos cancelaciones simultáneas no pueden reembolsar dos veces.
    Al cancelarse, la habitación vuelve a quedar libre en esas fechas, porque
    la regla contra la sobreventa ignora las reservas canceladas.
    """
    reserva = buscar_reserva(sesion, codigo, usuario, bloquear=True)
    if reserva.estado not in ESTADOS_CANCELABLES:
        raise HTTPException(status.HTTP_409_CONFLICT, f"No se puede cancelar una reserva {reserva.estado}")

    # Si se pagó en línea, primero se devuelve el dinero. Si la pasarela no
    # responde, la reserva NO se cancela: así nunca queda cancelada sin reembolso.
    cobro = sesion.scalar(select(Pago).where(Pago.reserva_id == reserva.id, Pago.tipo == "cobro",
                                             Pago.estado == "aprobado"))
    reembolso = None
    if cobro is not None:
        try:
            resultado = servicios_externos.reembolsar(cobro.transaccion)
        except (servicios_externos.ServicioNoDisponible, servicios_externos.SolicitudRechazada):
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                                "La pasarela de pago no responde y no se pudo hacer el reembolso. "
                                "La reserva sigue activa; intente de nuevo en unos minutos.")
        reembolso = Pago(reserva_id=reserva.id, tipo="reembolso", estado=resultado["estado"],
                         transaccion=resultado["transaccion"], monto=cobro.monto,
                         marca=cobro.marca, ultimos4=cobro.ultimos4)
        sesion.add(reembolso)
        registrar(sesion, usuario, "reembolso", "reserva", reserva.codigo,
                  transaccion=reembolso.transaccion, monto=str(cobro.monto))

    anterior = reserva.estado
    reserva.estado = "cancelada"
    reserva.actualizada_en = func.now()
    registrar(sesion, usuario, "cancelar_reserva", "reserva", reserva.codigo, estado_anterior=anterior)
    sesion.commit()
    sesion.refresh(reserva)

    aviso = (f"\nSe reembolsaron USD {reembolso.monto} a la tarjeta {reembolso.marca} terminada en "
             f"{reembolso.ultimos4}. Puede tardar unos días en reflejarse.\n") if reembolso else ""
    correo.programar(
        tareas, reserva.correo_huesped, f"Reserva cancelada {reserva.codigo}",
        f"Hola, {reserva.nombre_huesped}:\n\nSu reserva {reserva.codigo} del "
        f"{reserva.fecha_entrada:%d/%m/%Y} al {reserva.fecha_salida:%d/%m/%Y} fue cancelada.\n{aviso}")
    return salida_reserva(reserva)
