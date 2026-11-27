"""Configuración leída del entorno.

Cada valor sensible puede llegar de dos formas:
  - NOMBRE_FILE: ruta a un archivo con el valor (secretos de Docker en /run/secrets).
  - NOMBRE:      el valor directo (útil solo para pruebas locales).
Así ninguna contraseña queda escrita en el código ni en el repositorio.

Los valores se leen una sola vez, al importar el módulo. Si falta una
variable obligatoria, la API no arranca y el error dice cuál falta: es
preferible a descubrirlo a mitad de una solicitud.
"""
import os
from decimal import Decimal
from email.utils import parseaddr
from pathlib import Path
from zoneinfo import ZoneInfo


def leer(nombre: str, defecto: str | None = None) -> str | None:
    """Devuelve el valor de una variable, con prioridad para NOMBRE_FILE.

    Si existe NOMBRE_FILE, lee el archivo al que apunta (sin espacios ni saltos
    de línea al final); si no, usa NOMBRE; si tampoco existe, ``defecto``.
    """
    ruta = os.getenv(f"{nombre}_FILE")
    if ruta:
        return Path(ruta).read_text(encoding="utf-8").strip()
    return os.getenv(nombre, defecto)


def obligatorio(nombre: str) -> str:
    """Como ``leer``, pero detiene el arranque si la variable falta o está vacía."""
    valor = leer(nombre)
    if not valor:
        raise RuntimeError(f"Falta la variable {nombre} (o {nombre}_FILE)")
    return valor


# ---------------------------------------------------------------------
# Base de datos
# ---------------------------------------------------------------------
DB_HOST = leer("DB_HOST", "db")
DB_PORT = int(leer("DB_PORT", "5432"))
DB_NAME = leer("DB_NAME", "hotel")
DB_USER = leer("DB_USER", "app_hotel")
DB_PASSWORD = obligatorio("DB_PASSWORD")
# Cifrado de la conexión. En la base local de Docker basta "prefer"; con una
# base en la nube (Supabase) se usa "require" para no aceptar conexiones sin TLS.
DB_SSLMODE = leer("DB_SSLMODE", "prefer")
# Conexiones por réplica de la API (fijas + extra en momentos de carga)
DB_POOL = int(leer("DB_POOL", "5"))
DB_POOL_EXTRA = int(leer("DB_POOL_EXTRA", "5"))
# "si" en Vercel: el pooler de Supabase en modo transacción (puerto 6543) reparte
# las conexiones entre todas las instancias de la función. Entonces la API no
# guarda conexiones abiertas ni usa sentencias preparadas (ese modo no las admite).
DB_MODO_TRANSACCION = (leer("DB_MODO_TRANSACCION", "no") or "no").lower() in ("si", "sí", "true", "1")

# ---------------------------------------------------------------------
# Sesiones y seguridad
# ---------------------------------------------------------------------
# Clave con la que se firman los tokens de sesión; quien la conozca podría
# fabricar tokens válidos, por eso es un secreto obligatorio.
JWT_SECRET = obligatorio("JWT_SECRET")
JWT_ALGORITMO = "HS256"
JWT_MINUTOS = int(leer("JWT_MINUTOS", "30"))

# Bloqueo de cuenta ante intentos fallidos de inicio de sesión
MAX_INTENTOS = int(leer("MAX_INTENTOS", "5"))
MINUTOS_BLOQUEO = int(leer("MINUTOS_BLOQUEO", "15"))

# Zona horaria del hotel: define "hoy" para las reservas y la fecha de las facturas
ZONA_HORARIA = ZoneInfo("America/Costa_Rica")

# ---------------------------------------------------------------------
# Servicios externos (bloque 3)
# ---------------------------------------------------------------------
# Simulador de la pasarela de pago y de Hacienda
SIMULADOR_URL = leer("SIMULADOR_URL", "http://simulador:8000")
SERVICIOS_LLAVE = obligatorio("SERVICIOS_LLAVE")   # llave de comercio ante la pasarela y Hacienda

