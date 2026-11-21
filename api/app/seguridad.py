"""Contraseñas (Argon2id) y tokens de acceso (JWT).

- Contraseñas: nunca se guardan en texto plano. Se guarda su hash Argon2id,
  que incluye una sal aleatoria y es costoso de calcular a propósito, para que
  un atacante con una copia de la base no pueda probar millones de claves.
- Sesiones: al iniciar sesión, la API entrega un token JWT firmado con
  JWT_SECRET. El navegador lo envía en cada solicitud y la API comprueba su
  firma y su vencimiento sin guardar estado (sirve en cualquier réplica).
"""
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
    """Devuelve el hash Argon2id de una contraseña, con su sal y parámetros incluidos."""
    return hasher.hash(contrasena)


def verificar(hash_guardado: str | None, contrasena: str) -> bool:
    """Indica si la contraseña corresponde al hash guardado.

    Si el usuario no existe (``hash_guardado`` es None), igual se verifica
    contra un hash falso: así la respuesta tarda lo mismo y nadie puede saber,
    midiendo el tiempo, si un correo está registrado. En ese caso el resultado
    siempre es False.
    """
    try:
        return hasher.verify(hash_guardado or _HASH_FALSO, contrasena) and hash_guardado is not None
    except (VerifyMismatchError, InvalidHashError):
        return False


def crear_token(usuario_id: int, rol: str, nombre: str) -> str:
    """Crea el token de sesión (JWT) de un usuario.

    Contenido: el identificador (sub), el rol y el nombre, que la interfaz usa
    para mostrar el menú correcto; la fecha de emisión (iat) y la de
    vencimiento (exp), JWT_MINUTOS después. Va firmado con HMAC-SHA256: si
    alguien altera cualquier dato, la firma deja de coincidir.
    """
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
    """Comprueba la firma y el vencimiento del token y devuelve su contenido.

    Lanza ``jwt.PyJWTError`` si el token está alterado, vencido o mal formado.
    """
    # Se fija el algoritmo para impedir tokens firmados con "none" u otro
    return jwt.decode(token, config.JWT_SECRET, algorithms=[config.JWT_ALGORITMO])
