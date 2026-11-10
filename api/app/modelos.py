"""Tablas de la base de datos vistas desde Python (SQLAlchemy ORM).

La estructura real (restricciones, regla contra la sobreventa, índices)
está en db/init/01_esquema.sql; aquí solo se describen las columnas que
usa la API.
"""
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import ForeignKey, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Usuario(Base):
    __tablename__ = "usuarios"

    id: Mapped[int] = mapped_column(primary_key=True)
    correo: Mapped[str]
    nombre: Mapped[str]
    hash_contrasena: Mapped[str]
    rol: Mapped[str]
    activo: Mapped[bool] = mapped_column(default=True)
    intentos_fallidos: Mapped[int] = mapped_column(default=0)
    bloqueado_hasta: Mapped[datetime | None]
    creado_en: Mapped[datetime] = mapped_column(server_default=func.now())


class TipoHabitacion(Base):
    __tablename__ = "tipos_habitacion"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str]
    capacidad: Mapped[int]
    descripcion: Mapped[str | None]


class Tarifa(Base):
    __tablename__ = "tarifas"

    tipo_id: Mapped[int] = mapped_column(ForeignKey("tipos_habitacion.id"), primary_key=True)
    temporada: Mapped[str] = mapped_column(primary_key=True)
    precio_noche: Mapped[Decimal]


class Habitacion(Base):
    __tablename__ = "habitaciones"

    id: Mapped[int] = mapped_column(primary_key=True)
    numero: Mapped[str]
    tipo_id: Mapped[int] = mapped_column(ForeignKey("tipos_habitacion.id"))
    piso: Mapped[int]
    estado_limpieza: Mapped[str]
    fuera_de_servicio: Mapped[bool]

    tipo: Mapped[TipoHabitacion] = relationship(lazy="joined")


class Reserva(Base):
    __tablename__ = "reservas"

    id: Mapped[int] = mapped_column(primary_key=True)
    codigo: Mapped[str]
    habitacion_id: Mapped[int] = mapped_column(ForeignKey("habitaciones.id"))
    cliente_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    nombre_huesped: Mapped[str]
    correo_huesped: Mapped[str]
    personas: Mapped[int]
    fecha_entrada: Mapped[date]
    fecha_salida: Mapped[date]
    canal: Mapped[str]
    estado: Mapped[str]
    total: Mapped[Decimal]
    creada_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    creada_en: Mapped[datetime] = mapped_column(server_default=func.now())
    actualizada_en: Mapped[datetime] = mapped_column(server_default=func.now())

    referencia_externa: Mapped[str | None]   # número de reserva de la OTA

    habitacion: Mapped[Habitacion] = relationship(lazy="joined")
    factura: Mapped["Factura | None"] = relationship(lazy="selectin", back_populates="reserva")


class RegistroBitacora(Base):
    __tablename__ = "bitacora"

    id: Mapped[int] = mapped_column(primary_key=True)
    fecha: Mapped[datetime] = mapped_column(server_default=func.now())
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    accion: Mapped[str]
    entidad: Mapped[str]
    entidad_id: Mapped[str | None]
    detalle: Mapped[dict] = mapped_column(JSONB, default=dict)


class Pago(Base):
    __tablename__ = "pagos"

    id: Mapped[int] = mapped_column(primary_key=True)
    reserva_id: Mapped[int] = mapped_column(ForeignKey("reservas.id"))
    tipo: Mapped[str]            # cobro o reembolso
    estado: Mapped[str]          # aprobado o rechazado
    transaccion: Mapped[str]
    monto: Mapped[Decimal]
    marca: Mapped[str | None]
    ultimos4: Mapped[str | None]
    motivo: Mapped[str | None]
    creado_en: Mapped[datetime] = mapped_column(server_default=func.now())


class Factura(Base):
    __tablename__ = "facturas"

    id: Mapped[int] = mapped_column(primary_key=True)
    reserva_id: Mapped[int] = mapped_column(ForeignKey("reservas.id"))
    clave: Mapped[str]
    consecutivo: Mapped[str]
    subtotal: Mapped[Decimal]
    impuesto: Mapped[Decimal]
    total: Mapped[Decimal]
    estado: Mapped[str] = mapped_column(default="pendiente")
    mensaje: Mapped[str | None]
    emitida_en: Mapped[datetime] = mapped_column(server_default=func.now())
    respondida_en: Mapped[datetime | None]

    reserva: Mapped[Reserva] = relationship(back_populates="factura")
