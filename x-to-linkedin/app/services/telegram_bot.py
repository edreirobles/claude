"""
Bot de Telegram para controlar el sistema X → LinkedIn.

Funcionalidades:
- Enviar URL de tweet → genera post → preview → Programar / Publicar / Descartar
- /hoy     → posts programados para hoy
- /pendientes → todos los posts en cola con botón cancelar
- Notificaciones automáticas de publicación y errores

Solo acepta mensajes del TELEGRAM_USER_ID configurado en .env
"""
import asyncio
import logging
import re
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from ..config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# ── Estado global ──────────────────────────────────────────────────────────
_application: Optional[Application] = None

# Posts generados esperando confirmación del usuario
# Clave: message_id del mensaje de preview → datos del post
_pending: dict[int, dict] = {}

# Regex para detectar URLs de X / Twitter
_TWEET_RE = re.compile(
    r"https?://(?:www\.)?(?:x\.com|twitter\.com)/\S+/status/\d+",
    re.IGNORECASE,
)


# ── Seguridad ──────────────────────────────────────────────────────────────

def _authorized(update: Update) -> bool:
    return bool(settings.telegram_user_id) and (
        update.effective_user.id == settings.telegram_user_id
    )


async def _deny(update: Update):
    await update.message.reply_text("No estás autorizado para usar este bot.")


# ── Comandos ───────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        await _deny(update)
        return
    await update.message.reply_text(
        "👋 *X → LinkedIn Bot*\n\n"
        "Envíame un URL de tweet y lo convierto en un post de LinkedIn.\n\n"
        "Comandos:\n"
        "/hoy — posts de hoy\n"
        "/pendientes — posts en cola\n"
        "/help — ayuda",
        parse_mode="Markdown",
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        await _deny(update)
        return
    await update.message.reply_text(
        "📖 *Cómo usar el bot*\n\n"
        "1\\. Envía un URL de tweet \\(x\\.com o twitter\\.com\\)\n"
        "2\\. El bot genera el post de LinkedIn con IA\n"
        "3\\. Elige: *Programar* / *Publicar ahora* / *Descartar*\n\n"
        "*Comandos:*\n"
        "/hoy — posts programados para hoy con horario\n"
        "/pendientes — todos los posts en cola \\(con opción a cancelar\\)\n"
        "/start — bienvenida",
        parse_mode="MarkdownV2",
    )


async def cmd_hoy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        await _deny(update)
        return

    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo

    from sqlalchemy import select

    from ..database import AsyncSessionLocal
    from ..models import ScheduledPost

    mty_tz = ZoneInfo("America/Monterrey")
    now_mty = datetime.now(mty_tz)
    today_start = (
        now_mty.replace(hour=0, minute=0, second=0, microsecond=0)
        .astimezone(timezone.utc)
        .replace(tzinfo=None)
    )
    today_end = (
        now_mty.replace(hour=23, minute=59, second=59)
        .astimezone(timezone.utc)
        .replace(tzinfo=None)
    )

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ScheduledPost)
            .where(ScheduledPost.status.in_(["scheduled", "published", "failed"]))
            .where(ScheduledPost.scheduled_at >= today_start)
            .where(ScheduledPost.scheduled_at <= today_end)
            .order_by(ScheduledPost.scheduled_at)
        )
        posts = result.scalars().all()

    if not posts:
        await update.message.reply_text("📭 No hay posts programados para hoy.")
        return

    icons = {"scheduled": "⏰", "published": "✅", "failed": "❌"}
    lines = ["📅 *Posts de hoy:*\n"]
    for p in posts:
        sched = datetime.fromisoformat(str(p.scheduled_at)).replace(tzinfo=timezone.utc)
        sched_mty = sched.astimezone(mty_tz)
        icon = icons.get(p.status, "❓")
        preview = (p.linkedin_text or "")[:80].replace("\n", " ")
        lines.append(f"{icon} {sched_mty.strftime('%H:%M')} — {preview}…")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_pendientes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        await _deny(update)
        return

    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo

    from sqlalchemy import select

    from ..database import AsyncSessionLocal
    from ..models import ScheduledPost

    mty_tz = ZoneInfo("America/Monterrey")

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ScheduledPost)
            .where(ScheduledPost.status == "scheduled")
            .order_by(ScheduledPost.scheduled_at)
        )
        posts = result.scalars().all()

    if not posts:
        await update.message.reply_text("📭 No hay posts programados pendientes.")
        return

    await update.message.reply_text(
        f"📋 *{len(posts)} post{'s' if len(posts) > 1 else ''} en cola:*",
        parse_mode="Markdown",
    )

    for p in posts[:15]:
        sched = datetime.fromisoformat(str(p.scheduled_at)).replace(tzinfo=timezone.utc)
        sched_mty = sched.astimezone(mty_tz)
        preview = (p.linkedin_text or "")[:100].replace("\n", " ")
        keyboard = [[
            InlineKeyboardButton(
                f"❌ Cancelar #{p.id}",
                callback_data=f"cancel:{p.id}",
            )
        ]]
        await update.message.reply_text(
            f"⏰ *{sched_mty.strftime('%d/%m %H:%M')}* — {preview}…",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown",
        )


