"""Dependencias compartidas: usuario actual y control de acceso por rol.

FastAPI ejecuta estas funciones antes de cada ruta que las declara con
``Depends``. Así la autenticación y los permisos se escriben una sola vez:

- ``usuario_actual``: lee el token de la cabecera Authorization y devuelve el usuario.
- ``requiere_rol``: además exige que el usuario tenga uno de los roles indicados.
- ``registrar``: agrega una entrada a la bitácora de auditoría.
"""
import socket

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from . import seguridad
from .db import obtener_sesion
from .modelos import RegistroBitacora, Usuario

# Extrae el token de la cabecera "Authorization: Bearer <token>".
# auto_error=False: si falta, devuelve None y el error lo decide usuario_actual.
oauth2 = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)

# Nombre del contenedor que atiende la solicitud (sirve para demostrar
# que Nginx reparte las solicitudes entre las réplicas)
REPLICA = socket.gethostname()

# Roles del personal del hotel; el resto de las cuentas son clientes
PERSONAL = ("recepcionista", "limpieza", "mantenimiento", "gerente")

# Misma respuesta para token ausente, alterado, vencido o de una cuenta
# desactivada: no se revela cuál de los casos ocurrió.
_NO_AUTENTICADO = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Debe iniciar sesión",
    headers={"WWW-Authenticate": "Bearer"},
)


def usuario_actual(
    token: str | None = Depends(oauth2),
    sesion: Session = Depends(obtener_sesion),
) -> Usuario:
    """Devuelve el usuario dueño del token, o responde 401.

    Pasos: 1) exige que haya token; 2) verifica su firma y vencimiento;
    3) busca al usuario en la base; 4) rechaza cuentas inexistentes o desactivadas.
    """
    if not token:
        raise _NO_AUTENTICADO
    try:
        datos = seguridad.leer_token(token)
    except jwt.PyJWTError:
        raise _NO_AUTENTICADO
    usuario = sesion.get(Usuario, int(datos["sub"]))
    # Se consulta la base en cada solicitud: si gerencia desactiva una
    # cuenta, su token deja de servir de inmediato.
    if usuario is None or not usuario.activo:
        raise _NO_AUTENTICADO
    return usuario


def requiere_rol(*roles: str):
    """Fabrica una dependencia que solo deja pasar a los roles indicados.

    Uso: Depends(requiere_rol("recepcionista", "gerente")).
    Primero autentica con ``usuario_actual`` (401 si falla) y luego compara el
    rol (403 si no está permitido). El rol se lee de la base, no del token,
    así que un cambio de rol se aplica de inmediato.
    """

    def verificar(usuario: Usuario = Depends(usuario_actual)) -> Usuario:
        if usuario.rol not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Su rol no tiene permiso para esta acción")
        return usuario

    return verificar


def registrar(
    sesion: Session,
    usuario: Usuario | None,
    accion: str,
    entidad: str,
    entidad_id: str | int | None = None,
    **detalle,
) -> None:
    """Agrega un registro a la bitácora dentro de la misma transacción.

    Como se agrega a la misma sesión que la operación auditada, ambos se
    guardan juntos con el commit, o ninguno: nunca queda una acción sin su
    registro. ``usuario`` es None en acciones de sistemas externos (la OTA) o
    anónimas (suscripción). El detalle incluye la réplica que atendió.
    """
    sesion.add(
        RegistroBitacora(
            usuario_id=usuario.id if usuario else None,
            accion=accion,
            entidad=entidad,
            entidad_id=str(entidad_id) if entidad_id is not None else None,
            detalle={**detalle, "replica": REPLICA},
        )
    )
