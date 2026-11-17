"""Configuración leída del entorno.

Cada valor sensible puede llegar de dos formas:
  - NOMBRE_FILE: ruta a un archivo con el valor (secretos de Docker en /run/secrets).
  - NOMBRE:      el valor directo (útil solo para pruebas locales).
Así ninguna contraseña queda escrita en el código ni en el repositorio.
"""
import os
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo


def leer(nombre: str, defecto: str | None = None) -> str | None:
    ruta = os.getenv(f"{nombre}_FILE")
    if ruta:
        return Path(ruta).read_text(encoding="utf-8").strip()
    return os.getenv(nombre, defecto)


def obligatorio(nombre: str) -> str:
    valor = leer(nombre)
    if not valor:
        raise RuntimeError(f"Falta la variable {nombre} (o {nombre}_FILE)")
    return valor


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

JWT_SECRET = obligatorio("JWT_SECRET")
JWT_ALGORITMO = "HS256"
JWT_MINUTOS = int(leer("JWT_MINUTOS", "30"))

# Bloqueo de cuenta ante intentos fallidos de inicio de sesión
MAX_INTENTOS = int(leer("MAX_INTENTOS", "5"))
MINUTOS_BLOQUEO = int(leer("MINUTOS_BLOQUEO", "15"))

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
# Para un servicio de envío real (Brevo, SendGrid, Amazon SES, Resend...): casi
# todos aceptan SMTP con usuario y contraseña sobre TLS. Mailpit no los necesita.
SMTP_USUARIO = leer("SMTP_USUARIO")
SMTP_PASSWORD = leer("SMTP_PASSWORD")      # admite SMTP_PASSWORD_FILE (secreto de Docker)
SMTP_TLS = (leer("SMTP_TLS", "no") or "no").lower() in ("si", "sí", "true", "1")

# Facturación electrónica (datos ficticios del emisor)
IVA = Decimal("0.13")
EMISOR_NOMBRE = "Hotel Soluna S.A."
EMISOR_CEDULA = "3101999999"   # cédula jurídica ficticia
