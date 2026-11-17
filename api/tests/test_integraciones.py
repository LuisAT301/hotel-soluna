"""Pruebas del bloque 3: pasarela de pago, factura electrónica, OTA y correos."""
import hashlib
import hmac
import json
import os
import time
from datetime import date, timedelta
from decimal import Decimal

import httpx
import pytest

from .conftest import iniciar_sesion

ENTRADA = date.today() + timedelta(days=50)
SALIDA = ENTRADA + timedelta(days=2)

APROBADA = "4242 4242 4242 4242"
RECHAZADA = "4000 0000 0000 0002"
PASARELA_CAIDA = "4000 0000 0000 0119"


@pytest.fixture(autouse=True)
def _simulador(simulador):
    """Todas las pruebas de este archivo necesitan el simulador encendido."""
    return simulador


def tokenizar(simulador, numero=APROBADA):
    """Lo que hace el navegador: enviar la tarjeta a la pasarela, no a la API."""
    r = httpx.post(f"{simulador}/pasarela/tokens", json={
        "numero": numero, "titular": "Cliente de Prueba", "vencimiento": "12/39", "cvv": "123"})
    assert r.status_code == 201, r.text
    return r.json()["token"]


def reserva_pendiente(cliente_http, habitacion_id=1):
    cliente = iniciar_sesion(cliente_http, "cliente@soluna.test")
    r = cliente_http.post("/api/reservas", headers=cliente, json={
        "habitacion_id": habitacion_id, "fecha_entrada": str(ENTRADA), "fecha_salida": str(SALIDA),
        "personas": 2})
    assert r.status_code == 201, r.text
    return r.json(), cliente


# ------------------------------------------------------------- pasarela de pago
def test_pago_aprobado_confirma_factura_y_avisa(cliente_http, simulador, admin_db, correos):
    reserva, cliente = reserva_pendiente(cliente_http)
    r = cliente_http.post(f"/api/reservas/{reserva['codigo']}/pago", headers=cliente,
                          json={"token": tokenizar(simulador)})
    assert r.status_code == 200, r.text
    pago = r.json()
    assert pago["reserva"]["estado"] == "confirmada" and pago["reserva"]["tiene_factura"]
    assert pago["marca"] == "Visa" and pago["ultimos4"] == "4242"

    # Monto cobrado = hospedaje + IVA del 13 %
    subtotal = Decimal(reserva["total"])
    assert Decimal(pago["monto"]) == subtotal + (subtotal * Decimal("0.13")).quantize(Decimal("0.01"))

    factura = pago["factura"]
    assert factura["estado"] == "aceptada"
    assert len(factura["clave"]) == 50 and factura["clave"].startswith("506")
    assert factura["clave"][21:41] == factura["consecutivo"] == "00100001010000000001"
    assert Decimal(factura["total"]) == Decimal(pago["monto"])

    # Hacienda la tiene registrada
    assert httpx.get(f"{simulador}/hacienda/comprobantes/{factura['clave']}").status_code == 200
    # Se envió el correo de confirmación con la factura
    assert correos and correos[-1]["destino"] == "cliente@soluna.test"
    assert factura["clave"] in correos[-1]["cuerpo"]
    # La base del hotel no guarda el número de tarjeta
    filas = admin_db.execute("SELECT pagos::text FROM pagos").fetchall()
    assert filas and all("4242424242424242" not in fila for (fila,) in filas)


def test_pago_rechazado_deja_la_reserva_pendiente(cliente_http, simulador, admin_db):
    reserva, cliente = reserva_pendiente(cliente_http)
    r = cliente_http.post(f"/api/reservas/{reserva['codigo']}/pago", headers=cliente,
                          json={"token": tokenizar(simulador, RECHAZADA)})
    assert r.status_code == 402 and "fondos insuficientes" in r.json()["detail"]
    assert cliente_http.get(f"/api/reservas/{reserva['codigo']}", headers=cliente).json()["estado"] == "pendiente_pago"
    assert admin_db.execute("SELECT estado FROM pagos").fetchall() == [("rechazado",)]
    # Con otra tarjeta sí se puede pagar
    r = cliente_http.post(f"/api/reservas/{reserva['codigo']}/pago", headers=cliente,
                          json={"token": tokenizar(simulador)})
    assert r.status_code == 200


