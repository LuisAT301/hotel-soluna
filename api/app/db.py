"""Conexión a PostgreSQL con SQLAlchemy 2.0."""
from collections.abc import Iterator

from sqlalchemy import URL, create_engine
from sqlalchemy.orm import Session, sessionmaker

from . import config

url = URL.create(
    "postgresql+psycopg",
    username=config.DB_USER,
    password=config.DB_PASSWORD,  # URL.create escapa caracteres especiales
    host=config.DB_HOST,
    port=config.DB_PORT,
    database=config.DB_NAME,
)

# Cada réplica de la API mantiene un grupo pequeño de conexiones.
# Con 3 réplicas: 3 x (5 + 5) = 30 conexiones como máximo, por debajo
# del límite de 100 que PostgreSQL trae por defecto.
engine = create_engine(url, pool_size=5, max_overflow=5, pool_pre_ping=True)
SesionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def obtener_sesion() -> Iterator[Session]:
    """Dependencia de FastAPI: una sesión por solicitud."""
    with SesionLocal() as sesion:
        yield sesion
