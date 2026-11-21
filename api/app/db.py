"""Conexión a PostgreSQL con SQLAlchemy 2.0.

Construye el motor de base de datos (engine) a partir de la configuración y
ofrece ``obtener_sesion``, la dependencia que entrega a cada ruta de la API
una sesión propia. La sesión se cierra sola al terminar la solicitud, así que
ninguna conexión queda abierta por descuido.

El motor se configura de dos formas, según dónde corre la API:
- Docker (base local o Supabase en modo sesión): grupo de conexiones persistentes por réplica.
- Vercel (Supabase en modo transacción): sin grupo propio; el pooler de Supabase reparte las conexiones.
"""
from collections.abc import Iterator

from sqlalchemy import URL, create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from . import config

# Cadena de conexión armada por partes: URL.create escapa los caracteres
# especiales de la contraseña. "sslmode" decide si la conexión exige TLS
# (require en Supabase; disable dentro de la red interna de Docker).
url = URL.create(
    "postgresql+psycopg",
    username=config.DB_USER,
    password=config.DB_PASSWORD,  # URL.create escapa caracteres especiales
    host=config.DB_HOST,
    port=config.DB_PORT,
    database=config.DB_NAME,
    query={"sslmode": config.DB_SSLMODE},
)

if config.DB_MODO_TRANSACCION:
    # Vercel: cada solicitud toma una conexión del pooler de Supabase y la
    # devuelve al terminar; sin sentencias preparadas, que ese modo no admite.
    engine = create_engine(url, poolclass=NullPool, connect_args={"prepare_threshold": None})
else:
    # Docker: cada réplica de la API mantiene un grupo pequeño de conexiones.
    # Base local: 3 x (5 + 5) = 30 como máximo, por debajo del límite de 100 de
    # PostgreSQL. Supabase en modo sesión: 3 x (1 + 1) = 6 por computadora.
    # pool_pre_ping comprueba cada conexión antes de usarla y descarta las que
    # se cortaron (por ejemplo, si la base se reinició).
    engine = create_engine(url, pool_size=config.DB_POOL, max_overflow=config.DB_POOL_EXTRA,
                           pool_pre_ping=True)

# Fábrica de sesiones. expire_on_commit=False conserva los datos de los objetos
# después del commit, para poder devolverlos en la respuesta sin otra consulta.
SesionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def obtener_sesion() -> Iterator[Session]:
    """Dependencia de FastAPI: una sesión por solicitud.

    FastAPI ejecuta el código hasta ``yield``, entrega la sesión a la ruta y,
    cuando la respuesta termina, sale del bloque ``with``, que cierra la sesión
    y devuelve la conexión al grupo. Si la ruta no hizo commit, los cambios
    pendientes se descartan.
    """
    with SesionLocal() as sesion:
        yield sesion
