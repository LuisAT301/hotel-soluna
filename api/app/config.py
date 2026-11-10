"""Configuración leída del entorno.

Cada valor sensible puede llegar de dos formas:
  - NOMBRE_FILE: ruta a un archivo con el valor (secretos de Docker en /run/secrets).
  - NOMBRE:      el valor directo (útil solo para pruebas locales).
Así ninguna contraseña queda escrita en el código ni en el repositorio.
"""
import os
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

JWT_SECRET = obligatorio("JWT_SECRET")
JWT_ALGORITMO = "HS256"
JWT_MINUTOS = int(leer("JWT_MINUTOS", "30"))

# Bloqueo de cuenta ante intentos fallidos de inicio de sesión
MAX_INTENTOS = int(leer("MAX_INTENTOS", "5"))
MINUTOS_BLOQUEO = int(leer("MINUTOS_BLOQUEO", "15"))

ZONA_HORARIA = ZoneInfo("America/Costa_Rica")
