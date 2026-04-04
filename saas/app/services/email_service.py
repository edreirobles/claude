"""
Servicio de email usando la API de Resend (https://resend.com).
No requiere dependencias adicionales — usa httpx que ya está en requirements.
"""

import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

RESEND_API_URL = "https://api.resend.com/emails"


async def send_password_reset_email(to_email: str, reset_url: str) -> bool:
    """
    Envía el correo de recuperación de contraseña.
    Retorna True si se envió correctamente, False si falló.
    """
    if not settings.resend_api_key:
        # En desarrollo, solo logueamos el enlace
        logger.warning(
            "RESEND_API_KEY no configurado. Enlace de reset (solo dev): %s", reset_url
        )
        return True

    html_body = f"""
<!DOCTYPE html>
<html lang="es">
<head><meta charset="UTF-8" /></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background:#f9fafb; margin:0; padding:40px 16px;">
  <div style="max-width:480px; margin:0 auto; background:#fff; border-radius:16px; padding:40px; box-shadow:0 2px 16px rgba(0,0,0,.08);">
    <div style="font-size:22px; font-weight:900; color:#0A66C2; margin-bottom:24px;">PostLinked</div>
    <h1 style="font-size:20px; font-weight:700; margin:0 0 12px;">Recupera tu contraseña</h1>
    <p style="color:#4B5563; font-size:15px; line-height:1.6; margin:0 0 28px;">
      Recibimos una solicitud para restablecer la contraseña de tu cuenta. Haz clic en el botón para crear una nueva:
    </p>
    <a href="{reset_url}"
       style="display:inline-block; background:#0A66C2; color:#fff; text-decoration:none;
              font-weight:700; font-size:15px; padding:14px 28px; border-radius:8px;">
      Restablecer contraseña
    </a>
    <p style="color:#9CA3AF; font-size:13px; margin-top:28px; line-height:1.5;">
      Este enlace expira en <strong>1 hora</strong>. Si no solicitaste este cambio, ignora este correo.<br/>
      Tu contraseña no cambiará hasta que uses el enlace.
    </p>
    <hr style="border:none; border-top:1px solid #E5E7EB; margin:28px 0 16px;" />
    <p style="color:#9CA3AF; font-size:12px; margin:0;">© 2025 PostLinked · edreirobles.com</p>
  </div>
</body>
</html>
"""

    payload = {
        "from": settings.from_email,
        "to": [to_email],
        "subject": "Recupera tu contraseña — PostLinked",
        "html": html_body,
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                RESEND_API_URL,
                headers={
                    "Authorization": f"Bearer {settings.resend_api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        if response.status_code in (200, 201):
            return True
        logger.error("Resend API error %s: %s", response.status_code, response.text)
        return False
    except Exception as e:
        logger.error("Error enviando email de reset: %s", e)
        return False
