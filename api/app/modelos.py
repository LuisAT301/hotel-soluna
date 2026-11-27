"""Tablas de la base de datos vistas desde Python (SQLAlchemy ORM).

La estructura real (restricciones, regla contra la sobreventa, índices)
está en db/init/01_esquema.sql; aquí solo se describen las columnas que
usa la API.

Cada clase corresponde a una tabla y cada atributo ``Mapped[...]`` a una
columna. ``Mapped[X | None]`` indica una columna que admite nulos. Las
relaciones (``relationship``) permiten navegar de un objeto a otro, por
ejemplo ``reserva.habitacion.tipo.nombre``, sin escribir el JOIN a mano.
"""
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Computed, ForeignKey, exists, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, column_property, mapped_column, relationship


class Base(DeclarativeBase):
    """Clase base común: registra todas las tablas en los mismos metadatos."""
    pass


class Usuario(Base):
    """Cuenta del sistema: clientes y personal del hotel.

    ``intentos_fallidos`` y ``bloqueado_hasta`` implementan el bloqueo
    temporal de la cuenta tras varias contraseñas equivocadas.
    """
    __tablename__ = "usuarios"

    id: Mapped[int] = mapped_column(primary_key=True)
    correo: Mapped[str]
    nombre: Mapped[str]
    hash_contrasena: Mapped[str]                 # Argon2id; nunca la contraseña
    rol: Mapped[str]                             # cliente, recepcionista, limpieza, mantenimiento o gerente
    activo: Mapped[bool] = mapped_column(default=True)
    intentos_fallidos: Mapped[int] = mapped_column(default=0)
    bloqueado_hasta: Mapped[datetime | None]
    creado_en: Mapped[datetime] = mapped_column(server_default=func.now())


class TipoHabitacion(Base):
    """Categoría de habitación (estándar, superior, suite) con su capacidad máxima."""
    __tablename__ = "tipos_habitacion"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str]
    capacidad: Mapped[int]
    descripcion: Mapped[str | None]


class Tarifa(Base):
    """Precio por noche de un tipo de habitación en una temporada (alta o baja).

    La clave primaria es compuesta (tipo_id, temporada): hay una sola tarifa
    por tipo y temporada.
    """
    __tablename__ = "tarifas"

    tipo_id: Mapped[int] = mapped_column(ForeignKey("tipos_habitacion.id"), primary_key=True)
    temporada: Mapped[str] = mapped_column(primary_key=True)
    precio_noche: Mapped[Decimal]


class Habitacion(Base):
    """Habitación física del hotel, con su estado de limpieza."""
    __tablename__ = "habitaciones"

    id: Mapped[int] = mapped_column(primary_key=True)
    numero: Mapped[str]
    tipo_id: Mapped[int] = mapped_column(ForeignKey("tipos_habitacion.id"))
    piso: Mapped[int]
    estado_limpieza: Mapped[str]                 # sucia, en_limpieza, limpia o inspeccionada
    fuera_de_servicio: Mapped[bool]              # si es True, no se ofrece para reservar

    # lazy="joined": el tipo se carga en la misma consulta que la habitación
    tipo: Mapped[TipoHabitacion] = relationship(lazy="joined")


