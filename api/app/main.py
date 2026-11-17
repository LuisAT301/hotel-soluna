"""Punto de entrada de la API del Hotel Soluna."""
from fastapi import FastAPI, Request

from .dependencias import REPLICA
from .routers import auth, habitaciones, ota, pagos, publico, reservas, sistema, usuarios

app = FastAPI(
    title="API Hotel Soluna",
    version="0.3.0",
    description="Prototipo del proyecto de Arquitectura de computación en la nube (ULACIT).",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

for modulo in (auth, usuarios, habitaciones, reservas, pagos, ota, publico, sistema):
    app.include_router(modulo.router)


@app.middleware("http")
async def cabecera_replica(request: Request, call_next):
    """Agrega la cabecera X-Replica para ver qué contenedor atendió cada solicitud."""
    respuesta = await call_next(request)
    respuesta.headers["X-Replica"] = REPLICA
    return respuesta
