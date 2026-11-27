"""Gestión de reservas en recepción: tablero, búsqueda, ingreso, salida y cambios.

Son las etapas 1 y 2 del panel del personal. Todas las rutas son para
recepción y gerencia:

  GET   /api/gestion/tablero                         situación de cada habitación hoy (etapa 2).
  POST  /api/gestion/liberar-no-presentados         libera ya las reservas sin ingreso pasada la garantía.
  GET   /api/gestion/reservas                        busca por código, huésped, correo o habitación.
  GET   /api/gestion/reservas/{codigo}               detalle con habitación, acciones posibles e historial.
  GET   /api/gestion/reservas/{codigo}/alternativas  habitaciones a las que se puede mover, con su precio.
  POST  /api/gestion/reservas/{codigo}/check-in      registra el ingreso: confirmada pasa a en_curso.
  POST  /api/gestion/reservas/{codigo}/check-out     registra la salida: en_curso pasa a finalizada.
  PATCH /api/gestion/reservas/{codigo}               cambia la habitación, las fechas o las personas.

La cancelación ya existe en POST /api/reservas/{codigo}/cancelar y el
personal la usa desde el mismo panel.

Ciclo de vida de una reserva:

    pendiente_pago --pago--> confirmada --check-in--> en_curso --check-out--> finalizada
          |                       |
          +-------cancelar--------+--> cancelada

Reglas de dinero:
  - Si la reserva ya se pagó y facturó en línea, un cambio que altere el
    monto se rechaza: la factura no puede quedar distinta de lo cobrado.
    Las noches adicionales se registran como una reserva nueva.
  - En una salida anticipada, las noches que faltaban se liberan para otros
    huéspedes y el monto no cambia (no hay reembolso automático).

Límite del modelo de datos: una reserva ocupa una sola habitación durante
toda la estadía. Para mover a un huésped que ya ingresó, la habitación nueva
debe estar libre desde su fecha de entrada; la ruta de alternativas solo
ofrece las que cumplen esa condición.
"""
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from psycopg import errors as pg_errores
from sqlalchemy import and_, func, or_, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import config, correo, facturacion
from ..db import obtener_sesion
from ..dependencias import registrar, requiere_rol
from ..esquemas import (Alternativa, CambioReserva, DetalleReserva, EventoReserva, HabitacionEnTablero,
                        ReservaEnTablero, ReservaLiberada, ReservaSalida, ResumenTablero, SalidaHuesped, Tablero,
                        VistaRecepcion)
from ..facturacion import impuesto_de
from ..modelos import Habitacion, Pago, PagoCaja, RegistroBitacora, Reserva, Solicitud, Usuario
from .cuentas import CERO, cuenta_de, lineas_cuenta_final, texto_cuenta
from .reservas import (CANALES_PAGO_EN_HOTEL, ESTADOS_CANCELABLES, MAX_NOCHES, bloque_pago_en_hotel,
                       buscar_reserva, calcular_total, garantia_hasta, habitaciones_libres, hoy, salida_reserva)

router = APIRouter(prefix="/api/gestion", tags=["gestión de reservas"])
RECEPCION = requiere_rol("recepcionista", "gerente")

# Reservas que todavía se pueden atender (las finalizadas y canceladas son historia)
ESTADOS_ACTIVOS = ("pendiente_pago", "confirmada", "en_curso")
# Estados de limpieza en los que una habitación puede recibir a un huésped
LISTA_PARA_HUESPED = ("limpia", "inspeccionada")
MAX_RESULTADOS = 100
# Cómo se nombra cada estado dentro de una frase ("una reserva en curso")
EN_FRASE = {"pendiente_pago": "pendiente de pago", "confirmada": "confirmada", "en_curso": "en curso",
            "finalizada": "finalizada", "cancelada": "cancelada"}


