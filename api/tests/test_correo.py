"""Fase 4: envío por un proveedor real sin rebotes, sin contraseñas en claro y sin abuso."""
import ssl

import pytest

from app import config, correo

# conftest reemplaza correo.enviar en todas las pruebas; aquí se prueba la función real
enviar = correo.enviar


class SMTPFalso:
    """Reemplaza a smtplib.SMTP y anota lo que la API le pide."""
    instancias: list["SMTPFalso"] = []

    def __init__(self, host, puerto, timeout):
        self.host, self.puerto, self.pasos = host, puerto, []
        SMTPFalso.instancias.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def starttls(self, context=None):
        self.pasos.append(("starttls", context))

    def login(self, usuario, contrasena):
        self.pasos.append(("login", usuario))

    def send_message(self, mensaje):
        self.pasos.append(("enviar", mensaje["To"], mensaje["Message-ID"]))


@pytest.fixture
def proveedor(monkeypatch):
    """Configuración como la de Vercel con Brevo, pero sin conectarse a nada."""
    SMTPFalso.instancias.clear()
    monkeypatch.setattr(correo.smtplib, "SMTP", SMTPFalso)
    for nombre, valor in {"SMTP_HOST": "smtp-relay.brevo.com", "SMTP_PORT": 587, "SMTP_TLS": True,
                          "SMTP_USUARIO": "cuenta@smtp-brevo.com", "SMTP_PASSWORD": "x",
                          "CORREO_OMITIR_PRUEBA": True,
                          "CORREO_REMITENTE": "Hotel Soluna <reservas@gmail.com>",
                          "CORREO_DOMINIO": "hotel-soluna-web.vercel.app"}.items():
        monkeypatch.setattr(config, nombre, valor)
    return SMTPFalso.instancias


@pytest.mark.parametrize("destino, de_prueba", [
    ("cliente@soluna.test", True), ("ana@viajero.test", True), ("x@example.com", True),
    ("x@correo.example", True), ("x@sub.example.org", True), ("x@gmail.com", False),
    ("x@ulacit.ac.cr", False), ("x@notexample.com", False),
])
def test_reconoce_dominios_de_prueba(destino, de_prueba):
    assert correo.es_de_prueba(destino) is de_prueba


def test_envia_con_tls_verificado_y_usuario(proveedor):
    enviar("huesped@gmail.com", "Confirmación", "Hola")
    pasos = proveedor[0].pasos
    assert [p[0] for p in pasos] == ["starttls", "login", "enviar"]
    contexto = pasos[0][1]
    assert contexto.verify_mode == ssl.CERT_REQUIRED and contexto.check_hostname
    assert pasos[2][2].endswith("@hotel-soluna-web.vercel.app>")   # Message-ID del hotel, no de Gmail


def test_no_escribe_a_dominios_de_prueba(proveedor):
    enviar("cliente@soluna.test", "Confirmación", "Hola")
    assert proveedor == []


def test_no_envia_la_contrasena_sin_cifrar(proveedor, monkeypatch):
    monkeypatch.setattr(config, "SMTP_TLS", False)
    enviar("huesped@gmail.com", "Confirmación", "Hola")
    assert proveedor == []


def test_mailpit_sigue_recibiendo_dominios_de_prueba(proveedor, monkeypatch):
    """En Docker no se omite nada: Mailpit captura todo y no sale de la máquina."""
    for nombre, valor in {"SMTP_HOST": "mailpit", "SMTP_PORT": 1025, "SMTP_TLS": False,
                          "SMTP_USUARIO": None, "CORREO_OMITIR_PRUEBA": False}.items():
        monkeypatch.setattr(config, nombre, valor)
    enviar("cliente@soluna.test", "Confirmación", "Hola")
    assert [p[0] for p in proveedor[0].pasos] == ["enviar"]


def test_tope_de_bienvenidas_por_hora(cliente_http, admin_db, correos, monkeypatch):
    monkeypatch.setattr(config, "CORREO_BIENVENIDAS_HORA", 2)
    for i in range(4):
        r = cliente_http.post("/api/suscripciones", json={"correo": f"persona{i}@correo.test"})
        assert r.status_code == 202
    assert admin_db.execute("SELECT count(*) FROM suscriptores").fetchone() == (4,)   # todos se guardan
    assert len(correos) == 2                                                           # solo 2 bienvenidas
