"""Formatos de entrada y salida de la API (validados por Pydantic).

Cada clase describe un cuerpo JSON. En la entrada, Pydantic rechaza con un
error 422 cualquier dato con tipo, longitud o formato incorrecto antes de que
llegue a la lógica de la API. En la salida, define qué campos se devuelven,
de modo que nunca se filtre por accidente una columna interna (por ejemplo,
el hash de la contraseña). ``from_attributes=True`` permite construir la
respuesta directamente desde un objeto de la base de datos.
"""
import re
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

# Valores admitidos: cualquier otro se rechaza con 422
Rol = Literal["cliente", "recepcionista", "limpieza", "mantenimiento", "gerente"]
EstadoLimpieza = Literal["sucia", "en_limpieza", "limpia", "inspeccionada"]


class Token(BaseModel):
    """Respuesta del inicio de sesión: el token y los datos que usa la interfaz."""
    access_token: str
    token_type: str = "bearer"
    rol: Rol
    nombre: str


class RegistroCliente(BaseModel):
    """Datos para que un cliente cree su cuenta desde el sitio web."""
    nombre: str = Field(min_length=2, max_length=120)
    correo: EmailStr
    contrasena: str = Field(min_length=8, max_length=128)

    @field_validator("correo")
    @classmethod
    def a_minusculas(cls, v: str) -> str:
        """Guarda el correo en minúsculas: Ana@x.com y ana@x.com son la misma cuenta."""
        return v.lower()


class NuevoUsuario(RegistroCliente):
    """Cuenta que crea gerencia, con el rol que tendrá."""
    rol: Rol


class UsuarioSalida(BaseModel):
    """Datos públicos de una cuenta (sin el hash de la contraseña)."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre: str
    correo: str
    rol: Rol
    activo: bool


class HabitacionSalida(BaseModel):
    """Habitación con su tipo y estado, para recepción y limpieza."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    numero: str
    piso: int
    tipo: str
    capacidad: int
    estado_limpieza: EstadoLimpieza
    fuera_de_servicio: bool


class CambioLimpieza(BaseModel):
    """Nuevo estado de limpieza que registra el personal."""
    estado: EstadoLimpieza


class Disponible(BaseModel):
    """Habitación libre para las fechas consultadas, con el precio de la estadía."""
    habitacion_id: int
    numero: str
    tipo: str
    capacidad: int
    noches: int
    total: Decimal


class NuevaReserva(BaseModel):
    """Solicitud de reserva. Las fechas se validan en la ruta (salida posterior a la entrada)."""
    habitacion_id: int
    fecha_entrada: date
    fecha_salida: date
    personas: int = Field(ge=1, le=10)
    # Solo para reservas que crea el personal a nombre de un huésped;
    # si reserva un cliente con su cuenta, se usan sus propios datos.
    nombre_huesped: str | None = Field(default=None, min_length=2, max_length=120)
    correo_huesped: EmailStr | None = None
    # Teléfono de contacto: obligatorio en las reservas que llegan por teléfono
    telefono_huesped: str | None = Field(default=None, max_length=25)
    # Cómo llegó la reserva al personal: en el mostrador o por teléfono (se ignora si reserva un cliente)
    canal: Literal["recepcion", "telefono"] | None = None

    @field_validator("telefono_huesped")
    @classmethod
    def telefono_valido(cls, valor: str | None) -> str | None:
        """Recorta y une los espacios; exige solo números, espacios, guiones, paréntesis y un "+"
        inicial, con 8 a 15 dígitos (el máximo internacional, E.164). Vacío equivale a no indicarlo."""
        if valor is None or not valor.strip():
            return None
        valor = " ".join(valor.split())
        digitos = sum(c.isdigit() for c in valor)
        if not re.fullmatch(r"\+?[0-9 ()-]{8,20}", valor) or not 8 <= digitos <= 15:
            raise ValueError("Teléfono inválido: use números, espacios, guiones o paréntesis, con 8 a 15 dígitos")
        return valor