class Reserva(Base):
    """Reserva de una habitación entre dos fechas.

    ``cliente_id`` es nulo cuando recepción reserva para alguien sin cuenta o
    cuando la reserva llega de la OTA; ``creada_por`` es el usuario del
    personal que la registró, si lo hubo. La base de datos impide que dos
    reservas activas de la misma habitación se traslapen en fechas.
    """
    __tablename__ = "reservas"

    id: Mapped[int] = mapped_column(primary_key=True)
    codigo: Mapped[str]                          # código visible para el huésped, por ejemplo SOL-AB12CD
    habitacion_id: Mapped[int] = mapped_column(ForeignKey("habitaciones.id"))
    cliente_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    nombre_huesped: Mapped[str]
    correo_huesped: Mapped[str]
    telefono_huesped: Mapped[str | None]         # contacto; obligatorio en reservas por teléfono
    personas: Mapped[int]
    fecha_entrada: Mapped[date]
    fecha_salida: Mapped[date]                   # día de salida: esa noche ya no se cobra
    canal: Mapped[str]                           # web, recepcion, telefono u ota
    estado: Mapped[str]                          # pendiente_pago, confirmada, en_curso, finalizada o cancelada
    total: Mapped[Decimal]                       # hospedaje sin impuestos
    creada_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    creada_en: Mapped[datetime] = mapped_column(server_default=func.now())
    actualizada_en: Mapped[datetime] = mapped_column(server_default=func.now())

    referencia_externa: Mapped[str | None]   # número de reserva de la OTA

    habitacion: Mapped[Habitacion] = relationship(lazy="joined")
    # lazy="selectin": las facturas de varias reservas se traen en una sola consulta adicional
    # Solo la factura del hospedaje pagado en línea; la de la cuenta final se consulta aparte
    factura: Mapped["Factura | None"] = relationship(
        lazy="selectin", viewonly=True,
        primaryjoin="and_(Reserva.id == Factura.reserva_id, Factura.concepto == 'hospedaje')")


class RegistroBitacora(Base):
    """Entrada de la bitácora de auditoría: quién hizo qué, sobre qué y cuándo.

    ``entidad`` y ``entidad_id`` señalan el objeto afectado (por ejemplo,
    "reserva" y su código) sin clave foránea, para poder auditar cualquier tipo.
    """
    __tablename__ = "bitacora"

    id: Mapped[int] = mapped_column(primary_key=True)
    fecha: Mapped[datetime] = mapped_column(server_default=func.now())
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    accion: Mapped[str]
    entidad: Mapped[str]
    entidad_id: Mapped[str | None]
    detalle: Mapped[dict] = mapped_column(JSONB, default=dict)


class Pago(Base):
    """Movimiento con la pasarela: un cobro o un reembolso, aprobado o rechazado.

    Solo guarda la marca y los últimos cuatro dígitos de la tarjeta. Un
    reembolso es un registro nuevo; los pagos nunca se modifican.
    """
    __tablename__ = "pagos"

    id: Mapped[int] = mapped_column(primary_key=True)
    reserva_id: Mapped[int] = mapped_column(ForeignKey("reservas.id"))
    tipo: Mapped[str]            # cobro o reembolso
    estado: Mapped[str]          # aprobado o rechazado
    transaccion: Mapped[str]     # identificador que asigna la pasarela
    monto: Mapped[Decimal]
    marca: Mapped[str | None]
    ultimos4: Mapped[str | None]
    motivo: Mapped[str | None]   # por qué se rechazó, si fue el caso
    creado_en: Mapped[datetime] = mapped_column(server_default=func.now())


class Factura(Base):
    """Factura electrónica de una reserva: la del hospedaje pagado en línea o la de la cuenta final.

    Hay como máximo una de cada concepto por reserva. La de la cuenta final
    (lo cobrado en el hotel: hospedaje que se paga al llegar y consumos)
    guarda sus líneas, para reenviarlas si Hacienda no respondió.
    ``estado`` empieza en "pendiente" y cambia a "aceptada" o "rechazada"
    cuando responde Hacienda.
    """
    __tablename__ = "facturas"

    id: Mapped[int] = mapped_column(primary_key=True)
    reserva_id: Mapped[int] = mapped_column(ForeignKey("reservas.id"))
    clave: Mapped[str]                           # clave numérica de 50 dígitos
    consecutivo: Mapped[str]                     # número de comprobante de 20 dígitos
    subtotal: Mapped[Decimal]
    impuesto: Mapped[Decimal]
    total: Mapped[Decimal]
    estado: Mapped[str] = mapped_column(default="pendiente")
    mensaje: Mapped[str | None]                  # respuesta de Hacienda
    concepto: Mapped[str] = mapped_column(default="hospedaje")    # hospedaje o cuenta_final
    lineas: Mapped[list | None] = mapped_column(JSONB)           # solo en la cuenta final
    emitida_en: Mapped[datetime] = mapped_column(server_default=func.now())
    respondida_en: Mapped[datetime | None]

    reserva: Mapped[Reserva] = relationship()


