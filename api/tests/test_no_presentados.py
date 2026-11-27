"""Liberación automática de las reservas no presentadas.

Una reserva que se paga al llegar (recepción o teléfono) se garantiza hasta
las 17:00 del día de entrada. Si a esa hora el huésped no registró su
ingreso ni pagó un adelanto, la función liberar_no_presentados de la base la
cancela: en Supabase la ejecuta pg_cron cada hora y recepción puede
ejecutarla a mano desde el panel. Las pruebas comprueban qué se libera, qué
no, la constancia en la bitácora, los permisos y que el tablero, el detalle
y el correo anuncian lo mismo que hace la función.
"""
from datetime import date, datetime, time, timedelta
from decimal import Decimal

import pytest

from app import config
from app.modelos import Reserva
from app.routers.reservas import bloque_pago_en_hotel, garantia_hasta, hoy

from .conftest import iniciar_sesion
from .test_gestion import H101, H102, H103, H201, reserva_bd

H104, H105, H106 = 4, 5, 6
URL = "/api/gestion/liberar-no-presentados"


@pytest.fixture
def recepcion(cliente_http):
    """Sesión de recepción."""
    return iniciar_sesion(cliente_http, "recepcion@soluna.test")


def por_telefono(admin_db, codigo, entrada, habitacion_id, **extra):
    """Reserva por teléfono confirmada y sin ingreso, de dos noches."""
    reserva_bd(admin_db, codigo, entrada, entrada + timedelta(days=2), habitacion_id=habitacion_id, **extra)
    admin_db.execute("UPDATE reservas SET canal = 'telefono' WHERE codigo = %s", (codigo,))
    return codigo


def estado(admin_db, codigo):
    """Estado actual de una reserva en la base."""
    return admin_db.execute("SELECT estado FROM reservas WHERE codigo = %s", (codigo,)).fetchone()[0]


def test_libera_la_llegada_vencida_y_deja_constancia(cliente_http, admin_db, recepcion):
    """La llegada de ayer sin ingreso ni adelanto se cancela, la habitación queda libre y la bitácora lo registra.

    La entrada de la reserva la escribe la función sin usuario (lo hizo el
    sistema); la API agrega otra con la persona de recepción que pulsó el botón.
    """
    ayer = hoy() - timedelta(days=1)
    por_telefono(admin_db, "SOL-NOVINO", ayer, H101)

    r = cliente_http.post(URL, headers=recepcion)
    assert r.status_code == 200, r.text
    assert r.json() == [{"codigo": "SOL-NOVINO", "habitacion": "101", "fecha_entrada": str(ayer)}]
    assert estado(admin_db, "SOL-NOVINO") == "cancelada"

    usuario, detalle = admin_db.execute(
        "SELECT usuario_id, detalle FROM bitacora WHERE accion = 'liberar_no_presentado' "
        "AND entidad = 'reserva' AND entidad_id = 'SOL-NOVINO'").fetchone()
    assert usuario is None
    assert detalle == {"fecha_entrada": str(ayer), "hora_garantia": config.HORA_GARANTIA}
    quien, resumen = admin_db.execute(
        "SELECT u.correo, b.detalle FROM bitacora b JOIN usuarios u ON u.id = b.usuario_id "
        "WHERE b.accion = 'liberar_no_presentados'").fetchone()
    assert quien == "recepcion@soluna.test" and resumen["reservas"] == ["SOL-NOVINO"]

    tablero = {h["numero"]: h for h in cliente_http.get("/api/gestion/tablero", headers=recepcion).json()["habitaciones"]}
    assert tablero["101"]["situacion"] == "libre" and tablero["101"]["llegada"] is None


def test_es_idempotente(cliente_http, admin_db, recepcion):
    """La segunda ejecución no encuentra nada: no repite cancelaciones ni deja entradas vacías en la bitácora."""
    por_telefono(admin_db, "SOL-NOVINO", hoy() - timedelta(days=1), H101)
    assert len(cliente_http.post(URL, headers=recepcion).json()) == 1
    assert cliente_http.post(URL, headers=recepcion).json() == []
    total = admin_db.execute("SELECT count(*) FROM bitacora WHERE accion IN "
                             "('liberar_no_presentado', 'liberar_no_presentados')").fetchone()[0]
    assert total == 2


