"""Pagos por SINPE Móvil o transferencia con comprobante que recepción revisa (etapa 6).

Comprueban el envío del cliente (monto, número, archivo y sus validaciones),
los correos de cada paso, la bandeja y el archivo para recepción, la
aceptación (pago, confirmación y factura) y el rechazo con motivo, el
bloqueo del pago con tarjeta mientras hay un comprobante en revisión, la
cancelación, la retención de las imágenes y los permisos de la base.
"""
import base64
import os
from datetime import date, timedelta
from decimal import Decimal

import httpx
import psycopg
import pytest

from app import config

from .conftest import iniciar_sesion

ENTRADA = date.today() + timedelta(days=60)
SALIDA = ENTRADA + timedelta(days=2)
# Una imagen PNG real de 1 x 1 píxel
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")
PNG_B64 = base64.b64encode(PNG).decode()


@pytest.fixture(autouse=True)
def _simulador(simulador):
    """La aceptación emite la factura y la envía al simulador de Hacienda."""
    return simulador


@pytest.fixture
def cliente(cliente_http):
    """Sesión del cliente de prueba."""
    return iniciar_sesion(cliente_http, "cliente@soluna.test")


@pytest.fixture
def recepcion(cliente_http):
    """Sesión de recepción."""
    return iniciar_sesion(cliente_http, "recepcion@soluna.test")


def reservar(cliente_http, cliente, habitacion_id=1):
    """Reserva en línea del cliente, pendiente de pago."""
    r = cliente_http.post("/api/reservas", headers=cliente, json={
        "habitacion_id": habitacion_id, "fecha_entrada": str(ENTRADA), "fecha_salida": str(SALIDA), "personas": 2})
    assert r.status_code == 201, r.text
    return r.json()


def enviar(cliente_http, cliente, reserva, **cambios):
    """Envía un comprobante por SINPE Móvil con el monto exacto y la imagen, salvo lo que se cambie."""
    cuerpo = {"metodo": "sinpe", "numero": "FT26110042", "monto": reserva["total_con_impuesto"], "archivo": PNG_B64,
              **cambios}
    return cliente_http.post(f"/api/reservas/{reserva['codigo']}/comprobantes", headers=cliente, json=cuerpo)


def pendiente(cliente_http, recepcion):
    """El único comprobante de la bandeja de pendientes."""
    bandeja = cliente_http.get("/api/gestion/comprobantes", headers=recepcion).json()
    assert len(bandeja) == 1, bandeja
    return bandeja[0]


def test_envio_con_imagen_acuse_y_aviso(cliente_http, admin_db, cliente, correos):
    """El cliente ve el monto y los datos del hotel, envía el comprobante y la reserva queda en revisión.

    El número se guarda sin espacios y en mayúsculas. Llegan dos correos: el
    acuse al cliente y el aviso al buzón de recepción, con el total esperado.
    """
    reserva = reservar(cliente_http, cliente)
    datos = cliente_http.get(f"/api/reservas/{reserva['codigo']}/comprobantes", headers=cliente).json()
    assert (datos["monto"], datos["sinpe"], datos["cuenta"], datos["comprobantes"]) == \
        (reserva["total_con_impuesto"], config.SINPE_HOTEL, config.CUENTA_HOTEL, [])

    r = enviar(cliente_http, cliente, reserva, numero=" ft 2611-0042 ")
    assert r.status_code == 201, r.text
    [comprobante] = r.json()["comprobantes"]
    assert (comprobante["numero"], comprobante["estado"], comprobante["tiene_archivo"], comprobante["tipo_archivo"]) == \
        ("FT2611-0042", "pendiente", True, "image/png")
    assert comprobante["revisado_por"] is None

    vista = cliente_http.get(f"/api/reservas/{reserva['codigo']}", headers=cliente).json()
    assert (vista["estado"], vista["comprobante_estado"]) == ("pendiente_pago", "pendiente")
    guardado = admin_db.execute("SELECT archivo FROM comprobantes").fetchone()[0]
    assert bytes(guardado) == PNG

    acuse, aviso = correos
    assert acuse["destino"] == "cliente@soluna.test"
    assert acuse["asunto"] == f"Recibimos su comprobante de pago ({reserva['codigo']})"
    assert "FT2611-0042" in acuse["cuerpo"] and "sigue pendiente de pago" in acuse["cuerpo"]
    assert aviso["destino"] == config.CORREO_RECEPCION
    assert aviso["asunto"] == f"Comprobante por revisar: {reserva['codigo']}"
    assert f"total esperado: USD {reserva['total_con_impuesto']}" in aviso["cuerpo"]
    detalle = admin_db.execute("SELECT detalle FROM bitacora WHERE accion = 'comprobante_enviado'").fetchone()[0]
    assert (detalle["metodo"], detalle["numero"], detalle["archivo"]) == ("sinpe", "FT2611-0042", "image/png")


