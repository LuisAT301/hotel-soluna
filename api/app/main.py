"""Punto de entrada de la API del Hotel Soluna.

Crea la aplicación FastAPI, le conecta los diez grupos de rutas (routers) y
agrega un middleware que identifica la réplica que atendió cada solicitud.

El mismo objeto ``app`` se ejecuta de dos maneras:
- En Docker, uvicorn lo sirve dentro de cada una de las réplicas que Nginx balancea.
- En Vercel, la plataforma lo detecta en ``app/main.py`` y lo ejecuta como función sin servidor.
"""
from fastapi import FastAPI, Request

from .dependencias import REPLICA
from .routers import (auth, gestion, habitaciones, ota, pagos, publico, resenas, reservas, sistema,
                      usuarios)

# La documentación interactiva (Swagger) queda bajo /api para que Nginx y los
# reenvíos de Vercel, que solo dejan pasar /api/*, también la publiquen.
app = FastAPI(
    title="API Hotel Soluna",
    version="0.3.0",
    description="Prototipo del proyecto de Arquitectura de computación en la nube (ULACIT).",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

# Cada módulo de routers define sus rutas y los roles que pueden usarlas:
#   auth          inicio de sesión y registro de clientes
#   usuarios      administración de cuentas del personal (gerencia)
#   habitaciones  catálogo y estado de limpieza
#   reservas      disponibilidad, creación, consulta y cancelación
#   gestion       recepción: búsqueda, check-in, check-out y cambios de reservas
#   pagos         cobro con la pasarela, factura electrónica y reembolso
#   ota           avisos firmados de la agencia de viajes en línea
#   publico       datos del sitio (tipos de habitación) y suscripciones
#   resenas       reseñas verificadas de huéspedes con una estadía cumplida
#   sistema       salud del servicio y bitácora
for modulo in (auth, usuarios, habitaciones, reservas, gestion, pagos, ota, publico, resenas, sistema):
    app.include_router(modulo.router)


@app.middleware("http")
async def cabecera_replica(request: Request, call_next):
    """Agrega la cabecera X-Replica para ver qué contenedor atendió cada solicitud.

    Se ejecuta alrededor de todas las rutas: primero deja que la ruta responda
    y luego añade a la respuesta el nombre de la réplica. Con ella se demuestra
    el balanceo de carga de Nginx entre las réplicas de Docker.
    """
    respuesta = await call_next(request)
    respuesta.headers["X-Replica"] = REPLICA
    return respuesta
