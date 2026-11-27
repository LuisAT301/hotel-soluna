"""Tablero de habitaciones: la situación de cada habitación hoy y los indicadores del día.

Usa las mismas ayudas que las pruebas de recepción para crear reservas con
fechas pasadas o en curso directamente en la base.
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import event

from app.db import engine
from app.routers.reservas import hoy

from .conftest import iniciar_sesion
from .test_gestion import H101, H102, H103, limpieza, reserva_bd


@pytest.fixture
def recepcion(cliente_http):
    """Cabecera de sesión de la cuenta de recepción."""
    return iniciar_sesion(cliente_http, "recepcion@soluna.test")


def ver_tablero(cliente_http, cabecera):
    """Pide el tablero y lo devuelve con las habitaciones indexadas por número."""
    r = cliente_http.get("/api/gestion/tablero", headers=cabecera)
    assert r.status_code == 200, r.text
    datos = r.json()
    return datos, {h["numero"]: h for h in datos["habitaciones"]}


@pytest.mark.parametrize("correo, esperado", [
    ("recepcion@soluna.test", 200), ("gerencia@soluna.test", 200),
    ("cliente@soluna.test", 403), ("limpieza@soluna.test", 403), ("mantenimiento@soluna.test", 403),
])
def test_solo_recepcion_y_gerencia_ven_el_tablero(cliente_http, correo, esperado):
    """El tablero muestra nombres de huéspedes: es exclusivo de recepción y gerencia."""
    cabecera = iniciar_sesion(cliente_http, correo)
    assert cliente_http.get("/api/gestion/tablero", headers=cabecera).status_code == esperado
    assert cliente_http.get("/api/gestion/tablero").status_code == 401


def test_situacion_de_cada_habitacion(cliente_http, admin_db, recepcion):
    """Cada combinación de reservas y estado de la habitación da la situación esperada."""
    dia = hoy()
    d = lambda n: dia + timedelta(days=n)  # noqa: E731
    reserva_bd(admin_db, "SOL-OCUPA1", d(-2), d(2), "en_curso", H101)
    reserva_bd(admin_db, "SOL-SALE01", d(-3), d(0), "en_curso", H102)        # día de cambio:
    reserva_bd(admin_db, "SOL-ENTRA1", d(0), d(2), "confirmada", H102)       # uno sale y otro llega
    reserva_bd(admin_db, "SOL-LLEGA1", d(0), d(3), "confirmada", H103)
    reserva_bd(admin_db, "SOL-ATRAS1", d(-1), d(2), "confirmada", 4)         # 104
    limpieza(admin_db, 5, "limpia", fuera_de_servicio=True)                  # 105
    limpieza(admin_db, 6, "sucia")                                           # 106
    reserva_bd(admin_db, "SOL-TARDE1", d(-4), d(-1), "en_curso", 7)          # 107: debió salir ayer
    reserva_bd(admin_db, "SOL-PENDI1", d(0), d(1), "pendiente_pago", 8)      # 108
    reserva_bd(admin_db, "SOL-FUTUR1", d(5), d(7), "confirmada", 9)          # 109: aún no
    reserva_bd(admin_db, "SOL-CANCE1", d(0), d(2), "cancelada", 10)          # 110: no cuenta
    limpieza(admin_db, 11, "limpia", fuera_de_servicio=True)                 # 111, con llegada hoy
    reserva_bd(admin_db, "SOL-AVERI1", d(0), d(2), "confirmada", 11)

    datos, h = ver_tablero(cliente_http, recepcion)
    assert datos["fecha"] == str(dia)
    situaciones = {n: h[n]["situacion"] for n in
                   ("101", "102", "103", "104", "105", "106", "107", "108", "109", "110", "111")}
    assert situaciones == {
        "101": "ocupada", "102": "sale_hoy", "103": "llega_hoy", "104": "llegada_atrasada",
        "105": "fuera_de_servicio", "106": "libre", "107": "sale_hoy", "108": "llega_hoy",
        "109": "libre", "110": "libre", "111": "fuera_de_servicio",
    }
    assert h["101"]["ocupante"]["codigo"] == "SOL-OCUPA1" and h["101"]["llegada"] is None
    assert (h["102"]["ocupante"]["codigo"], h["102"]["llegada"]["codigo"]) == ("SOL-SALE01", "SOL-ENTRA1")
    assert h["108"]["llegada"]["estado"] == "pendiente_pago"
    assert h["111"]["llegada"]["codigo"] == "SOL-AVERI1"     # fuera de servicio, pero con alguien por llegar
    assert h["109"]["ocupante"] is None and h["109"]["llegada"] is None
    assert h["101"]["piso"] == 1 and h["101"]["tipo"] == "estándar"

    # 46 habitaciones, 2 fuera de servicio; 3 ocupadas de 44 en servicio = 6,8 %
    assert datos["resumen"] == {
        "habitaciones": 46, "en_servicio": 44, "ocupadas": 3, "ocupacion": "6.8",
        "llegadas": 5, "salidas": 2, "libres_listas": 37, "por_limpiar": 1, "fuera_de_servicio": 2,
    }


def test_el_tablero_sigue_el_dia_de_recepcion(cliente_http, admin_db, recepcion):
    """Ingreso y salida cambian la situación: llega hoy, ocupada, libre por limpiar."""
    dia = hoy()
    reserva_bd(admin_db, "SOL-CICLO1", dia, dia + timedelta(days=2))
    assert ver_tablero(cliente_http, recepcion)[1]["101"]["situacion"] == "llega_hoy"

    assert cliente_http.post("/api/gestion/reservas/SOL-CICLO1/check-in", headers=recepcion).status_code == 200
    datos, h = ver_tablero(cliente_http, recepcion)
    assert h["101"]["situacion"] == "ocupada" and datos["resumen"]["ocupadas"] == 1

    assert cliente_http.post("/api/gestion/reservas/SOL-CICLO1/check-out", headers=recepcion,
                             json={"metodo_pago": "efectivo"}).status_code == 200
    datos, h = ver_tablero(cliente_http, recepcion)
    assert h["101"]["situacion"] == "libre" and h["101"]["estado_limpieza"] == "sucia"
    assert datos["resumen"]["por_limpiar"] == 1 and datos["resumen"]["ocupacion"] == "0.0"


def contar_consultas(cliente_http, cabecera):
    """Cuántas sentencias SQL envía la API para armar el tablero."""
    sentencias = []

    def anotar(conexion, cursor, sentencia, *args):
        sentencias.append(sentencia)

    event.listen(engine, "before_cursor_execute", anotar)
    try:
        assert cliente_http.get("/api/gestion/tablero", headers=cabecera).status_code == 200
    finally:
        event.remove(engine, "before_cursor_execute", anotar)
    return len(sentencias)


def test_numero_fijo_de_consultas(cliente_http, admin_db, recepcion):
    """El tablero cuesta lo mismo a la base con 1 reserva que con 20: no consulta habitación por habitación."""
    dia = hoy()
    reserva_bd(admin_db, "SOL-UNA001", dia, dia + timedelta(days=1))
    con_una = contar_consultas(cliente_http, recepcion)
    for n in range(2, 21):
        reserva_bd(admin_db, f"SOL-VAR{n:03d}", dia - timedelta(days=1), dia + timedelta(days=2),
                   "en_curso", habitacion_id=n)
    assert contar_consultas(cliente_http, recepcion) == con_una
    assert con_una <= 3          # la sesión del usuario, las habitaciones y las reservas del día
    # 19 huéspedes alojados de 46 habitaciones en servicio = 41,3 %
    assert Decimal(ver_tablero(cliente_http, recepcion)[0]["resumen"]["ocupacion"]) == Decimal("41.3")
