"""Simulador en modo Vercel (PANEL_PUBLICO=no): el panel y la OTA piden la llave."""
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

PUERTO = 8125
LLAVE = {"Authorization": f"Bearer {os.environ['SERVICIOS_LLAVE']}"}


@pytest.fixture(scope="module")
def simulador_protegido():
    carpeta = Path(__file__).resolve().parents[2] / "simulador"
    entorno = {**os.environ, "PANEL_PUBLICO": "no", "API_URL": "http://127.0.0.1:9"}
    entorno.pop("SIM_DB_HOST", None)  # en memoria: aquí solo importa la protección
    proceso = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "simulador:app", "--port", str(PUERTO), "--log-level", "warning"],
        cwd=carpeta, env=entorno)
    url = f"http://127.0.0.1:{PUERTO}"
    for _ in range(50):
        try:
            if httpx.get(f"{url}/salud").status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.2)
    yield url
    proceso.terminate()
    proceso.wait()


def test_panel_y_ota_piden_la_llave(simulador_protegido):
    url = simulador_protegido
    assert httpx.get(f"{url}/panel").status_code == 401
    assert httpx.post(f"{url}/ota/enviar").status_code == 401
    assert httpx.get(f"{url}/hacienda/comprobantes/x").status_code == 401
    assert httpx.get(f"{url}/panel", headers=LLAVE).status_code == 200


def test_sin_documentacion_publica(simulador_protegido):
    assert httpx.get(f"{simulador_protegido}/docs").status_code == 404
    assert httpx.get(f"{simulador_protegido}/openapi.json").status_code == 404


def test_tokenizar_sigue_abierto_para_el_navegador(simulador_protegido):
    r = httpx.post(f"{simulador_protegido}/pasarela/tokens", json={
        "numero": "4242 4242 4242 4242", "titular": "Cliente", "vencimiento": "12/39", "cvv": "123"})
    assert r.status_code == 201 and r.json()["ultimos4"] == "4242"
