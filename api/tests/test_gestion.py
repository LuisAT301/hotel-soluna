"""Gestión de reservas en recepción: búsqueda, check-in, check-out y cambios.

Las reservas con fechas pasadas o en curso se crean directamente en la base,
porque la API no permite reservar en el pasado. "Hoy" se toma de la misma
función que usa la API (fecha de Costa Rica), para que las pruebas no fallen
cerca de la medianoche en un servidor con otra zona horaria.
"""
from datetime import timedelta
from decimal import Decimal

import pytest

from app.db import SesionLocal
from app.routers.reservas import calcular_total, hoy

from .conftest import iniciar_sesion

# Habitaciones del catálogo inicial: ids 1 a 20 son estándar (101 a 120),
# 21 a 38 superiores (201 a 218) y 39 a 46 suites (301 a 308).
H101, H102, H103, H201 = 1, 2, 3, 21
ESTANDAR, SUPERIOR = 1, 2


def reserva_bd(admin_db, codigo, entrada, salida, estado="confirmada", habitacion_id=H101,
               nombre="Ana Mora Solís", correo="ana@correo.test", total=None):
    """Inserta una reserva tal cual en la base y devuelve su código.

    Si no se indica el total, se calcula con las tarifas reales, como lo haría la API.
    """
    if total is None:
        tipo = admin_db.execute("SELECT tipo_id FROM habitaciones WHERE id = %s", (habitacion_id,)).fetchone()[0]
        total = precio(tipo, entrada, salida)
    admin_db.execute(
        "INSERT INTO reservas (codigo, habitacion_id, nombre_huesped, correo_huesped, personas, "
        "fecha_entrada, fecha_salida, canal, estado, total) VALUES (%s, %s, %s, %s, 2, %s, %s, "
        "'recepcion', %s, %s)",
        (codigo, habitacion_id, nombre, correo, entrada, salida, estado, total))
    return codigo


def precio(tipo_id, entrada, salida):
    """Total de la estadía con la misma función de la API (precio por temporada de cada noche)."""
    with SesionLocal() as sesion:
        return calcular_total(sesion, tipo_id, entrada, salida)


def limpieza(admin_db, habitacion_id, estado, fuera_de_servicio=False):
    """Pone una habitación en el estado de limpieza indicado (y fuera de servicio, si se pide)."""
    admin_db.execute("UPDATE habitaciones SET estado_limpieza = %s, fuera_de_servicio = %s WHERE id = %s",
                     (estado, fuera_de_servicio, habitacion_id))


def estado_bd(admin_db, codigo):
    """Estado, fechas, habitación y total de la reserva, leídos de la base."""
    return admin_db.execute(
        "SELECT r.estado, r.fecha_entrada, r.fecha_salida, h.numero, r.total "
        "FROM reservas r JOIN habitaciones h ON h.id = r.habitacion_id WHERE r.codigo = %s",
        (codigo,)).fetchone()


@pytest.fixture
def recepcion(cliente_http):
    """Cabecera de sesión de la cuenta de recepción."""
    return iniciar_sesion(cliente_http, "recepcion@soluna.test")


# ------------------------------------------------------------- permisos
@pytest.mark.parametrize("correo, esperado", [
    ("recepcion@soluna.test", 200), ("gerencia@soluna.test", 200),
    ("cliente@soluna.test", 403), ("limpieza@soluna.test", 403), ("mantenimiento@soluna.test", 403),
])
def test_solo_recepcion_y_gerencia_gestionan(cliente_http, admin_db, correo, esperado):
    """La búsqueda, el detalle y el check-in son exclusivos de recepción y gerencia."""
    reserva_bd(admin_db, "SOL-PERM01", hoy(), hoy() + timedelta(days=2))
    cabecera = iniciar_sesion(cliente_http, correo)
    assert cliente_http.get("/api/gestion/reservas", headers=cabecera).status_code == esperado
    assert cliente_http.get("/api/gestion/reservas/SOL-PERM01", headers=cabecera).status_code == esperado
    if esperado == 403:
        r = cliente_http.post("/api/gestion/reservas/SOL-PERM01/check-in", headers=cabecera)
        assert r.status_code == 403
    assert cliente_http.get("/api/gestion/reservas").status_code == 401