# ---------------------------------------------------------------------
# Funciones de apoyo
# ---------------------------------------------------------------------
def conflicto(mensaje: str) -> HTTPException:
    """Error 409: la acción es válida en general, pero no en el estado actual de la reserva."""
    return HTTPException(status.HTTP_409_CONFLICT, mensaje)


def bloquear_habitacion(sesion: Session, habitacion_id: int) -> Habitacion:
    """Bloquea la fila de la habitación hasta el final de la transacción y la lee de nuevo.

    Así, dos ingresos o salidas simultáneos en la misma habitación se atienden
    uno después del otro y el segundo ve lo que hizo el primero. El orden de
    bloqueo es siempre reserva y después habitación, para que dos operaciones
    nunca se esperen mutuamente.
    """
    sesion.execute(select(Habitacion.id).where(Habitacion.id == habitacion_id).with_for_update())
    return sesion.get(Habitacion, habitacion_id, populate_existing=True)


def acciones_posibles(reserva: Reserva, dia: date) -> list[str]:
    """Acciones que tienen sentido hoy para la reserva, en el orden en que se muestran."""
    acciones = []
    if reserva.estado == "confirmada" and reserva.fecha_entrada <= dia < reserva.fecha_salida:
        acciones.append("check_in")
    if reserva.estado == "en_curso":
        acciones.append("check_out")
    if reserva.estado in ESTADOS_ACTIVOS:
        acciones.append("modificar")
    if reserva.estado in ESTADOS_CANCELABLES:
        acciones.append("cancelar")
    return acciones


def validar_nuevas_fechas(reserva: Reserva, entrada: date, salida: date, dia: date) -> None:
    """Valida las fechas propuestas para una reserva existente.

    Difiere de la validación al reservar en dos puntos:
      - Una entrada que ya pasó se acepta si no cambia: es el caso de un
        huésped alojado o de una llegada atrasada a la que se le cambia la
        habitación. Una entrada nueva, en cambio, no puede ser pasada.
      - Si el huésped ya ingresó, la entrada no cambia, y la salida debe ser
        posterior a hoy: para irse hoy se registra la salida.
    """
    if reserva.estado == "en_curso" and entrada != reserva.fecha_entrada:
        raise conflicto("El huésped ya ingresó: la fecha de entrada no se puede cambiar.")
    if entrada != reserva.fecha_entrada and entrada < dia:
        raise HTTPException(422, "La fecha de entrada ya pasó")
    if salida <= entrada:
        raise HTTPException(422, "La salida debe ser posterior a la entrada")
    if salida <= dia:
        aviso = " Si el huésped se va hoy, registre su salida." if reserva.estado == "en_curso" else ""
        raise HTTPException(422, f"La salida debe ser posterior a hoy.{aviso}")
    if (salida - entrada).days > MAX_NOCHES:
        raise HTTPException(422, f"Máximo {MAX_NOCHES} noches por reserva")


