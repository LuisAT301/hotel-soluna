"""Dependencias compartidas: usuario actual y control de acceso por rol."""
import socket

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from . import seguridad
from .db import obtener_sesion
from .modelos import RegistroBitacora, Usuario

oauth2 = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)

# Nombre del contenedor que atiende la solicitud (sirve para demostrar
# que Nginx reparte las solicitudes entre las réplicas)
REPLICA = socket.gethostname()

PERSONAL = ("recepcionista", "limpieza", "mantenimiento", "gerente")

_NO_AUTENTICADO = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Debe iniciar sesión",
    headers={"WWW-Authenticate": "Bearer"},
)


def usuario_actual(
    token: str | None = Depends(oauth2),
    sesion: Session = Depends(obtener_sesion),
) -> Usuario:
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
    """Uso: Depends(requiere_rol("recepcionista", "gerente"))."""

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
    """Agrega un registro a la bitácora dentro de la misma transacción."""
    sesion.add(
        RegistroBitacora(
            usuario_id=usuario.id if usuario else None,
            accion=accion,
            entidad=entidad,
            entidad_id=str(entidad_id) if entidad_id is not None else None,
            detalle={**detalle, "replica": REPLICA},
        )
    )
