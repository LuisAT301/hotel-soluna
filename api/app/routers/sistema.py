"""Salud del servicio y bitácora."""
import logging

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ..db import obtener_sesion
from ..dependencias import REPLICA, requiere_rol
from ..esquemas import BitacoraSalida
from ..modelos import RegistroBitacora, Usuario

router = APIRouter(prefix="/api", tags=["sistema"])
registro = logging.getLogger("soluna.salud")
_aviso_esquema_dado = False


@router.get("/salud")
def salud(respuesta: Response, sesion: Session = Depends(obtener_sesion)):
    """Lo consultan el healthcheck de Docker y Nginx. Indica qué réplica respondió."""
    global _aviso_esquema_dado
    try:
        sesion.execute(text("SELECT 1"))
        base = "ok"
        # Una base creada antes del bloque 3 no tiene la tabla de pagos: la API
        # enciende, pero las reservas fallan. Se avisa en vez de fallar en silencio.
        if sesion.execute(text("SELECT to_regclass('public.pagos')")).scalar() is None:
            base = "desactualizada: ejecute docker compose down -v y vuelva a levantar"
            if not _aviso_esquema_dado:
                registro.error("La base de datos no tiene las tablas del bloque 3. "
                               "Ejecute 'docker compose down -v' y luego 'docker compose up --build -d'.")
                _aviso_esquema_dado = True
    except Exception:  # noqa: BLE001 - cualquier falla de la base cuenta como caída
        base = "sin conexión"
        respuesta.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"estado": "ok" if base == "ok" else "degradado", "base_de_datos": base, "replica": REPLICA}


@router.get("/bitacora", response_model=list[BitacoraSalida], tags=["sistema"])
def bitacora(
    limite: int = 100,
    sesion: Session = Depends(obtener_sesion),
    _: Usuario = Depends(requiere_rol("gerente")),
):
    """RNF-12: solo gerencia consulta la bitácora."""
    consulta = select(RegistroBitacora).order_by(RegistroBitacora.id.desc()).limit(min(limite, 500))
    return sesion.scalars(consulta).all()
