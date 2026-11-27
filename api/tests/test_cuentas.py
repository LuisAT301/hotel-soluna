"""Cuenta de la habitación: consumos, pagos en caja, cobro al salir y factura final.

Las estadías se crean directamente en la base (ver test_gestion). Por
omisión son de recepción: el hospedaje se paga en el hotel y suma a la cuenta.
"""
import os
from datetime import timedelta
from decimal import Decimal

import httpx
import psycopg
import pytest

from app.routers.reservas import hoy

from .conftest import iniciar_sesion
from .test_gestion import reserva_bd

IVA = Decimal("0.13")


def iva(monto):
    """IVA del 13 % con redondeo comercial a céntimos, como la API."""
    from decimal import ROUND_HALF_UP
    return (Decimal(monto) * IVA).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def alojada(admin_db, codigo="SOL-CUENT1", habitacion_id=1, estado="en_curso", canal="recepcion",
            correo="huesped@correo.test"):
    """Una estadía de tres noches que empezó ayer; devuelve su total de hospedaje (sin IVA)."""
    dia = hoy()
    reserva_bd(admin_db, codigo, dia - timedelta(days=1), dia + timedelta(days=2), estado, habitacion_id,
               correo=correo)
    admin_db.execute("UPDATE reservas SET canal = %s WHERE codigo = %s", (canal, codigo))
    return Decimal(admin_db.execute("SELECT total FROM reservas WHERE codigo = %s", (codigo,)).fetchone()[0])


def servicio(admin_db, nombre):
    """Id de un servicio del catálogo por su nombre."""
    return admin_db.execute("SELECT id FROM servicios WHERE nombre = %s", (nombre,)).fetchone()[0]


def cargar(cliente_http, cabecera, codigo, **cuerpo):
    """Carga un consumo a la cuenta de la reserva."""
    return cliente_http.post(f"/api/gestion/reservas/{codigo}/cargos", headers=cabecera, json=cuerpo)


def cuenta(cliente_http, cabecera, codigo):
    """Estado de cuenta visto por el personal."""
    r = cliente_http.get(f"/api/gestion/reservas/{codigo}/cuenta", headers=cabecera)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture
def recepcion(cliente_http):
    """Sesión de recepción."""
    return iniciar_sesion(cliente_http, "recepcion@soluna.test")


@pytest.fixture
def gerencia(cliente_http):
    """Sesión de gerencia."""
    return iniciar_sesion(cliente_http, "gerencia@soluna.test")


# ------------------------------------------------------------- cargos
def test_cargo_del_catalogo_y_estado_de_cuenta(cliente_http, admin_db, recepcion):
    """Dos cervezas del catálogo suman al hospedaje; el IVA se calcula sobre todo lo que se cobra en el hotel."""
    hospedaje = alojada(admin_db)
    r = cargar(cliente_http, recepcion, "SOL-CUENT1", servicio_id=servicio(admin_db, "Cerveza nacional"), cantidad=2)
    assert r.status_code == 201, r.text
    c = r.json()
    subtotal = hospedaje + Decimal("8.00")
    assert c["hospedaje_modalidad"] == "en_hotel" and Decimal(c["hospedaje"]) == hospedaje
    assert Decimal(c["consumos"]) == Decimal("8.00") and Decimal(c["subtotal"]) == subtotal
    assert Decimal(c["impuesto"]) == iva(subtotal) and Decimal(c["por_pagar"]) == subtotal + iva(subtotal)
    cargo = c["cargos"][0]
    assert (cargo["descripcion"], cargo["cantidad"], cargo["categoria"], cargo["creado_por"]) == \
        ("Cerveza nacional", 2, "bar", "Recepción Soluna")
    accion = admin_db.execute("SELECT detalle FROM bitacora WHERE accion = 'cargar_consumo'").fetchone()[0]
    assert accion["total"] == "8.00"


def test_cambiar_el_precio_no_altera_lo_ya_cargado(cliente_http, admin_db, recepcion, gerencia):
    """El cargo copia el precio del momento: si gerencia lo sube después, lo cargado no cambia."""
    alojada(admin_db)
    nuevo = cliente_http.post("/api/servicios", headers=gerencia, json={
        "nombre": "Prueba Kayak", "categoria": "tours", "precio": "20.00"}).json()
    cargar(cliente_http, recepcion, "SOL-CUENT1", servicio_id=nuevo["id"])
    assert cliente_http.patch(f"/api/servicios/{nuevo['id']}", headers=gerencia,
                              json={"precio": "30.00"}).status_code == 200
    c = cargar(cliente_http, recepcion, "SOL-CUENT1", servicio_id=nuevo["id"]).json()
    assert [Decimal(x["total"]) for x in c["cargos"]] == [Decimal("20.00"), Decimal("30.00")]


