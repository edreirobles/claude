"""
Ruta del webhook de Telegram:
  POST /telegram/webhook  — Telegram envía cada update aquí
"""

from fastapi import APIRouter, Request, Response

router = APIRouter(prefix="/telegram", tags=["telegram"])


@router.post("/webhook")
async def telegram_webhook(request: Request):
    """Recibe updates de Telegram y los procesa con el bot."""
    from app.services.telegram_saas_bot import get_bot_app

    bot_app = get_bot_app()
    if bot_app is None:
        return Response(status_code=200)  # Bot no configurado

    import json
    from telegram import Update

    body = await request.body()
    data = json.loads(body)
    update = Update.de_json(data, bot_app.bot)
    await bot_app.process_update(update)

    return Response(status_code=200)
