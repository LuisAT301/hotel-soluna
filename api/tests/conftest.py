"""Configuración de las pruebas.

Se ejecutan contra una base PostgreSQL real, creada con los mismos scripts
de db/init. Variables necesarias (ver README, sección Pruebas):
    DB_HOST, DB_PORT, DB_PASSWORD   usuario app_hotel
    ADMIN_DB_PASSWORD               usuario postgres (solo para limpiar entre pruebas)
    JWT_SECRET, DEMO_PASSWORD
"""
import os

import psycopg
import pytest
from fastapi.testclient import TestClient


def _admin():
    return psycopg.connect(
        host=os.environ["DB_HOST"], port=os.environ.get("DB_PORT", "5432"), dbname="hotel",
        user="postgres", password=os.environ["ADMIN_DB_PASSWORD"], autocommit=True,
    )


@pytest.fixture(autouse=True)
def base_limpia():
    """Cada prueba empieza con el catálogo intacto, sin reservas y con las cuentas demo."""
    with _admin() as c:
        c.execute("TRUNCATE bitacora, reservas, usuarios RESTART IDENTITY CASCADE")
        c.execute("UPDATE habitaciones SET estado_limpieza = 'limpia', fuera_de_servicio = false")
    from app import seed
    seed.main()
    yield


@pytest.fixture
def cliente_http():
    from app.main import app
    with TestClient(app) as c:
        yield c


@pytest.fixture
def admin_db():
    with _admin() as c:
        yield c


def iniciar_sesion(cliente_http, correo, contrasena=None):
    r = cliente_http.post("/api/auth/login", data={
        "username": correo, "password": contrasena or os.environ["DEMO_PASSWORD"]})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}