# ------------------------------------------------------------- búsqueda
def test_vistas_de_recepcion(cliente_http, admin_db, recepcion):
    """Llegadas, salidas, huéspedes en casa, activas y todas devuelven lo que corresponde."""
    dia = hoy()
    reserva_bd(admin_db, "SOL-LLEGA1", dia, dia + timedelta(days=2), habitacion_id=H101)
    reserva_bd(admin_db, "SOL-ATRAS1", dia - timedelta(days=1), dia + timedelta(days=2), habitacion_id=H102)
    reserva_bd(admin_db, "SOL-ENCAS1", dia - timedelta(days=2), dia + timedelta(days=3), "en_curso", H103)
    reserva_bd(admin_db, "SOL-SALE01", dia - timedelta(days=3), dia, "en_curso", H201)
    reserva_bd(admin_db, "SOL-FUTUR1", dia + timedelta(days=10), dia + timedelta(days=12), habitacion_id=H101)
    reserva_bd(admin_db, "SOL-CANCE1", dia, dia + timedelta(days=1), "cancelada", habitacion_id=H101)

    def codigos(vista):
        r = cliente_http.get(f"/api/gestion/reservas?vista={vista}", headers=recepcion)
        assert r.status_code == 200, r.text
        return {x["codigo"] for x in r.json()}

    assert codigos("llegadas") == {"SOL-LLEGA1", "SOL-ATRAS1"}   # incluye la llegada atrasada
    assert codigos("salidas") == {"SOL-SALE01"}
    assert codigos("en_casa") == {"SOL-ENCAS1", "SOL-SALE01"}
    assert codigos("activas") == {"SOL-LLEGA1", "SOL-ATRAS1", "SOL-ENCAS1", "SOL-SALE01", "SOL-FUTUR1"}
    assert "SOL-CANCE1" in codigos("todas")


@pytest.mark.parametrize("texto, esperados", [
    ("sol-encas1", {"SOL-ENCAS1"}),          # código sin importar mayúsculas
    ("MORA", {"SOL-ENCAS1"}),                # parte del nombre
    ("luis@", {"SOL-OTRO01"}),               # parte del correo
    ("102", {"SOL-OTRO01"}),                 # número exacto de habitación
    ("%", set()),                            # los comodines se buscan como texto
    ("_", set()),
])
def test_busqueda_por_texto(cliente_http, admin_db, recepcion, texto, esperados):
    """El texto se busca en el código, el nombre y el correo, o como número de habitación."""
    dia = hoy()
    reserva_bd(admin_db, "SOL-ENCAS1", dia - timedelta(days=1), dia + timedelta(days=2), "en_curso", H101)
    reserva_bd(admin_db, "SOL-OTRO01", dia + timedelta(days=5), dia + timedelta(days=7), habitacion_id=H102,
               nombre="Luis Arce", correo="luis@correo.test")
    r = cliente_http.get("/api/gestion/reservas", params={"q": texto}, headers=recepcion)
    assert r.status_code == 200, r.text
    assert {x["codigo"] for x in r.json()} == esperados


# ------------------------------------------------------------- día completo en recepción
def test_ciclo_de_un_dia_en_recepcion(cliente_http, admin_db, recepcion, correos):
    """El huésped que llega no entra hasta que sale el anterior y limpieza prepara la habitación.

    1. La habitación 101 todavía está ocupada: el check-in se rechaza.
    2. Sale el huésped anterior: su reserva se finaliza y la habitación queda sucia.
    3. Con la habitación sucia, el check-in se rechaza.
    4. Limpieza la deja lista y el check-in funciona.
    """
    dia = hoy()
    reserva_bd(admin_db, "SOL-ANTER1", dia - timedelta(days=3), dia, "en_curso", H101,
               nombre="Pedro Vargas", correo="pedro@correo.test")
    reserva_bd(admin_db, "SOL-NUEVO1", dia, dia + timedelta(days=2), "confirmada", H101)
    entrar = "/api/gestion/reservas/SOL-NUEVO1/check-in"

    r = cliente_http.post(entrar, headers=recepcion)
    assert r.status_code == 409 and "SOL-ANTER1" in r.json()["detail"]

    # El hospedaje se paga en el hotel: sin método de pago la salida se rechaza; con él, se cobra
    r = cliente_http.post("/api/gestion/reservas/SOL-ANTER1/check-out", headers=recepcion)
    assert r.status_code == 409 and "saldo pendiente" in r.json()["detail"]
    r = cliente_http.post("/api/gestion/reservas/SOL-ANTER1/check-out", headers=recepcion, json={"metodo_pago": "efectivo"})
    assert r.status_code == 200 and r.json()["estado"] == "finalizada", r.text
    assert estado_bd(admin_db, "SOL-ANTER1")[2] == dia          # salió el día previsto: fecha intacta
    assert admin_db.execute("SELECT estado_limpieza FROM habitaciones WHERE id = 1").fetchone()[0] == "sucia"
    assert correos[-1]["destino"] == "pedro@correo.test" and "reseña" in correos[-1]["cuerpo"]

    r = cliente_http.post(entrar, headers=recepcion)
    assert r.status_code == 409 and "no está lista" in r.json()["detail"]

    personal_limpieza = iniciar_sesion(cliente_http, "limpieza@soluna.test")
    assert cliente_http.patch("/api/habitaciones/1/limpieza", headers=personal_limpieza,
                              json={"estado": "limpia"}).status_code == 200
    r = cliente_http.post(entrar, headers=recepcion)
    assert r.status_code == 200 and r.json()["estado"] == "en_curso", r.text

    # El detalle ofrece ahora el check-out y el historial dice quién hizo qué
    detalle = cliente_http.get("/api/gestion/reservas/SOL-NUEVO1", headers=recepcion).json()
    assert detalle["acciones"] == ["check_out", "modificar"]
    assert [(e["accion"], e["usuario"]) for e in detalle["historial"]] == [("check_in", "Recepción Soluna")]