# ---------------------------------------------------------------------
# Consulta
# ---------------------------------------------------------------------
@router.get("/reservas", response_model=list[ReservaSalida])
def buscar(
    q: str = Query("", max_length=60, description="Código, nombre, correo o número de habitación"),
    vista: VistaRecepcion = "activas",
    sesion: Session = Depends(obtener_sesion),
    _: Usuario = Depends(RECEPCION),
):
    """Reservas para atender en recepción, hasta 100.

    Vistas:
      activas   pendientes de pago, confirmadas y en curso.
      llegadas  confirmadas cuya estadía ya empezó y aún no ingresan (hoy o atrasadas).
      salidas   en curso que deben salir hoy o ya debieron hacerlo.
      en_casa   huéspedes alojados ahora mismo.
      todas     sin filtro de estado.
    El texto se busca en el código, el nombre y el correo (sin distinguir
    mayúsculas) o como número exacto de habitación.
    """
    dia = hoy()
    consulta = select(Reserva).join(Habitacion, Reserva.habitacion_id == Habitacion.id)
    if vista == "activas":
        consulta = consulta.where(Reserva.estado.in_(ESTADOS_ACTIVOS))
    elif vista == "llegadas":
        consulta = consulta.where(Reserva.estado == "confirmada", Reserva.fecha_entrada <= dia,
                                  Reserva.fecha_salida > dia)
    elif vista == "salidas":
        consulta = consulta.where(Reserva.estado == "en_curso", Reserva.fecha_salida <= dia)
    elif vista == "en_casa":
        consulta = consulta.where(Reserva.estado == "en_curso")

    texto = q.strip()
    if texto:
        # Los comodines de LIKE (% y _) que escriba el usuario se buscan como texto normal
        literal = texto.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        patron = f"%{literal}%"
        consulta = consulta.where(or_(
            Reserva.codigo.ilike(patron, escape="\\"),
            Reserva.nombre_huesped.ilike(patron, escape="\\"),
            Reserva.correo_huesped.ilike(patron, escape="\\"),
            Habitacion.numero == texto,
        ))
    consulta = consulta.order_by(Reserva.fecha_entrada, Reserva.codigo).limit(MAX_RESULTADOS)
    return [salida_reserva(r) for r in sesion.scalars(consulta)]


@router.get("/reservas/{codigo}", response_model=DetalleReserva)
def detalle(codigo: str, sesion: Session = Depends(obtener_sesion), usuario: Usuario = Depends(RECEPCION)):
    """La reserva con su habitación, si se pagó en línea, las acciones posibles hoy y su historial.

    El historial sale de la bitácora: todo lo que se hizo con el código de la
    reserva, en orden, con el nombre de quien lo hizo.
    """
    reserva = buscar_reserva(sesion, codigo, usuario)
    pagada = sesion.scalar(select(Pago.id).where(
        Pago.reserva_id == reserva.id, Pago.tipo == "cobro", Pago.estado == "aprobado")) is not None
    eventos = sesion.execute(
        select(RegistroBitacora, Usuario.nombre)
        .outerjoin(Usuario, RegistroBitacora.usuario_id == Usuario.id)
        .where(RegistroBitacora.entidad == "reserva", RegistroBitacora.entidad_id == reserva.codigo)
        .order_by(RegistroBitacora.fecha, RegistroBitacora.id))
    return DetalleReserva(
        reserva=salida_reserva(reserva),
        piso=reserva.habitacion.piso,
        estado_limpieza=reserva.habitacion.estado_limpieza,
        fuera_de_servicio=reserva.habitacion.fuera_de_servicio,
        pagada_en_linea=pagada,
        acciones=acciones_posibles(reserva, hoy()),
        historial=[EventoReserva(fecha=e.fecha, accion=e.accion, usuario=nombre, detalle=e.detalle)
                   for e, nombre in eventos],
    )


@router.get("/reservas/{codigo}/alternativas", response_model=list[Alternativa])
def alternativas(
    codigo: str,
    entrada: date | None = Query(None, description="Nueva entrada; por omisión, la actual"),
    salida: date | None = Query(None, description="Nueva salida; por omisión, la actual"),
    personas: int | None = Query(None, ge=1, le=10),
    sesion: Session = Depends(obtener_sesion),
    usuario: Usuario = Depends(RECEPCION),
):
    """Habitaciones donde cabe la reserva con las fechas y personas indicadas, con su total.

    Incluye la habitación actual si sigue libre (marcada con ``actual``). Para
    un huésped que ya ingresó, solo ofrece habitaciones listas para recibirlo.
    """
    reserva = buscar_reserva(sesion, codigo, usuario)
    if reserva.estado not in ESTADOS_ACTIVOS:
        raise conflicto(f"No se puede modificar una reserva {EN_FRASE[reserva.estado]}.")
    entrada = entrada or reserva.fecha_entrada
    salida = salida or reserva.fecha_salida
    validar_nuevas_fechas(reserva, entrada, salida, hoy())

    libres = habitaciones_libres(sesion, entrada, salida, personas or reserva.personas,
                                 excluir_reserva_id=reserva.id)
    totales = {}
    resultado = []
    for h in libres:
        actual = h.id == reserva.habitacion_id
        if reserva.estado == "en_curso" and not actual and h.estado_limpieza not in LISTA_PARA_HUESPED:
            continue
        if h.tipo_id not in totales:
            totales[h.tipo_id] = calcular_total(sesion, h.tipo_id, entrada, salida)
        resultado.append(Alternativa(habitacion_id=h.id, numero=h.numero, tipo=h.tipo.nombre,
                                     capacidad=h.tipo.capacidad, estado_limpieza=h.estado_limpieza,
                                     total=totales[h.tipo_id], actual=actual))
    return resultado


