"""Pruebas de la página de inicio: catálogo público y suscripción por correo."""
from .conftest import iniciar_sesion


def test_catalogo_publico_con_precio_desde(cliente_http):
    r = cliente_http.get("/api/tipos-habitacion")
    assert r.status_code == 200
    tipos = {t["nombre"]: t for t in r.json()}
    assert list(tipos) == ["estándar", "superior", "suite"]       # de menor a mayor capacidad
    assert float(tipos["estándar"]["precio_desde"]) == 85          # tarifa de temporada baja
    assert tipos["suite"]["habitaciones"] == 8
    assert sum(t["habitaciones"] for t in tipos.values()) == 46


def test_suscripcion_guarda_el_correo_y_da_la_bienvenida(cliente_http, admin_db, correos):
    r = cliente_http.post("/api/suscripciones", json={"correo": "Viajera@Correo.test"})
    assert r.status_code == 202
    assert admin_db.execute("SELECT correo, activo FROM suscriptores").fetchall() == [("viajera@correo.test", True)]
    assert correos[-1]["destino"] == "viajera@correo.test" and "Bienvenida" in correos[-1]["asunto"]


def test_suscripcion_repetida_no_duplica_ni_revela_nada(cliente_http, admin_db, correos):
    primera = cliente_http.post("/api/suscripciones", json={"correo": "repite@correo.test"})
    segunda = cliente_http.post("/api/suscripciones", json={"correo": "REPITE@correo.test"})
    # Misma respuesta: no se puede averiguar si un correo ya estaba en la lista
    assert primera.status_code == segunda.status_code == 202 and primera.json() == segunda.json()
    assert admin_db.execute("SELECT count(*) FROM suscriptores").fetchone() == (1,)
    assert len(correos) == 1   # la bienvenida se envía una sola vez


def test_suscripcion_rechaza_correo_invalido(cliente_http):
    assert cliente_http.post("/api/suscripciones", json={"correo": "no-es-un-correo"}).status_code == 422


def test_solo_gerencia_ve_la_lista_de_suscriptores(cliente_http):
    cliente_http.post("/api/suscripciones", json={"correo": "lista@correo.test"})
    assert cliente_http.get("/api/suscripciones").status_code == 401
    cliente = iniciar_sesion(cliente_http, "cliente@soluna.test")
    assert cliente_http.get("/api/suscripciones", headers=cliente).status_code == 403
    gerente = iniciar_sesion(cliente_http, "gerencia@soluna.test")
    r = cliente_http.get("/api/suscripciones", headers=gerente)
    assert r.status_code == 200 and [s["correo"] for s in r.json()] == ["lista@correo.test"]