def test_solo_libera_lo_que_corresponde(cliente_http, admin_db, recepcion):
    """No se liberan las reservas en línea ni de la agencia, ni las de huéspedes ya hospedados, ni las que
    tienen un adelanto, ni las que llegan mañana, ni las tomadas después de la hora de garantía.
    """
    dia = hoy()
    ayer = dia - timedelta(days=1)
    por_telefono(admin_db, "SOL-LIBERA", ayer, H101)
    reserva_bd(admin_db, "SOL-MOSTRA", ayer, dia + timedelta(days=1), habitacion_id=H201)   # mostrador: sí se libera
    reserva_bd(admin_db, "SOL-WEB001", ayer, dia + timedelta(days=1), habitacion_id=H102)
    admin_db.execute("UPDATE reservas SET canal = 'web' WHERE codigo = 'SOL-WEB001'")
    reserva_bd(admin_db, "SOL-OTA001", ayer, dia + timedelta(days=1), habitacion_id=H103)
    admin_db.execute("UPDATE reservas SET canal = 'ota' WHERE codigo = 'SOL-OTA001'")
    reserva_bd(admin_db, "SOL-ADENTR", ayer, dia + timedelta(days=1), estado="en_curso", habitacion_id=H104)
    por_telefono(admin_db, "SOL-MANANA", dia + timedelta(days=1), H105)
    por_telefono(admin_db, "SOL-ADELAN", ayer, H106)
    admin_db.execute(
        "INSERT INTO pagos_caja (reserva_id, metodo, monto, recibido_por) "
        "SELECT r.id, 'sinpe', 50, u.id FROM reservas r, usuarios u "
        "WHERE r.codigo = 'SOL-ADELAN' AND u.correo = 'recepcion@soluna.test'")
    # Llamó ayer a las 7 p. m. para llegar esa misma noche: no tuvo plazo que vencer
    por_telefono(admin_db, "SOL-TARDE1", ayer, 7)
    admin_db.execute("UPDATE reservas SET creada_en = %s WHERE codigo = 'SOL-TARDE1'",
                     (datetime.combine(ayer, time(19), tzinfo=config.ZONA_HORARIA),))

    liberadas = [r["codigo"] for r in cliente_http.post(URL, headers=recepcion).json()]
    assert liberadas == ["SOL-LIBERA", "SOL-MOSTRA"]
    for codigo, esperado in (("SOL-WEB001", "confirmada"), ("SOL-OTA001", "confirmada"), ("SOL-ADENTR", "en_curso"),
                             ("SOL-MANANA", "confirmada"), ("SOL-ADELAN", "confirmada"), ("SOL-TARDE1", "confirmada")):
        assert estado(admin_db, codigo) == esperado, codigo


def test_el_tablero_y_el_detalle_anuncian_lo_mismo(cliente_http, admin_db, recepcion):
    """Garantía vencida solo donde la función liberaría: con adelanto o tomada tarde no hay plazo que vencer."""
    ayer = hoy() - timedelta(days=1)
    por_telefono(admin_db, "SOL-VENCID", ayer, H101)
    por_telefono(admin_db, "SOL-ADELAN", ayer, H102)
    admin_db.execute(
        "INSERT INTO pagos_caja (reserva_id, metodo, monto, recibido_por) "
        "SELECT r.id, 'efectivo', 40, u.id FROM reservas r, usuarios u "
        "WHERE r.codigo = 'SOL-ADELAN' AND u.correo = 'recepcion@soluna.test'")
    por_telefono(admin_db, "SOL-TARDE1", ayer, H103)
    admin_db.execute("UPDATE reservas SET creada_en = %s WHERE codigo = 'SOL-TARDE1'",
                     (datetime.combine(ayer, time(18, 30), tzinfo=config.ZONA_HORARIA),))

    tablero = {h["numero"]: h for h in cliente_http.get("/api/gestion/tablero", headers=recepcion).json()["habitaciones"]}
    assert [tablero[n]["llegada"]["garantia_vencida"] for n in ("101", "102", "103")] == [True, False, False]
    for codigo, tiene in (("SOL-VENCID", True), ("SOL-ADELAN", False), ("SOL-TARDE1", False)):
        detalle = cliente_http.get(f"/api/gestion/reservas/{codigo}", headers=recepcion).json()
        assert (detalle["reserva"]["garantia_hasta"] is not None) == tiene, codigo

    assert [r["codigo"] for r in cliente_http.post(URL, headers=recepcion).json()] == ["SOL-VENCID"]


