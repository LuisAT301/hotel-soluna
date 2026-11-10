"""Pruebas del bloque 1: autenticación, roles, disponibilidad, reservas y bitácora."""
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import httpx
import psycopg
import pytest

from .conftest import iniciar_sesion

ENTRADA = date.today() + timedelta(days=40)
SALIDA = ENTRADA + timedelta(days=3)


def _reserva(habitacion_id=1, entrada=ENTRADA, salida=SALIDA, **extra):
    return {"habitacion_id": habitacion_id, "fecha_entrada": str(entrada),
            "fecha_salida": str(salida), "personas": 2, **extra}


# ------------------------------------------------------------- salud
def test_salud_indica_replica(cliente_http):
    r = cliente_http.get("/api/salud")
    assert r.status_code == 200
    assert r.json()["base_de_datos"] == "ok"
    assert r.headers["X-Replica"] == r.json()["replica"]


# ------------------------------------------------------------- autenticación
def test_contrasenas_guardadas_con_argon2id(admin_db):
    hashes = [h for (h,) in admin_db.execute("SELECT hash_contrasena FROM usuarios")]
    assert hashes and all(h.startswith("$argon2id$") for h in hashes)
    assert all(os.environ["DEMO_PASSWORD"] not in h for h in hashes)


def test_login_incorrecto_es_generico(cliente_http):
    malo = cliente_http.post("/api/auth/login", data={"username": "recepcion@soluna.test", "password": "x" * 9})
    inexistente = cliente_http.post("/api/auth/login", data={"username": "nadie@soluna.test", "password": "x" * 9})
    assert malo.status_code == inexistente.status_code == 401
    assert malo.json() == inexistente.json()


def test_bloqueo_tras_cinco_intentos(cliente_http):
    for _ in range(5):
        cliente_http.post("/api/auth/login", data={"username": "recepcion@soluna.test", "password": "incorrecta1"})
    # Ni siquiera la contraseña correcta entra mientras dure el bloqueo
    r = cliente_http.post("/api/auth/login", data={
        "username": "recepcion@soluna.test", "password": os.environ["DEMO_PASSWORD"]})
    assert r.status_code == 423


def test_token_alterado_es_rechazado(cliente_http):
    cabecera = iniciar_sesion(cliente_http, "gerencia@soluna.test")
    alterado = {"Authorization": cabecera["Authorization"][:-3] + "abc"}
    assert cliente_http.get("/api/auth/yo", headers=alterado).status_code == 401


def test_registro_de_cliente_siempre_es_cliente(cliente_http):
    r = cliente_http.post("/api/auth/registro", json={
        "nombre": "Ana Mora", "correo": "Ana@Correo.test", "contrasena": "Segura2026", "rol": "gerente"})
    assert r.status_code == 201
    assert r.json()["rol"] == "cliente" and r.json()["correo"] == "ana@correo.test"


def test_usuario_desactivado_pierde_acceso(cliente_http):
    gerente = iniciar_sesion(cliente_http, "gerencia@soluna.test")
    limpieza = iniciar_sesion(cliente_http, "limpieza@soluna.test")
    id_limpieza = next(u["id"] for u in cliente_http.get("/api/usuarios", headers=gerente).json()
                       if u["rol"] == "limpieza")
    assert cliente_http.post(f"/api/usuarios/{id_limpieza}/desactivar", headers=gerente).status_code == 200
    assert cliente_http.get("/api/habitaciones", headers=limpieza).status_code == 401


# ------------------------------------------------------------- roles
@pytest.mark.parametrize("correo, ruta, esperado", [
    ("limpieza@soluna.test", "/api/reservas", 403),
    ("mantenimiento@soluna.test", "/api/bitacora", 403),
    ("cliente@soluna.test", "/api/usuarios", 403),
    ("cliente@soluna.test", "/api/habitaciones", 403),
    ("recepcion@soluna.test", "/api/usuarios", 403),
    ("recepcion@soluna.test", "/api/reservas", 200),
    ("gerencia@soluna.test", "/api/bitacora", 200),
])
def test_permisos_por_rol(cliente_http, correo, ruta, esperado):
    assert cliente_http.get(ruta, headers=iniciar_sesion(cliente_http, correo)).status_code == esperado


