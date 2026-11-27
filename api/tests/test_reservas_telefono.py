"""Reservas que recepción toma por teléfono o en el mostrador, y que se pagan al llegar.

Comprueban el teléfono de contacto, el canal, el correo con el monto a pagar
a la llegada y la hora de garantía (17:00 del día de entrada), y cómo esa
garantía se ve en el tablero.
"""
from datetime import date, datetime, timedelta
from decimal import Decimal

import psycopg
import pytest

from app import config
from app.routers.reservas import garantia_hasta, hoy

from .conftest import iniciar_sesion
from .test_gestion import H101, H102, precio, reserva_bd

ENTRADA = date.today() + timedelta(days=30)
SALIDA = ENTRADA + timedelta(days=2)


def por_telefono(**extra):
    """Cuerpo de una reserva tomada por teléfono, con valores por defecto."""
    return {"habitacion_id": H101, "fecha_entrada": str(ENTRADA), "fecha_salida": str(SALIDA), "personas": 2,
            "nombre_huesped": "Ana Mora Solís", "correo_huesped": "Ana@Correo.test",
            "telefono_huesped": " +506  8888-1234 ", "canal": "telefono", **extra}


@pytest.fixture
def recepcion(cliente_http):
    """Sesión de recepción."""
    return iniciar_sesion(cliente_http, "recepcion@soluna.test")


def test_reserva_por_telefono_y_su_correo(cliente_http, admin_db, recepcion, correos):
    """La reserva nace confirmada, por el canal teléfono, con el teléfono limpio y la garantía a las 17:00.

    El huésped recibe un correo con el código, la habitación, el teléfono, el
    monto con IVA a pagar al llegar y la política de no presentación.
    """
    r = cliente_http.post("/api/reservas", headers=recepcion, json=por_telefono())
    assert r.status_code == 201, r.text
    reserva = r.json()
    assert (reserva["canal"], reserva["estado"], reserva["telefono_huesped"]) == \
        ("telefono", "confirmada", "+506 8888-1234")
    garantia = datetime.fromisoformat(reserva["garantia_hasta"])
    assert garantia.date() == ENTRADA and garantia.hour == 17 and garantia.utcoffset() == timedelta(hours=-6)

    correo = correos[-1]
    subtotal = precio(1, ENTRADA, SALIDA)
    impuesto = (subtotal * Decimal("0.13")).quantize(Decimal("0.01"))
    assert correo["destino"] == "ana@correo.test"
    assert correo["asunto"] == f"Reserva confirmada {reserva['codigo']}: pago a su llegada"
    for texto in (reserva["codigo"], "Habitación: 101 (estándar)", "Teléfono de contacto: +506 8888-1234",
                  "Hospedaje (2 noches)", f"Total: USD {subtotal + impuesto}", "5:00 p. m.",
                  f"{ENTRADA:%d/%m/%Y}", "no podremos conservar el precio acordado",
                  "dependerá de las habitaciones disponibles", config.TELEFONO_HOTEL):
        assert texto in correo["cuerpo"], texto
    detalle = admin_db.execute("SELECT detalle FROM bitacora WHERE accion = 'crear_reserva'").fetchone()[0]
    assert detalle["canal"] == "telefono"


def test_reserva_en_el_mostrador_tambien_se_paga_al_llegar(cliente_http, recepcion, correos):
    """Sin canal, la reserva del personal es de mostrador: teléfono opcional, mismo correo y garantía."""
    cuerpo = por_telefono(canal=None, telefono_huesped=None)
    r = cliente_http.post("/api/reservas", headers=recepcion, json=cuerpo)
    assert r.status_code == 201 and r.json()["canal"] == "recepcion" and r.json()["telefono_huesped"] is None
    assert r.json()["garantia_hasta"] is not None
    assert "pago a su llegada" in correos[-1]["asunto"] and "Teléfono de contacto" not in correos[-1]["cuerpo"]


@pytest.mark.parametrize("telefono", [None, "", "   "])
def test_por_telefono_exige_un_numero(cliente_http, recepcion, telefono):
    """Una reserva por teléfono sin número de contacto se rechaza con 422."""
    r = cliente_http.post("/api/reservas", headers=recepcion, json=por_telefono(telefono_huesped=telefono))
    assert r.status_code == 422 and "teléfono" in r.text


@pytest.mark.parametrize("telefono", ["abc12345678", "1234567", "+506 8888-1234 ext 5", "1" * 16, "88888888+"])
def test_telefono_con_formato_invalido(cliente_http, recepcion, telefono):
    """Letras, menos de 8 o más de 15 dígitos, o un "+" fuera del inicio: 422."""
    r = cliente_http.post("/api/reservas", headers=recepcion, json=por_telefono(telefono_huesped=telefono))
    assert r.status_code == 422