@pytest.mark.parametrize("estado, entrada, salida, fuera_de_servicio, mensaje", [
    ("pendiente_pago", 0, 2, False, "pendiente de pago"),
    ("confirmada", 3, 5, False, "prevista para el"),       # todavía no llega
    ("confirmada", -4, -1, False, "terminó"),               # la estadía ya pasó
    ("confirmada", 0, 2, True, "fuera de servicio"),
    ("en_curso", -1, 2, False, "en curso"),                 # ya ingresó
    ("cancelada", 0, 2, False, "cancelada"),
])
def test_check_in_rechazado(cliente_http, admin_db, recepcion, estado, entrada, salida,
                            fuera_de_servicio, mensaje):
    """El check-in exige una reserva confirmada, la fecha correcta y una habitación en servicio."""
    dia = hoy()
    reserva_bd(admin_db, "SOL-RECHA1", dia + timedelta(days=entrada), dia + timedelta(days=salida), estado)
    limpieza(admin_db, H101, "limpia", fuera_de_servicio)
    r = cliente_http.post("/api/gestion/reservas/SOL-RECHA1/check-in", headers=recepcion)
    assert r.status_code == 409 and mensaje in r.json()["detail"], r.text
    assert estado_bd(admin_db, "SOL-RECHA1")[0] == estado


def test_llegada_atrasada_puede_ingresar(cliente_http, admin_db, recepcion):
    """Una reserva que empezó ayer y no se registró aún admite el check-in hoy."""
    dia = hoy()
    reserva_bd(admin_db, "SOL-ATRAS1", dia - timedelta(days=1), dia + timedelta(days=2))
    r = cliente_http.post("/api/gestion/reservas/SOL-ATRAS1/check-in", headers=recepcion)
    assert r.status_code == 200 and r.json()["estado"] == "en_curso"


def test_check_out_solo_de_estadia_en_curso(cliente_http, admin_db, recepcion):
    """La salida de una reserva que no ha ingresado, o que ya salió, se rechaza con 409."""
    dia = hoy()
    reserva_bd(admin_db, "SOL-CONFI1", dia, dia + timedelta(days=2))
    reserva_bd(admin_db, "SOL-FINAL1", dia - timedelta(days=5), dia - timedelta(days=2), "finalizada", H102)
    for codigo in ("SOL-CONFI1", "SOL-FINAL1"):
        r = cliente_http.post(f"/api/gestion/reservas/{codigo}/check-out", headers=recepcion)
        assert r.status_code == 409, r.text


def test_salida_anticipada_libera_las_noches(cliente_http, admin_db, recepcion):
    """Si el huésped se va antes, la salida pasa a hoy, el monto no cambia y la habitación se libera."""
    dia = hoy()
    reserva_bd(admin_db, "SOL-ANTIC1", dia - timedelta(days=1), dia + timedelta(days=4), "en_curso")
    total = estado_bd(admin_db, "SOL-ANTIC1")[4]
    libres = lambda: {h["numero"] for h in cliente_http.get(  # noqa: E731
        "/api/disponibilidad", params={"entrada": str(dia), "salida": str(dia + timedelta(days=4))}).json()}
    assert "101" not in libres()

    r = cliente_http.post("/api/gestion/reservas/SOL-ANTIC1/check-out", headers=recepcion, json={"metodo_pago": "efectivo"})
    assert r.status_code == 200, r.text
    assert estado_bd(admin_db, "SOL-ANTIC1") == ("finalizada", dia - timedelta(days=1), dia, "101", total)
    assert "101" in libres()
    detalle = admin_db.execute("SELECT detalle FROM bitacora WHERE accion = 'check_out'").fetchone()[0]
    assert detalle["salida_prevista"] == str(dia + timedelta(days=4))