# ---------------------------------------------------------------------
# Tablero de habitaciones (etapa 2)
# ---------------------------------------------------------------------
def situacion_de(habitacion: Habitacion, ocupante: ReservaEnTablero | None,
                 llegada: ReservaEnTablero | None, dia: date) -> str:
    """Situación de una habitación hoy, en orden de prioridad.

    Un huésped alojado manda sobre todo lo demás, porque es quien está en la
    habitación ahora; después, que esté fuera de servicio; después, una
    llegada pendiente. El tablero muestra igual al ocupante y a la llegada
    aunque la situación resuma solo uno de los dos.
    """
    if ocupante is not None:
        return "sale_hoy" if ocupante.fecha_salida <= dia else "ocupada"
    if habitacion.fuera_de_servicio:
        return "fuera_de_servicio"
    if llegada is not None:
        return "llegada_atrasada" if llegada.fecha_entrada < dia else "llega_hoy"
    return "libre"


@router.get("/tablero", response_model=Tablero)
def tablero(sesion: Session = Depends(obtener_sesion), _: Usuario = Depends(RECEPCION)):
    """Situación de cada habitación hoy, con sus reservas activas y los indicadores del día.

    Algoritmo (dos consultas, sin importar cuántas reservas haya):
      1. Lee las 46 habitaciones con su tipo.
      2. Lee solo las reservas que tocan el día: las en curso (el huésped está
         en el hotel, aunque su salida ya haya pasado) y las confirmadas o
         pendientes de pago cuya estadía ya empezó y aún no termina (llegadas
         de hoy o atrasadas). Pide solo las columnas que el tablero muestra.
      3. Reparte esas reservas por habitación y calcula la situación de cada una.
      4. Cuenta los indicadores: ocupación, llegadas, salidas, habitaciones
         libres y listas, por limpiar y fuera de servicio.
    El panel la consulta una vez por minuto y solo mientras la pantalla está
    visible, para no gastar consultas del plan gratuito de la base.
    """
    dia = hoy()
    ahora = datetime.now(config.ZONA_HORARIA)
    habitaciones = sesion.scalars(select(Habitacion).order_by(Habitacion.piso, Habitacion.numero)).all()
    filas = sesion.execute(
        select(Reserva.habitacion_id, Reserva.codigo, Reserva.nombre_huesped, Reserva.personas,
               Reserva.fecha_entrada, Reserva.fecha_salida, Reserva.estado, Reserva.canal,
               Reserva.creada_en, Reserva.con_adelanto)
        .where(or_(Reserva.estado == "en_curso",
                   and_(Reserva.estado.in_(("pendiente_pago", "confirmada")),
                        Reserva.fecha_entrada <= dia, Reserva.fecha_salida > dia)))
        .order_by(Reserva.fecha_entrada))

    ocupantes: dict[int, ReservaEnTablero] = {}
    llegadas: dict[int, ReservaEnTablero] = {}
    for fila in filas:
        limite = garantia_hasta(fila.canal, fila.estado, fila.fecha_entrada, fila.creada_en, fila.con_adelanto)
        reserva = ReservaEnTablero(codigo=fila.codigo, nombre_huesped=fila.nombre_huesped, personas=fila.personas,
                                   fecha_entrada=fila.fecha_entrada, fecha_salida=fila.fecha_salida,
                                   estado=fila.estado, garantia_vencida=limite is not None and ahora >= limite)
        destino = ocupantes if fila.estado == "en_curso" else llegadas
        destino.setdefault(fila.habitacion_id, reserva)   # la más antigua, si hubiera dos

    resultado = []
    for h in habitaciones:
        ocupante, llegada = ocupantes.get(h.id), llegadas.get(h.id)
        resultado.append(HabitacionEnTablero(
            id=h.id, numero=h.numero, piso=h.piso, tipo=h.tipo.nombre, capacidad=h.tipo.capacidad,
            estado_limpieza=h.estado_limpieza, fuera_de_servicio=h.fuera_de_servicio,
            situacion=situacion_de(h, ocupante, llegada, dia), ocupante=ocupante, llegada=llegada))

    fuera = sum(h.fuera_de_servicio for h in resultado)
    en_servicio = len(resultado) - fuera
    ocupadas = sum(h.ocupante is not None for h in resultado)
    ocupacion = (Decimal(ocupadas * 100) / en_servicio if en_servicio else Decimal(0)) \
        .quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    resumen = ResumenTablero(
        habitaciones=len(resultado), en_servicio=en_servicio, ocupadas=ocupadas, ocupacion=ocupacion,
        llegadas=sum(h.llegada is not None for h in resultado),
        salidas=sum(h.situacion == "sale_hoy" for h in resultado),
        libres_listas=sum(h.situacion == "libre" and h.estado_limpieza in LISTA_PARA_HUESPED for h in resultado),
        por_limpiar=sum(h.estado_limpieza in ("sucia", "en_limpieza") for h in resultado),
        fuera_de_servicio=fuera,
    )
    return Tablero(fecha=dia, resumen=resumen, habitaciones=resultado)