def test_sin_token_no_hay_acceso(cliente_http):
    assert cliente_http.get("/api/reservas").status_code == 401


def test_limpieza_actualiza_estado(cliente_http):
    r = cliente_http.patch("/api/habitaciones/1/limpieza", json={"estado": "sucia"},
                           headers=iniciar_sesion(cliente_http, "limpieza@soluna.test"))
    assert r.status_code == 200 and r.json()["estado_limpieza"] == "sucia"


# ------------------------------------------------------------- disponibilidad y reservas
def test_disponibilidad_y_precio_por_temporada(cliente_http):
    entrada = date(date.today().year + 1, 4, 29)  # 2 noches de alta (abril) y 1 de baja (mayo)
    r = cliente_http.get("/api/disponibilidad", params={
        "entrada": str(entrada), "salida": str(entrada + timedelta(days=3)), "personas": 2})
    assert r.status_code == 200
    estandar = next(h for h in r.json() if h["tipo"] == "estándar")
    assert float(estandar["total"]) == 120 + 120 + 85
    assert len(r.json()) == 46


def test_capacidad_filtra_habitaciones(cliente_http):
    r = cliente_http.get("/api/disponibilidad", params={
        "entrada": str(ENTRADA), "salida": str(SALIDA), "personas": 4})
    assert {h["tipo"] for h in r.json()} == {"suite"}


def test_fechas_invalidas(cliente_http):
    ayer = date.today() - timedelta(days=1)
    r = cliente_http.get("/api/disponibilidad", params={"entrada": str(ayer), "salida": str(SALIDA)})
    assert r.status_code == 422


def test_reserva_de_cliente_queda_pendiente_de_pago(cliente_http):
    r = cliente_http.post("/api/reservas", json=_reserva(),
                          headers=iniciar_sesion(cliente_http, "cliente@soluna.test"))
    assert r.status_code == 201
    assert r.json()["estado"] == "pendiente_pago" and r.json()["canal"] == "web"
    assert r.json()["codigo"].startswith("SOL-")


def test_no_hay_sobreventa(cliente_http):
    recepcion = iniciar_sesion(cliente_http, "recepcion@soluna.test")
    huesped = {"nombre_huesped": "Luis Pérez", "correo_huesped": "luis@correo.test"}
    assert cliente_http.post("/api/reservas", json=_reserva(**huesped), headers=recepcion).status_code == 201
    # Traslape parcial: rechazada
    traslape = _reserva(entrada=ENTRADA + timedelta(days=2), salida=SALIDA + timedelta(days=2), **huesped)
    assert cliente_http.post("/api/reservas", json=traslape, headers=recepcion).status_code == 409
    # Entra el mismo día en que sale el anterior: permitida
    contigua = _reserva(entrada=SALIDA, salida=SALIDA + timedelta(days=2), **huesped)
    assert cliente_http.post("/api/reservas", json=contigua, headers=recepcion).status_code == 201
    # La habitación ya no aparece disponible en esas fechas
    libres = cliente_http.get("/api/disponibilidad", params={"entrada": str(ENTRADA), "salida": str(SALIDA)}).json()
    assert 1 not in [h["habitacion_id"] for h in libres]