# ------------------------------------------------------------- cambios
def test_cambio_de_habitacion_recalcula_el_total(cliente_http, admin_db, recepcion, correos):
    """Pasar de una estándar a una superior cobra la tarifa superior y avisa al huésped."""
    dia = hoy()
    entrada, salida = dia + timedelta(days=20), dia + timedelta(days=23)
    reserva_bd(admin_db, "SOL-CAMBI1", entrada, salida)
    r = cliente_http.patch("/api/gestion/reservas/SOL-CAMBI1", headers=recepcion, json={"habitacion_id": H201})
    assert r.status_code == 200, r.text
    assert r.json()["habitacion"] == "201" and r.json()["tipo"] == "superior"
    assert Decimal(r.json()["total"]) == precio(SUPERIOR, entrada, salida)
    assert correos[-1]["asunto"] == "Reserva modificada SOL-CAMBI1" and "Habitación: 201" in correos[-1]["cuerpo"]
    detalle = admin_db.execute("SELECT detalle FROM bitacora WHERE accion = 'modificar_reserva'").fetchone()[0]
    assert detalle["antes"]["habitacion"] == "101" and detalle["despues"]["habitacion"] == "201"


def test_cambio_de_fechas_y_personas(cliente_http, admin_db, recepcion, correos):
    """Mover las fechas recalcula el total; cambiar solo las personas no avisa por correo."""
    dia = hoy()
    reserva_bd(admin_db, "SOL-FECHA1", dia + timedelta(days=20), dia + timedelta(days=22))
    nueva_entrada, nueva_salida = dia + timedelta(days=30), dia + timedelta(days=35)
    r = cliente_http.patch("/api/gestion/reservas/SOL-FECHA1", headers=recepcion, json={
        "fecha_entrada": str(nueva_entrada), "fecha_salida": str(nueva_salida)})
    assert r.status_code == 200, r.text
    assert Decimal(r.json()["total"]) == precio(ESTANDAR, nueva_entrada, nueva_salida)
    enviados = len(correos)

    r = cliente_http.patch("/api/gestion/reservas/SOL-FECHA1", headers=recepcion, json={"personas": 1})
    assert r.status_code == 200 and r.json()["personas"] == 1
    assert len(correos) == enviados

    r = cliente_http.patch("/api/gestion/reservas/SOL-FECHA1", headers=recepcion, json={"personas": 1})
    assert r.status_code == 422                                   # nada cambió
    r = cliente_http.patch("/api/gestion/reservas/SOL-FECHA1", headers=recepcion, json={"personas": 3})
    assert r.status_code == 422                                   # una estándar admite 2


def test_no_se_mueve_a_una_habitacion_ocupada(cliente_http, admin_db, recepcion):
    """La regla contra la sobreventa de la base también protege los cambios: 409."""
    dia = hoy()
    reserva_bd(admin_db, "SOL-DUENO1", dia + timedelta(days=20), dia + timedelta(days=23), habitacion_id=H101)
    reserva_bd(admin_db, "SOL-INTRU1", dia + timedelta(days=22), dia + timedelta(days=25), habitacion_id=H102)
    r = cliente_http.patch("/api/gestion/reservas/SOL-INTRU1", headers=recepcion, json={"habitacion_id": H101})
    assert r.status_code == 409 and "no está libre" in r.json()["detail"]
    assert estado_bd(admin_db, "SOL-INTRU1")[3] == "102"


@pytest.mark.parametrize("cambio, codigo, mensaje", [
    ({"fecha_entrada": "AYER"}, 409, "ya ingresó"),
    ({"fecha_salida": "HOY"}, 422, "registre su salida"),
])
def test_huesped_en_casa_reglas_de_fechas(cliente_http, admin_db, recepcion, cambio, codigo, mensaje):
    """Con el huésped alojado, la entrada no cambia y la salida no puede ser hoy ni antes."""
    dia = hoy()
    reserva_bd(admin_db, "SOL-ENCAS1", dia - timedelta(days=2), dia + timedelta(days=2), "en_curso")
    valores = {"AYER": str(dia - timedelta(days=1)), "HOY": str(dia)}
    r = cliente_http.patch("/api/gestion/reservas/SOL-ENCAS1", headers=recepcion,
                           json={k: valores[v] for k, v in cambio.items()})
    assert r.status_code == codigo and mensaje in r.json()["detail"], r.text