@router.post("/liberar-no-presentados", response_model=list[ReservaLiberada])
def liberar_no_presentados(sesion: Session = Depends(obtener_sesion), usuario: Usuario = Depends(RECEPCION)):
    """Libera ahora las reservas no presentadas, lo mismo que pg_cron hace cada hora en Supabase.

    La regla vive en la función liberar_no_presentados() de la base, para
    que la tarea programada y este botón hagan exactamente lo mismo: cancela
    las reservas que se pagan al llegar, confirmadas, sin adelanto pagado y
    tomadas antes de la hora de garantía del día de entrada, cuando esa hora
    ya pasó. Cada una queda en
    la bitácora como acción del sistema; aquí se registra además quién pidió
    la liberación.
    """
    filas = sesion.execute(text("SELECT * FROM liberar_no_presentados(:hora)"),
                           {"hora": config.HORA_GARANTIA}).all()
    if filas:
        registrar(sesion, usuario, "liberar_no_presentados", "sistema", None,
                  reservas=[f.codigo_reserva for f in filas])
    sesion.commit()
    return [ReservaLiberada(codigo=f.codigo_reserva, habitacion=f.numero_habitacion, fecha_entrada=f.entrada)
            for f in filas]


# ---------------------------------------------------------------------
# Ingreso y salida
# ---------------------------------------------------------------------
@router.post("/reservas/{codigo}/check-in", response_model=ReservaSalida)
def check_in(codigo: str, sesion: Session = Depends(obtener_sesion), usuario: Usuario = Depends(RECEPCION)):
    """Registra el ingreso del huésped: la reserva pasa de confirmada a en curso.

    Condiciones, en este orden:
      1. La reserva está confirmada (una pendiente de pago se paga primero).
      2. Hoy está dentro de la estadía: no antes de la entrada ni desde la salida.
      3. La habitación está en servicio, limpia o inspeccionada.
      4. Nadie más ocupa la habitación (el huésped anterior ya registró su salida).
    Reserva y habitación quedan bloqueadas durante la operación.
    """
    reserva = buscar_reserva(sesion, codigo, usuario, bloquear=True)
    dia = hoy()
    if reserva.estado == "pendiente_pago":
        raise conflicto("La reserva está pendiente de pago: el huésped debe pagarla antes de ingresar.")
    if reserva.estado != "confirmada":
        raise conflicto(f"No se puede registrar el ingreso de una reserva {EN_FRASE[reserva.estado]}.")
    if dia < reserva.fecha_entrada:
        raise conflicto(f"La llegada está prevista para el {reserva.fecha_entrada:%d/%m/%Y}.")
    if dia >= reserva.fecha_salida:
        raise conflicto(f"La estadía terminó el {reserva.fecha_salida:%d/%m/%Y}: ya no se puede registrar "
                        "el ingreso.")

    habitacion = bloquear_habitacion(sesion, reserva.habitacion_id)
    if habitacion.fuera_de_servicio:
        raise conflicto(f"La habitación {habitacion.numero} está fuera de servicio: asigne otra antes del "
                        "ingreso.")
    if habitacion.estado_limpieza not in LISTA_PARA_HUESPED:
        raise conflicto(f"La habitación {habitacion.numero} todavía no está lista "
                        f"({habitacion.estado_limpieza.replace('_', ' ')}): espere a limpieza o asigne otra.")
    ocupante = sesion.scalar(select(Reserva.codigo).where(
        Reserva.habitacion_id == habitacion.id, Reserva.estado == "en_curso", Reserva.id != reserva.id))
    if ocupante:
        raise conflicto(f"La habitación {habitacion.numero} sigue ocupada por la reserva {ocupante}: "
                        "registre primero su salida.")

    reserva.estado = "en_curso"
    reserva.actualizada_en = func.now()
    registrar(sesion, usuario, "check_in", "reserva", reserva.codigo, habitacion=habitacion.numero)
    sesion.commit()
    sesion.refresh(reserva)
    return salida_reserva(reserva)