# ── Mensajes de texto (detección de URL de tweet) ─────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        await _deny(update)
        return

    text = update.message.text or ""
    match = _TWEET_RE.search(text)

    if match:
        await _process_tweet_url(update, context, match.group(0))
    else:
        await update.message.reply_text(
            "Envíame un URL de tweet para generar un post de LinkedIn.\n"
            "Ejemplo: https://x.com/usuario/status/12345\n\n"
            "O usa /pendientes para ver los posts en cola."
        )


async def _process_tweet_url(
    update: Update, context: ContextTypes.DEFAULT_TYPE, url: str
):
    """Scraping + generación + preview + botones de acción."""
    from sqlalchemy import select

    from ..database import AsyncSessionLocal
    from ..models import AppSettings
    from ..services.post_generator import generate_linkedin_post
    from ..services.x_scraper import scrape_tweet

    wait_msg = await update.message.reply_text("⏳ Generando post de LinkedIn…")

    # 1. Scraping del tweet
    try:
        tweet = await scrape_tweet(url)
    except Exception as e:
        await wait_msg.edit_text(f"❌ No pude extraer el tweet:\n`{e}`", parse_mode="Markdown")
        return

    # 2. Prompt personalizado
    async with AsyncSessionLocal() as db:
        cfg_result = await db.execute(select(AppSettings).where(AppSettings.id == 1))
        cfg = cfg_result.scalar_one_or_none()
        custom_prompt = cfg.custom_prompt if cfg else None

    # 3. Generar post con Claude
    try:
        linkedin_text = await generate_linkedin_post(
            tweet=tweet,
            language=settings.post_language or "es",
            custom_prompt=custom_prompt,
        )
    except Exception as e:
        await wait_msg.edit_text(f"❌ Error generando el post:\n`{e}`", parse_mode="Markdown")
        return

    # 4. Verificar si el contenido es publicable
    if linkedin_text.startswith("[NO_PUBLICAR]"):
        reason = linkedin_text.split(":", 1)[-1].strip()
        await wait_msg.edit_text(
            f"⚠️ Este tweet no es publicable:\n_{reason}_",
            parse_mode="Markdown",
        )
        return

    # 5. Determinar tipo de media
    if tweet.has_video:
        media_type = "video"
    elif tweet.pdf_url:
        media_type = "document"
    elif tweet.images:
        media_type = "image"
    else:
        media_type = "generate"

    post_data = {
        "tweet_url": url,
        "tweet_text": tweet.text,
        "tweet_author": tweet.author_name or tweet.author_handle or "",
        "linkedin_text": linkedin_text,
        "media_type": media_type,
        "image_urls": tweet.images or [],
        "use_first_image": True,
        "pdf_url": tweet.pdf_url,
        "document_title": (
            tweet.paper_info.get("title", "Documento") if tweet.paper_info else "Documento"
        ),
    }

    # 6. Mostrar preview con botones temporales (message_id aún no conocido)
    icons = {"video": "🎥", "document": "📄", "image": "🖼️", "generate": "🎨"}
    media_icon = icons.get(media_type, "📝")
    preview = linkedin_text[:900] + ("…" if len(linkedin_text) > 900 else "")

    # Botones provisionales (se actualizan con el message_id real)
    preview_msg = await wait_msg.edit_text(
        f"{media_icon} *Preview del post:*\n\n{preview}",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("📅 Programar", callback_data="sched:0"),
            InlineKeyboardButton("🚀 Publicar ahora", callback_data="pub:0"),
        ], [
            InlineKeyboardButton("❌ Descartar", callback_data="disc:0"),
        ]]),
        parse_mode="Markdown",
    )

    # Guardar datos con el message_id real como clave
    mid = preview_msg.message_id
    _pending[mid] = post_data

    # Actualizar botones con el message_id correcto
    await preview_msg.edit_reply_markup(
        InlineKeyboardMarkup([[
            InlineKeyboardButton("📅 Programar", callback_data=f"sched:{mid}"),
            InlineKeyboardButton("🚀 Publicar ahora", callback_data=f"pub:{mid}"),
        ], [
            InlineKeyboardButton("❌ Descartar", callback_data=f"disc:{mid}"),
        ]])
    )


