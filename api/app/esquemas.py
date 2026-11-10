"""Formatos de entrada y salida de la API (validados por Pydantic)."""
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

import email_validator
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

# Se aceptan correos del dominio reservado ".test" (por ejemplo,
# cliente@soluna.test) porque en el prototipo los correos nunca salen:
# los captura Mailpit. En producción esta línea se elimina.
if "test" in email_validator.SPECIAL_USE_DOMAIN_NAMES:
    email_validator.SPECIAL_USE_DOMAIN_NAMES.remove("test")

Rol = Literal["cliente", "recepcionista", "limpieza", "mantenimiento", "gerente"]
EstadoLimpieza = Literal["sucia", "en_limpieza", "limpia", "inspeccionada"]


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    rol: Rol
    nombre: str


class RegistroCliente(BaseModel):
    nombre: str = Field(min_length=2, max_length=120)
    correo: EmailStr
    contrasena: str = Field(min_length=8, max_length=128)

    @field_validator("correo")
    @classmethod
    def a_minusculas(cls, v: str) -> str:
        return v.lower()


class NuevoUsuario(RegistroCliente):
    rol: Rol


class UsuarioSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre: str
    correo: str
    rol: Rol
    activo: bool


class HabitacionSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    numero: str
    piso: int
    tipo: str
    capacidad: int
    estado_limpieza: EstadoLimpieza
    fuera_de_servicio: bool


class CambioLimpieza(BaseModel):
    estado: EstadoLimpieza


class Disponible(BaseModel):
    habitacion_id: int
    numero: str
    tipo: str
    capacidad: int
    noches: int
    total: Decimal


class NuevaReserva(BaseModel):
    habitacion_id: int
    fecha_entrada: date
    fecha_salida: date
    personas: int = Field(ge=1, le=10)
    # Solo para reservas que crea el personal a nombre de un huésped;
    # si reserva un cliente con su cuenta, se usan sus propios datos.
    nombre_huesped: str | None = Field(default=None, min_length=2, max_length=120)
    correo_huesped: EmailStr | None = None


class ReservaSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    codigo: str
    habitacion: str
    tipo: str
    nombre_huesped: str
    correo_huesped: str
    personas: int
    fecha_entrada: date
    fecha_salida: date
    canal: str
    estado: str
    total: Decimal
    creada_en: datetime


class BitacoraSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    fecha: datetime
    usuario_id: int | None
    accion: str
    entidad: str
    entidad_id: str | None
    detalle: dict
