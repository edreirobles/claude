"""
Bot de Telegram para el SaaS de X → LinkedIn.

Flujo de onboarding:
  1. Usuario envía /start al bot
  2. Bot crea cuenta (o recupera existente) usando telegram_id
  3. Bot envía link de acceso al dashboard (token de 15 min)
  4. Desde el dashboard el usuario configura X, LinkedIn y automatización

Comandos:
  /start      — Crear cuenta / bienvenida
  /dashboard  — Link al dashboard web
  /estado     — Ver suscripción y configuración
  /upgrade    — Obtener link de pago Pro ($10/mes)
  /ayuda      — Ayuda

Notificaciones (enviadas por automation_engine):
  - Post publicado con éxito
  - Error al publicar
  - Límite mensual alcanzado (plan Free)
"""

import asyncio
import logging
from typing import Optional

from telegram import (
    Bot,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

from app.config import settings

logger = logging.getLogger(__name__)

# Instancia global del bot
_bot_app: Optional[Application] = None


def get_bot_app() -> Optional[Application]:
    return _bot_app


async def setup_bot() -> Optional[Application]:
    """Inicializa el bot. Llamado al arrancar la app."""
    global _bot_app

    if not settings.telegram_bot_token:
        logger.warning("TELEGRAM_BOT_TOKEN no configurado — bot deshabilitado")
        return None

    app = Application.builder().token(settings.telegram_bot_token).build()

    # Registrar comandos
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("dashboard", cmd_dashboard))
    app.add_handler(CommandHandler("estado", cmd_estado))
    app.add_handler(CommandHandler("upgrade", cmd_upgrade))
    app.add_handler(CommandHandler("ayuda", cmd_ayuda))
    app.add_handler(CallbackQueryHandler(handle_callback))

    await app.initialize()

    # En producción usamos webhook; en desarrollo polling
    if settings.environment == "production" and settings.app_url:
        webhook_url = f"{settings.app_url}/telegram/webhook"
        await app.bot.set_webhook(
            url=webhook_url,
            allowed_updates=["message", "callback_query"],
        )
        logger.info(f"Webhook de Telegram configurado en {webhook_url}")
    else:
        # Polling en background para desarrollo
        await app.bot.delete_webhook(drop_pending_updates=True)
        asyncio.create_task(_run_polling(app))
        logger.info("Bot de Telegram iniciado en modo polling (desarrollo)")

    _bot_app = app
    return app


async def _run_polling(app: Application):
    """Corre el polling en background (solo para desarrollo)."""
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)


async def teardown_bot():
    """Detiene el bot al apagar la app."""
    global _bot_app
    if _bot_app:
        try:
            if settings.environment != "production":
                await _bot_app.updater.stop()
            await _bot_app.stop()
            await _bot_app.shutdown()
        except Exception as e:
            logger.warning(f"Error al detener el bot: {e}")
        _bot_app = None


# ---------------------------------------------------------------------------
# Helpers de DB
# ---------------------------------------------------------------------------

async def _get_or_create_user(telegram_id: str, chat_id: str, username: Optional[str], full_name: Optional[str]):
    """Obtiene o crea un usuario basado en su telegram_id."""
    from app.database import AsyncSessionLocal
    from app.models import Subscription, User, UserCredentials
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.telegram_id == telegram_id))
        user = result.scalar_one_or_none()

        if not user:
            user = User(
                telegram_id=telegram_id,
                telegram_chat_id=chat_id,
                telegram_username=username,
                full_name=full_name,
            )
            db.add(user)
            await db.flush()
            db.add(Subscription(user_id=user.id))
            db.add(UserCredentials(user_id=user.id))
            await db.commit()
            await db.refresh(user)
            logger.info(f"Nuevo usuario creado vía Telegram: {telegram_id} (@{username})")
        else:
            # Actualizar datos de Telegram por si cambiaron
            user.telegram_chat_id = chat_id
            if username:
                user.telegram_username = username
            if full_name and not user.full_name:
                user.full_name = full_name
            await db.commit()

        return user.id


async def _get_user_status(user_id: int) -> dict:
    """Devuelve un dict con el estado del usuario para mostrar en Telegram."""
    from app.database import AsyncSessionLocal
    from app.models import Subscription, User, UserCredentials
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(User)
            .options(selectinload(User.subscription), selectinload(User.credentials))
            .where(User.id == user_id)
        )
        user = result.scalar_one_or_none()
        if not user:
            return {}

        sub = user.subscription
        creds = user.credentials

        plan_label = "Pro 🔥" if (sub and sub.plan.value == "pro") else "Gratis"
        can_post = sub.can_post if sub else True
        posts_info = (
            f"{sub.posts_used_this_month}/{sub.free_posts_limit}" if sub and sub.plan.value == "free"
            else "ilimitados"
        )
        configured = creds.is_configured if creds else False

        return {
            "display_name": user.display_name,
            "plan": plan_label,
            "can_post": can_post,
            "posts_info": posts_info,
            "configured": configured,
            "x_username": creds.x_username if creds else None,
            "automation_enabled": creds.automation_enabled if creds else False,
        }


