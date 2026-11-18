"""Correos a los huéspedes.

En Docker se envían como tarea de fondo, después de responder al usuario, y
los captura Mailpit: nunca llegan a nadie. En Vercel salen por un proveedor
real (Brevo) dentro de la misma solicitud. En ambos casos, si el servidor de
correo falla, la reserva o el pago no se pierden: solo queda el error en el
registro de la API.
"""
import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formatdate, make_msgid, parseaddr

from . import config

registro = logging.getLogger("soluna.correo")

# Dominios reservados para pruebas y documentación (RFC 2606 y RFC 6761)
DOMINIOS_DE_PRUEBA = (".test", ".example", ".invalid", ".localhost",
                      "example.com", "example.net", "example.org")


def es_de_prueba(destino: str) -> bool:
    dominio = destino.rsplit("@", 1)[-1].lower().rstrip(".")
    return any(dominio == d.lstrip(".") or dominio.endswith(d if d.startswith(".") else "." + d)
               for d in DOMINIOS_DE_PRUEBA)


def programar(tareas, destino: str, asunto: str, cuerpo: str) -> None:
    """Envía después de responder (Docker) o en la misma solicitud (Vercel)."""
    if config.CORREO_SEGUNDO_PLANO:
        tareas.add_task(enviar, destino, asunto, cuerpo)
    else:
        enviar(destino, asunto, cuerpo)


def enviar(destino: str, asunto: str, cuerpo: str) -> None:
    if not config.SMTP_HOST or config.SMTP_HOST.lower() == "ninguno":
        registro.warning("Sin servidor de correo configurado: no se envió '%s' a %s", asunto, destino)
        return
    if config.CORREO_OMITIR_PRUEBA and es_de_prueba(destino):
        registro.info("Dominio de prueba: no se envió '%s' a %s", asunto, destino)
        return
    if config.SMTP_USUARIO and not config.SMTP_TLS:
        registro.error("SMTP_TLS está apagado: no se envía la contraseña del correo sin cifrar")
        return
    remitente = parseaddr(config.CORREO_REMITENTE)[1]
    mensaje = EmailMessage()
    mensaje["From"] = config.CORREO_REMITENTE
    mensaje["To"] = destino
    mensaje["Subject"] = asunto
    mensaje["Date"] = formatdate(localtime=True)
    mensaje["Message-ID"] = make_msgid(domain=remitente.rsplit("@", 1)[-1] or "soluna.test")
    mensaje.set_content(cuerpo + "\n\nHotel Soluna · Playa Sámara, Guanacaste\n")
    try:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=10) as smtp:
            if config.SMTP_TLS:
                # cifra la conexión antes de enviar la contraseña y verifica el certificado
                smtp.starttls(context=ssl.create_default_context())
            if config.SMTP_USUARIO:
                smtp.login(config.SMTP_USUARIO, config.SMTP_PASSWORD or "")
            smtp.send_message(mensaje)
    except (OSError, smtplib.SMTPException) as error:
        registro.error("No se pudo enviar el correo '%s' a %s: %s", asunto, destino, error)


def detalle_reserva(reserva) -> str:
    return (
        f"Código de reserva: {reserva.codigo}\n"
        f"Habitación: {reserva.habitacion.numero} ({reserva.habitacion.tipo.nombre})\n"
        f"Entrada: {reserva.fecha_entrada:%d/%m/%Y} (desde las 15:00)\n"
        f"Salida: {reserva.fecha_salida:%d/%m/%Y} (hasta las 12:00)\n"
        f"Personas: {reserva.personas}"
    )
