"""Correos a los huéspedes.

Se envían como tarea de fondo, después de responder al usuario: si el
servidor de correo falla, la reserva o el pago no se pierden; solo queda
el error en el registro de la API. En el prototipo los captura Mailpit.
"""
import logging
import smtplib
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

from . import config

registro = logging.getLogger("soluna.correo")


def enviar(destino: str, asunto: str, cuerpo: str) -> None:
    mensaje = EmailMessage()
    mensaje["From"] = config.CORREO_REMITENTE
    mensaje["To"] = destino
    mensaje["Subject"] = asunto
    mensaje["Date"] = formatdate(localtime=True)
    mensaje["Message-ID"] = make_msgid(domain="soluna.test")
    mensaje.set_content(cuerpo + "\n\nHotel Soluna · Playa Sámara, Guanacaste\n")
    try:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=10) as smtp:
            if config.SMTP_TLS:
                smtp.starttls()          # cifra la conexión antes de enviar la contraseña
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