class Resena(Base):
    """Reseña verificada: la escribe el titular de una reservación ya cumplida.

    Hay como máximo una por reservación (restricción UNIQUE en la base).
    """
    __tablename__ = "resenas"

    id: Mapped[int] = mapped_column(primary_key=True)
    reserva_id: Mapped[int] = mapped_column(ForeignKey("reservas.id"))
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    calificacion: Mapped[int]                    # de 1 a 5 estrellas
    comentario: Mapped[str]
    creada_en: Mapped[datetime] = mapped_column(server_default=func.now())

    # Se cargan en la misma consulta: el sitio muestra el autor y el tipo de habitación
    reserva: Mapped[Reserva] = relationship(lazy="joined")
    usuario: Mapped[Usuario] = relationship(lazy="joined")


class Suscriptor(Base):
    """Correo dejado en el sitio web para recibir ofertas y novedades."""
    __tablename__ = "suscriptores"

    id: Mapped[int] = mapped_column(primary_key=True)
    correo: Mapped[str]
    origen: Mapped[str] = mapped_column(default="sitio_web")
    activo: Mapped[bool] = mapped_column(default=True)   # False si pidió no recibir más correos
    creado_en: Mapped[datetime] = mapped_column(server_default=func.now())


class Solicitud(Base):
    """Solicitud de un huésped durante su estadía: una conversación con un área del hotel.

    Hay como máximo una abierta por reserva (índice único parcial en la
    base): mientras siga abierta, los mensajes nuevos del huésped van a ella.
    Sin relaciones cargadas por defecto: las consultas del chat unen solo
    las columnas que necesitan, para que cada actualización cueste poco.
    """
    __tablename__ = "solicitudes"

    id: Mapped[int] = mapped_column(primary_key=True)
    reserva_id: Mapped[int] = mapped_column(ForeignKey("reservas.id"))
    categoria: Mapped[str] = mapped_column(default="recepcion")    # recepcion, limpieza o mantenimiento
    estado: Mapped[str] = mapped_column(default="abierta")         # abierta, en_atencion o resuelta
    asignada_a: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    simulada: Mapped[bool] = mapped_column(default=False)
    creada_en: Mapped[datetime] = mapped_column(server_default=func.now())
    actualizada_en: Mapped[datetime] = mapped_column(server_default=func.now())
    pendiente_desde: Mapped[datetime | None]                       # el huésped espera respuesta desde aquí
    resuelta_en: Mapped[datetime | None]


class Mensaje(Base):
    """Un mensaje de una solicitud, del huésped o del personal. No se edita ni se borra desde la API."""
    __tablename__ = "mensajes"

    id: Mapped[int] = mapped_column(primary_key=True)
    solicitud_id: Mapped[int] = mapped_column(ForeignKey("solicitudes.id"))
    autor: Mapped[str]                                             # huesped o personal
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))   # nulo: huésped simulado
    texto: Mapped[str]
    creado_en: Mapped[datetime] = mapped_column(server_default=func.now())


class Servicio(Base):
    """Servicio del catálogo que se puede cargar a la cuenta de una habitación (precio sin IVA)."""
    __tablename__ = "servicios"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str]
    categoria: Mapped[str]       # room_service, restaurante, bar, minibar, spa, lavanderia, transporte, tours, otros
    precio: Mapped[Decimal]
    activo: Mapped[bool] = mapped_column(default=True)