def test_huesped_en_casa_extiende_y_cambia_de_habitacion(cliente_http, admin_db, recepcion):
    """Extender recalcula el total; mudarse exige una habitación lista y deja sucia la anterior."""
    dia = hoy()
    entrada = dia - timedelta(days=1)
    reserva_bd(admin_db, "SOL-ENCAS1", entrada, dia + timedelta(days=2), "en_curso")
    r = cliente_http.patch("/api/gestion/reservas/SOL-ENCAS1", headers=recepcion,
                           json={"fecha_salida": str(dia + timedelta(days=4))})
    assert r.status_code == 200 and Decimal(r.json()["total"]) == precio(ESTANDAR, entrada, dia + timedelta(days=4))

    limpieza(admin_db, H102, "sucia")
    r = cliente_http.patch("/api/gestion/reservas/SOL-ENCAS1", headers=recepcion, json={"habitacion_id": H102})
    assert r.status_code == 409 and "no está lista" in r.json()["detail"]

    r = cliente_http.patch("/api/gestion/reservas/SOL-ENCAS1", headers=recepcion, json={"habitacion_id": H103})
    assert r.status_code == 200 and r.json()["habitacion"] == "103"
    assert admin_db.execute("SELECT estado_limpieza FROM habitaciones WHERE id = 1").fetchone()[0] == "sucia"


def test_reserva_pagada_no_cambia_de_monto(cliente_http, admin_db, recepcion):
    """Si ya se pagó y facturó en línea, solo se aceptan cambios que no alteran el monto."""
    dia = hoy()
    entrada, salida = dia + timedelta(days=20), dia + timedelta(days=22)
    reserva_bd(admin_db, "SOL-PAGAD1", entrada, salida)
    subtotal = precio(ESTANDAR, entrada, salida)
    impuesto = (subtotal * Decimal("0.13")).quantize(Decimal("0.01"))
    admin_db.execute(
        "INSERT INTO facturas (reserva_id, clave, consecutivo, subtotal, impuesto, total) "
        "SELECT id, repeat('1', 50), repeat('2', 20), %s, %s, %s FROM reservas WHERE codigo = 'SOL-PAGAD1'",
        (subtotal, impuesto, subtotal + impuesto))

    r = cliente_http.patch("/api/gestion/reservas/SOL-PAGAD1", headers=recepcion,
                           json={"fecha_salida": str(salida + timedelta(days=1))})
    assert r.status_code == 409 and "reserva nueva" in r.json()["detail"]
    # Otra estándar en las mismas fechas cuesta lo mismo: se permite
    r = cliente_http.patch("/api/gestion/reservas/SOL-PAGAD1", headers=recepcion, json={"habitacion_id": H102})
    assert r.status_code == 200 and r.json()["habitacion"] == "102"


@pytest.mark.parametrize("estado", ["finalizada", "cancelada"])
def test_reserva_cerrada_no_se_modifica(cliente_http, admin_db, recepcion, estado):
    """Las reservas finalizadas o canceladas son historia: no se modifican (409)."""
    dia = hoy()
    reserva_bd(admin_db, "SOL-CERRA1", dia - timedelta(days=5), dia - timedelta(days=2), estado)
    r = cliente_http.patch("/api/gestion/reservas/SOL-CERRA1", headers=recepcion, json={"personas": 1})
    assert r.status_code == 409
    detalle = cliente_http.get("/api/gestion/reservas/SOL-CERRA1", headers=recepcion).json()
    assert detalle["acciones"] == []


def test_alternativas_de_habitacion(cliente_http, admin_db, recepcion):
    """Ofrece la habitación actual y las libres, sin las ocupadas ni las sucias si el huésped ya está."""
    dia = hoy()
    reserva_bd(admin_db, "SOL-ENCAS1", dia - timedelta(days=1), dia + timedelta(days=2), "en_curso", H101)
    reserva_bd(admin_db, "SOL-OCUPA1", dia, dia + timedelta(days=1), "confirmada", H102)
    limpieza(admin_db, H103, "sucia")
    r = cliente_http.get("/api/gestion/reservas/SOL-ENCAS1/alternativas", headers=recepcion)
    assert r.status_code == 200, r.text
    opciones = {o["numero"]: o for o in r.json()}
    assert opciones["101"]["actual"] is True
    assert "102" not in opciones and "103" not in opciones and "104" in opciones
    assert Decimal(opciones["201"]["total"]) == precio(SUPERIOR, dia - timedelta(days=1), dia + timedelta(days=2))

    # Con 3 personas solo sirven superiores y suites
    r = cliente_http.get("/api/gestion/reservas/SOL-ENCAS1/alternativas?personas=3", headers=recepcion)
    assert {o["tipo"] for o in r.json()} == {"superior", "suite"}