def test_sin_archivo_y_pdf(cliente_http, cliente, recepcion):
    """El archivo es opcional, y un PDF se acepta igual que una imagen."""
    sin = reservar(cliente_http, cliente, habitacion_id=1)
    assert enviar(cliente_http, cliente, sin, archivo=None).json()["comprobantes"][0]["tiene_archivo"] is False
    con_pdf = reservar(cliente_http, cliente, habitacion_id=2)
    pdf = base64.b64encode(b"%PDF-1.4\n%prueba\n").decode()
    r = enviar(cliente_http, cliente, con_pdf, numero="TRF-0099", metodo="transferencia", archivo=pdf)
    assert r.json()["comprobantes"][0]["tipo_archivo"] == "application/pdf"


@pytest.mark.parametrize("cambios, texto", [
    ({"monto": "1.00"}, "El monto pagado debe ser"),
    ({"archivo": "esto no es base64!!"}, "no llegó completo"),
    ({"archivo": base64.b64encode(b"GIF89a" + b"0" * 20).decode()}, "JPG o PNG, o un PDF"),
    ({"archivo": base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 1_572_864).decode()}, "supera 1,5 MB"),
    ({"numero": "ab"}, "de 4 a 40"),
    ({"numero": "FT 26/11"}, "de 4 a 40"),
    ({"metodo": "tarjeta"}, "metodo"),
])
def test_validaciones(cliente_http, admin_db, cliente, correos, cambios, texto):
    """Lo inválido se rechaza con 422, sin guardar nada ni enviar correos."""
    reserva = reservar(cliente_http, cliente)
    r = enviar(cliente_http, cliente, reserva, **cambios)
    assert r.status_code == 422 and texto in r.text, r.text
    assert admin_db.execute("SELECT count(*) FROM comprobantes").fetchone()[0] == 0
    assert correos == []


def test_un_comprobante_a_la_vez_y_numero_unico(cliente_http, cliente, recepcion):
    """No se envía un segundo comprobante mientras el primero está en revisión, ni se repite un número.

    Recepción, que registra los pagos en la cuenta de la habitación, no envía comprobantes.
    """
    reserva = reservar(cliente_http, cliente, habitacion_id=1)
    assert enviar(cliente_http, cliente, reserva).status_code == 201
    assert enviar(cliente_http, cliente, reserva, numero="OTRO-1234").status_code == 409
    otra = reservar(cliente_http, cliente, habitacion_id=2)
    r = enviar(cliente_http, cliente, otra)
    assert r.status_code == 409 and "ya se registró" in r.text
    # El mismo número por otro método es otro comprobante
    assert enviar(cliente_http, cliente, otra, metodo="transferencia").status_code == 201
    assert enviar(cliente_http, recepcion, reserva, numero="RECEP-0001").status_code == 403


def test_solo_el_titular(cliente_http, cliente):
    """Para otro cliente, la reserva ajena no existe (404), al ver ni al enviar."""
    reserva = reservar(cliente_http, cliente)
    assert cliente_http.post("/api/auth/registro", json={
        "nombre": "Otra Clienta", "correo": "otra@correo.test", "contrasena": "Segura2026"}).status_code == 201
    otra = iniciar_sesion(cliente_http, "otra@correo.test", "Segura2026")
    assert cliente_http.get(f"/api/reservas/{reserva['codigo']}/comprobantes", headers=otra).status_code == 404
    assert enviar(cliente_http, otra, reserva).status_code == 404


