"""Mantenimiento de la base: retención de la bitácora según la ocupación y límites por consulta.

La función ``mantenimiento`` se prueba directamente en la base, como la
ejecutaría pg_cron en Supabase. Para simular la ocupación alta se le pasa un
límite de 1 MB, que la base de pruebas ya supera.
"""
import os

import psycopg
import pytest


def registros_viejos(admin_db, dias, cantidad):
    """Agrega a la bitácora ``cantidad`` registros con ``dias`` de antigüedad."""
    admin_db.execute(
        "INSERT INTO bitacora (fecha, accion, entidad, entidad_id) "
        "SELECT now() - make_interval(days => %s), 'crear_reserva', 'reserva', 'SOL-' || %s || '-' || g "
        "FROM generate_series(1, %s) AS g", (dias, dias, cantidad))


def contar(admin_db, accion="crear_reserva"):
    """Registros de la bitácora con esa acción."""
    return admin_db.execute("SELECT count(*) FROM bitacora WHERE accion = %s", (accion,)).fetchone()[0]


def conexion_api():
    """Conexión con el usuario de la API (app_hotel), el mismo que usan las réplicas."""
    return psycopg.connect(host=os.environ["DB_HOST"], port=os.environ["DB_PORT"],
                           dbname=os.environ.get("DB_NAME", "hotel"), user="app_hotel",
                           password=os.environ["DB_PASSWORD"], autocommit=True)


def test_retencion_normal_conserva_un_anio(admin_db):
    """Con ocupación normal se borra solo lo que tiene más de 365 días, y queda constancia."""
    registros_viejos(admin_db, 400, 3)
    registros_viejos(admin_db, 200, 2)
    resumen = admin_db.execute("SELECT mantenimiento()").fetchone()[0]
    assert "borradas: 3 de bitácora" in resumen and "ALTA" not in resumen
    assert contar(admin_db) == 2
    detalle = admin_db.execute("SELECT detalle FROM bitacora WHERE accion = 'mantenimiento'").fetchone()[0]
    assert detalle["ocupacion_alta"] is False and detalle["retencion_bitacora_dias"] == 365
    assert detalle["bitacora"] == 3


def test_ocupacion_alta_reduce_la_retencion_a_90_dias(admin_db):
    """Cerca del límite del plan, la bitácora se recorta a 90 días para no llegar a solo lectura."""
    registros_viejos(admin_db, 120, 2)
    registros_viejos(admin_db, 30, 4)
    resumen = admin_db.execute("SELECT mantenimiento(true, 1)").fetchone()[0]
    assert "OCUPACIÓN ALTA" in resumen and "borradas: 2 de bitácora" in resumen
    assert contar(admin_db) == 4
    detalle = admin_db.execute("SELECT detalle FROM bitacora WHERE accion = 'mantenimiento'").fetchone()[0]
    assert detalle["ocupacion_alta"] is True and detalle["retencion_bitacora_dias"] == 90


def test_vigilancia_no_toca_nada_con_ocupacion_normal(admin_db):
    """La revisión de cada hora no borra ni registra nada mientras la ocupación es normal."""
    registros_viejos(admin_db, 400, 2)
    resumen = admin_db.execute("SELECT mantenimiento(true)").fetchone()[0]
    assert resumen.startswith("Ocupación normal")
    assert contar(admin_db) == 2 and contar(admin_db, "mantenimiento") == 0


def test_limpia_la_idempotencia_vieja_del_simulador(admin_db):
    """Las llaves de idempotencia de más de 7 días se borran; las recientes se conservan."""
    if admin_db.execute("SELECT to_regclass('simulador.idempotencia')").fetchone()[0] is None:
        pytest.skip("La base de pruebas no tiene el esquema del simulador")
    admin_db.execute(
        "INSERT INTO simulador.idempotencia (llave, huella, respuesta, creado_en) VALUES "
        "('prueba-vieja', 'h', '{}', now() - interval '10 days'), ('prueba-nueva', 'h', '{}', now())")
    try:
        admin_db.execute("SELECT mantenimiento()")
        llaves = {f[0] for f in admin_db.execute(
            "SELECT llave FROM simulador.idempotencia WHERE llave LIKE 'prueba-%'")}
        assert llaves == {"prueba-nueva"}
    finally:
        admin_db.execute("DELETE FROM simulador.idempotencia WHERE llave LIKE 'prueba-%'")


def test_la_api_no_puede_ejecutar_el_mantenimiento():
    """El usuario de la API no puede llamar a la función: no le corresponde borrar la bitácora."""
    with conexion_api() as conexion:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conexion.execute("SELECT mantenimiento()")


def test_limites_de_tiempo_de_la_api():
    """Ninguna consulta de la API ocupa la base más de 15 s ni deja una transacción abierta más de 60 s."""
    with conexion_api() as conexion:
        assert conexion.execute("SHOW statement_timeout").fetchone()[0] == "15s"
        assert conexion.execute("SHOW idle_in_transaction_session_timeout").fetchone()[0] == "1min"
        with pytest.raises(psycopg.errors.QueryCanceled):
            conexion.execute("SET statement_timeout = '200ms'")   # misma regla, más corta para la prueba
            conexion.execute("SELECT pg_sleep(1)")
