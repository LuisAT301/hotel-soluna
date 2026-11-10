"""Contraseñas (Argon2id) y tokens de acceso (JWT)."""
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from . import config

# Argon2id con los parámetros mínimos que recomienda OWASP
# (19 MiB de memoria, 2 iteraciones, 1 hilo). Valores más altos protegen
# más, pero en una prueba de carga con 200 usuarios agotarían la memoria
# de una laptop.
hasher = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)

# Hash de una contraseña cualquiera, para que el tiempo de respuesta sea
# parecido exista o no el correo (evita adivinar qué cuentas existen).
_HASH_FALSO = hasher.hash("contrasena-que-no-existe")


def hashear(contrasena: str) -> str:
    return hasher.hash(contrasena)


def verificar(hash_guardado: str | None, contrasena: str) -> bool:
    try:
        return hasher.verify(hash_guardado or _HASH_FALSO, contrasena) and hash_guardado is not None
    except (VerifyMismatchError, InvalidHashError):
        return False


def crear_token(usuario_id: int, rol: str, nombre: str) -> str:
    ahora = datetime.now(timezone.utc)
    datos = {
        "sub": str(usuario_id),
        "rol": rol,
        "nombre": nombre,
        "iat": ahora,
        "exp": ahora + timedelta(minutes=config.JWT_MINUTOS),
    }
    return jwt.encode(datos, config.JWT_SECRET, algorithm=config.JWT_ALGORITMO)


def leer_token(token: str) -> dict:
    # Se fija el algoritmo para impedir tokens firmados con "none" u otro
    return jwt.decode(token, config.JWT_SECRET, algorithms=[config.JWT_ALGORITMO])