def test_tarjeta_bloqueada_mientras_se_revisa(cliente_http, cliente, simulador):
    """Con un comprobante en revisión, la reserva no se cobra con tarjeta (409); una pagada no recibe comprobantes."""
    reserva = reservar(cliente_http, cliente, habitacion_id=1)
    assert enviar(cliente_http, cliente, reserva).status_code == 201
    token = httpx.post(f"{simulador}/pasarela/tokens", json={
        "numero": "4242 4242 4242 4242", "titular": "Cliente de Prueba", "vencimiento": "12/39", "cvv": "123"}
    ).json()["token"]
    r = cliente_http.post(f"/api/reservas/{reserva['codigo']}/pago", headers=cliente, json={"token": token})
    assert r.status_code == 409 and "revisando" in r.text

    pagada = reservar(cliente_http, cliente, habitacion_id=2)
    token = httpx.post(f"{simulador}/pasarela/tokens", json={
        "numero": "4242 4242 4242 4242", "titular": "Cliente de Prueba", "vencimiento": "12/39", "cvv": "123"}
    ).json()["token"]
    assert cliente_http.post(f"/api/reservas/{pagada['codigo']}/pago", headers=cliente,
                             json={"token": token}).status_code == 200
    assert enviar(cliente_http, cliente, pagada, numero="TARDE-0001").status_code == 409


def test_bandeja_y_archivo_para_recepcion(cliente_http, cliente, recepcion):
    """Recepción ve el comprobante con su reserva y el monto esperado, y abre la imagen tal como se envió."""
    reserva = reservar(cliente_http, cliente)
    enviar(cliente_http, cliente, reserva)
    c = pendiente(cliente_http, recepcion)
    assert (c["codigo"], c["habitacion"], c["monto"], c["monto_esperado"], c["estado_reserva"], c["tiene_archivo"]) == \
        (reserva["codigo"], "101", reserva["total_con_impuesto"], reserva["total_con_impuesto"], "pendiente_pago",
         True)
    archivo = cliente_http.get(f"/api/gestion/comprobantes/{c['id']}/archivo", headers=recepcion)
    assert archivo.status_code == 200 and archivo.content == PNG
    assert archivo.headers["content-type"] == "image/png"
    assert archivo.headers["cache-control"] == "private, no-store"
    assert archivo.headers["x-content-type-options"] == "nosniff"
    assert cliente_http.get("/api/gestion/comprobantes?vista=revisados", headers=recepcion).json() == []


@pytest.mark.parametrize("cuenta", ["cliente@soluna.test", "limpieza@soluna.test"])
def test_bandeja_solo_para_recepcion_y_gerencia(cliente_http, cliente, recepcion, cuenta):
    """Ni el cliente ni limpieza ven la bandeja, los archivos ni las acciones de revisión."""
    reserva = reservar(cliente_http, cliente)
    enviar(cliente_http, cliente, reserva)
    cid = pendiente(cliente_http, recepcion)["id"]
    otro = iniciar_sesion(cliente_http, cuenta)
    assert cliente_http.get("/api/gestion/comprobantes", headers=otro).status_code == 403
    assert cliente_http.get(f"/api/gestion/comprobantes/{cid}/archivo", headers=otro).status_code == 403
    assert cliente_http.post(f"/api/gestion/comprobantes/{cid}/aceptar", headers=otro).status_code == 403
    gerencia = iniciar_sesion(cliente_http, "gerencia@soluna.test")
    assert len(cliente_http.get("/api/gestion/comprobantes", headers=gerencia).json()) == 1


