"""Solicitudes de huéspedes: chat entre el huésped alojado y el personal.

Las estadías en curso se crean directamente en la base (ver test_gestion).
"""
import os
from datetime import timedelta

import psycopg
import pytest
from sqlalchemy import event

from app.db import engine
from app.routers.reservas import hoy

from .conftest import iniciar_sesion
from .test_gestion import reserva_bd

URL_CHAT = "/api/reservas/{}/solicitudes"


def alojada(admin_db, codigo="SOL-CHAT01", habitacion_id=1, de_la_cuenta=True, estado="en_curso",
            correo="cliente@soluna.test"):
    """Una estadía en curso del cliente de prueba: hecha con su cuenta o solo a nombre de su correo."""
    dia = hoy()
    reserva_bd(admin_db, codigo, dia - timedelta(days=1), dia + timedelta(days=2), estado, habitacion_id,
               nombre="Cliente de Prueba", correo=correo)
    if de_la_cuenta:
        admin_db.execute("UPDATE reservas SET cliente_id = (SELECT id FROM usuarios WHERE correo = %s) "
                         "WHERE codigo = %s", (correo, codigo))
    return codigo


def escribir(cliente_http, cabecera, codigo, texto="El aire acondicionado no enfría.", categoria=None):
    """El huésped escribe al hotel."""
    cuerpo = {"texto": texto} | ({"categoria": categoria} if categoria else {})
    return cliente_http.post(URL_CHAT.format(codigo), headers=cabecera, json=cuerpo)


def bandeja(cliente_http, cabecera, **parametros):
    """La bandeja del personal (con parámetros opcionales de consulta incremental)."""
    r = cliente_http.get("/api/solicitudes", headers=cabecera, params=parametros)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture
def cliente(cliente_http):
    """Sesión del cliente de prueba."""
    return iniciar_sesion(cliente_http, "cliente@soluna.test")


@pytest.fixture
def recepcion(cliente_http):
    """Sesión de recepción."""
    return iniciar_sesion(cliente_http, "recepcion@soluna.test")


# ------------------------------------------------------------- huésped
def test_huesped_escribe_y_sus_mensajes_van_a_una_sola_solicitud(cliente_http, admin_db, cliente):
    """El primer mensaje abre una solicitud; los siguientes se suman a ella mientras siga abierta."""
    codigo = alojada(admin_db)
    r = escribir(cliente_http, cliente, codigo, categoria="mantenimiento")
    assert r.status_code == 201, r.text
    assert escribir(cliente_http, cliente, codigo, "¿Pueden revisarlo pronto?").status_code == 201

    chat = cliente_http.get(URL_CHAT.format(codigo), headers=cliente).json()
    assert chat["puede_escribir"] is True and chat["habitacion"] == "101"
    assert chat["abierta"]["categoria"] == "mantenimiento" and chat["abierta"]["estado"] == "abierta"
    assert [m["texto"] for m in chat["mensajes"]] == ["El aire acondicionado no enfría.", "¿Pueden revisarlo pronto?"]
    assert admin_db.execute("SELECT count(*) FROM solicitudes").fetchone()[0] == 1


def test_reserva_a_nombre_de_su_correo_tambien_sirve(cliente_http, admin_db, cliente):
    """Si recepción reservó a nombre del correo del cliente (sin su cuenta), igual puede escribir."""
    codigo = alojada(admin_db, de_la_cuenta=False)
    assert escribir(cliente_http, cliente, codigo).status_code == 201


def test_reserva_ajena_o_inexistente_responde_igual(cliente_http, admin_db, cliente):
    """Un código ajeno y uno inexistente dan la misma respuesta: 404."""
    alojada(admin_db, "SOL-AJENA1", de_la_cuenta=False, correo="otra@correo.test")
    ajena = escribir(cliente_http, cliente, "SOL-AJENA1")
    inexistente = escribir(cliente_http, cliente, "SOL-NOEXIS")
    assert ajena.status_code == inexistente.status_code == 404
    assert ajena.json() == inexistente.json()


@pytest.mark.parametrize("estado", ["confirmada", "finalizada"])
def test_solo_se_escribe_durante_la_estadia(cliente_http, admin_db, cliente, estado):
    """Antes del ingreso o después de la salida, el chat se puede leer pero no escribir (409)."""
    codigo = alojada(admin_db, estado=estado)
    assert cliente_http.get(URL_CHAT.format(codigo), headers=cliente).json()["puede_escribir"] is False
    r = escribir(cliente_http, cliente, codigo)
    assert r.status_code == 409 and "durante su estadía" in r.json()["detail"]