def test_usa_la_hora_de_garantia_configurada(cliente_http, admin_db, recepcion, monkeypatch):
    """La API pasa HORA_GARANTIA a la función: con garantía hasta la medianoche, la llegada de hoy ya venció."""
    por_telefono(admin_db, "SOL-HOY001", hoy(), H101)
    monkeypatch.setattr(config, "HORA_GARANTIA", 0)
    assert [r["codigo"] for r in cliente_http.post(URL, headers=recepcion).json()] == ["SOL-HOY001"]
    detalle = admin_db.execute("SELECT detalle FROM bitacora WHERE accion = 'liberar_no_presentado'").fetchone()[0]
    assert detalle["hora_garantia"] == 0


def test_la_funcion_de_la_base_responde_por_si_sola(admin_db):
    """pg_cron llama a la función directamente, sin la API: devuelve lo liberado y respeta la hora indicada."""
    dia = hoy()
    por_telefono(admin_db, "SOL-AYER01", dia - timedelta(days=1), H101)
    # Con la hora por omisión (17:00, la que usa pg_cron) la llegada de ayer ya venció
    filas = admin_db.execute("SELECT codigo_reserva, numero_habitacion, entrada FROM liberar_no_presentados()").fetchall()
    assert filas == [("SOL-AYER01", "101", dia - timedelta(days=1))]

    por_telefono(admin_db, "SOL-HOY001", dia, H102)
    ahora = datetime.now(config.ZONA_HORARIA)
    if ahora.hour < 23:
        # Con la garantía una hora más tarde que ahora, la llegada de hoy todavía está a tiempo
        admin_db.execute("SELECT * FROM liberar_no_presentados(%s)", (ahora.hour + 1,))
        assert estado(admin_db, "SOL-HOY001") == "confirmada"
    # Con la garantía hasta las 00:00, ya venció
    admin_db.execute("SELECT * FROM liberar_no_presentados(0)")
    assert estado(admin_db, "SOL-HOY001") == "cancelada"


@pytest.mark.parametrize("cuenta", ["limpieza@soluna.test", "mantenimiento@soluna.test", "cliente@soluna.test"])
def test_solo_recepcion_y_gerencia(cliente_http, admin_db, cuenta):
    """Las demás cuentas reciben 403 y no se libera nada; sin sesión, 401."""
    por_telefono(admin_db, "SOL-NOVINO", hoy() - timedelta(days=1), H101)
    assert cliente_http.post(URL, headers=iniciar_sesion(cliente_http, cuenta)).status_code == 403
    assert cliente_http.post(URL).status_code == 401
    assert estado(admin_db, "SOL-NOVINO") == "confirmada"
    gerencia = iniciar_sesion(cliente_http, "gerencia@soluna.test")
    assert [r["codigo"] for r in cliente_http.post(URL, headers=gerencia).json()] == ["SOL-NOVINO"]


def test_garantia_con_adelanto_o_tomada_tarde():
    """Sin plazo que vencer: con adelanto, o tomada a la hora de garantía del día de llegada o después."""
    dia = date(2026, 12, 20)
    limite = datetime(2026, 12, 20, 17, tzinfo=config.ZONA_HORARIA)
    assert garantia_hasta("telefono", "confirmada", dia, limite - timedelta(minutes=1)) == limite
    assert garantia_hasta("telefono", "confirmada", dia, limite) is None
    assert garantia_hasta("recepcion", "confirmada", dia, limite + timedelta(hours=2)) is None
    assert garantia_hasta("telefono", "confirmada", dia, limite - timedelta(days=3), con_adelanto=True) is None


def test_el_correo_anuncia_la_liberacion_o_la_explica():
    """El correo avisa que la reserva se libera sola; si se tomó tarde, explica que se guarda esa noche."""
    dia = date(2026, 12, 20)
    limite = datetime(2026, 12, 20, 17, tzinfo=config.ZONA_HORARIA)

    def reserva(creada_en):
        return Reserva(canal="telefono", estado="confirmada", fecha_entrada=dia, fecha_salida=dia + timedelta(days=1),
                       total=Decimal("100.00"), creada_en=creada_en)

    a_tiempo = bloque_pago_en_hotel(reserva(limite - timedelta(days=5)))
    assert "hasta las 5:00 p. m. del 20/12/2026" in a_tiempo
    assert "se liberará automáticamente" in a_tiempo and "Si ya pagó un adelanto, la reserva se mantiene" in a_tiempo

    tarde = bloque_pago_en_hotel(reserva(limite + timedelta(hours=2)))
    assert "después de las 5:00 p. m." in tarde and "no se libera automáticamente" in tarde
    assert "se liberará automáticamente" not in tarde
