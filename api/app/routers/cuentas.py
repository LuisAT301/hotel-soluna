"""Cuenta de la habitación: consumos, pagos en caja y factura final (etapa 5).

Durante la estadía, recepción carga a la cuenta lo que el huésped consume
(room service, restaurante, bar, spa, tours...), del catálogo o como cargo
libre. Al registrar la salida (en gestion.py) se cobra lo pendiente y se
emite la factura electrónica final, con una línea por consumo.

Rutas:
  GET   /api/servicios                                      catálogo (recepción y gerencia; gerencia ve
                                                            también los inactivos con ?todos=true).
  POST  /api/servicios                                      agrega un servicio (gerencia).
  PATCH /api/servicios/{id}                                 lo cambia, activa o desactiva (gerencia).
  GET   /api/gestion/reservas/{codigo}/cuenta               estado de cuenta (recepción y gerencia).
  POST  /api/gestion/reservas/{codigo}/cargos               carga un consumo (huésped alojado).
  POST  /api/gestion/reservas/{codigo}/cargos/{id}/anular   anula un cargo, con motivo.
  POST  /api/gestion/reservas/{codigo}/pagos                registra un pago en caja.
  GET   /api/reservas/{codigo}/cuenta                       el huésped ve su cuenta.

Cómo se calcula lo que hay que pagar a la salida:

    hospedaje   = total de la estadía si se paga en el hotel (recepción o teléfono); 0 si se pagó
                  en línea, si la paga la agencia o si se canceló
    consumos    = suma de los cargos no anulados
    subtotal    = hospedaje + consumos
    IVA         = 13 % del subtotal (como lo calcula la factura)
    total       = subtotal + IVA
    por pagar   = total - pagos en caja   (si los pagos superan el total, la diferencia queda a favor)

Nada se borra: un cargo equivocado se anula con motivo y queda a la vista;
un pago no se edita. Todo queda además en la bitácora.
"""
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from psycopg import errors as pg_errores
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import facturacion
from ..db import obtener_sesion
from ..dependencias import registrar, requiere_rol
from ..esquemas import (AnulacionCargo, CambioServicio, CargoSalida, CuentaSalida, FacturaFinalSalida, NuevoCargo,
                        NuevoPagoCaja, NuevoServicio, PagoCajaSalida, ServicioSalida)
from ..facturacion import impuesto_de
from ..modelos import Cargo, Factura, PagoCaja, Reserva, Servicio, Usuario
from .reservas import CANALES_PAGO_EN_HOTEL, buscar_reserva
from .solicitudes import reserva_del_huesped

router = APIRouter(tags=["cuenta de la habitación"])

RECEPCION = requiere_rol("recepcionista", "gerente")
GERENCIA = requiere_rol("gerente")
HUESPED = requiere_rol("cliente")
CERO = Decimal("0.00")
METODOS = {"efectivo": "efectivo", "tarjeta": "tarjeta", "sinpe": "SINPE Móvil", "transferencia": "transferencia"}


# ---------------------------------------------------------------------
# Estado de cuenta
# ---------------------------------------------------------------------
def modalidad_hospedaje(reserva: Reserva) -> str:
    """Cómo se paga la estadía: en línea, por la agencia, en el hotel, o nada si se canceló."""
    if reserva.estado == "cancelada":
        return "cancelada"
    if reserva.canal in CANALES_PAGO_EN_HOTEL:
        return "en_hotel"
    return "agencia" if reserva.canal == "ota" else "en_linea"