def test_limite_de_mensajes_por_minuto(cliente_http, admin_db, cliente):
    """Hasta 5 mensajes por minuto; el sexto se rechaza con 429."""
    codigo = alojada(admin_db)
    for n in range(5):
        assert escribir(cliente_http, cliente, codigo, f"Mensaje {n}").status_code == 201
    assert escribir(cliente_http, cliente, codigo, "Uno más").status_code == 429


@pytest.mark.parametrize("texto", ["", "     ", "x" * 1001])
def test_mensajes_invalidos(cliente_http, admin_db, cliente, texto):
    """Vacío, solo espacios o más de 1000 caracteres: 422."""
    codigo = alojada(admin_db)
    assert escribir(cliente_http, cliente, codigo, texto).status_code == 422


def test_el_personal_no_usa_el_chat_del_huesped(cliente_http, admin_db, recepcion):
    """Las rutas del huésped son solo para cuentas de cliente; sin sesión, 401."""
    codigo = alojada(admin_db)
    assert cliente_http.get(URL_CHAT.format(codigo), headers=recepcion).status_code == 403
    assert cliente_http.get(URL_CHAT.format(codigo)).status_code == 401


# ------------------------------------------------------------- personal
def test_cada_area_ve_lo_suyo(cliente_http, admin_db, cliente):
    """Recepción y gerencia ven todo; limpieza y mantenimiento, solo su área; el cliente, nada."""
    escribir(cliente_http, cliente, alojada(admin_db, "SOL-CHAT01", 1), categoria="limpieza")
    escribir(cliente_http, cliente, alojada(admin_db, "SOL-CHAT02", 2), categoria="mantenimiento")
    escribir(cliente_http, cliente, alojada(admin_db, "SOL-CHAT03", 3), categoria="recepcion")
    vistas = {}
    for correo in ("recepcion", "gerencia", "limpieza", "mantenimiento"):
        cabecera = iniciar_sesion(cliente_http, f"{correo}@soluna.test")
        vistas[correo] = {s["categoria"] for s in bandeja(cliente_http, cabecera)["solicitudes"]}
    assert vistas == {"recepcion": {"limpieza", "mantenimiento", "recepcion"},
                      "gerencia": {"limpieza", "mantenimiento", "recepcion"},
                      "limpieza": {"limpieza"}, "mantenimiento": {"mantenimiento"}}
    assert cliente_http.get("/api/solicitudes", headers=cliente).status_code == 403
    assert cliente_http.get("/api/solicitudes").status_code == 401


def test_conversacion_completa(cliente_http, admin_db, cliente, recepcion):
    """El huésped escribe, recepción responde, el huésped ve la respuesta y recepción resuelve.

    Responder deja la solicitud en atención, asignada y sin respuesta pendiente.
    Al huésped no se le muestra el nombre de quien respondió.
    """
    codigo = alojada(admin_db)
    escribir(cliente_http, cliente, codigo, "¿A qué hora es el desayuno?")
    solicitud = bandeja(cliente_http, recepcion)["solicitudes"][0]
    assert solicitud["pendiente_desde"] is not None and solicitud["habitacion"] == "101"
    assert solicitud["ultimo_mensaje"] == "¿A qué hora es el desayuno?"

    r = cliente_http.post(f"/api/solicitudes/{solicitud['id']}/mensajes", headers=recepcion,
                          json={"texto": "De 7 a 10 a. m. en el restaurante."})
    assert r.status_code == 201 and r.json()["nombre"] == "Recepción Soluna"
    s = bandeja(cliente_http, recepcion)["solicitudes"][0]
    assert (s["estado"], s["asignada_a"], s["pendiente_desde"]) == ("en_atencion", "Recepción Soluna", None)

    chat = cliente_http.get(URL_CHAT.format(codigo), headers=cliente).json()
    assert [(m["autor"], m["nombre"]) for m in chat["mensajes"]] == [("huesped", None), ("personal", None)]

    r = cliente_http.patch(f"/api/solicitudes/{s['id']}", headers=recepcion, json={"estado": "resuelta"})
    assert r.status_code == 200 and r.json()["estado"] == "resuelta" and r.json()["resuelta_en"]
    r = cliente_http.post(f"/api/solicitudes/{s['id']}/mensajes", headers=recepcion, json={"texto": "Algo más"})
    assert r.status_code == 409

    # Un mensaje nuevo del huésped abre otra solicitud
    escribir(cliente_http, cliente, codigo, "Gracias. ¿Tienen sombrillas de playa?")
    assert admin_db.execute("SELECT count(*) FROM solicitudes").fetchone()[0] == 2
    acciones = [f[0] for f in admin_db.execute(
        "SELECT accion FROM bitacora WHERE entidad = 'solicitud' ORDER BY id")]
    assert acciones == ["actualizar_solicitud"]