@pytest.mark.parametrize("telefono", ["88881234", "(506) 8888-1234", "+1 212 555 0100"])
def test_telefonos_validos(cliente_http, recepcion, telefono):
    """Formatos comunes de Costa Rica e internacionales se aceptan."""
    r = cliente_http.post("/api/reservas", headers=recepcion, json=por_telefono(telefono_huesped=telefono))
    assert r.status_code == 201, r.text


def test_el_cliente_no_elige_canal_ni_tiene_garantia(cliente_http):
    """Un cliente que reserva en línea queda en el canal web aunque pida otro; su reserva no tiene garantía."""
    cliente = iniciar_sesion(cliente_http, "cliente@soluna.test")
    r = cliente_http.post("/api/reservas", headers=cliente, json=por_telefono(canal="telefono"))
    assert r.status_code == 201
    assert (r.json()["canal"], r.json()["estado"], r.json()["garantia_hasta"]) == ("web", "pendiente_pago", None)


def test_garantia_solo_para_pago_al_llegar_sin_ingreso():
    """La garantía aplica a recepción y teléfono mientras la reserva está confirmada; no a web ni a la OTA."""
    dia = date(2026, 12, 20)
    assert garantia_hasta("telefono", "confirmada", dia).isoformat() == "2026-12-20T17:00:00-06:00"
    assert garantia_hasta("recepcion", "confirmada", dia) is not None
    for canal, estado in (("web", "confirmada"), ("ota", "confirmada"), ("telefono", "en_curso"),
                          ("telefono", "cancelada"), ("recepcion", "finalizada")):
        assert garantia_hasta(canal, estado, dia) is None


def test_el_tablero_marca_la_garantia_vencida(cliente_http, admin_db, recepcion):
    """Una llegada por teléfono de ayer sin ingreso tiene la garantía vencida; una de mañana, todavía no."""
    dia = hoy()
    reserva_bd(admin_db, "SOL-AYER01", dia - timedelta(days=1), dia + timedelta(days=2), habitacion_id=H101)
    reserva_bd(admin_db, "SOL-WEB001", dia - timedelta(days=1), dia + timedelta(days=2), habitacion_id=H102)
    admin_db.execute("UPDATE reservas SET canal = 'telefono' WHERE codigo = 'SOL-AYER01'")
    admin_db.execute("UPDATE reservas SET canal = 'web' WHERE codigo = 'SOL-WEB001'")
    tablero = {h["numero"]: h for h in cliente_http.get("/api/gestion/tablero", headers=recepcion).json()["habitaciones"]}
    assert tablero["101"]["llegada"]["garantia_vencida"] is True
    assert tablero["102"]["llegada"]["garantia_vencida"] is False      # pagada en línea: sin garantía que vencer

    detalle = cliente_http.get("/api/gestion/reservas/SOL-AYER01", headers=recepcion).json()
    assert detalle["reserva"]["garantia_hasta"].startswith(str(dia - timedelta(days=1)))


def test_modificar_repite_monto_y_garantia(cliente_http, recepcion, correos):
    """Si se cambian las fechas de una reserva por teléfono, el correo trae el monto nuevo y la nueva garantía."""
    codigo = cliente_http.post("/api/reservas", headers=recepcion, json=por_telefono()).json()["codigo"]
    nueva_entrada, nueva_salida = ENTRADA + timedelta(days=5), ENTRADA + timedelta(days=8)
    r = cliente_http.patch(f"/api/gestion/reservas/{codigo}", headers=recepcion, json={
        "fecha_entrada": str(nueva_entrada), "fecha_salida": str(nueva_salida)})
    assert r.status_code == 200, r.text
    cuerpo = correos[-1]["cuerpo"]
    assert correos[-1]["asunto"] == f"Reserva modificada {codigo}"
    assert "Hospedaje (3 noches)" in cuerpo and f"{nueva_entrada:%d/%m/%Y}, su día de llegada" in cuerpo


def test_la_base_rechaza_telefonos_y_canales_invalidos(admin_db):
    """La base revisa también el formato del teléfono y los canales admitidos."""
    base = ("INSERT INTO reservas (codigo, habitacion_id, nombre_huesped, correo_huesped, telefono_huesped, "
            "personas, fecha_entrada, fecha_salida, canal, estado, total) VALUES "
            "('SOL-BASE01', 1, 'X', 'x@correo.test', %s, 2, current_date + 40, current_date + 42, %s, "
            "'confirmada', 100)")
    for telefono, canal in (("llámeme", "telefono"), ("88881234", "fax")):
        with pytest.raises(psycopg.errors.CheckViolation):
            admin_db.execute(base, (telefono, canal))