def cuenta_de(sesion: Session, reserva: Reserva, para_huesped: bool = False) -> CuentaSalida:
    """Arma el estado de cuenta de la reserva con tres consultas: cargos, pagos y factura final.

    Al huésped no se le muestra quién cargó un consumo o recibió un pago.
    """
    modalidad = modalidad_hospedaje(reserva)
    hospedaje = reserva.total if modalidad == "en_hotel" else CERO
    cargos = sesion.execute(
        select(Cargo, Usuario.nombre).outerjoin(Usuario, Cargo.creado_por == Usuario.id)
        .where(Cargo.reserva_id == reserva.id).order_by(Cargo.id)).all()
    pagos = sesion.execute(
        select(PagoCaja, Usuario.nombre).outerjoin(Usuario, PagoCaja.recibido_por == Usuario.id)
        .where(PagoCaja.reserva_id == reserva.id).order_by(PagoCaja.id)).all()
    factura = sesion.scalar(select(Factura).where(Factura.reserva_id == reserva.id,
                                                  Factura.concepto == "cuenta_final"))

    consumos = sum((c.total for c, _ in cargos if c.anulado_en is None), CERO)
    subtotal = hospedaje + consumos
    impuesto = impuesto_de(subtotal)
    total = subtotal + impuesto
    pagado = sum((p.monto for p, _ in pagos), CERO)
    return CuentaSalida(
        codigo=reserva.codigo, estado=reserva.estado, hospedaje_modalidad=modalidad, hospedaje=hospedaje,
        consumos=consumos, subtotal=subtotal, impuesto=impuesto, total=total, pagado=pagado,
        por_pagar=max(total - pagado, CERO), a_favor=max(pagado - total, CERO),
        puede_cargar=reserva.estado == "en_curso",
        cargos=[CargoSalida(id=c.id, categoria=c.categoria, descripcion=c.descripcion, cantidad=c.cantidad,
                            precio_unitario=c.precio_unitario, total=c.total, creado_en=c.creado_en,
                            creado_por=None if para_huesped else nombre, anulado=c.anulado_en is not None,
                            motivo_anulacion=c.motivo_anulacion)
                for c, nombre in cargos],
        pagos=[PagoCajaSalida(id=p.id, metodo=p.metodo, monto=p.monto, referencia=p.referencia,
                              creado_en=p.creado_en, recibido_por=None if para_huesped else nombre)
               for p, nombre in pagos],
        factura_final=FacturaFinalSalida(consecutivo=factura.consecutivo, clave=factura.clave, estado=factura.estado,
                                         total=factura.total, emitida_en=factura.emitida_en) if factura else None,
    )


def lineas_cuenta_final(sesion: Session, reserva: Reserva) -> tuple[list[dict], Decimal]:
    """Líneas de la factura final: el hospedaje (si se paga en el hotel) y cada cargo vigente.

    Los montos van como texto para no perder precisión en JSON. Devuelve las
    líneas y su suma (el subtotal de la factura).
    """
    lineas = []
    if modalidad_hospedaje(reserva) == "en_hotel":
        noches = (reserva.fecha_salida - reserva.fecha_entrada).days
        lineas.append({
            "detalle": (f"Hospedaje en habitación {reserva.habitacion.tipo.nombre}, {noches} "
                        f"{'noche' if noches == 1 else 'noches'}, del {reserva.fecha_entrada:%d/%m/%Y} al "
                        f"{reserva.fecha_salida:%d/%m/%Y} (reserva {reserva.codigo})"),
            "cantidad": 1, "precio_unitario": str(reserva.total), "subtotal": str(reserva.total)})
    for cargo in sesion.scalars(select(Cargo).where(Cargo.reserva_id == reserva.id, Cargo.anulado_en.is_(None))
                                .order_by(Cargo.id)):
        lineas.append({"detalle": f"{cargo.descripcion} ({cargo.creado_en:%d/%m/%Y})", "cantidad": cargo.cantidad,
                       "precio_unitario": str(cargo.precio_unitario), "subtotal": str(cargo.total)})
    return lineas, sum((Decimal(linea["subtotal"]) for linea in lineas), CERO)


def texto_cuenta(cuenta: CuentaSalida) -> str:
    """Resumen de la cuenta para el correo de salida: cada concepto, los totales, los pagos y la factura."""
    partes = ["Resumen de su cuenta"]
    if cuenta.hospedaje_modalidad == "en_linea":
        partes.append("  Hospedaje: pagado en línea al reservar")
    elif cuenta.hospedaje_modalidad == "agencia":
        partes.append("  Hospedaje: pagado a la agencia de viajes")
    else:
        partes.append(f"  Hospedaje: USD {cuenta.hospedaje}")
    for c in cuenta.cargos:
        if not c.anulado:
            partes.append(f"  {c.cantidad} x {c.descripcion}: USD {c.total}")
    partes += [f"  Subtotal: USD {cuenta.subtotal}", f"  IVA (13 %): USD {cuenta.impuesto}",
               f"  Total cobrado en el hotel: USD {cuenta.total}"]
    for p in cuenta.pagos:
        partes.append(f"  Pagado con {METODOS[p.metodo]} el {p.creado_en:%d/%m/%Y}: USD {p.monto}")
    if cuenta.factura_final:
        partes.append(f"Factura electrónica {cuenta.factura_final.consecutivo}\n"
                      f"Clave: {cuenta.factura_final.clave}")
    return "\n".join(partes) + "\n"