@router.post("/reservas/{codigo}/check-out", response_model=ReservaSalida)
def check_out(codigo: str, tareas: BackgroundTasks, datos: SalidaHuesped | None = None,
              sesion: Session = Depends(obtener_sesion), usuario: Usuario = Depends(RECEPCION)):
    """Registra la salida: cobra la cuenta, emite la factura final y deja la habitación sucia para limpieza.

    Algoritmo, en una sola transacción:
      1. Calcula la cuenta. Si queda saldo, exige el método de pago (409 si
         falta) y registra el cobro por el saldo exacto.
      2. Si hubo algo que cobrar en el hotel (hospedaje que se paga al llegar
         o consumos), emite la factura electrónica final con una línea por
         concepto. Se envía a Hacienda después de confirmar la transacción.
      3. Cierra las solicitudes abiertas, marca la habitación sucia y
         finaliza la reserva.

    Si el huésped se va antes de lo previsto, la salida se adelanta a hoy (o
    al día siguiente de la entrada, si llegó hoy) y las noches restantes
    quedan libres para otros huéspedes. El monto no cambia. Al final se le
    envía un correo de agradecimiento con el resumen de su cuenta y la
    invitación a dejar una reseña.
    """
    reserva = buscar_reserva(sesion, codigo, usuario, bloquear=True)
    if reserva.estado != "en_curso":
        raise conflicto(f"Solo se registra la salida de una estadía en curso; esta reserva está "
                        f"{EN_FRASE[reserva.estado]}.")
    cuenta = cuenta_de(sesion, reserva)
    extra = {}
    if cuenta.por_pagar > CERO:
        if not (datos and datos.metodo_pago):
            raise conflicto(f"La cuenta tiene un saldo pendiente de USD {cuenta.por_pagar}. Indique el método de "
                            "pago para cobrarlo al registrar la salida.")
        sesion.add(PagoCaja(reserva_id=reserva.id, metodo=datos.metodo_pago, monto=cuenta.por_pagar,
                            referencia=datos.referencia, recibido_por=usuario.id))
        extra["cobrado"] = str(cuenta.por_pagar)
        extra["metodo_pago"] = datos.metodo_pago
    dia = hoy()
    if dia < reserva.fecha_salida:
        extra["salida_prevista"] = str(reserva.fecha_salida)
        reserva.fecha_salida = max(dia, reserva.fecha_entrada + timedelta(days=1))

    # Factura final por lo cobrado en el hotel (si no se emitió antes)
    factura = None
    if cuenta.subtotal > CERO and cuenta.factura_final is None:
        lineas, subtotal = lineas_cuenta_final(sesion, reserva)
        factura = facturacion.crear_cuenta_final(sesion, reserva, lineas, subtotal)
        extra["factura_final"] = factura.consecutivo

    habitacion = bloquear_habitacion(sesion, reserva.habitacion_id)
    habitacion.estado_limpieza = "sucia"
    # Las solicitudes que el huésped dejó abiertas se cierran con su salida
    sesion.execute(update(Solicitud)
                   .where(Solicitud.reserva_id == reserva.id, Solicitud.estado != "resuelta")
                   .values(estado="resuelta", resuelta_en=func.now(), pendiente_desde=None,
                           actualizada_en=func.now()))
    reserva.estado = "finalizada"
    reserva.actualizada_en = func.now()
    registrar(sesion, usuario, "check_out", "reserva", reserva.codigo, habitacion=habitacion.numero, **extra)
    sesion.commit()
    sesion.refresh(reserva)
    # El cobro y la factura ya quedaron guardados; si Hacienda no responde, la factura queda pendiente
    if factura is not None:
        facturacion.enviar_a_hacienda(sesion, factura)

    correo.programar(
        tareas, reserva.correo_huesped, "Gracias por hospedarse en el Hotel Soluna",
        f"Hola, {reserva.nombre_huesped}:\n\nRegistramos su salida de la habitación {habitacion.numero}. "
        f"Gracias por elegirnos; esperamos recibirle de nuevo en Playa Sámara.\n\n"
        f"{texto_cuenta(cuenta_de(sesion, reserva, para_huesped=True))}\n"
        f"Si desea contar su experiencia, puede escribir una reseña en la sección Reseñas de nuestro sitio "
        f"web con el código {reserva.codigo}. Para opinar necesita una cuenta de cliente con este mismo "
        f"correo.\n")
    return salida_reserva(reserva)