def test_cargo_libre(cliente_http, admin_db, recepcion):
    """Un cargo fuera del catálogo exige descripción, categoría y precio."""
    alojada(admin_db)
    assert cargar(cliente_http, recepcion, "SOL-CUENT1", descripcion="Botella de vino").status_code == 422
    r = cargar(cliente_http, recepcion, "SOL-CUENT1", descripcion="  Botella de vino  tinto ", categoria="restaurante",
               precio_unitario="35.50", cantidad=1)
    assert r.status_code == 201 and r.json()["cargos"][0]["descripcion"] == "Botella de vino tinto"
    for malo in ({"precio_unitario": "-1"}, {"precio_unitario": "1.234"}, {"cantidad": 0}, {"cantidad": 100}):
        cuerpo = {"descripcion": "Algo", "categoria": "otros", "precio_unitario": "5", **malo}
        assert cargar(cliente_http, recepcion, "SOL-CUENT1", **cuerpo).status_code == 422


@pytest.mark.parametrize("estado", ["confirmada", "finalizada", "cancelada"])
def test_solo_se_carga_a_huespedes_alojados(cliente_http, admin_db, recepcion, estado):
    """Antes del ingreso, después de la salida o si se canceló, no se cargan consumos (409)."""
    alojada(admin_db, estado=estado)
    r = cargar(cliente_http, recepcion, "SOL-CUENT1", servicio_id=servicio(admin_db, "Batido natural"))
    assert r.status_code == 409


def test_anular_un_cargo(cliente_http, admin_db, recepcion):
    """Un cargo anulado queda a la vista con su motivo y deja de sumar; no se anula dos veces."""
    alojada(admin_db)
    alojada(admin_db, "SOL-OTRA01", habitacion_id=2)
    c = cargar(cliente_http, recepcion, "SOL-CUENT1", servicio_id=servicio(admin_db, "Masaje relajante de 60 minutos")).json()
    cargo = c["cargos"][0]["id"]
    url = f"/api/gestion/reservas/SOL-CUENT1/cargos/{cargo}/anular"
    assert cliente_http.post(url, headers=recepcion, json={"motivo": "  "}).status_code == 422
    assert cliente_http.post(f"/api/gestion/reservas/SOL-OTRA01/cargos/{cargo}/anular", headers=recepcion,
                             json={"motivo": "Cargado a otra habitación"}).status_code == 404
    r = cliente_http.post(url, headers=recepcion, json={"motivo": "Cargado a otra habitación"})
    assert r.status_code == 200
    anulado = r.json()["cargos"][0]
    assert anulado["anulado"] is True and anulado["motivo_anulacion"] == "Cargado a otra habitación"
    assert Decimal(r.json()["consumos"]) == 0
    assert cliente_http.post(url, headers=recepcion, json={"motivo": "Otra vez"}).status_code == 409


# ------------------------------------------------------------- pagos y modalidades
def test_pagos_en_caja(cliente_http, admin_db, recepcion):
    """Un adelanto reduce lo pendiente; no se acepta más que el saldo; con saldo cero no hay pago que registrar."""
    hospedaje = alojada(admin_db)
    total = hospedaje + iva(hospedaje)
    url = "/api/gestion/reservas/SOL-CUENT1/pagos"
    r = cliente_http.post(url, headers=recepcion, json={"monto": "50.00", "metodo": "sinpe", "referencia": "  889 "})
    assert r.status_code == 201
    assert Decimal(r.json()["pagado"]) == 50 and Decimal(r.json()["por_pagar"]) == total - 50
    assert r.json()["pagos"][0]["referencia"] == "889" and r.json()["pagos"][0]["recibido_por"] == "Recepción Soluna"
    r = cliente_http.post(url, headers=recepcion, json={"monto": str(total), "metodo": "tarjeta"})
    assert r.status_code == 422 and "supera el saldo" in r.json()["detail"]
    r = cliente_http.post(url, headers=recepcion, json={"monto": str(total - 50), "metodo": "efectivo"})
    assert Decimal(r.json()["por_pagar"]) == 0
    assert cliente_http.post(url, headers=recepcion, json={"monto": "1", "metodo": "efectivo"}).status_code == 409
    assert cliente_http.post(url, headers=recepcion, json={"monto": "1", "metodo": "cheque"}).status_code == 422