def reintentar_factura(sesion: Session, reserva: Reserva) -> None:
    """Si la factura final quedó pendiente porque Hacienda no respondió, la reenvía."""
    factura = sesion.scalar(select(Factura).where(Factura.reserva_id == reserva.id,
                                                  Factura.concepto == "cuenta_final", Factura.estado == "pendiente"))
    if factura is not None:
        facturacion.enviar_a_hacienda(sesion, factura)


@router.get("/api/gestion/reservas/{codigo}/cuenta", response_model=CuentaSalida)
def ver_cuenta(codigo: str, sesion: Session = Depends(obtener_sesion), usuario: Usuario = Depends(RECEPCION)):
    """Estado de cuenta de la reserva, con quién cargó cada consumo y recibió cada pago."""
    reserva = buscar_reserva(sesion, codigo, usuario)
    reintentar_factura(sesion, reserva)
    return cuenta_de(sesion, reserva)


@router.get("/api/reservas/{codigo}/cuenta", response_model=CuentaSalida)
def cuenta_del_huesped(codigo: str, sesion: Session = Depends(obtener_sesion), usuario: Usuario = Depends(HUESPED)):
    """El huésped titular ve su cuenta: consumos, pagos, lo pendiente y la factura final."""
    reserva = reserva_del_huesped(sesion, codigo, usuario)
    reintentar_factura(sesion, reserva)
    return cuenta_de(sesion, reserva, para_huesped=True)


# ---------------------------------------------------------------------
# Consumos y pagos
# ---------------------------------------------------------------------
@router.post("/api/gestion/reservas/{codigo}/cargos", response_model=CuentaSalida, status_code=status.HTTP_201_CREATED)
def cargar(codigo: str, datos: NuevoCargo, sesion: Session = Depends(obtener_sesion),
           usuario: Usuario = Depends(RECEPCION)):
    """Carga un consumo a la cuenta de un huésped alojado.

    Del catálogo: se copian el nombre, la categoría y el precio vigentes (si
    después cambia el precio, lo ya cargado no cambia). Libre: se indican
    descripción, categoría y precio.
    """
    reserva = buscar_reserva(sesion, codigo, usuario, bloquear=True)
    if reserva.estado != "en_curso":
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Solo se cargan consumos a huéspedes alojados (con el ingreso registrado).")
    if datos.servicio_id is not None:
        servicio = sesion.get(Servicio, datos.servicio_id)
        if servicio is None or not servicio.activo:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Ese servicio no está disponible en el catálogo")
        descripcion, categoria, precio = servicio.nombre, servicio.categoria, servicio.precio
    else:
        if not (datos.descripcion and datos.categoria and datos.precio_unitario):
            raise HTTPException(422, "Para un cargo fuera del catálogo indique descripción, categoría y precio.")
        if len(datos.descripcion) < 2:
            raise HTTPException(422, "La descripción es muy corta.")
        descripcion, categoria, precio = datos.descripcion, datos.categoria, datos.precio_unitario
    cargo = Cargo(reserva_id=reserva.id, servicio_id=datos.servicio_id, categoria=categoria,
                  descripcion=descripcion, cantidad=datos.cantidad, precio_unitario=precio, creado_por=usuario.id)
    sesion.add(cargo)
    sesion.flush()
    registrar(sesion, usuario, "cargar_consumo", "reserva", reserva.codigo, cargo=cargo.id,
              descripcion=descripcion, cantidad=datos.cantidad, total=str(precio * datos.cantidad))
    sesion.commit()
    return cuenta_de(sesion, reserva)


@router.post("/api/gestion/reservas/{codigo}/cargos/{cargo_id}/anular", response_model=CuentaSalida)
def anular_cargo(codigo: str, cargo_id: int, datos: AnulacionCargo, sesion: Session = Depends(obtener_sesion),
                 usuario: Usuario = Depends(RECEPCION)):
    """Anula un cargo con motivo, mientras el huésped siga alojado. El cargo queda a la vista como anulado."""
    reserva = buscar_reserva(sesion, codigo, usuario, bloquear=True)
    if reserva.estado != "en_curso":
        raise HTTPException(status.HTTP_409_CONFLICT, "La cuenta ya está cerrada: no se pueden anular cargos.")
    cargo = sesion.get(Cargo, cargo_id)
    if cargo is None or cargo.reserva_id != reserva.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Cargo no encontrado en esta cuenta")
    if cargo.anulado_en is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Ese cargo ya estaba anulado.")
    cargo.anulado_en = func.now()
    cargo.anulado_por = usuario.id
    cargo.motivo_anulacion = datos.motivo
    registrar(sesion, usuario, "anular_cargo", "reserva", reserva.codigo, cargo=cargo.id,
              descripcion=cargo.descripcion, total=str(cargo.total), motivo=datos.motivo)
    sesion.commit()
    return cuenta_de(sesion, reserva)


