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

from sqlalchemy import ForeignKey, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


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
    personas: Mapped[int]
    fecha_entrada: Mapped[date]
    fecha_salida: Mapped[date]                   # día de salida: esa noche ya no se cobra
    canal: Mapped[str]                           # web, recepcion u ota
    estado: Mapped[str]                          # pendiente_pago, confirmada, en_curso, finalizada o cancelada
    total: Mapped[Decimal]                       # hospedaje sin impuestos
    creada_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    creada_en: Mapped[datetime] = mapped_column(server_default=func.now())
    actualizada_en: Mapped[datetime] = mapped_column(server_default=func.now())

    referencia_externa: Mapped[str | None]   # número de reserva de la OTA

    habitacion: Mapped[Habitacion] = relationship(lazy="joined")
    # lazy="selectin": las facturas de varias reservas se traen en una sola consulta adicional
    factura: Mapped["Factura | None"] = relationship(lazy="selectin", back_populates="reserva")


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
    """Factura electrónica de una reserva pagada (como máximo una por reserva).

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
    emitida_en: Mapped[datetime] = mapped_column(server_default=func.now())
    respondida_en: Mapped[datetime | None]

    reserva: Mapped[Reserva] = relationship(back_populates="factura")


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