class ReservaSalida(BaseModel):
    """Reserva tal como la ve el huésped o el personal, con el desglose del IVA."""
    model_config = ConfigDict(from_attributes=True)

    codigo: str
    habitacion: str
    tipo: str
    nombre_huesped: str
    correo_huesped: str
    telefono_huesped: str | None
    personas: int
    fecha_entrada: date
    fecha_salida: date
    canal: str
    estado: str
    total: Decimal                 # hospedaje, sin impuestos
    impuesto: Decimal              # IVA del 13 %
    total_con_impuesto: Decimal    # lo que se cobra
    tiene_factura: bool
    creada_en: datetime
    # Hasta cuándo se garantizan la habitación y la tarifa (reservas que se pagan al llegar y aún no ingresan)
    garantia_hasta: datetime | None = None


class SolicitudPago(BaseModel):
    """Pago de una reserva con el token que la pasarela le dio al navegador."""
    # Token de un solo uso que entrega la pasarela al navegador. La API
    # nunca recibe el número de tarjeta ni el código de seguridad.
    token: str = Field(pattern=r"^tok_[A-Za-z0-9_-]{8,64}$")


class FacturaSalida(BaseModel):
    """Factura electrónica con su estado ante Hacienda."""
    model_config = ConfigDict(from_attributes=True)

    clave: str
    consecutivo: str
    subtotal: Decimal
    impuesto: Decimal
    total: Decimal
    estado: str
    mensaje: str | None
    emitida_en: datetime


class PagoSalida(BaseModel):
    """Resultado de un pago aprobado: la reserva confirmada, el cobro y la factura."""
    reserva: ReservaSalida
    transaccion: str
    marca: str | None
    ultimos4: str | None
    monto: Decimal
    factura: FacturaSalida


class ReservaOTA(BaseModel):
    """Aviso que envía la agencia de viajes en línea (OTA)."""
    referencia: str = Field(pattern=r"^[A-Z0-9-]{4,40}$")
    tipo: Literal["estándar", "superior", "suite"]
    fecha_entrada: date
    fecha_salida: date
    personas: int = Field(ge=1, le=10)
    nombre_huesped: str = Field(min_length=2, max_length=120)
    correo_huesped: EmailStr


class TipoHabitacionSalida(BaseModel):
    """Catálogo público que muestra la página de inicio."""
    nombre: str
    capacidad: int
    descripcion: str | None
    precio_desde: Decimal       # tarifa por noche más baja (temporada baja)
    habitaciones: int


class NuevaSuscripcion(BaseModel):
    """Correo que deja un visitante en el formulario de novedades."""
    correo: EmailStr

    @field_validator("correo")
    @classmethod
    def a_minusculas(cls, v: str) -> str:
        """Evita suscripciones duplicadas que solo difieren en mayúsculas."""
        return v.lower()


class NuevaResena(BaseModel):
    """Reseña que envía un huésped con sesión iniciada."""
    codigo_reserva: str = Field(max_length=20, description="Por ejemplo, SOL-7KQ2MX")
    calificacion: int = Field(ge=1, le=5)
    comentario: str = Field(min_length=10, max_length=1000)

    @field_validator("codigo_reserva")
    @classmethod
    def codigo_normalizado(cls, v: str) -> str:
        """Acepta el código en minúsculas y con espacios alrededor; exige el formato SOL-XXXXXX."""
        v = v.strip().upper()
        if not (v.startswith("SOL-") and v[4:].isalnum() and len(v) == 10):
            raise ValueError("El código de reservación tiene el formato SOL-XXXXXX")
        return v

    @field_validator("comentario")
    @classmethod
    def sin_espacios_sobrantes(cls, v: str) -> str:
        """Quita espacios al inicio y al final; un comentario de puros espacios no llega a 10 caracteres."""
        v = v.strip()
        if len(v) < 10:
            raise ValueError("Escriba al menos 10 caracteres")
        return v