# ---------------------------------------------------------------------------
# Comandos
# ---------------------------------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Crea la cuenta (si no existe) y da la bienvenida."""
    tg_user = update.effective_user
    telegram_id = str(tg_user.id)
    chat_id = str(update.effective_chat.id)
    username = tg_user.username
    full_name = tg_user.full_name

    user_id = await _get_or_create_user(telegram_id, chat_id, username, full_name)

    from app.auth import create_telegram_login_token
    login_token = create_telegram_login_token(user_id)
    dashboard_url = f"{settings.app_url}/app/?tg_token={login_token}"

    keyboard = [
        [InlineKeyboardButton("Abrir dashboard", url=dashboard_url)],
        [InlineKeyboardButton("Ver mis planes", callback_data="show_plans")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f"Hola, *{tg_user.first_name}*! 👋\n\n"
        "Bienvenido a *X → LinkedIn Automator*.\n\n"
        "Conecto tu cuenta de X con LinkedIn y publico automáticamente usando IA.\n\n"
        "Toca *Abrir dashboard* para configurar tus cuentas y activar la automatización.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup,
    )


async def cmd_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Genera un link fresco al dashboard."""
    tg_user = update.effective_user
    telegram_id = str(tg_user.id)
    chat_id = str(update.effective_chat.id)

    user_id = await _get_or_create_user(telegram_id, chat_id, tg_user.username, tg_user.full_name)

    from app.auth import create_telegram_login_token
    login_token = create_telegram_login_token(user_id)
    dashboard_url = f"{settings.app_url}/app/?tg_token={login_token}"

    keyboard = [[InlineKeyboardButton("Abrir dashboard", url=dashboard_url)]]
    await update.message.reply_text(
        "Aquí está tu link al dashboard (válido 15 min):",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def cmd_estado(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Muestra el estado actual de la cuenta."""
    tg_user = update.effective_user
    telegram_id = str(tg_user.id)
    chat_id = str(update.effective_chat.id)

    user_id = await _get_or_create_user(telegram_id, chat_id, tg_user.username, tg_user.full_name)
    status_data = await _get_user_status(user_id)

    if not status_data:
        await update.message.reply_text("No encontré tu cuenta. Envía /start para comenzar.")
        return

    config_icon = "✅" if status_data["configured"] else "⚠️"
    automation_icon = "🟢" if status_data["automation_enabled"] else "🔴"
    x_account = f"@{status_data['x_username']}" if status_data["x_username"] else "no configurada"

    msg = (
        f"*Estado de tu cuenta*\n\n"
        f"Plan: *{status_data['plan']}*\n"
        f"Posts este mes: *{status_data['posts_info']}*\n\n"
        f"{config_icon} Configuración: {'completa' if status_data['configured'] else 'pendiente'}\n"
        f"Cuenta X: {x_account}\n"
        f"{automation_icon} Automatización: {'activa' if status_data['automation_enabled'] else 'desactivada'}"
    )

    keyboard = []
    if not status_data["configured"]:
        from app.auth import create_telegram_login_token
        login_token = create_telegram_login_token(user_id)
        dashboard_url = f"{settings.app_url}/app/?tg_token={login_token}"
        keyboard.append([InlineKeyboardButton("Configurar ahora", url=dashboard_url)])
    if status_data["plan"] == "Gratis":
        keyboard.append([InlineKeyboardButton("Upgrade a Pro — $10/mes", callback_data="show_upgrade")])

    await update.message.reply_text(
        msg,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None,
    )


async def cmd_upgrade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Envía link de pago para upgrade a Pro."""
    tg_user = update.effective_user
    telegram_id = str(tg_user.id)
    chat_id = str(update.effective_chat.id)

    user_id = await _get_or_create_user(telegram_id, chat_id, tg_user.username, tg_user.full_name)

    checkout_url = await _get_checkout_url(user_id)
    if not checkout_url:
        await update.message.reply_text(
            "Para hacer upgrade, abre el dashboard y haz clic en *Upgrade a Pro*.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    keyboard = [[InlineKeyboardButton("Pagar $10/mes — Plan Pro", url=checkout_url)]]
    await update.message.reply_text(
        "*Plan Pro — $10/mes*\n\n"
        "✅ Posts ilimitados\n"
        "✅ Prompt de IA personalizado\n"
        "✅ Automatización continua\n"
        "✅ Soporte prioritario\n\n"
        "Cancela cuando quieras desde el dashboard.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def cmd_ayuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "*Comandos disponibles:*\n\n"
        "/start — Crear cuenta o bienvenida\n"
        "/dashboard — Link al dashboard web\n"
        "/estado — Ver tu suscripción y configuración\n"
        "/upgrade — Mejorar a plan Pro ($10/mes)\n"
        "/ayuda — Esta ayuda\n\n"
        "Si tienes problemas, abre el dashboard y usa el botón de soporte.",
        parse_mode=ParseMode.MARKDOWN,
    )


# ---------------------------------------------------------------------------
# Callbacks de botones inline
# ---------------------------------------------------------------------------

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "show_plans":
        await query.message.reply_text(
            "*Planes disponibles:*\n\n"
            "🆓 *Gratis* — $0/mes\n"
            "• 5 posts al mes\n"
            "• Generación con IA\n"
            "• Dashboard básico\n\n"
            "🔥 *Pro* — $10/mes\n"
            "• Posts ilimitados\n"
            "• Prompt de IA personalizado\n"
            "• Automatización continua\n"
            "• Soporte prioritario\n\n"
            "Usa /upgrade para activar el plan Pro.",
            parse_mode=ParseMode.MARKDOWN,
        )

    elif query.data == "show_upgrade":
        tg_user = update.effective_user
        user_id = await _get_or_create_user(
            str(tg_user.id), str(query.message.chat_id), tg_user.username, tg_user.full_name
        )
        checkout_url = await _get_checkout_url(user_id)
        if checkout_url:
            keyboard = [[InlineKeyboardButton("Pagar $10/mes", url=checkout_url)]]
            await query.message.reply_text(
                "Haz clic para completar el pago:",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
        else:
            await query.message.reply_text("Abre /dashboard para hacer el upgrade.")


# ---------------------------------------------------------------------------
# Notificaciones (llamadas por automation_engine)
# ---------------------------------------------------------------------------

async def notify_post_published(telegram_chat_id: str, tweet_url: str, linkedin_post_id: str):
    """Notifica al usuario que su post fue publicado en LinkedIn."""
    if not _bot_app:
        return
    try:
        await _bot_app.bot.send_message(
            chat_id=telegram_chat_id,
            text=(
                "✅ *Post publicado en LinkedIn*\n\n"
                f"Tweet: {tweet_url}\n"
                f"LinkedIn ID: `{linkedin_post_id}`"
            ),
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception as e:
        logger.warning(f"No se pudo notificar a {telegram_chat_id}: {e}")


async def notify_post_failed(telegram_chat_id: str, tweet_url: str, error: str):
    """Notifica al usuario que falló al publicar."""
    if not _bot_app:
        return
    try:
        await _bot_app.bot.send_message(
            chat_id=telegram_chat_id,
            text=(
                "❌ *Error al publicar en LinkedIn*\n\n"
                f"Tweet: {tweet_url}\n"
                f"Error: {error}"
            ),
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception as e:
        logger.warning(f"No se pudo notificar a {telegram_chat_id}: {e}")


async def notify_limit_reached(telegram_chat_id: str):
    """Notifica que el plan Free alcanzó el límite mensual."""
    if not _bot_app:
        return
    try:
        await _bot_app.bot.send_message(
            chat_id=telegram_chat_id,
            text=(
                "⚠️ *Límite mensual alcanzado*\n\n"
                "Has usado todos tus posts gratuitos este mes.\n\n"
                "Usa /upgrade para obtener posts ilimitados por $10/mes."
            ),
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception as e:
        logger.warning(f"No se pudo notificar a {telegram_chat_id}: {e}")


# ---------------------------------------------------------------------------
# Helper de checkout
# ---------------------------------------------------------------------------

async def _get_checkout_url(user_id: int) -> Optional[str]:
    """Crea una sesión de Stripe Checkout y devuelve la URL."""
    if not settings.stripe_secret_key or not settings.stripe_price_id_pro:
        return None
    try:
        import stripe
        from app.database import AsyncSessionLocal
        from app.models import Subscription, User
        from sqlalchemy import select

        stripe.api_key = settings.stripe_secret_key

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(User).where(User.id == user_id)
            )
            user = result.scalar_one_or_none()
            if not user:
                return None

            sub_result = await db.execute(
                select(Subscription).where(Subscription.user_id == user_id)
            )
            sub = sub_result.scalar_one_or_none()

            # Crear o reusar customer de Stripe
            customer_id = sub.stripe_customer_id if sub else None
            if not customer_id:
                customer = stripe.Customer.create(
                    name=user.display_name,
                    metadata={"user_id": str(user_id)},
                )
                customer_id = customer.id
                if sub:
                    sub.stripe_customer_id = customer_id
                    await db.commit()

        session = stripe.checkout.Session.create(
            customer=customer_id,
            mode="subscription",
            line_items=[{"price": settings.stripe_price_id_pro, "quantity": 1}],
            success_url=f"{settings.app_url}/app/?payment=success",
            cancel_url=f"{settings.app_url}/app/?payment=canceled",
            metadata={"user_id": str(user_id)},
            allow_promotion_codes=True,
        )
        return session.url

    except Exception as e:
        logger.error(f"Error creando checkout de Stripe: {e}")
        return None