# ── Callbacks de botones ───────────────────────────────────────────────────

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # Seguridad también en callbacks
    if bool(settings.telegram_user_id) and query.from_user.id != settings.telegram_user_id:
        return

    data = query.data or ""

    if data.startswith("cancel:"):
        await _do_cancel(query, int(data.split(":")[1]))
    elif data.startswith("sched:"):
        await _do_schedule(query, int(data.split(":")[1]))
    elif data.startswith("pub:"):
        await _do_publish_now(query, int(data.split(":")[1]))
    elif data.startswith("disc:"):
        _pending.pop(int(data.split(":")[1]), None)
        await query.edit_message_reply_markup(None)
        await query.message.reply_text("🗑️ Post descartado.")


async def _do_schedule(query, msg_id: int):
    post_data = _pending.get(msg_id)
    if not post_data:
        await query.edit_message_reply_markup(None)
        await query.message.reply_text(
            "⚠️ Los datos ya no están en memoria. Genera el post de nuevo."
        )
        return

    from datetime import timezone
    from zoneinfo import ZoneInfo

    from ..database import AsyncSessionLocal
    from ..models import ScheduledPost
    from ..services.scheduler_service import schedule_post
    from ..services.x_likes_monitor import get_next_auto_slot

    await query.edit_message_reply_markup(None)

    async with AsyncSessionLocal() as db:
        run_at = await get_next_auto_slot(db)
        post = ScheduledPost(
            tweet_url=post_data["tweet_url"],
            tweet_text=post_data["tweet_text"],
            tweet_author=post_data["tweet_author"],
            linkedin_text=post_data["linkedin_text"],
            image_urls=post_data["image_urls"],
            status="scheduled",
            scheduled_at=run_at,
            use_first_image=post_data["use_first_image"],
            media_type=post_data["media_type"],
            pdf_url=post_data.get("pdf_url"),
            document_title=post_data.get("document_title", "Documento"),
        )
        db.add(post)
        await db.commit()
        await db.refresh(post)
        schedule_post(post.id, run_at)

    _pending.pop(msg_id, None)

    mty_tz = ZoneInfo("America/Monterrey")
    run_at_mty = run_at.replace(tzinfo=timezone.utc).astimezone(mty_tz)
    await query.message.reply_text(
        f"✅ Post #{post.id} programado para el "
        f"*{run_at_mty.strftime('%d/%m a las %H:%M')}* (Monterrey)",
        parse_mode="Markdown",
    )


async def _do_publish_now(query, msg_id: int):
    post_data = _pending.get(msg_id)
    if not post_data:
        await query.edit_message_reply_markup(None)
        await query.message.reply_text(
            "⚠️ Los datos ya no están en memoria. Genera el post de nuevo."
        )
        return

    from datetime import datetime

    from sqlalchemy import select

    from ..database import AsyncSessionLocal
    from ..models import LinkedInToken, ScheduledPost
    from ..services.linkedin_client import LinkedInClient
    from ..services.post_generator import (
        download_pdf,
        download_tweet_video,
        generate_free_image,
    )

    await query.edit_message_reply_markup(None)
    status_msg = await query.message.reply_text("⏳ Publicando en LinkedIn…")

    async with AsyncSessionLocal() as db:
        token_result = await db.execute(select(LinkedInToken).limit(1))
        token = token_result.scalar_one_or_none()
        if not token:
            await status_msg.edit_text(
                "❌ LinkedIn no está conectado. Conéctalo desde la app web."
            )
            return

        media_type = post_data["media_type"]
        video_bytes = None
        document_bytes = None
        generated_image_bytes = None

        if media_type == "video":
            video_bytes = await download_tweet_video(post_data["tweet_url"])
            if not video_bytes:
                media_type = "image"
        elif media_type == "document" and post_data.get("pdf_url"):
            document_bytes = await download_pdf(post_data["pdf_url"])
        elif media_type == "generate":
            generated_image_bytes = await generate_free_image(post_data["linkedin_text"])

        li_client = LinkedInClient(token.access_token, token.person_urn)
        try:
            result = await li_client.create_post(
                text=post_data["linkedin_text"],
                image_urls=post_data["image_urls"] if media_type == "image" else None,
                use_first_image=media_type == "image" and post_data["use_first_image"],
                video_bytes=video_bytes,
                document_bytes=document_bytes,
                document_title=post_data.get("document_title", "Documento"),
                generated_image_bytes=generated_image_bytes,
            )
        except Exception as e:
            await status_msg.edit_text(f"❌ Error al publicar en LinkedIn:\n`{e}`", parse_mode="Markdown")
            return

        post = ScheduledPost(
            tweet_url=post_data["tweet_url"],
            tweet_text=post_data["tweet_text"],
            tweet_author=post_data["tweet_author"],
            linkedin_text=post_data["linkedin_text"],
            image_urls=post_data["image_urls"],
            status="published",
            published_at=datetime.utcnow(),
            linkedin_post_id=result.get("post_id", ""),
            use_first_image=post_data["use_first_image"],
            media_type=media_type,
            pdf_url=post_data.get("pdf_url"),
            document_title=post_data.get("document_title", "Documento"),
        )
        db.add(post)
        await db.commit()

    _pending.pop(msg_id, None)
    await status_msg.edit_text("✅ ¡Publicado en LinkedIn exitosamente!")


