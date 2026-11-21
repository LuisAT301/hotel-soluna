"""Reseñas verificadas: solo opina el titular de una estadía cumplida, una vez por reservación."""
from datetime import date, timedelta

import pytest

from .conftest import iniciar_sesion

COMENTARIO = "Excelente atención y la playa a dos pasos."


def estadia(admin_db, codigo, correo="cliente@soluna.test", estado="finalizada", salida=None,
            habitacion_id=1, con_cuenta=True):
    """Crea una reservación directamente en la base (la API no permite fechas pasadas).

    Por defecto, una estadía de dos noches que terminó hace cinco días. Con
    ``con_cuenta=False`` queda sin cliente asociado, como las de recepción o la OTA.
    """
    salida = salida or date.today() - timedelta(days=5)
    cliente_id = None
    if con_cuenta:
        cliente_id = admin_db.execute("SELECT id FROM usuarios WHERE correo = %s", (correo,)).fetchone()[0]
    admin_db.execute(
        "INSERT INTO reservas (codigo, habitacion_id, cliente_id, nombre_huesped, correo_huesped, personas, "
        "fecha_entrada, fecha_salida, canal, estado, total) VALUES (%s, %s, %s, 'Huésped', %s, 2, %s, %s, "
        "'web', %s, 170)",
        (codigo, habitacion_id, cliente_id, correo, salida - timedelta(days=2), salida, estado))
    return codigo


def opinar(cliente_http, cabecera, codigo, calificacion=5, comentario=COMENTARIO):
    """Envía una reseña con la sesión indicada (o sin sesión, si ``cabecera`` es None)."""
    return cliente_http.post("/api/resenas", headers=cabecera or {}, json={
        "codigo_reserva": codigo, "calificacion": calificacion, "comentario": comentario})


def test_sin_resenas_el_resumen_esta_vacio(cliente_http):
    """Sin reseñas, el listado público responde sin promedio y sin elementos."""
    r = cliente_http.get("/api/resenas")
    assert r.status_code == 200 and r.json() == {"promedio": None, "total": 0, "resenas": []}


def test_sin_cuenta_no_se_puede_opinar(cliente_http, admin_db):
    """Sin iniciar sesión, la reseña se rechaza con 401 aunque la estadía exista."""
    estadia(admin_db, "SOL-PASAD1")
    assert opinar(cliente_http, None, "SOL-PASAD1").status_code == 401


def test_estadia_cumplida_publica_la_resena(cliente_http, admin_db):
    """La reseña de una estadía cumplida se publica con el autor abreviado, el tipo y el promedio."""
    estadia(admin_db, "SOL-PASAD1")
    cliente = iniciar_sesion(cliente_http, "cliente@soluna.test")
    r = opinar(cliente_http, cliente, " sol-pasad1 ", calificacion=4)   # se normaliza el código
    assert r.status_code == 201, r.text
    assert r.json()["autor"] == "Cliente P." and r.json()["tipo_habitacion"] == "estándar"

    resumen = cliente_http.get("/api/resenas").json()
    assert resumen["total"] == 1 and float(resumen["promedio"]) == 4.0
    assert resumen["resenas"][0]["comentario"] == COMENTARIO
    # Queda constancia en la bitácora
    accion = admin_db.execute("SELECT accion, entidad_id FROM bitacora WHERE accion = 'publicar_resena'").fetchone()
    assert accion == ("publicar_resena", "SOL-PASAD1")


def test_una_sola_resena_por_reservacion(cliente_http, admin_db):
    """La segunda reseña sobre la misma reservación se rechaza con 409."""
    estadia(admin_db, "SOL-PASAD1")
    cliente = iniciar_sesion(cliente_http, "cliente@soluna.test")
    assert opinar(cliente_http, cliente, "SOL-PASAD1").status_code == 201
    assert opinar(cliente_http, cliente, "SOL-PASAD1", calificacion=1).status_code == 409
    assert cliente_http.get("/api/resenas").json()["total"] == 1


def test_codigo_inexistente_o_ajeno_responde_igual(cliente_http, admin_db):
    """Un código que no existe y uno de otra persona dan la misma respuesta (404)."""
    estadia(admin_db, "SOL-AJENA1", correo="otro@correo.test", con_cuenta=False)
    cliente = iniciar_sesion(cliente_http, "cliente@soluna.test")
    ajena = opinar(cliente_http, cliente, "SOL-AJENA1")
    inexistente = opinar(cliente_http, cliente, "SOL-NOEXIS")
    assert ajena.status_code == inexistente.status_code == 404
    assert ajena.json() == inexistente.json()


@pytest.mark.parametrize("estado, dias_para_salir", [
    ("confirmada", 10),        # todavía no termina: es futura
    ("cancelada", -5),         # nunca se hospedó
    ("pendiente_pago", -5),    # nunca se pagó
])
def test_estadia_no_cumplida_no_admite_resena(cliente_http, admin_db, estado, dias_para_salir):
    """Estadías futuras, canceladas o sin pagar no admiten reseña (409)."""
    estadia(admin_db, "SOL-NOCUMP", estado=estado, salida=date.today() + timedelta(days=dias_para_salir))
    cliente = iniciar_sesion(cliente_http, "cliente@soluna.test")
    r = opinar(cliente_http, cliente, "SOL-NOCUMP")
    assert r.status_code == 409, r.text


def test_huesped_sin_cuenta_al_reservar_puede_opinar_despues(cliente_http, admin_db):
    """Quien reservó por recepción y luego creó su cuenta con el mismo correo puede opinar."""
    estadia(admin_db, "SOL-RECEP1", correo="ana@correo.test", con_cuenta=False)
    assert cliente_http.post("/api/auth/registro", json={
        "nombre": "Ana Mora Solís", "correo": "Ana@Correo.test", "contrasena": "Segura2026"}).status_code == 201
    ana = iniciar_sesion(cliente_http, "ana@correo.test", "Segura2026")
    r = opinar(cliente_http, ana, "SOL-RECEP1")
    assert r.status_code == 201 and r.json()["autor"] == "Ana S."


@pytest.mark.parametrize("cambio", [
    {"calificacion": 0}, {"calificacion": 6}, {"comentario": "Corto"}, {"comentario": "          ."},
    {"codigo_reserva": "RES-123456"}, {"codigo_reserva": "SOL-12"},
])
def test_datos_invalidos_se_rechazan(cliente_http, admin_db, cambio):
    """Calificación fuera de 1 a 5, comentario muy corto o código con otro formato: 422."""
    estadia(admin_db, "SOL-PASAD1")
    cliente = iniciar_sesion(cliente_http, "cliente@soluna.test")
    cuerpo = {"codigo_reserva": "SOL-PASAD1", "calificacion": 5, "comentario": COMENTARIO, **cambio}
    assert cliente_http.post("/api/resenas", headers=cliente, json=cuerpo).status_code == 422


def test_la_api_no_puede_editar_ni_borrar_resenas(admin_db):
    """El usuario de la base de la API solo puede leer y agregar reseñas."""
    import os

    import psycopg
    conexion = psycopg.connect(host=os.environ["DB_HOST"], port=os.environ["DB_PORT"],
                               dbname=os.environ.get("DB_NAME", "hotel"), user="app_hotel",
                               password=os.environ["DB_PASSWORD"], autocommit=True)
    with conexion:
        for sql in ("UPDATE resenas SET calificacion = 5", "DELETE FROM resenas"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conexion.execute(sql)