@pytest.mark.parametrize("canal, modalidad", [("web", "en_linea"), ("ota", "agencia")])
def test_hospedaje_ya_pagado_no_suma(cliente_http, admin_db, recepcion, canal, modalidad):
    """Si el hospedaje se pagó en línea o lo paga la agencia, la cuenta solo tiene los consumos."""
    alojada(admin_db, canal=canal)
    c = cargar(cliente_http, recepcion, "SOL-CUENT1", servicio_id=servicio(admin_db, "Agua embotellada"), cantidad=4).json()
    assert c["hospedaje_modalidad"] == modalidad and Decimal(c["hospedaje"]) == 0
    assert Decimal(c["total"]) == Decimal("10.00") + iva("10.00")


# ------------------------------------------------------------- salida y factura final
def test_salida_cobra_el_saldo_y_emite_la_factura_final(cliente_http, admin_db, recepcion, simulador, correos):
    """Al salir se cobra exactamente lo pendiente y Hacienda acepta la factura con una línea por concepto."""
    hospedaje = alojada(admin_db)
    cargar(cliente_http, recepcion, "SOL-CUENT1", servicio_id=servicio(admin_db, "Cena del día"), cantidad=2)
    c = cargar(cliente_http, recepcion, "SOL-CUENT1", servicio_id=servicio(admin_db, "Cóctel de la casa")).json()
    cliente_http.post(f"/api/gestion/reservas/SOL-CUENT1/cargos/{c['cargos'][1]['id']}/anular", headers=recepcion,
                      json={"motivo": "No lo pidió"})
    cliente_http.post("/api/gestion/reservas/SOL-CUENT1/pagos", headers=recepcion,
                      json={"monto": "100.00", "metodo": "efectivo"})
    subtotal = hospedaje + Decimal("44.00")
    total = subtotal + iva(subtotal)

    url = "/api/gestion/reservas/SOL-CUENT1/check-out"
    r = cliente_http.post(url, headers=recepcion)
    assert r.status_code == 409 and str(total - 100) in r.json()["detail"]
    r = cliente_http.post(url, headers=recepcion, json={"metodo_pago": "tarjeta", "referencia": "VOUCHER-77"})
    assert r.status_code == 200 and r.json()["estado"] == "finalizada", r.text

    final = cuenta(cliente_http, recepcion, "SOL-CUENT1")
    assert Decimal(final["por_pagar"]) == 0 and Decimal(final["pagado"]) == total
    assert [(p["metodo"], Decimal(p["monto"])) for p in final["pagos"]] == [("efectivo", 100), ("tarjeta", total - 100)]
    factura = final["factura_final"]
    assert factura["estado"] == "aceptada" and Decimal(factura["total"]) == total
    lineas = admin_db.execute("SELECT lineas FROM facturas WHERE concepto = 'cuenta_final'").fetchone()[0]
    assert len(lineas) == 2 and lineas[0]["detalle"].startswith("Hospedaje") and lineas[1]["cantidad"] == 2
    enviado = httpx.get(f"{simulador}/hacienda/comprobantes/{factura['clave']}",
                        headers={"Authorization": f"Bearer {os.environ['SERVICIOS_LLAVE']}"}).json()
    assert Decimal(enviado["comprobante"]["total"]) == total
    cuerpo = correos[-1]["cuerpo"]
    assert "Resumen de su cuenta" in cuerpo and "2 x Cena del día" in cuerpo and factura["consecutivo"] in cuerpo
    assert "Cóctel" not in cuerpo                                         # lo anulado no aparece
    assert cargar(cliente_http, recepcion, "SOL-CUENT1", descripcion="Tarde", categoria="otros",
                  precio_unitario="1").status_code == 409                 # la cuenta quedó cerrada


def test_salida_sin_nada_que_cobrar(cliente_http, admin_db, recepcion):
    """Hospedaje pagado en línea y sin consumos: la salida no pide pago ni emite factura final."""
    alojada(admin_db, canal="web")
    r = cliente_http.post("/api/gestion/reservas/SOL-CUENT1/check-out", headers=recepcion)
    assert r.status_code == 200
    assert cuenta(cliente_http, recepcion, "SOL-CUENT1")["factura_final"] is None