def test_cancelar_libera_la_habitacion(cliente_http):
    cliente = iniciar_sesion(cliente_http, "cliente@soluna.test")
    codigo = cliente_http.post("/api/reservas", json=_reserva(), headers=cliente).json()["codigo"]
    assert cliente_http.post(f"/api/reservas/{codigo}/cancelar", headers=cliente).json()["estado"] == "cancelada"
    otra = iniciar_sesion(cliente_http, "recepcion@soluna.test")
    r = cliente_http.post("/api/reservas", json=_reserva(nombre_huesped="Otro Huésped",
                                                         correo_huesped="otro@correo.test"), headers=otra)
    assert r.status_code == 201


def test_cliente_no_ve_reservas_ajenas(cliente_http):
    recepcion = iniciar_sesion(cliente_http, "recepcion@soluna.test")
    codigo = cliente_http.post("/api/reservas", json=_reserva(
        nombre_huesped="Huésped Ajeno", correo_huesped="ajeno@correo.test"), headers=recepcion).json()["codigo"]
    cliente = iniciar_sesion(cliente_http, "cliente@soluna.test")
    assert cliente_http.get(f"/api/reservas/{codigo}", headers=cliente).status_code == 404
    assert cliente_http.post(f"/api/reservas/{codigo}/cancelar", headers=cliente).status_code == 404
    assert cliente_http.get("/api/reservas", headers=cliente).json() == []


def test_bitacora_registra_quien_hizo_que(cliente_http):
    cliente = iniciar_sesion(cliente_http, "cliente@soluna.test")
    codigo = cliente_http.post("/api/reservas", json=_reserva(), headers=cliente).json()["codigo"]
    cliente_http.post(f"/api/reservas/{codigo}/cancelar", headers=cliente)
    registros = cliente_http.get("/api/bitacora", headers=iniciar_sesion(cliente_http, "gerencia@soluna.test")).json()
    acciones = [(r["accion"], r["entidad_id"]) for r in registros]
    assert ("crear_reserva", codigo) in acciones and ("cancelar_reserva", codigo) in acciones
    assert all("replica" in r["detalle"] for r in registros)


# ------------------------------------------------------------- base de datos
def test_api_no_puede_borrar_ni_alterar(admin_db):
    """El usuario de la API (app_hotel) no puede borrar reservas ni tocar la bitácora."""
    conexion = psycopg.connect(host=os.environ["DB_HOST"], port=os.environ["DB_PORT"], dbname="hotel",
                               user="app_hotel", password=os.environ["DB_PASSWORD"], autocommit=True)
    with conexion:
        for sql in ("DELETE FROM reservas", "DELETE FROM bitacora", "UPDATE bitacora SET accion = 'x'",
                    "DROP TABLE tarifas", "TRUNCATE habitaciones"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conexion.execute(sql)


# ------------------------------------------------------------- concurrencia (servidor real, 2 procesos)
@pytest.fixture(scope="module")
def servidor():
    proceso = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", "8123", "--workers", "2", "--log-level", "warning"],
        cwd=os.path.dirname(os.path.dirname(__file__)))
    for _ in range(50):
        try:
            if httpx.get("http://127.0.0.1:8123/api/salud").status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.2)
    yield "http://127.0.0.1:8123"
    proceso.terminate()
    proceso.wait()


def test_reservas_simultaneas_solo_una_gana(servidor):
    """Diez solicitudes al mismo tiempo por la misma habitación y fechas: solo una se acepta."""
    token = httpx.post(f"{servidor}/api/auth/login", data={
        "username": "recepcion@soluna.test", "password": os.environ["DEMO_PASSWORD"]}).json()["access_token"]
    cabecera = {"Authorization": f"Bearer {token}"}
    cuerpo = _reserva(habitacion_id=5, nombre_huesped="Carrera", correo_huesped="carrera@correo.test")

    def reservar(_):
        return httpx.post(f"{servidor}/api/reservas", json=cuerpo, headers=cabecera, timeout=30).status_code

    with ThreadPoolExecutor(max_workers=10) as hilos:
        codigos = sorted(hilos.map(reservar, range(10)))
    assert codigos.count(201) == 1 and codigos.count(409) == 9, codigos
