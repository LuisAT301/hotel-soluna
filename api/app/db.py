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
    query={"sslmode": config.DB_SSLMODE},
)

# Cada réplica de la API mantiene un grupo pequeño de conexiones.
# En Docker: 3 x (5 + 5) = 30 como máximo, por debajo del límite de 100 de
# PostgreSQL. En Supabase (plan gratuito) se baja a 3 x (2 + 2) = 12.
engine = create_engine(url, pool_size=config.DB_POOL, max_overflow=config.DB_POOL_EXTRA,
                       pool_pre_ping=True)
SesionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def obtener_sesion() -> Iterator[Session]:
    """Dependencia de FastAPI: una sesión por solicitud."""
    with SesionLocal() as sesion:
        yield sesion