async def _do_cancel(query, post_id: int):
    from sqlalchemy import select

    from ..database import AsyncSessionLocal
    from ..models import ScheduledPost
    from ..services.scheduler_service import cancel_scheduled_post

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ScheduledPost).where(ScheduledPost.id == post_id)
        )
        post = result.scalar_one_or_none()
        if not post or post.status != "scheduled":
            await query.edit_message_reply_markup(None)
            await query.message.reply_text("⚠️ Este post ya no está programado.")
            return
        cancel_scheduled_post(post_id)
        post.status = "cancelled"
        await db.commit()

    await query.edit_message_reply_markup(None)
    await query.message.reply_text(f"❌ Post #{post_id} cancelado.")


# ── Notificaciones desde el scheduler ──────────────────────────────────────

async def notify_published(post_id: int, linkedin_text: str):
    """Llamar desde el scheduler cuando un post se publica exitosamente."""
    if not _application or not settings.telegram_user_id:
        return
    try:
        preview = (linkedin_text or "")[:150].replace("\n", " ")
        await _application.bot.send_message(
            chat_id=settings.telegram_user_id,
            text=f"✅ *Post #{post_id} publicado en LinkedIn*\n\n_{preview}…_",
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.warning(f"Notificación Telegram (publicado) falló: {e}")


async def notify_failed(post_id: int, error: str):
    """Llamar desde el scheduler cuando un post falla."""
    if not _application or not settings.telegram_user_id:
        return
    try:
        await _application.bot.send_message(
            chat_id=settings.telegram_user_id,
            text=f"❌ *Post #{post_id} falló*\n\nError: `{error[:300]}`",
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.warning(f"Notificación Telegram (error) falló: {e}")


# ── Lifecycle ───────────────────────────────────────────────────────────────

async def start_bot():
    """Inicializa y arranca el bot. Llamar desde el lifespan de FastAPI."""
    global _application

    if not settings.telegram_bot_token:
        logger.info("TELEGRAM_BOT_TOKEN no configurado — bot de Telegram desactivado")
        return
    if not settings.telegram_user_id:
        logger.warning("TELEGRAM_USER_ID no configurado — bot de Telegram desactivado")
        return

    _application = Application.builder().token(settings.telegram_bot_token).build()

    _application.add_handler(CommandHandler("start", cmd_start))
    _application.add_handler(CommandHandler("help", cmd_help))
    _application.add_handler(CommandHandler("hoy", cmd_hoy))
    _application.add_handler(CommandHandler("pendientes", cmd_pendientes))
    _application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )
    _application.add_handler(CallbackQueryHandler(handle_callback))

    await _application.initialize()
    await _application.start()
    await _application.updater.start_polling(drop_pending_updates=True)

    logger.info(
        f"Bot de Telegram iniciado (usuario autorizado: {settings.telegram_user_id})"
    )


async def stop_bot():
    """Detiene el bot. Llamar desde el shutdown del lifespan."""
    global _application
    if _application:
        try:
            await _application.updater.stop()
            await _application.stop()
            await _application.shutdown()
        except Exception as e:
            logger.warning(f"Error deteniendo bot de Telegram: {e}")
        finally:
            _application = None
            logger.info("Bot de Telegram detenido")