def test_aceptar_confirma_y_factura(cliente_http, admin_db, cliente, recepcion, correos):
    """Al aceptar se registra el pago, la reserva queda confirmada con su factura y el cliente recibe la confirmación."""
    reserva = reservar(cliente_http, cliente)
    enviar(cliente_http, cliente, reserva)
    cid = pendiente(cliente_http, recepcion)["id"]
    correos.clear()

    r = cliente_http.post(f"/api/gestion/comprobantes/{cid}/aceptar", headers=recepcion)
    assert r.status_code == 200, r.text
    assert (r.json()["estado"], r.json()["revisado_por"], r.json()["estado_reserva"]) == \
        ("aceptado", "Recepción Soluna", "confirmada")
    assert r.json()["revisado_en"] is not None

    vista = cliente_http.get(f"/api/reservas/{reserva['codigo']}", headers=cliente).json()
    assert (vista["estado"], vista["tiene_factura"], vista["comprobante_estado"]) == ("confirmada", True, "aceptado")
    factura = cliente_http.get(f"/api/reservas/{reserva['codigo']}/factura", headers=cliente).json()
    assert factura["estado"] == "aceptada" and factura["total"] == reserva["total_con_impuesto"]
    transaccion, monto, marca = admin_db.execute(
        "SELECT transaccion, monto, marca FROM pagos WHERE tipo = 'cobro'").fetchone()
    assert (transaccion, monto, marca) == (f"comp_{cid}", Decimal(reserva["total_con_impuesto"]), "SINPE Móvil")

    [confirmacion] = correos
    assert confirmacion["asunto"] == f"Reserva confirmada {reserva['codigo']}"
    for texto in ("por SINPE Móvil (comprobante FT26110042)", "verificado por la recepción",
                  factura["consecutivo"], factura["clave"]):
        assert texto in confirmacion["cuerpo"], texto
    assert admin_db.execute("SELECT detalle->>'factura' FROM bitacora WHERE accion = 'comprobante_aceptado'"
                            ).fetchone()[0] == factura["consecutivo"]

    # Ya revisado: no se acepta ni se rechaza de nuevo, y pasa a la vista de revisados
    assert cliente_http.post(f"/api/gestion/comprobantes/{cid}/aceptar", headers=recepcion).status_code == 409
    assert cliente_http.post(f"/api/gestion/comprobantes/{cid}/rechazar", headers=recepcion,
                             json={"motivo": "Prueba"}).status_code == 409
    assert cliente_http.get("/api/gestion/comprobantes", headers=recepcion).json() == []
    revisados = cliente_http.get("/api/gestion/comprobantes?vista=revisados", headers=recepcion).json()
    assert [c["id"] for c in revisados] == [cid]


def test_rechazar_con_motivo_y_reenviar(cliente_http, admin_db, cliente, recepcion, correos):
    """El rechazo exige un motivo, que llega al cliente por correo; después puede enviar otro, incluso con el mismo número."""
    reserva = reservar(cliente_http, cliente)
    enviar(cliente_http, cliente, reserva)
    cid = pendiente(cliente_http, recepcion)["id"]
    correos.clear()
    assert cliente_http.post(f"/api/gestion/comprobantes/{cid}/rechazar", headers=recepcion,
                             json={"motivo": "  "}).status_code == 422

    r = cliente_http.post(f"/api/gestion/comprobantes/{cid}/rechazar", headers=recepcion,
                          json={"motivo": "  El número  no aparece en la cuenta del hotel. "})
    assert r.status_code == 200, r.text
    assert (r.json()["estado"], r.json()["motivo"]) == ("rechazado", "El número no aparece en la cuenta del hotel.")
    [aviso] = correos
    assert aviso["asunto"] == f"No pudimos confirmar su pago ({reserva['codigo']})"
    assert "El número no aparece en la cuenta del hotel." in aviso["cuerpo"]
    assert "Puede enviar un nuevo comprobante" in aviso["cuerpo"]

    vista = cliente_http.get(f"/api/reservas/{reserva['codigo']}", headers=cliente).json()
    assert (vista["estado"], vista["comprobante_estado"], vista["comprobante_motivo"]) == \
        ("pendiente_pago", "rechazado", "El número no aparece en la cuenta del hotel.")
    assert admin_db.execute("SELECT count(*) FROM pagos").fetchone()[0] == 0
    assert enviar(cliente_http, cliente, reserva).status_code == 201
    # La reserva muestra el comprobante más reciente: el nuevo, en revisión
    vista = cliente_http.get(f"/api/reservas/{reserva['codigo']}", headers=cliente).json()
    assert (vista["comprobante_estado"], vista["comprobante_motivo"]) == ("pendiente", None)


def test_cancelar_anula_el_comprobante_pendiente(cliente_http, admin_db, cliente, correos):
    """Si el cliente cancela antes de la revisión, el comprobante queda sin efecto y el correo lo explica."""
    reserva = reservar(cliente_http, cliente)
    enviar(cliente_http, cliente, reserva)
    assert cliente_http.post(f"/api/reservas/{reserva['codigo']}/cancelar", headers=cliente).status_code == 200
    estado, motivo = admin_db.execute("SELECT estado, motivo FROM comprobantes").fetchone()
    assert estado == "rechazado" and "se canceló" in motivo
    assert "quedó sin efecto" in correos[-1]["cuerpo"]