def test_pasarela_caida_no_confirma(cliente_http, simulador, admin_db):
    reserva, cliente = reserva_pendiente(cliente_http)
    r = cliente_http.post(f"/api/reservas/{reserva['codigo']}/pago", headers=cliente,
                          json={"token": tokenizar(simulador, PASARELA_CAIDA)})
    assert r.status_code == 503
    assert cliente_http.get(f"/api/reservas/{reserva['codigo']}", headers=cliente).json()["estado"] == "pendiente_pago"
    assert admin_db.execute("SELECT count(*) FROM pagos").fetchone() == (0,)


def test_no_se_paga_dos_veces(cliente_http, simulador):
    reserva, cliente = reserva_pendiente(cliente_http)
    ruta = f"/api/reservas/{reserva['codigo']}/pago"
    assert cliente_http.post(ruta, headers=cliente, json={"token": tokenizar(simulador)}).status_code == 200
    assert cliente_http.post(ruta, headers=cliente, json={"token": tokenizar(simulador)}).status_code == 409


def test_token_de_un_solo_uso(cliente_http, simulador):
    token = tokenizar(simulador)
    primera, cliente = reserva_pendiente(cliente_http, habitacion_id=1)
    segunda, _ = reserva_pendiente(cliente_http, habitacion_id=2)
    assert cliente_http.post(f"/api/reservas/{primera['codigo']}/pago", headers=cliente,
                             json={"token": token}).status_code == 200
    r = cliente_http.post(f"/api/reservas/{segunda['codigo']}/pago", headers=cliente, json={"token": token})
    assert r.status_code == 422


def test_pasarela_exige_la_llave_del_comercio(simulador):
    """Nadie más que la API del hotel puede cobrar con un token."""
    r = httpx.post(f"{simulador}/pasarela/cobros", headers={"Idempotency-Key": "intento-ajeno"},
                   json={"token": tokenizar(simulador), "monto": "10.00", "referencia": "x"})
    assert r.status_code == 401


def test_tarjeta_invalida_se_rechaza_en_la_pasarela(simulador):
    r = httpx.post(f"{simulador}/pasarela/tokens", json={
        "numero": "4242 4242 4242 4241", "titular": "X Y", "vencimiento": "12/39", "cvv": "123"})
    assert r.status_code == 422


def test_cliente_no_paga_reservas_ajenas(cliente_http, simulador):
    recepcion = iniciar_sesion(cliente_http, "recepcion@soluna.test")
    codigo = cliente_http.post("/api/reservas", headers=recepcion, json={
        "habitacion_id": 3, "fecha_entrada": str(ENTRADA), "fecha_salida": str(SALIDA), "personas": 1,
        "nombre_huesped": "Otra Persona", "correo_huesped": "otra@correo.test"}).json()["codigo"]
    cliente = iniciar_sesion(cliente_http, "cliente@soluna.test")
    r = cliente_http.post(f"/api/reservas/{codigo}/pago", headers=cliente, json={"token": tokenizar(simulador)})
    assert r.status_code == 404


def test_cancelar_reserva_pagada_reembolsa(cliente_http, simulador, admin_db, correos):
    reserva, cliente = reserva_pendiente(cliente_http)
    cliente_http.post(f"/api/reservas/{reserva['codigo']}/pago", headers=cliente,
                      json={"token": tokenizar(simulador)})
    r = cliente_http.post(f"/api/reservas/{reserva['codigo']}/cancelar", headers=cliente)
    assert r.status_code == 200 and r.json()["estado"] == "cancelada"
    tipos = admin_db.execute("SELECT tipo, estado FROM pagos ORDER BY id").fetchall()
    assert tipos == [("cobro", "aprobado"), ("reembolso", "aprobado")]
    assert "reembols" in correos[-1]["cuerpo"]