# ---------------------------------------------------------------------
# Cambios de habitación, fechas o personas
# ---------------------------------------------------------------------
@router.patch("/reservas/{codigo}", response_model=ReservaSalida)
def modificar(codigo: str, cambio: CambioReserva, tareas: BackgroundTasks,
              sesion: Session = Depends(obtener_sesion), usuario: Usuario = Depends(RECEPCION)):
    """Cambia la habitación, las fechas o el número de personas, y recalcula el total.

    Algoritmo:
      1. Bloquea la reserva y completa los campos omitidos con sus valores actuales.
      2. Valida las fechas (reglas distintas si el huésped ya ingresó), la
         habitación (en servicio, con capacidad y, si el huésped ya está en
         el hotel, lista para recibirlo) y que el monto no cambie si ya se
         pagó y facturó en línea.
      3. Guarda los cambios; si la base los rechaza por traslape con otra
         reserva, responde 409.
      4. Si el huésped ya estaba alojado y cambió de habitación, la anterior
         queda sucia.
      5. Registra en la bitácora los valores de antes y después, y avisa al
         huésped por correo si cambiaron las fechas o la habitación.
    """
    reserva = buscar_reserva(sesion, codigo, usuario, bloquear=True)
    if reserva.estado not in ESTADOS_ACTIVOS:
        raise conflicto(f"No se puede modificar una reserva {EN_FRASE[reserva.estado]}.")
    entrada = cambio.fecha_entrada or reserva.fecha_entrada
    salida = cambio.fecha_salida or reserva.fecha_salida
    personas = cambio.personas or reserva.personas
    habitacion_id = cambio.habitacion_id or reserva.habitacion_id
    if (entrada, salida, personas, habitacion_id) == (reserva.fecha_entrada, reserva.fecha_salida,
                                                      reserva.personas, reserva.habitacion_id):
        raise HTTPException(422, "No hay cambios que guardar.")
    validar_nuevas_fechas(reserva, entrada, salida, hoy())

    habitacion = sesion.get(Habitacion, habitacion_id)
    if habitacion is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Habitación no encontrada")
    cambia_habitacion = habitacion.id != reserva.habitacion_id
    if cambia_habitacion and habitacion.fuera_de_servicio:
        raise conflicto(f"La habitación {habitacion.numero} está fuera de servicio.")
    if cambia_habitacion and reserva.estado == "en_curso" and habitacion.estado_limpieza not in LISTA_PARA_HUESPED:
        raise conflicto(f"La habitación {habitacion.numero} todavía no está lista para recibir al huésped.")
    if personas > habitacion.tipo.capacidad:
        raise HTTPException(422, f"La habitación {habitacion.numero} admite como máximo "
                                 f"{habitacion.tipo.capacidad} personas")

    total = calcular_total(sesion, habitacion.tipo_id, entrada, salida)
    if reserva.factura is not None and total != reserva.total:
        raise conflicto(
            f"La reserva ya se pagó y facturó en línea por USD {reserva.total} (sin IVA) y con este cambio "
            f"costaría USD {total}. Para noches adicionales, cree una reserva nueva; para otros cambios, "
            "cancélela (se reembolsa el pago) y reserve de nuevo.")

    anterior = reserva.habitacion
    antes = {"habitacion": anterior.numero, "entrada": str(reserva.fecha_entrada),
             "salida": str(reserva.fecha_salida), "personas": reserva.personas, "total": str(reserva.total)}
    despues = {"habitacion": habitacion.numero, "entrada": str(entrada), "salida": str(salida),
               "personas": personas, "total": str(total)}
    reserva.habitacion_id = habitacion.id
    reserva.fecha_entrada, reserva.fecha_salida = entrada, salida
    reserva.personas = personas
    reserva.total = total
    reserva.actualizada_en = func.now()
    try:
        # flush envía el UPDATE ahora: la regla "sin_traslape" de la base revisa las nuevas fechas
        sesion.flush()
    except IntegrityError as error:
        sesion.rollback()
        if isinstance(error.orig, pg_errores.ExclusionViolation):
            raise conflicto(f"La habitación {despues['habitacion']} no está libre en esas fechas.")
        raise
    if cambia_habitacion and reserva.estado == "en_curso":
        anterior.estado_limpieza = "sucia"   # el huésped la usó: limpieza debe prepararla de nuevo
    registrar(sesion, usuario, "modificar_reserva", "reserva", reserva.codigo, antes=antes, despues=despues)
    sesion.commit()
    sesion.refresh(reserva)

    if antes["habitacion"] != despues["habitacion"] or antes["entrada"] != despues["entrada"] \
            or antes["salida"] != despues["salida"]:
        # Si se paga al llegar, el correo repite el monto y la hora de garantía con los datos nuevos
        pago = (f"\n{bloque_pago_en_hotel(reserva)}" if reserva.canal in CANALES_PAGO_EN_HOTEL
                else f"Total con IVA: USD {reserva.total + impuesto_de(reserva.total)}\n")
        correo.programar(
            tareas, reserva.correo_huesped, f"Reserva modificada {reserva.codigo}",
            f"Hola, {reserva.nombre_huesped}:\n\nActualizamos su reserva en el Hotel Soluna. Estos son los "
            f"datos vigentes:\n\n{correo.detalle_reserva(reserva)}\n{pago}")
    return salida_reserva(reserva)
