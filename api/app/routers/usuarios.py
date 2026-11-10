"""RF-17: gestión de cuentas del personal (solo gerencia)."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import seguridad
from ..db import obtener_sesion
from ..dependencias import registrar, requiere_rol
from ..esquemas import NuevoUsuario, UsuarioSalida
from ..modelos import Usuario

router = APIRouter(prefix="/api/usuarios", tags=["usuarios"])
solo_gerencia = requiere_rol("gerente")


@router.get("", response_model=list[UsuarioSalida])
def listar(sesion: Session = Depends(obtener_sesion), _: Usuario = Depends(solo_gerencia)):
    return sesion.scalars(select(Usuario).order_by(Usuario.rol, Usuario.nombre)).all()


@router.post("", response_model=UsuarioSalida, status_code=201)
def crear(
    datos: NuevoUsuario,
    sesion: Session = Depends(obtener_sesion),
    gerente: Usuario = Depends(solo_gerencia),
):
    """Cada empleado recibe su propia cuenta (RNF-07: sin cuentas compartidas)."""
    if sesion.scalar(select(Usuario).where(Usuario.correo == datos.correo)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Ya existe una cuenta con ese correo")
    usuario = Usuario(
        nombre=datos.nombre,
        correo=datos.correo,
        hash_contrasena=seguridad.hashear(datos.contrasena),
        rol=datos.rol,
    )
    sesion.add(usuario)
    sesion.flush()
    registrar(sesion, gerente, "crear_usuario", "usuario", usuario.id, rol=datos.rol)
    sesion.commit()
    return usuario


@router.post("/{usuario_id}/desactivar", response_model=UsuarioSalida)
def desactivar(
    usuario_id: int,
    sesion: Session = Depends(obtener_sesion),
    gerente: Usuario = Depends(solo_gerencia),
):
    usuario = sesion.get(Usuario, usuario_id)
    if usuario is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Usuario no encontrado")
    if usuario.id == gerente.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No puede desactivar su propia cuenta")
    usuario.activo = False
    registrar(sesion, gerente, "desactivar_usuario", "usuario", usuario.id)
    sesion.commit()
    return usuario