@router.post("/api/gestion/reservas/{codigo}/pagos", response_model=CuentaSalida, status_code=status.HTTP_201_CREATED)
def pagar_en_caja(codigo: str, datos: NuevoPagoCaja, sesion: Session = Depends(obtener_sesion),
                  usuario: Usuario = Depends(RECEPCION)):
    """Registra un pago en la recepción: el hospedaje al llegar, un adelanto o el saldo.

    No se acepta más de lo pendiente: el cambio en efectivo se entrega en el
    mostrador, no queda como saldo a favor.
    """
    reserva = buscar_reserva(sesion, codigo, usuario, bloquear=True)
    if reserva.estado not in ("confirmada", "en_curso"):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Solo se registran pagos de reservas confirmadas o con el huésped alojado.")
    cuenta = cuenta_de(sesion, reserva)
    if cuenta.por_pagar == CERO:
        raise HTTPException(status.HTTP_409_CONFLICT, "La cuenta no tiene saldo pendiente.")
    if datos.monto > cuenta.por_pagar:
        raise HTTPException(422, f"El pago supera el saldo pendiente (USD {cuenta.por_pagar}).")
    sesion.add(PagoCaja(reserva_id=reserva.id, metodo=datos.metodo, monto=datos.monto, referencia=datos.referencia,
                        recibido_por=usuario.id))
    registrar(sesion, usuario, "pago_caja", "reserva", reserva.codigo, metodo=datos.metodo, monto=str(datos.monto))
    sesion.commit()
    return cuenta_de(sesion, reserva)


# ---------------------------------------------------------------------
# Catálogo de servicios (gerencia)
# ---------------------------------------------------------------------
@router.get("/api/servicios", response_model=list[ServicioSalida])
def catalogo(todos: bool = Query(False, description="Incluir los inactivos (solo gerencia)"),
             sesion: Session = Depends(obtener_sesion), usuario: Usuario = Depends(RECEPCION)):
    """Servicios del catálogo, por categoría y nombre. Recepción ve solo los activos."""
    consulta = select(Servicio).order_by(Servicio.categoria, Servicio.nombre)
    if not (todos and usuario.rol == "gerente"):
        consulta = consulta.where(Servicio.activo.is_(True))
    return sesion.scalars(consulta).all()


def guardar_servicio(sesion: Session) -> None:
    """Confirma el cambio del catálogo; un nombre repetido responde 409."""
    try:
        sesion.flush()
    except IntegrityError as error:
        sesion.rollback()
        if isinstance(error.orig, pg_errores.UniqueViolation):
            raise HTTPException(status.HTTP_409_CONFLICT, "Ya existe un servicio con ese nombre.")
        raise


@router.post("/api/servicios", response_model=ServicioSalida, status_code=status.HTTP_201_CREATED)
def agregar_servicio(datos: NuevoServicio, sesion: Session = Depends(obtener_sesion),
                     usuario: Usuario = Depends(GERENCIA)):
    """Agrega un servicio al catálogo."""
    servicio = Servicio(nombre=datos.nombre, categoria=datos.categoria, precio=datos.precio)
    sesion.add(servicio)
    guardar_servicio(sesion)
    registrar(sesion, usuario, "crear_servicio", "servicio", servicio.id, nombre=servicio.nombre,
              precio=str(servicio.precio))
    sesion.commit()
    return servicio


@router.patch("/api/servicios/{servicio_id}", response_model=ServicioSalida)
def cambiar_servicio(servicio_id: int, datos: CambioServicio, sesion: Session = Depends(obtener_sesion),
                     usuario: Usuario = Depends(GERENCIA)):
    """Cambia nombre, categoría o precio, o activa y desactiva un servicio (no se borra: hay cargos que lo usan)."""
    servicio = sesion.get(Servicio, servicio_id)
    if servicio is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Servicio no encontrado")
    cambios = {campo: valor for campo, valor in datos.model_dump(exclude_none=True).items()
               if getattr(servicio, campo) != valor}
    if not cambios:
        raise HTTPException(422, "No hay cambios que guardar.")
    antes = {campo: str(getattr(servicio, campo)) for campo in cambios}
    for campo, valor in cambios.items():
        setattr(servicio, campo, valor)
    guardar_servicio(sesion)
    registrar(sesion, usuario, "editar_servicio", "servicio", servicio.id, antes=antes,
              despues={campo: str(valor) for campo, valor in cambios.items()})
    sesion.commit()
    return servicio