def test_cancelar_pagada_con_comprobante(cliente_http, admin_db, cliente, recepcion, correos):
    """La devolución de un pago por SINPE no pasa por la pasarela: queda registrada y el correo dice cómo se hará."""
    reserva = reservar(cliente_http, cliente)
    enviar(cliente_http, cliente, reserva)
    cid = pendiente(cliente_http, recepcion)["id"]
    cliente_http.post(f"/api/gestion/comprobantes/{cid}/aceptar", headers=recepcion)
    r = cliente_http.post(f"/api/reservas/{reserva['codigo']}/cancelar", headers=cliente)
    assert r.status_code == 200 and r.json()["estado"] == "cancelada"
    assert admin_db.execute("SELECT transaccion FROM pagos WHERE tipo = 'reembolso'").fetchone()[0] == f"dev_comp_{cid}"
    assert f"Le devolveremos USD {reserva['total_con_impuesto']} por SINPE Móvil" in correos[-1]["cuerpo"]


def test_la_retencion_borra_solo_imagenes_viejas(cliente_http, admin_db, cliente, recepcion):
    """El mantenimiento borra la imagen de un comprobante revisado hace más de 90 días y conserva el registro."""
    viejo = reservar(cliente_http, cliente, habitacion_id=1)
    enviar(cliente_http, cliente, viejo)
    cid = pendiente(cliente_http, recepcion)["id"]
    cliente_http.post(f"/api/gestion/comprobantes/{cid}/rechazar", headers=recepcion, json={"motivo": "Ilegible"})
    reciente = reservar(cliente_http, cliente, habitacion_id=2)
    enviar(cliente_http, cliente, reciente, numero="NUEVO-0001")
    admin_db.execute("UPDATE comprobantes SET revisado_en = now() - interval '91 days' WHERE id = %s", (cid,))

    assert "1 imágenes de comprobantes" in admin_db.execute("SELECT mantenimiento()").fetchone()[0]
    filas = admin_db.execute("SELECT numero, archivo IS NULL, tipo_archivo FROM comprobantes ORDER BY id").fetchall()
    assert filas == [("FT26110042", True, "image/png"), ("NUEVO-0001", False, "image/png")]
    assert cliente_http.get(f"/api/gestion/comprobantes/{cid}/archivo", headers=recepcion).status_code == 404


def test_la_api_no_puede_borrar_ni_alterar_comprobantes(cliente_http, cliente):
    """El usuario de la API no borra comprobantes ni cambia lo que envió el cliente."""
    reserva = reservar(cliente_http, cliente)
    enviar(cliente_http, cliente, reserva)
    conexion = psycopg.connect(host=os.environ["DB_HOST"], port=os.environ["DB_PORT"],
                               dbname=os.environ.get("DB_NAME", "hotel"), user="app_hotel",
                               password=os.environ["DB_PASSWORD"], autocommit=True)
    with conexion:
        for sql in ("DELETE FROM comprobantes", "UPDATE comprobantes SET monto = 1",
                    "UPDATE comprobantes SET numero = 'X'", "UPDATE comprobantes SET archivo = NULL"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conexion.execute(sql)


def test_no_se_acepta_si_la_reserva_ya_no_espera_pago(cliente_http, admin_db, cliente, recepcion):
    """Si la reserva dejó de estar pendiente de pago por otra vía, aceptar responde 409 y no registra el pago."""
    reserva = reservar(cliente_http, cliente)
    enviar(cliente_http, cliente, reserva)
    cid = pendiente(cliente_http, recepcion)["id"]
    admin_db.execute("UPDATE reservas SET estado = 'confirmada' WHERE codigo = %s", (reserva["codigo"],))
    r = cliente_http.post(f"/api/gestion/comprobantes/{cid}/aceptar", headers=recepcion)
    assert r.status_code == 409 and "ya no está pendiente de pago" in r.text
    assert admin_db.execute("SELECT count(*) FROM pagos").fetchone()[0] == 0
    assert admin_db.execute("SELECT estado FROM comprobantes").fetchone()[0] == "pendiente"