def test_tomar_reasignar_y_reabrir(cliente_http, admin_db, cliente):
    """Limpieza toma la solicitud y la pasa a mantenimiento (y deja de verla); reabrir choca con otra abierta."""
    codigo = alojada(admin_db)
    escribir(cliente_http, cliente, codigo, "La ducha gotea.", categoria="limpieza")
    limpieza = iniciar_sesion(cliente_http, "limpieza@soluna.test")
    mantenimiento = iniciar_sesion(cliente_http, "mantenimiento@soluna.test")
    sid = bandeja(cliente_http, limpieza)["solicitudes"][0]["id"]

    r = cliente_http.patch(f"/api/solicitudes/{sid}", headers=limpieza, json={"tomar": True})
    assert r.json()["estado"] == "en_atencion" and r.json()["asignada_a"] == "Limpieza Soluna"
    r = cliente_http.patch(f"/api/solicitudes/{sid}", headers=limpieza, json={"categoria": "mantenimiento"})
    assert r.status_code == 200 and r.json()["categoria"] == "mantenimiento"
    assert bandeja(cliente_http, limpieza)["solicitudes"] == []
    assert cliente_http.patch(f"/api/solicitudes/{sid}", headers=limpieza,
                              json={"estado": "resuelta"}).status_code == 404     # ya no es de su área
    assert cliente_http.patch(f"/api/solicitudes/{sid}", headers=mantenimiento,
                              json={"estado": "resuelta"}).status_code == 200
    assert cliente_http.patch(f"/api/solicitudes/{sid}", headers=mantenimiento, json={}).status_code == 422

    # Mientras tanto el huésped abre otra; reabrir la primera violaría "una abierta por reserva"
    escribir(cliente_http, cliente, codigo, "Ahora no hay agua caliente.")
    r = cliente_http.patch(f"/api/solicitudes/{sid}", headers=mantenimiento, json={"estado": "abierta"})
    assert r.status_code == 409 and "otra solicitud abierta" in r.json()["detail"]


def test_consulta_incremental(cliente_http, admin_db, cliente, recepcion):
    """Con 'desde' llega solo lo que cambió; con 'despues' solo los mensajes nuevos."""
    codigo = alojada(admin_db)
    escribir(cliente_http, cliente, codigo, "Primero")
    inicial = bandeja(cliente_http, recepcion)
    sid = inicial["solicitudes"][0]["id"]
    conversacion = bandeja(cliente_http, recepcion, abierta=sid)
    ultimo = conversacion["mensajes"][-1]["id"]

    # Fuera del margen de 10 s no hay cambios: lista vacía
    admin_db.execute("UPDATE solicitudes SET actualizada_en = now() - interval '1 minute'")
    sin_cambios = bandeja(cliente_http, recepcion, desde=inicial["ahora"], abierta=sid, despues=ultimo)
    assert sin_cambios["solicitudes"] == [] and sin_cambios["mensajes"] == []

    escribir(cliente_http, cliente, codigo, "Segundo")
    nuevo = bandeja(cliente_http, recepcion, desde=sin_cambios["ahora"], abierta=sid, despues=ultimo)
    assert [s["id"] for s in nuevo["solicitudes"]] == [sid]
    assert [m["texto"] for m in nuevo["mensajes"]] == ["Segundo"]


def contar_consultas(cliente_http, cabecera, **parametros):
    """Sentencias SQL que la API envía para una consulta de la bandeja."""
    sentencias = []

    def anotar(conexion, cursor, sentencia, *args):
        sentencias.append(sentencia)

    event.listen(engine, "before_cursor_execute", anotar)
    try:
        bandeja(cliente_http, cabecera, **parametros)
    finally:
        event.remove(engine, "before_cursor_execute", anotar)
    return len(sentencias)


