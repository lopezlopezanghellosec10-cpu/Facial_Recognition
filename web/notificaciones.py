"""Avisos a la persona (aprobado, rechazado...).

Siempre se escriben en la consola del servidor. Si hay un servidor SMTP
configurado con variables de entorno, además se mandan por correo.
"""

import logging
import os
import smtplib
from email.message import EmailMessage

registro = logging.getLogger("uvicorn.error")


def notificar(correo: str | None, asunto: str, texto: str) -> None:
    """Avisa a una persona. Nunca lanza errores: un aviso fallido no debe romper nada."""
    if not correo:
        return

    registro.info("NOTIFICACION para %s | %s | %s", correo, asunto, texto)

    host = os.getenv("SMTP_HOST")
    if not host:
        return

    try:
        mensaje = EmailMessage()
        mensaje["Subject"] = asunto
        mensaje["From"] = os.getenv("SMTP_FROM") or os.getenv("SMTP_USER", "")
        mensaje["To"] = correo
        mensaje.set_content(texto)

        with smtplib.SMTP(host, int(os.getenv("SMTP_PORT", "587")), timeout=15) as servidor:
            servidor.starttls()
            usuario = os.getenv("SMTP_USER")
            if usuario:
                servidor.login(usuario, os.getenv("SMTP_PASSWORD", ""))
            servidor.send_message(mensaje)
    except Exception:
        registro.exception("No se pudo enviar el correo a %s", correo)