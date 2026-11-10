"""Configuración de las pruebas.

Se ejecutan contra una base PostgreSQL real, creada con los mismos scripts
de db/init. Variables necesarias (ver README, sección Pruebas):
    DB_HOST, DB_PORT, DB_PASSWORD   usuario app_hotel
    ADMIN_DB_PASSWORD               usuario postgres (solo para limpiar entre pruebas)
    JWT_SECRET, DEMO_PASSWORD
Las del bloque 3 tienen valores por defecto: las pruebas levantan su propio
simulador de servicios externos y reemplazan el envío de correos.
"""
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient

PUERTO_SIMULADOR = 8124
os.environ.setdefault("SERVICIOS_LLAVE", "llave-de-servicios-para-pruebas")
os.environ.setdefault("OTA_SECRETO", "secreto-de-la-ota-para-pruebas")
os.environ.setdefault("SIMULADOR_URL", f"http://127.0.0.1:{PUERTO_SIMULADOR}")


def _admin():
    return psycopg.connect(
        host=os.environ["DB_HOST"], port=os.environ.get("DB_PORT", "5432"), dbname="hotel",
        user="postgres", password=os.environ["ADMIN_DB_PASSWORD"], autocommit=True,
    )


@pytest.fixture(autouse=True)
def base_limpia():
    """Cada prueba empieza con el catálogo intacto, sin reservas y con las cuentas demo."""
    with _admin() as c:
        c.execute("TRUNCATE bitacora, pagos, facturas, reservas, usuarios RESTART IDENTITY CASCADE")
        c.execute("UPDATE habitaciones SET estado_limpieza = 'limpia', fuera_de_servicio = false")
        c.execute("ALTER SEQUENCE consecutivo_factura RESTART")
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


@pytest.fixture(scope="session")
def simulador():
    """El simulador real de servicios externos, en un proceso aparte."""
    carpeta = Path(__file__).resolve().parents[2] / "simulador"
    proceso = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "simulador:app", "--port", str(PUERTO_SIMULADOR),
         "--log-level", "warning"],
        cwd=carpeta, env={**os.environ, "API_URL": "http://127.0.0.1:9"})
    url = os.environ["SIMULADOR_URL"]
    for _ in range(50):
        try:
            if httpx.get(f"{url}/salud").status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.2)
    yield url
    proceso.terminate()
    proceso.wait()


@pytest.fixture(autouse=True)
def correos(monkeypatch):
    """Guarda en una lista los correos que la API enviaría, en lugar de enviarlos."""
    from app import correo
    enviados = []
    monkeypatch.setattr(correo, "enviar", lambda destino, asunto, cuerpo: enviados.append(
        {"destino": destino, "asunto": asunto, "cuerpo": cuerpo}))
    return enviados