def test_la_bandeja_cuesta_lo_mismo_con_muchas_solicitudes(cliente_http, admin_db, cliente, recepcion):
    """Con 1 o con 10 solicitudes, la bandeja con conversación abierta cuesta 4 sentencias como máximo."""
    escribir(cliente_http, cliente, alojada(admin_db, "SOL-CHAT01", 1))
    sid = bandeja(cliente_http, recepcion)["solicitudes"][0]["id"]
    con_una = contar_consultas(cliente_http, recepcion, abierta=sid)
    for n in range(2, 11):
        codigo = alojada(admin_db, f"SOL-CHAT{n:02d}", n)
        escribir(cliente_http, cliente, codigo)
    assert contar_consultas(cliente_http, recepcion, abierta=sid) == con_una <= 4


# ------------------------------------------------------------- simulador y salida
def test_simulador_de_huespedes(cliente_http, admin_db, recepcion):
    """Sin huéspedes alojados no hay a quién simular (409); con uno, llega un pedido simulado."""
    assert cliente_http.post("/api/solicitudes/simular", headers=recepcion).status_code == 409
    alojada(admin_db)
    r = cliente_http.post("/api/solicitudes/simular", headers=recepcion)
    assert r.status_code == 201, r.text
    assert r.json()["simulada"] is True and r.json()["codigo_reserva"] == "SOL-CHAT01"
    assert r.json()["pendiente_desde"] is not None and r.json()["ultimo_mensaje"]
    autor = admin_db.execute("SELECT autor, usuario_id FROM mensajes").fetchone()
    assert autor == ("huesped", None)
    limpieza = iniciar_sesion(cliente_http, "limpieza@soluna.test")
    assert cliente_http.post("/api/solicitudes/simular", headers=limpieza).status_code == 403


def test_la_salida_cierra_las_solicitudes_abiertas(cliente_http, admin_db, cliente, recepcion):
    """Al registrar la salida, la solicitud abierta queda resuelta y el huésped ya no puede escribir."""
    codigo = alojada(admin_db)
    escribir(cliente_http, cliente, codigo)
    assert cliente_http.post(f"/api/gestion/reservas/{codigo}/check-out", headers=recepcion,
                             json={"metodo_pago": "efectivo"}).status_code == 200
    estado = admin_db.execute("SELECT estado, pendiente_desde FROM solicitudes").fetchone()
    assert estado == ("resuelta", None)
    assert escribir(cliente_http, cliente, codigo).status_code == 409


# ------------------------------------------------------------- base de datos
def test_la_api_no_puede_borrar_ni_editar_la_conversacion(admin_db):
    """El usuario de la API no borra solicitudes, ni edita o borra mensajes, ni cambia la reserva de una solicitud."""
    conexion = psycopg.connect(host=os.environ["DB_HOST"], port=os.environ["DB_PORT"],
                               dbname=os.environ.get("DB_NAME", "hotel"), user="app_hotel",
                               password=os.environ["DB_PASSWORD"], autocommit=True)
    with conexion:
        for sql in ("DELETE FROM solicitudes", "DELETE FROM mensajes", "UPDATE mensajes SET texto = 'x'",
                    "UPDATE solicitudes SET reserva_id = 1"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conexion.execute(sql)


def test_mantenimiento_borra_solicitudes_resueltas_viejas(cliente_http, admin_db, cliente):
    """Las resueltas hace más de 90 días se borran con sus mensajes; las recientes y las abiertas quedan."""
    vieja = alojada(admin_db, "SOL-VIEJA1", 1)
    reciente = alojada(admin_db, "SOL-RECIE1", 2)
    abierta = alojada(admin_db, "SOL-ABIER1", 3)
    for codigo in (vieja, reciente, abierta):
        escribir(cliente_http, cliente, codigo)
    admin_db.execute("UPDATE solicitudes s SET estado = 'resuelta', resuelta_en = now() - interval '100 days' "
                     "FROM reservas r WHERE r.id = s.reserva_id AND r.codigo = %s", (vieja,))
    admin_db.execute("UPDATE solicitudes s SET estado = 'resuelta', resuelta_en = now() - interval '10 days' "
                     "FROM reservas r WHERE r.id = s.reserva_id AND r.codigo = %s", (reciente,))
    resumen = admin_db.execute("SELECT mantenimiento()").fetchone()[0]
    assert "1 solicitudes resueltas" in resumen
    restantes = {f[0] for f in admin_db.execute(
        "SELECT r.codigo FROM solicitudes s JOIN reservas r ON r.id = s.reserva_id")}
    assert restantes == {reciente, abierta}
    assert admin_db.execute("SELECT count(*) FROM mensajes").fetchone()[0] == 2