# Secreto compartido con la OTA para verificar la firma de sus avisos
OTA_SECRETO = obligatorio("OTA_SECRETO")
OTA_TOLERANCIA_SEGUNDOS = 300   # avisos con más de 5 minutos se rechazan (repeticiones)

# Correo saliente. En el prototipo lo captura Mailpit y nunca llega a nadie.
SMTP_HOST = leer("SMTP_HOST", "mailpit")
SMTP_PORT = int(leer("SMTP_PORT", "1025"))
CORREO_REMITENTE = leer("CORREO_REMITENTE", "Hotel Soluna <reservas@soluna.test>")
# Dominio de los identificadores de mensaje (Message-ID): uno propio del hotel,
# no el del buzón remitente, que puede ser un Gmail que no envió el correo.
CORREO_DOMINIO = leer("CORREO_DOMINIO", "soluna.test")
# Para un servicio de envío real (Brevo en Vercel; también SendGrid, Amazon SES,
# Resend...): todos aceptan SMTP con usuario y contraseña sobre TLS. Mailpit no los necesita.
SMTP_USUARIO = leer("SMTP_USUARIO")
SMTP_PASSWORD = leer("SMTP_PASSWORD")      # admite SMTP_PASSWORD_FILE (secreto de Docker)
SMTP_TLS = (leer("SMTP_TLS", "no") or "no").lower() in ("si", "sí", "true", "1")
# "no" en Vercel: lo que corre después de responder puede quedar congelado, así
# que el correo se envía dentro de la misma solicitud.
CORREO_SEGUNDO_PLANO = (leer("CORREO_SEGUNDO_PLANO", "si") or "si").lower() in ("si", "sí", "true", "1")
# "si" con un proveedor real: no se escribe a dominios reservados para pruebas
# (.test, .example, .invalid...), como los de las cuentas de demostración. Esos
# envíos rebotarían y dañarían la reputación del remitente.
CORREO_OMITIR_PRUEBA = (leer("CORREO_OMITIR_PRUEBA", "no") or "no").lower() in ("si", "sí", "true", "1")
# Tope de correos de bienvenida por hora: el formulario de suscripción es
# público y, sin límite, serviría para enviar correo masivo a nombre del hotel.
CORREO_BIENVENIDAS_HORA = int(leer("CORREO_BIENVENIDAS_HORA", "30"))

# ---------------------------------------------------------------------
# Facturación electrónica (datos ficticios del emisor)
# ---------------------------------------------------------------------
IVA = Decimal("0.13")
EMISOR_NOMBRE = "Hotel Soluna S.A."
EMISOR_CEDULA = "3101999999"   # cédula jurídica ficticia

# ---------------------------------------------------------------------
# Reservas que se pagan al llegar (por teléfono o en el mostrador)
# ---------------------------------------------------------------------
# Hora del día de entrada (hora de Costa Rica) hasta la que se garantizan la
# habitación y la tarifa acordada. Después, si el huésped no se presentó, el
# precio no se conserva y la estadía depende de la disponibilidad.
HORA_GARANTIA = int(leer("HORA_GARANTIA", "17"))
# Teléfono que aparece en los correos para cambios o cancelaciones (dato ficticio del prototipo)
TELEFONO_HOTEL = leer("TELEFONO_HOTEL", "+506 2656-0000")

# Pagos por SINPE Móvil o transferencia (etapa 6): datos que se muestran al cliente para pagar. Son
# de demostración; la interfaz advierte que no se envíe dinero real.
SINPE_HOTEL = leer("SINPE_HOTEL", "6000-0000")
CUENTA_HOTEL = leer("CUENTA_HOTEL", "CR00 0000 0000 0000 0000 00")
TITULAR_CUENTA_HOTEL = leer("TITULAR_CUENTA_HOTEL", "Hotel Soluna S. A. (cuenta de demostración)")
# Buzón que recibe el aviso de cada comprobante por revisar; por omisión, la dirección del remitente
CORREO_RECEPCION = leer("CORREO_RECEPCION", "") or parseaddr(CORREO_REMITENTE)[1]