def test_factura_del_hospedaje_y_factura_final_conviven(cliente_http, admin_db, recepcion):
    """Una reserva pagada en línea conserva su factura de hospedaje y suma la final de los consumos."""
    alojada(admin_db, canal="web")
    admin_db.execute("INSERT INTO facturas (reserva_id, clave, consecutivo, subtotal, impuesto, total) "
                     "SELECT id, repeat('5', 50), repeat('6', 20), 100, 13, 113 FROM reservas WHERE codigo = 'SOL-CUENT1'")
    cargar(cliente_http, recepcion, "SOL-CUENT1", servicio_id=servicio(admin_db, "Clase de surf de 2 horas"))
    r = cliente_http.post("/api/gestion/reservas/SOL-CUENT1/check-out", headers=recepcion,
                          json={"metodo_pago": "tarjeta"})
    assert r.status_code == 200 and r.json()["tiene_factura"] is True
    conceptos = sorted(f[0] for f in admin_db.execute("SELECT concepto FROM facturas"))
    assert conceptos == ["cuenta_final", "hospedaje"]
    hospedaje = cliente_http.get("/api/reservas/SOL-CUENT1/factura", headers=recepcion).json()
    assert hospedaje["consecutivo"] == "6" * 20


# ------------------------------------------------------------- huésped, catálogo y base
def test_el_huesped_ve_su_cuenta(cliente_http, admin_db, recepcion):
    """El titular ve su cuenta sin los nombres del personal; un ajeno recibe 404 y el personal usa su propia ruta."""
    alojada(admin_db, correo="cliente@soluna.test")
    cargar(cliente_http, recepcion, "SOL-CUENT1", servicio_id=servicio(admin_db, "Snack del minibar"))
    cliente = iniciar_sesion(cliente_http, "cliente@soluna.test")
    r = cliente_http.get("/api/reservas/SOL-CUENT1/cuenta", headers=cliente)
    assert r.status_code == 200 and r.json()["cargos"][0]["creado_por"] is None
    assert Decimal(r.json()["consumos"]) == Decimal("3.50")
    alojada(admin_db, "SOL-AJENA1", habitacion_id=2, correo="otra@correo.test")
    assert cliente_http.get("/api/reservas/SOL-AJENA1/cuenta", headers=cliente).status_code == 404
    assert cliente_http.get("/api/reservas/SOL-CUENT1/cuenta", headers=recepcion).status_code == 403


def test_catalogo_de_servicios(cliente_http, admin_db, recepcion, gerencia):
    """Recepción lee el catálogo; gerencia lo administra. Un servicio inactivo no se ofrece ni se carga."""
    catalogo = cliente_http.get("/api/servicios", headers=recepcion).json()
    assert len(catalogo) >= 19 and {"room_service", "spa", "tours"} <= {s["categoria"] for s in catalogo}
    nuevo = {"nombre": "Prueba Yoga al amanecer", "categoria": "spa", "precio": "18.00"}
    assert cliente_http.post("/api/servicios", headers=recepcion, json=nuevo).status_code == 403
    creado = cliente_http.post("/api/servicios", headers=gerencia, json=nuevo)
    assert creado.status_code == 201
    assert cliente_http.post("/api/servicios", headers=gerencia, json=nuevo).status_code == 409
    sid = creado.json()["id"]
    assert cliente_http.patch(f"/api/servicios/{sid}", headers=gerencia, json={"activo": False}).status_code == 200
    assert cliente_http.patch(f"/api/servicios/{sid}", headers=gerencia, json={"activo": False}).status_code == 422
    assert sid not in {s["id"] for s in cliente_http.get("/api/servicios", headers=recepcion).json()}
    assert sid in {s["id"] for s in cliente_http.get("/api/servicios?todos=true", headers=gerencia).json()}
    # "todos" solo vale para gerencia: recepción sigue viendo únicamente los activos
    assert sid not in {s["id"] for s in cliente_http.get("/api/servicios?todos=true", headers=recepcion).json()}
    alojada(admin_db)
    assert cargar(cliente_http, recepcion, "SOL-CUENT1", servicio_id=sid).status_code == 404


def test_la_api_no_puede_borrar_ni_alterar_la_cuenta(admin_db):
    """El usuario de la API no borra cargos, pagos ni servicios, ni cambia montos ya registrados."""
    conexion = psycopg.connect(host=os.environ["DB_HOST"], port=os.environ["DB_PORT"],
                               dbname=os.environ.get("DB_NAME", "hotel"), user="app_hotel",
                               password=os.environ["DB_PASSWORD"], autocommit=True)
    with conexion:
        for sql in ("DELETE FROM cargos", "DELETE FROM pagos_caja", "DELETE FROM servicios",
                    "UPDATE cargos SET precio_unitario = 1", "UPDATE cargos SET cantidad = 1",
                    "UPDATE pagos_caja SET monto = 1", "UPDATE facturas SET subtotal = 1",
                    "UPDATE facturas SET lineas = '[]'"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conexion.execute(sql)