def test_api_no_puede_alterar_pagos_ni_montos_de_factura(admin_db):
    import psycopg
    conexion = psycopg.connect(host=os.environ["DB_HOST"], port=os.environ["DB_PORT"], dbname=os.environ.get("DB_NAME", "hotel"),
                               user="app_hotel", password=os.environ["DB_PASSWORD"], autocommit=True)
    with conexion:
        for sql in ("UPDATE pagos SET monto = 0", "DELETE FROM pagos",
                    "UPDATE facturas SET total = 0", "DELETE FROM facturas"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conexion.execute(sql)


# ------------------------------------------------------------- OTA
def aviso_ota(cliente_http, datos, secreto=None, fecha=None):
    cuerpo = json.dumps(datos).encode()
    fecha = fecha or int(time.time())
    firma = "sha256=" + hmac.new((secreto or os.environ["OTA_SECRETO"]).encode(),
                                 f"{fecha}.".encode() + cuerpo, hashlib.sha256).hexdigest()
    return cliente_http.post("/api/integraciones/ota/reservas", content=cuerpo, headers={
        "Content-Type": "application/json", "X-OTA-Fecha": str(fecha), "X-OTA-Firma": firma})


def _datos_ota(referencia="OTA-0001", tipo="suite"):
    return {"referencia": referencia, "tipo": tipo, "fecha_entrada": str(ENTRADA),
            "fecha_salida": str(SALIDA), "personas": 2, "nombre_huesped": "Emma Dubois",
            "correo_huesped": "emma@viajero.test"}


def test_ota_crea_reserva_confirmada(cliente_http, correos):
    r = aviso_ota(cliente_http, _datos_ota())
    assert r.status_code == 201, r.text
    assert r.json()["canal"] == "ota" and r.json()["estado"] == "confirmada" and r.json()["tipo"] == "suite"
    assert correos[-1]["destino"] == "emma@viajero.test"
    # Aparece en la bitácora sin usuario (la creó un sistema externo)
    gerente = iniciar_sesion(cliente_http, "gerencia@soluna.test")
    registro = next(b for b in cliente_http.get("/api/bitacora", headers=gerente).json()
                    if b["accion"] == "reserva_ota")
    assert registro["usuario_id"] is None and registro["detalle"]["referencia"] == "OTA-0001"


def test_ota_repetida_no_duplica(cliente_http):
    primera = aviso_ota(cliente_http, _datos_ota())
    segunda = aviso_ota(cliente_http, _datos_ota())
    assert (primera.status_code, segunda.status_code) == (201, 200)
    assert primera.json()["codigo"] == segunda.json()["codigo"]


@pytest.mark.parametrize("cambio", ["secreto", "cuerpo", "fecha"])
def test_ota_rechaza_avisos_no_autenticos(cliente_http, cambio):
    if cambio == "secreto":
        r = aviso_ota(cliente_http, _datos_ota(), secreto="otro-secreto")
    elif cambio == "fecha":
        r = aviso_ota(cliente_http, _datos_ota(), fecha=int(time.time()) - 3600)
    else:
        # Firma válida, pero alguien cambió el cuerpo en el camino
        cuerpo = json.dumps(_datos_ota()).encode()
        fecha = int(time.time())
        firma = "sha256=" + hmac.new(os.environ["OTA_SECRETO"].encode(), f"{fecha}.".encode() + cuerpo,
                                     hashlib.sha256).hexdigest()
        r = cliente_http.post("/api/integraciones/ota/reservas", content=cuerpo.replace(b"suite", b"superior"),
                              headers={"Content-Type": "application/json", "X-OTA-Fecha": str(fecha),
                                       "X-OTA-Firma": firma})
    assert r.status_code == 401


def test_ota_sin_disponibilidad(cliente_http):
    for i in range(8):  # el hotel tiene 8 suites
        assert aviso_ota(cliente_http, _datos_ota(f"OTA-S{i:03d}")).status_code == 201
    r = aviso_ota(cliente_http, _datos_ota("OTA-S999"))
    assert r.status_code == 409


# ------------------------------------------------------------- correo de recepción
def test_reserva_de_recepcion_envia_confirmacion(cliente_http, correos):
    recepcion = iniciar_sesion(cliente_http, "recepcion@soluna.test")
    r = cliente_http.post("/api/reservas", headers=recepcion, json={
        "habitacion_id": 4, "fecha_entrada": str(ENTRADA), "fecha_salida": str(SALIDA), "personas": 2,
        "nombre_huesped": "Luis Pérez", "correo_huesped": "luis@correo.test"})
    assert r.status_code == 201
    assert correos[-1]["destino"] == "luis@correo.test" and r.json()["codigo"] in correos[-1]["asunto"]