class ResenaSalida(BaseModel):
    """Reseña tal como se publica: sin correo ni apellido completo del autor."""
    autor: str                     # nombre y la inicial del apellido, por ejemplo "Ana M."
    calificacion: int
    comentario: str
    tipo_habitacion: str
    creada_en: datetime


class ResumenResenas(BaseModel):
    """Promedio, cantidad total y las reseñas más recientes, para la página de inicio."""
    promedio: Decimal | None       # None mientras no haya reseñas
    total: int
    resenas: list[ResenaSalida]


class SuscriptorSalida(BaseModel):
    """Suscriptor en la lista que consulta gerencia."""
    model_config = ConfigDict(from_attributes=True)

    correo: str
    origen: str
    activo: bool
    creado_en: datetime


class BitacoraSalida(BaseModel):
    """Entrada de la bitácora de auditoría."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    fecha: datetime
    usuario_id: int | None
    accion: str
    entidad: str
    entidad_id: str | None
    detalle: dict


# ---------------------------------------------------------------------
# Gestión de reservas en recepción (panel del personal)
# ---------------------------------------------------------------------
VistaRecepcion = Literal["activas", "llegadas", "salidas", "en_casa", "todas"]


class CambioReserva(BaseModel):
    """Cambios que recepción hace a una reserva; los campos omitidos conservan su valor actual."""
    habitacion_id: int | None = None
    fecha_entrada: date | None = None
    fecha_salida: date | None = None
    personas: int | None = Field(default=None, ge=1, le=10)


class Alternativa(BaseModel):
    """Habitación a la que se puede mover una reserva, con el total que tendría la estadía allí."""
    habitacion_id: int
    numero: str
    tipo: str
    capacidad: int
    estado_limpieza: str
    total: Decimal          # hospedaje sin impuestos, recalculado por temporada
    actual: bool            # es la habitación que la reserva ya tiene


class EventoReserva(BaseModel):
    """Una acción del historial de la reserva, tomada de la bitácora."""
    fecha: datetime
    accion: str
    usuario: str | None     # None: un sistema externo (la OTA)
    detalle: dict


class DetalleReserva(BaseModel):
    """Lo que recepción necesita para atender una reserva: datos, habitación, acciones e historial.

    ``acciones`` la calcula la API según el estado y la fecha, para que la
    interfaz muestre solo los botones que tienen sentido. La API vuelve a
    validar cada acción al ejecutarla.
    """
    reserva: ReservaSalida
    piso: int
    estado_limpieza: EstadoLimpieza
    fuera_de_servicio: bool
    pagada_en_linea: bool
    acciones: list[Literal["check_in", "check_out", "modificar", "cancelar"]]
    historial: list[EventoReserva]


# ---------------------------------------------------------------------
# Tablero de habitaciones (panel del personal, etapa 2)
# ---------------------------------------------------------------------
SituacionHabitacion = Literal["libre", "ocupada", "sale_hoy", "llega_hoy", "llegada_atrasada",
                              "fuera_de_servicio"]


class ReservaEnTablero(BaseModel):
    """Lo mínimo de una reserva que recepción necesita ver de un vistazo en el tablero."""
    codigo: str
    nombre_huesped: str
    personas: int
    fecha_entrada: date
    fecha_salida: date
    estado: str
    garantia_vencida: bool = False   # se paga al llegar, no ha ingresado y ya pasó la hora de garantía


class HabitacionEnTablero(BaseModel):
    """Una habitación hoy: su estado físico, su situación y las reservas que la tocan.

    ``ocupante`` es el huésped alojado (reserva en curso). ``llegada`` es la
    reserva que debe ingresar hoy o ya debió hacerlo. En un día de cambio de
    huésped puede haber las dos: uno sale y otro llega.
    """
    id: int
    numero: str
    piso: int
    tipo: str
    capacidad: int
    estado_limpieza: EstadoLimpieza
    fuera_de_servicio: bool
    situacion: SituacionHabitacion
    ocupante: ReservaEnTablero | None
    llegada: ReservaEnTablero | None


class ResumenTablero(BaseModel):
    """Indicadores del día para la cabecera del tablero."""
    habitaciones: int
    en_servicio: int
    ocupadas: int
    ocupacion: Decimal      # porcentaje de las habitaciones en servicio, con un decimal
    llegadas: int           # pendientes de ingresar (hoy o atrasadas)
    salidas: int            # huéspedes que deben salir hoy o ya debieron
    libres_listas: int      # libres hoy, sin llegada pendiente, en servicio y limpias
    por_limpiar: int        # sucias o en limpieza
    fuera_de_servicio: int


class Tablero(BaseModel):
    """Situación de todas las habitaciones en la fecha de hoy (hora de Costa Rica)."""
    fecha: date
    resumen: ResumenTablero
    habitaciones: list[HabitacionEnTablero]


# ---------------------------------------------------------------------
# Solicitudes de huéspedes: chat con el personal (etapa 3)
# ---------------------------------------------------------------------
CategoriaSolicitud = Literal["recepcion", "limpieza", "mantenimiento"]
EstadoSolicitud = Literal["abierta", "en_atencion", "resuelta"]


class NuevoMensaje(BaseModel):
    """Texto de un mensaje del chat: se recortan los espacios y no puede quedar vacío."""
    texto: str = Field(max_length=1000)

    @field_validator("texto")
    @classmethod
    def sin_espacios_sobrantes(cls, valor: str) -> str:
        """Quita espacios al inicio y al final; un mensaje vacío se rechaza con 422."""
        valor = valor.strip()
        if not valor:
            raise ValueError("Escriba un mensaje")
        return valor


class NuevoMensajeHuesped(NuevoMensaje):
    """Mensaje del huésped. El área solo cuenta si abre una solicitud nueva."""
    categoria: CategoriaSolicitud = "recepcion"


class CambioSolicitud(BaseModel):
    """Cambios del personal sobre una solicitud: tomarla, reasignarla a otra área o cambiar su estado."""
    estado: EstadoSolicitud | None = None
    categoria: CategoriaSolicitud | None = None
    tomar: bool = False


class MensajeSalida(BaseModel):
    """Un mensaje del chat. ``nombre`` es quién respondió del personal (nulo para el huésped)."""
    id: int
    solicitud_id: int
    autor: Literal["huesped", "personal"]
    nombre: str | None
    texto: str
    creado_en: datetime


class SolicitudSalida(BaseModel):
    """Una solicitud en la bandeja del personal, con la habitación, el huésped y el último mensaje."""
    id: int
    codigo_reserva: str
    habitacion: str
    nombre_huesped: str
    categoria: CategoriaSolicitud
    estado: EstadoSolicitud
    asignada_a: str | None
    simulada: bool
    creada_en: datetime
    actualizada_en: datetime
    pendiente_desde: datetime | None
    resuelta_en: datetime | None
    ultimo_mensaje: str | None


class BandejaSolicitudes(BaseModel):
    """Respuesta de la bandeja del personal.

    ``ahora`` es el punto de partida de la siguiente consulta incremental:
    la pantalla lo devuelve como ``desde`` y recibe solo lo que cambió.
    ``mensajes`` trae los mensajes nuevos de la conversación abierta.
    """
    ahora: datetime
    solicitudes: list[SolicitudSalida]
    mensajes: list[MensajeSalida]


class SolicitudBreve(BaseModel):
    """La solicitud abierta del huésped, si tiene una."""
    id: int
    categoria: CategoriaSolicitud
    estado: EstadoSolicitud


class ChatHuesped(BaseModel):
    """El chat de una estadía tal como lo ve el huésped."""
    codigo: str
    habitacion: str
    puede_escribir: bool          # solo durante la estadía (reserva en curso)
    abierta: SolicitudBreve | None
    mensajes: list[MensajeSalida]