class Cargo(Base):
    """Consumo cargado a la cuenta de una reserva. No se borra: si fue un error, se anula con motivo.

    Copia la descripción y el precio del catálogo al momento de cargarse;
    ``total`` lo calcula la base (cantidad por precio unitario).
    """
    __tablename__ = "cargos"

    id: Mapped[int] = mapped_column(primary_key=True)
    reserva_id: Mapped[int] = mapped_column(ForeignKey("reservas.id"))
    servicio_id: Mapped[int | None] = mapped_column(ForeignKey("servicios.id"))
    categoria: Mapped[str]
    descripcion: Mapped[str]
    cantidad: Mapped[int]
    precio_unitario: Mapped[Decimal]
    total: Mapped[Decimal] = mapped_column(Computed("cantidad * precio_unitario"))
    creado_en: Mapped[datetime] = mapped_column(server_default=func.now())
    creado_por: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    anulado_en: Mapped[datetime | None]
    anulado_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    motivo_anulacion: Mapped[str | None]


class PagoCaja(Base):
    """Pago recibido en la recepción para la cuenta de una reserva. No se edita ni se borra."""
    __tablename__ = "pagos_caja"

    id: Mapped[int] = mapped_column(primary_key=True)
    reserva_id: Mapped[int] = mapped_column(ForeignKey("reservas.id"))
    metodo: Mapped[str]          # efectivo, tarjeta, sinpe o transferencia
    monto: Mapped[Decimal]
    referencia: Mapped[str | None]
    recibido_por: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    creado_en: Mapped[datetime] = mapped_column(server_default=func.now())


# Si la reserva recibió algún pago en caja. Un adelanto la mantiene aunque pase la hora de garantía,
# así que no se libera sola. Se declara aquí porque necesita la tabla de pagos; viaja como un EXISTS
# dentro de la misma consulta de la reserva, sin consultas adicionales.
Reserva.con_adelanto = column_property(exists().where(PagoCaja.reserva_id == Reserva.id))


class Comprobante(Base):
    """Comprobante de un pago por SINPE Móvil o transferencia, que recepción revisa.

    El cliente indica el método, el número y el monto, y puede adjuntar una
    imagen o un PDF. Recepción lo acepta (se registra el pago y se confirma la
    reserva) o lo rechaza con un motivo. La API no puede borrarlo ni cambiar lo
    que el cliente envió; el mantenimiento borra el archivo 90 días después de
    revisado y conserva el resto como respaldo del pago.
    """
    __tablename__ = "comprobantes"

    id: Mapped[int] = mapped_column(primary_key=True)
    reserva_id: Mapped[int] = mapped_column(ForeignKey("reservas.id"))
    metodo: Mapped[str]                      # sinpe o transferencia
    numero: Mapped[str]                      # número del comprobante, en mayúsculas
    monto: Mapped[Decimal]                   # lo que el cliente dice que pagó (igual al total con IVA)
    # El archivo solo se carga cuando se pide (al mostrarlo); las listas no lo traen
    archivo: Mapped[bytes | None] = mapped_column(deferred=True)
    tipo_archivo: Mapped[str | None]         # image/jpeg, image/png o application/pdf
    estado: Mapped[str]                      # pendiente, aceptado o rechazado
    motivo: Mapped[str | None]               # por qué se rechazó
    enviado_por: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    enviado_en: Mapped[datetime] = mapped_column(server_default=func.now())
    revisado_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    revisado_en: Mapped[datetime | None]

    reserva: Mapped[Reserva] = relationship()


# El último comprobante de la reserva (su estado y, si se rechazó, el motivo), para que la lista de
# reservas muestre "en revisión" o "rechazado" sin consultas adicionales
def _del_ultimo_comprobante(columna):
    return column_property(
        select(columna).where(Comprobante.reserva_id == Reserva.id)
        .order_by(Comprobante.id.desc()).limit(1).correlate_except(Comprobante).scalar_subquery())


Reserva.comprobante_estado = _del_ultimo_comprobante(Comprobante.estado)
Reserva.comprobante_motivo = _del_ultimo_comprobante(Comprobante.motivo)
