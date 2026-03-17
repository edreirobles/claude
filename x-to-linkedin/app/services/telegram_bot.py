"""
Bot de Telegram para controlar el sistema X → LinkedIn.

Funcionalidades:
- Enviar URL de tweet → genera post → preview → Programar / Publicar / Regenerar / Descartar
- /hoy     → posts programados para hoy
- /pendientes → todos los posts en cola con botón cancelar
- /status  → estado del sistema de un vistazo
- Notificaciones automáticas de publicación, errores y aviso 5 min antes

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

# Modo edición para post programado: user_id → post_id
_awaiting_edit: dict[int, int] = {}
# Modo edición para preview pendiente (antes de programar/publicar): user_id → mid
_awaiting_edit_preview: dict[int, int] = {}

# Regex para detectar URLs de X / Twitter
_TWEET_RE = re.compile(
    r"https?://(?:www\.)?(?:x\.com|twitter\.com)/\S+/status/\d+",
    re.IGNORECASE,
)

_LI_CHAR_LIMIT = 3000


# ── Seguridad ──────────────────────────────────────────────────────────────

def _authorized(update: Update) -> bool:
    return bool(settings.telegram_user_id) and (
        update.effective_user.id == settings.telegram_user_id
    )


async def _deny(update: Update):
    await update.message.reply_text("No estás autorizado para usar este bot.")


# ── Teclado rápido de preview ──────────────────────────────────────────────

def _preview_keyboard(mid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📅 Programar", callback_data=f"sched:{mid}"),
            InlineKeyboardButton("🚀 Publicar ahora", callback_data=f"pub:{mid}"),
        ],
        [
            InlineKeyboardButton("✏️ Editar texto", callback_data=f"edit_pending:{mid}"),
            InlineKeyboardButton("🔄 Regenerar", callback_data=f"regen:{mid}"),
        ],
        [
            InlineKeyboardButton("🗑️ Descartar", callback_data=f"disc:{mid}"),
        ],
    ])


# ── Comandos ───────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        await _deny(update)
        return
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📅 Ver hoy", callback_data="cmd:hoy"),
            InlineKeyboardButton("📋 Pendientes", callback_data="cmd:pendientes"),
        ],
        [
            InlineKeyboardButton("📊 Estado", callback_data="cmd:status"),
            InlineKeyboardButton("📖 Ayuda", callback_data="cmd:help"),
        ],
    ])
    await update.message.reply_text(
        "👋 *X → LinkedIn Bot*\n\n"
        "Envíame un URL de tweet y lo convierto en un post de LinkedIn.",
        parse_mode="Markdown",
        reply_markup=keyboard,
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        await _deny(update)
        return
    await update.message.reply_text(
        "📖 *Cómo usar el bot*\n\n"
        "1\\. Envía un URL de tweet \\(x\\.com o twitter\\.com\\)\n"
        "2\\. El bot genera el post de LinkedIn con IA\n"
        "3\\. Elige: *Programar* / *Publicar ahora* / *Regenerar* / *Descartar*\n\n"
        "*Comandos:*\n"
        "/hoy — posts programados para hoy con horario\n"
        "/pendientes — todos los posts en cola \\(con opción a cancelar\\)\n"
        "/status — estado del sistema de un vistazo\n"
        "/start — bienvenida",
        parse_mode="MarkdownV2",
    )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        await _deny(update)
        return

    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo
    from sqlalchemy import select, func

    from ..database import AsyncSessionLocal
    from ..models import ScheduledPost, LinkedInToken
    from .scheduler_service import scheduler

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
        token_result = await db.execute(select(LinkedInToken).limit(1))
        token = token_result.scalar_one_or_none()
        li_status = "✅ Conectado" if token else "❌ Desconectado"

        posts_hoy_result = await db.execute(
            select(ScheduledPost)
            .where(ScheduledPost.scheduled_at >= today_start)
            .where(ScheduledPost.scheduled_at <= today_end)
        )
        posts_hoy = posts_hoy_result.scalars().all()
        hoy_sched = sum(1 for p in posts_hoy if p.status == "scheduled")
        hoy_pub = sum(1 for p in posts_hoy if p.status == "published")

        pend_result = await db.execute(
            select(func.count())
            .select_from(ScheduledPost)
            .where(ScheduledPost.status == "scheduled")
        )
        total_pend = pend_result.scalar()

    sched_status = "✅ Corriendo" if scheduler.running else "❌ Detenido"

    await update.message.reply_text(
        f"📊 *Estado del sistema*\n\n"
        f"🔗 LinkedIn: {li_status}\n"
        f"⚙️ Scheduler: {sched_status}\n\n"
        f"📅 *Hoy ({now_mty.strftime('%d/%m')}):*\n"
        f"  ⏰ Programados: {hoy_sched}\n"
        f"  ✅ Publicados: {hoy_pub}\n\n"
        f"📋 Total en cola: {total_pend}",
        parse_mode="Markdown",
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


# ── Mensajes de texto (detección de URL de tweet o modo edición) ──────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        await _deny(update)
        return

    user_id = update.effective_user.id
    text = update.message.text or ""

    # Modo edición de preview pendiente (antes de publicar/programar)
    if user_id in _awaiting_edit_preview:
        await _handle_edit_preview_text(update, text)
        return

    # Modo edición de post programado
    if user_id in _awaiting_edit:
        await _handle_edit_text(update, text)
        return

    match = _TWEET_RE.search(text)
    if match:
        await _process_tweet_url(update, context, match.group(0))
    else:
        await update.message.reply_text(
            "Envíame un URL de tweet para generar un post de LinkedIn.\n"
            "Ejemplo: https://x.com/usuario/status/12345\n\n"
            "O usa /pendientes para ver los posts en cola."
        )


async def _handle_edit_text(update: Update, new_text: str):
    """Actualiza el texto de un post programado con el texto enviado por el usuario."""
    from sqlalchemy import select

    from ..database import AsyncSessionLocal
    from ..models import ScheduledPost

    user_id = update.effective_user.id
    post_id = _awaiting_edit.pop(user_id)

    if not new_text.strip():
        await update.message.reply_text("⚠️ El texto está vacío. Edición cancelada.")
        return

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ScheduledPost).where(ScheduledPost.id == post_id)
        )
        post = result.scalar_one_or_none()
        if not post or post.status != "scheduled":
            await update.message.reply_text("⚠️ El post ya no está programado.")
            return
        post.linkedin_text = new_text.strip()
        await db.commit()

    char_count = len(new_text.strip())
    await update.message.reply_text(
        f"✅ *Post #{post_id} actualizado* ({char_count}/{_LI_CHAR_LIMIT} chars)",
        parse_mode="Markdown",
    )


# ── Procesado de tweet URL ─────────────────────────────────────────────────

async def _process_tweet_url(
    update: Update, context: ContextTypes.DEFAULT_TYPE, url: str
):
    """Scraping + generación + preview + botones de acción."""
    from sqlalchemy import select

    from ..database import AsyncSessionLocal
    from ..models import AppSettings
    from ..services.post_generator import generate_linkedin_post
    from ..services.x_scraper import scrape_tweet

    # Paso 1: Analizando tweet
    wait_msg = await update.message.reply_text("🔍 Analizando tweet…")

    try:
        tweet = await scrape_tweet(url)
    except Exception as e:
        await wait_msg.edit_text(f"❌ No pude extraer el tweet:\n`{e}`", parse_mode="Markdown")
        return

    # Paso 2: Generando con IA
    await wait_msg.edit_text("🤖 Generando post con IA…")

    async with AsyncSessionLocal() as db:
        cfg_result = await db.execute(select(AppSettings).where(AppSettings.id == 1))
        cfg = cfg_result.scalar_one_or_none()
        custom_prompt = cfg.custom_prompt if cfg else None

    try:
        linkedin_text = await generate_linkedin_post(
            tweet=tweet,
            language=settings.post_language or "es",
            custom_prompt=custom_prompt,
        )
    except Exception as e:
        await wait_msg.edit_text(f"❌ Error generando el post:\n`{e}`", parse_mode="Markdown")
        return

    if linkedin_text.startswith("[NO_PUBLICAR]"):
        reason = linkedin_text.split(":", 1)[-1].strip()
        await wait_msg.edit_text(
            f"⚠️ Este tweet no es publicable:\n_{reason}_",
            parse_mode="Markdown",
        )
        return

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

    await _show_preview(wait_msg, post_data, edit=True)


def _build_media_summary(post_data: dict) -> str:
    """Resumen de la multimedia que se adjuntará al publicar."""
    media_type = post_data["media_type"]
    lines = []

    if media_type == "video":
        lines.append("🎥 *Multimedia:* Video del tweet")
        if post_data.get("tweet_url"):
            lines.append(f"   └ Fuente: {post_data['tweet_url']}")

    elif media_type == "document":
        lines.append("📄 *Multimedia:* Documento PDF")
        title = post_data.get("document_title", "")
        pdf_url = post_data.get("pdf_url", "")
        if title:
            lines.append(f"   └ Título: {title}")
        if pdf_url:
            lines.append(f"   └ URL: {pdf_url}")

    elif media_type == "image":
        image_urls = post_data.get("image_urls") or []
        n = len(image_urls)
        lines.append(f"🖼️ *Multimedia:* {n} imagen{'es' if n != 1 else ''} del tweet")
        for i, url in enumerate(image_urls[:4], 1):
            lines.append(f"   └ [{i}] {url}")
        if n > 4:
            lines.append(f"   └ … y {n - 4} más")

    elif media_type == "generate":
        lines.append("🎨 *Multimedia:* Sin imagen/video — Google Imagen generará una automáticamente")

    else:
        lines.append("📝 *Multimedia:* Sin adjunto")

    return "\n".join(lines)


async def _show_preview(msg, post_data: dict, edit: bool = False):
    """Muestra (o edita) el mensaje de preview con botones de acción."""
    icons = {"video": "🎥", "document": "📄", "image": "🖼️", "generate": "🎨"}
    media_type = post_data["media_type"]
    media_icon = icons.get(media_type, "📝")
    linkedin_text = post_data["linkedin_text"]
    char_count = len(linkedin_text)
    char_bar = f"{char_count}/{_LI_CHAR_LIMIT}"
    if char_count > _LI_CHAR_LIMIT:
        char_bar = f"⚠️ {char_bar} — EXCEDE el límite"

    media_summary = _build_media_summary(post_data)

    # Header + media_summary + footer → ~3600 chars disponibles para el cuerpo
    _TG_BODY_LIMIT = 3600
    preview = linkedin_text[:_TG_BODY_LIMIT] + (
        "…\n_(texto cortado — usa ✏️ Editar para ver completo)_"
        if len(linkedin_text) > _TG_BODY_LIMIT else ""
    )

    text = (
        f"{media_icon} *Preview del post:*\n\n"
        f"{preview}\n\n"
        f"_{char_bar} caracteres_\n\n"
        f"{media_summary}"
    )

    if edit:
        preview_msg = await msg.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("📅 Programar", callback_data="sched:0"),
                InlineKeyboardButton("🚀 Publicar ahora", callback_data="pub:0"),
            ], [
                InlineKeyboardButton("🔄 Regenerar", callback_data="regen:0"),
                InlineKeyboardButton("🗑️ Descartar", callback_data="disc:0"),
            ]]),
            parse_mode="Markdown",
        )
    else:
        preview_msg = await msg.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("📅 Programar", callback_data="sched:0"),
                InlineKeyboardButton("🚀 Publicar ahora", callback_data="pub:0"),
            ], [
                InlineKeyboardButton("🔄 Regenerar", callback_data="regen:0"),
                InlineKeyboardButton("🗑️ Descartar", callback_data="disc:0"),
            ]]),
            parse_mode="Markdown",
        )

    mid = preview_msg.message_id
    _pending[mid] = post_data

    await preview_msg.edit_reply_markup(_preview_keyboard(mid))


# ── Callbacks de botones ───────────────────────────────────────────────────

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if bool(settings.telegram_user_id) and query.from_user.id != settings.telegram_user_id:
        return

    data = query.data or ""

    if data.startswith("cmd:"):
        await _do_quick_cmd(query, data[4:])
    elif data.startswith("cancel:"):
        await _do_cancel(query, int(data.split(":")[1]))
    elif data.startswith("sched:"):
        await _do_schedule(query, int(data.split(":")[1]))
    elif data.startswith("pub:"):
        await _do_publish_now(query, int(data.split(":")[1]))
    elif data.startswith("disc:"):
        await _do_discard_confirm(query, int(data.split(":")[1]))
    elif data.startswith("disc_yes:"):
        await _do_discard_final(query, int(data.split(":")[1]))
    elif data.startswith("disc_no:"):
        mid = int(data.split(":")[1])
        await query.edit_message_reply_markup(_preview_keyboard(mid))
    elif data.startswith("regen:"):
        await _do_regenerate(query, int(data.split(":")[1]))
    elif data.startswith("edit_pending:"):
        await _do_edit_pending(query, int(data.split(":")[1]))
    elif data.startswith("edit_pre:"):
        await _do_edit_pre(query, int(data.split(":")[1]))
    elif data.startswith("cancel_pre:"):
        await _do_cancel(query, int(data.split(":")[1]))


async def _do_quick_cmd(query, cmd: str):
    """Ejecuta un comando desde los botones inline del /start."""
    fake_update = query.message
    if cmd == "hoy":
        await fake_update.reply_text("Cargando posts de hoy…")
        # Invocar lógica directamente
        from datetime import datetime, timezone
        from zoneinfo import ZoneInfo
        from sqlalchemy import select
        from ..database import AsyncSessionLocal
        from ..models import ScheduledPost

        mty_tz = ZoneInfo("America/Monterrey")
        now_mty = datetime.now(mty_tz)
        today_start = now_mty.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc).replace(tzinfo=None)
        today_end = now_mty.replace(hour=23, minute=59, second=59).astimezone(timezone.utc).replace(tzinfo=None)

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
            await fake_update.reply_text("📭 No hay posts programados para hoy.")
            return

        icons = {"scheduled": "⏰", "published": "✅", "failed": "❌"}
        lines = ["📅 *Posts de hoy:*\n"]
        for p in posts:
            sched = datetime.fromisoformat(str(p.scheduled_at)).replace(tzinfo=timezone.utc)
            sched_mty = sched.astimezone(mty_tz)
            icon = icons.get(p.status, "❓")
            preview = (p.linkedin_text or "")[:80].replace("\n", " ")
            lines.append(f"{icon} {sched_mty.strftime('%H:%M')} — {preview}…")

        await fake_update.reply_text("\n".join(lines), parse_mode="Markdown")

    elif cmd == "pendientes":
        from datetime import datetime, timezone
        from zoneinfo import ZoneInfo
        from sqlalchemy import select
        from ..database import AsyncSessionLocal
        from ..models import ScheduledPost

        mty_tz = ZoneInfo("America/Monterrey")
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(ScheduledPost).where(ScheduledPost.status == "scheduled").order_by(ScheduledPost.scheduled_at)
            )
            posts = result.scalars().all()

        if not posts:
            await fake_update.reply_text("📭 No hay posts programados pendientes.")
            return

        await fake_update.reply_text(
            f"📋 *{len(posts)} post{'s' if len(posts) > 1 else ''} en cola:*",
            parse_mode="Markdown",
        )
        for p in posts[:15]:
            sched = datetime.fromisoformat(str(p.scheduled_at)).replace(tzinfo=timezone.utc)
            sched_mty = sched.astimezone(mty_tz)
            preview = (p.linkedin_text or "")[:100].replace("\n", " ")
            keyboard = [[InlineKeyboardButton(f"❌ Cancelar #{p.id}", callback_data=f"cancel:{p.id}")]]
            await fake_update.reply_text(
                f"⏰ *{sched_mty.strftime('%d/%m %H:%M')}* — {preview}…",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown",
            )

    elif cmd == "status":
        from datetime import datetime, timezone
        from zoneinfo import ZoneInfo
        from sqlalchemy import select, func
        from ..database import AsyncSessionLocal
        from ..models import ScheduledPost, LinkedInToken
        from .scheduler_service import scheduler

        mty_tz = ZoneInfo("America/Monterrey")
        now_mty = datetime.now(mty_tz)
        today_start = now_mty.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc).replace(tzinfo=None)
        today_end = now_mty.replace(hour=23, minute=59, second=59).astimezone(timezone.utc).replace(tzinfo=None)

        async with AsyncSessionLocal() as db:
            token_result = await db.execute(select(LinkedInToken).limit(1))
            token = token_result.scalar_one_or_none()
            li_status = "✅ Conectado" if token else "❌ Desconectado"

            posts_hoy_result = await db.execute(
                select(ScheduledPost)
                .where(ScheduledPost.scheduled_at >= today_start)
                .where(ScheduledPost.scheduled_at <= today_end)
            )
            posts_hoy = posts_hoy_result.scalars().all()
            hoy_sched = sum(1 for p in posts_hoy if p.status == "scheduled")
            hoy_pub = sum(1 for p in posts_hoy if p.status == "published")

            pend_result = await db.execute(
                select(func.count()).select_from(ScheduledPost).where(ScheduledPost.status == "scheduled")
            )
            total_pend = pend_result.scalar()

        sched_status = "✅ Corriendo" if scheduler.running else "❌ Detenido"
        await fake_update.reply_text(
            f"📊 *Estado del sistema*\n\n"
            f"🔗 LinkedIn: {li_status}\n"
            f"⚙️ Scheduler: {sched_status}\n\n"
            f"📅 *Hoy ({now_mty.strftime('%d/%m')}):*\n"
            f"  ⏰ Programados: {hoy_sched}\n"
            f"  ✅ Publicados: {hoy_pub}\n\n"
            f"📋 Total en cola: {total_pend}",
            parse_mode="Markdown",
        )

    elif cmd == "help":
        await fake_update.reply_text(
            "📖 *Cómo usar el bot*\n\n"
            "1. Envía un URL de tweet (x.com o twitter.com)\n"
            "2. El bot genera el post de LinkedIn con IA\n"
            "3. Elige: *Programar* / *Publicar ahora* / *Regenerar* / *Descartar*\n\n"
            "*Comandos:*\n"
            "/hoy — posts programados para hoy\n"
            "/pendientes — todos los posts en cola\n"
            "/status — estado del sistema\n"
            "/start — bienvenida",
            parse_mode="Markdown",
        )


async def _do_discard_confirm(query, mid: int):
    """Pide confirmación antes de descartar."""
    if mid not in _pending:
        await query.edit_message_reply_markup(None)
        await query.message.reply_text("⚠️ Este post ya no está disponible.")
        return
    await query.edit_message_reply_markup(
        InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Sí, descartar", callback_data=f"disc_yes:{mid}"),
            InlineKeyboardButton("↩️ Volver", callback_data=f"disc_no:{mid}"),
        ]])
    )


async def _do_discard_final(query, mid: int):
    """Descarta el post tras confirmación."""
    _pending.pop(mid, None)
    await query.edit_message_reply_markup(None)
    await query.message.reply_text("🗑️ Post descartado.")


async def _do_regenerate(query, mid: int):
    """Regenera el post con IA usando el mismo tweet."""
    post_data = _pending.get(mid)
    if not post_data:
        await query.edit_message_reply_markup(None)
        await query.message.reply_text(
            "⚠️ Los datos ya no están en memoria. Genera el post de nuevo."
        )
        return

    from sqlalchemy import select
    from ..database import AsyncSessionLocal
    from ..models import AppSettings
    from ..services.post_generator import generate_linkedin_post
    from ..services.x_scraper import scrape_tweet

    await query.edit_message_reply_markup(None)
    await query.edit_message_text("🤖 Regenerando post con IA…")

    try:
        tweet = await scrape_tweet(post_data["tweet_url"])
    except Exception as e:
        await query.edit_message_text(f"❌ No pude extraer el tweet:\n`{e}`", parse_mode="Markdown")
        return

    async with AsyncSessionLocal() as db:
        cfg_result = await db.execute(select(AppSettings).where(AppSettings.id == 1))
        cfg = cfg_result.scalar_one_or_none()
        custom_prompt = cfg.custom_prompt if cfg else None

    try:
        linkedin_text = await generate_linkedin_post(
            tweet=tweet,
            language=settings.post_language or "es",
            custom_prompt=custom_prompt,
        )
    except Exception as e:
        await query.edit_message_text(f"❌ Error regenerando:\n`{e}`", parse_mode="Markdown")
        return

    if linkedin_text.startswith("[NO_PUBLICAR]"):
        reason = linkedin_text.split(":", 1)[-1].strip()
        await query.edit_message_text(
            f"⚠️ Este tweet no es publicable:\n_{reason}_",
            parse_mode="Markdown",
        )
        _pending.pop(mid, None)
        return

    # Actualizar datos y mostrar nuevo preview en el mismo mensaje
    post_data["linkedin_text"] = linkedin_text
    _pending[mid] = post_data

    char_count = len(linkedin_text)
    char_bar = f"{char_count}/{_LI_CHAR_LIMIT}"
    if char_count > _LI_CHAR_LIMIT:
        char_bar = f"⚠️ {char_bar} — EXCEDE el límite"

    icons = {"video": "🎥", "document": "📄", "image": "🖼️", "generate": "🎨"}
    media_icon = icons.get(post_data["media_type"], "📝")
    media_summary = _build_media_summary(post_data)
    _TG_BODY_LIMIT = 3600
    preview = linkedin_text[:_TG_BODY_LIMIT] + (
        "…\n_(texto cortado — usa ✏️ Editar para ver completo)_"
        if len(linkedin_text) > _TG_BODY_LIMIT else ""
    )

    await query.edit_message_text(
        f"{media_icon} *Preview del post (regenerado):*\n\n"
        f"{preview}\n\n"
        f"_{char_bar} caracteres_\n\n"
        f"{media_summary}",
        reply_markup=_preview_keyboard(mid),
        parse_mode="Markdown",
    )


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
        generate_nano_banana_image,
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
            await status_msg.edit_text("⏳ Descargando video del tweet…")
            video_bytes = await download_tweet_video(post_data["tweet_url"])
            if not video_bytes:
                logger.warning("Video download failed, falling back to thumbnail/image")
                await status_msg.edit_text("⚠️ No se pudo descargar el video, publicando con thumbnail…")
                media_type = "image"  # usará el poster/thumbnail en image_urls si lo hay
        elif media_type == "document" and post_data.get("pdf_url"):
            document_bytes = await download_pdf(post_data["pdf_url"])
        elif media_type == "generate":
            generated_image_bytes = await generate_nano_banana_image(post_data["linkedin_text"])

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


async def _do_edit_pending(query, mid: int):
    """Entra en modo edición para un post pendiente (preview antes de publicar/programar)."""
    post_data = _pending.get(mid)
    if not post_data:
        await query.edit_message_reply_markup(None)
        await query.message.reply_text("⚠️ Los datos ya no están en memoria. Genera el post de nuevo.")
        return

    user_id = query.from_user.id
    _awaiting_edit_preview[user_id] = mid

    full_text = post_data["linkedin_text"]
    char_count = len(full_text)
    # Mostrar el texto completo en bloques si supera el límite de Telegram
    header = (
        f"✏️ *Modo edición — Preview*\n\n"
        f"Texto actual ({char_count}/{_LI_CHAR_LIMIT} chars):\n\n"
    )
    footer = "\n\n_Envía el nuevo texto en tu próximo mensaje para reemplazarlo._"

    # Si el texto + header + footer caben en un mensaje, enviarlo junto
    if len(header) + len(full_text) + len(footer) <= 4096:
        await query.message.reply_text(
            header + f"`{full_text}`" + footer,
            parse_mode="Markdown",
        )
    else:
        # Enviar header + texto en mensaje(s) separado(s)
        await query.message.reply_text(header, parse_mode="Markdown")
        # Enviar el texto en chunks de 4000 chars
        for i in range(0, len(full_text), 4000):
            chunk = full_text[i:i + 4000]
            await query.message.reply_text(f"`{chunk}`", parse_mode="Markdown")
        await query.message.reply_text(footer, parse_mode="Markdown")


async def _handle_edit_preview_text(update: Update, new_text: str):
    """Actualiza el texto del preview pendiente con el texto enviado."""
    user_id = update.effective_user.id
    mid = _awaiting_edit_preview.pop(user_id)

    if not new_text.strip():
        await update.message.reply_text("⚠️ El texto está vacío. Edición cancelada.")
        return

    post_data = _pending.get(mid)
    if not post_data:
        await update.message.reply_text("⚠️ Los datos ya no están en memoria. Genera el post de nuevo.")
        return

    post_data["linkedin_text"] = new_text.strip()
    _pending[mid] = post_data

    char_count = len(new_text.strip())
    char_bar = f"{char_count}/{_LI_CHAR_LIMIT}"
    if char_count > _LI_CHAR_LIMIT:
        char_bar = f"⚠️ {char_bar} — EXCEDE el límite"

    await update.message.reply_text(
        f"✅ *Texto actualizado* ({char_bar} chars)\n\n"
        f"Usa los botones del mensaje anterior para programar o publicar.",
        parse_mode="Markdown",
    )
    # Mostrar nuevo preview
    await _show_preview(update.message, post_data, edit=False)


async def _do_edit_pre(query, post_id: int):
    """Entra en modo edición para un post programado (desde notificación pre-publicación)."""
    from sqlalchemy import select
    from ..database import AsyncSessionLocal
    from ..models import ScheduledPost

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(ScheduledPost).where(ScheduledPost.id == post_id))
        post = result.scalar_one_or_none()
        if not post or post.status != "scheduled":
            await query.edit_message_reply_markup(None)
            await query.message.reply_text("⚠️ Este post ya no está programado.")
            return
        full_text = post.linkedin_text or ""

    user_id = query.from_user.id
    _awaiting_edit[user_id] = post_id

    await query.edit_message_reply_markup(None)
    await query.message.reply_text(
        f"✏️ *Modo edición — Post #{post_id}*\n\n"
        f"Texto actual:\n\n`{full_text}`\n\n"
        f"Envía el nuevo texto en tu próximo mensaje.\n"
        f"_(Envía cualquier URL de tweet para cancelar y empezar de nuevo)_",
        parse_mode="Markdown",
    )


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


async def notify_upcoming(
    post_id: int,
    linkedin_text: str,
    scheduled_at_str: str,
    media_type: str = "",
    media_detail: str = "",
):
    """Llamar desde el scheduler 10 min antes de la publicación."""
    if not _application or not settings.telegram_user_id:
        return
    try:
        preview = (linkedin_text or "")[:300]
        suffix = "…" if len(linkedin_text) > 300 else ""

        media_icons = {"video": "🎥 Video", "document": "📄 PDF", "image": "🖼️ Imagen", "generate": "🎨 Imagen generada por IA"}
        media_line = media_icons.get(media_type, "📝 Sin multimedia")
        if media_detail:
            media_line += f"\n   └ {media_detail}"

        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("✏️ Editar", callback_data=f"edit_pre:{post_id}"),
            InlineKeyboardButton("❌ Cancelar", callback_data=f"cancel_pre:{post_id}"),
        ]])
        await _application.bot.send_message(
            chat_id=settings.telegram_user_id,
            text=(
                f"⏰ *Post #{post_id} se publica a las {scheduled_at_str}*\n"
                f"_(en ~10 minutos)_\n\n"
                f"{preview}{suffix}\n\n"
                f"*Multimedia:* {media_line}"
            ),
            reply_markup=keyboard,
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.warning(f"Notificación Telegram (pre-publicación) falló: {e}")


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
    _application.add_handler(CommandHandler("status", cmd_status))
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
