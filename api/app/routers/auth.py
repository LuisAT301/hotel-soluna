"""Registro de clientes e inicio de sesión."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import config, seguridad
from ..db import obtener_sesion
from ..dependencias import registrar, usuario_actual
from ..esquemas import RegistroCliente, Token, UsuarioSalida
from ..modelos import Usuario

router = APIRouter(prefix="/api/auth", tags=["autenticación"])

_CREDENCIALES_INVALIDAS = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Correo o contraseña incorrectos",
    headers={"WWW-Authenticate": "Bearer"},
)


@router.post("/registro", response_model=UsuarioSalida, status_code=201)
def registrar_cliente(datos: RegistroCliente, sesion: Session = Depends(obtener_sesion)):
    """RF-02: un cliente crea su propia cuenta. Siempre recibe el rol "cliente"."""
    if sesion.scalar(select(Usuario).where(Usuario.correo == datos.correo)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Ya existe una cuenta con ese correo")
    usuario = Usuario(
        nombre=datos.nombre,
        correo=datos.correo,
        hash_contrasena=seguridad.hashear(datos.contrasena),
        rol="cliente",
    )
    sesion.add(usuario)
    sesion.flush()
    registrar(sesion, usuario, "registro", "usuario", usuario.id)
    sesion.commit()
    return usuario


@router.post("/login", response_model=Token)
def iniciar_sesion(
    formulario: OAuth2PasswordRequestForm = Depends(),
    sesion: Session = Depends(obtener_sesion),
):
    """RF-01: el campo "username" del formulario es el correo."""
    correo = formulario.username.strip().lower()
    # FOR UPDATE: si llegan dos intentos a la vez, se cuentan los dos
    usuario = sesion.scalar(select(Usuario).where(Usuario.correo == correo).with_for_update())
    ahora = datetime.now(timezone.utc)

    if usuario and usuario.bloqueado_hasta and usuario.bloqueado_hasta > ahora:
        raise HTTPException(
            status.HTTP_423_LOCKED,
            "Cuenta bloqueada temporalmente por intentos fallidos. Intente más tarde.",
        )

    if not seguridad.verificar(usuario.hash_contrasena if usuario else None, formulario.password):
        if usuario:
            usuario.intentos_fallidos += 1
            if usuario.intentos_fallidos >= config.MAX_INTENTOS:
                usuario.bloqueado_hasta = ahora + timedelta(minutes=config.MINUTOS_BLOQUEO)
                usuario.intentos_fallidos = 0
                registrar(sesion, usuario, "bloqueo_cuenta", "usuario", usuario.id)
            else:
                registrar(sesion, usuario, "login_fallido", "usuario", usuario.id)
            sesion.commit()
        raise _CREDENCIALES_INVALIDAS

    if not usuario.activo:
        raise _CREDENCIALES_INVALIDAS

    usuario.intentos_fallidos = 0
    usuario.bloqueado_hasta = None
    if seguridad.hasher.check_needs_rehash(usuario.hash_contrasena):
        usuario.hash_contrasena = seguridad.hashear(formulario.password)
    registrar(sesion, usuario, "login", "usuario", usuario.id)
    sesion.commit()
    return Token(
        access_token=seguridad.crear_token(usuario.id, usuario.rol, usuario.nombre),
        rol=usuario.rol,
        nombre=usuario.nombre,
    )


@router.get("/yo", response_model=UsuarioSalida)
def quien_soy(usuario: Usuario = Depends(usuario_actual)):
    return usuario
