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
import html
import logging
import re
import traceback
from datetime import datetime
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
from ..services.x_scraper import is_x_post_url

logger = logging.getLogger(__name__)
settings = get_settings()

# ── Estado global ──────────────────────────────────────────────────────────
_application: Optional[Application] = None

# Posts generados esperando confirmación del usuario
# Clave: message_id del mensaje de preview → datos del post
_pending: dict[int, dict] = {}

# Modo edición para post programado: user_id → post_id
_awaiting_edit: dict[int, int] = {}
# Modo revisión editorial para radar pendiente: user_id → post_id
_awaiting_radar_revision: dict[int, int] = {}
# Modo edición para preview pendiente (antes de programar/publicar): user_id → mid
_awaiting_edit_preview: dict[int, int] = {}
# Modo edición para sugerencia de respuesta a comentario: user_id → comment_id
_awaiting_comment_edit: dict[int, int] = {}
# Modo reprogramar: user_id → post_id
_awaiting_reschedule: dict[int, int] = {}
# Modo consulta por día: users esperando escribir una fecha
_awaiting_dia: set[int] = set()

# Regex para detectar cualquier URL genérica (no tweet)
_URL_RE = re.compile(
    r"https?://[^\s]+",
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


def _truncate_text_naturally(text: str, limit: int) -> str:
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    if len(cleaned) <= limit:
        return cleaned

    sentence_cut = max(
        cleaned.rfind(". ", 0, limit),
        cleaned.rfind("? ", 0, limit),
        cleaned.rfind("! ", 0, limit),
    )
    if sentence_cut >= int(limit * 0.6):
        return cleaned[:sentence_cut + 1].rstrip() + "…"

    word_cut = cleaned.rfind(" ", 0, limit)
    if word_cut >= int(limit * 0.6):
        return cleaned[:word_cut].rstrip(" ,;:") + "…"

    return cleaned[:limit].rstrip(" ,;:") + "…"


def _sanitize_comment_reply_preview(text: str) -> str:
    cleaned = (text or "").strip()
    if not cleaned:
        return ""

    cleaned = re.sub(r'^.*?"reply"\s*[: ,]\s*"', "", cleaned, flags=re.IGNORECASE | re.DOTALL)
    cleaned = cleaned.replace(r"\n", "\n").replace(r"\\n", "\n")
    cleaned = cleaned.strip().strip("`").strip()
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return cleaned


async def _handle_telegram_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    detail = "".join(
        traceback.format_exception(
            type(context.error),
            context.error,
            context.error.__traceback__,
        )
    ) if context.error else "Sin detalle de excepción."
    logger.error("Error no controlado en Telegram.\n%s", detail)


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


def _comment_reply_keyboard(comment_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Publicar respuesta", callback_data=f"comment_pub:{comment_id}"),
        ],
        [
            InlineKeyboardButton("✏️ Editar respuesta", callback_data=f"comment_edit:{comment_id}"),
            InlineKeyboardButton("⏭️ No publicar", callback_data=f"comment_dismiss:{comment_id}"),
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
        "Envíame un URL de tweet *o cualquier artículo/noticia web* y lo convierto en un post de LinkedIn.\n\n"
        "Si no hay imagen real en la fuente, lo preparo sin adjunto y cuido mejor la frase ancla.",
        parse_mode="Markdown",
        reply_markup=keyboard,
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        await _deny(update)
        return
    await update.message.reply_text(
        "📖 *Cómo usar el bot*\n\n"
        "1\\. Envía un URL de tweet \\(x\\.com\\) *o cualquier artículo web*\n"
        "2\\. El bot extrae el contenido y genera el post de LinkedIn con IA\n"
        "3\\. Si no hay imagen real, se publica sin adjunto y con mejor frase ancla\n"
        "4\\. Elige: *Programar* / *Publicar ahora* / *Regenerar* / *Descartar*\n\n"
        "*Comandos:*\n"
        "/hoy — posts de hoy con botones de edición\n"
        "/dia \\[DD/MM\\] — posts de cualquier día\n"
        "/pendientes — todos los posts en cola \\(con opción a cancelar\\)\n"
        "/articulos — busca artículos largos de X entre tus likes pendientes\n"
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
    from ..models import ScheduledPost
    from .linkedin_auth import LinkedInAuthError, ensure_valid_linkedin_token, load_linkedin_token
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
        token = await load_linkedin_token(db)
        li_note = ""
        if not token:
            li_status = "❌ Desconectado"
        else:
            try:
                await ensure_valid_linkedin_token(db)
                li_status = "✅ Conectado"
            except LinkedInAuthError as exc:
                li_status = "⚠️ Reconexión requerida"
                li_note = f"\n🔐 Acción: {exc}\n"

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
        f"{li_note}"
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
            .where(ScheduledPost.status.in_(["scheduled", "published", "failed", "approval_pending", "radar_slot"]))
            .where(ScheduledPost.scheduled_at >= today_start)
            .where(ScheduledPost.scheduled_at <= today_end)
            .order_by(ScheduledPost.scheduled_at)
        )
        posts = result.scalars().all()

    if not posts:
        await update.message.reply_text("📭 No hay posts programados para hoy.")
        return

    await update.message.reply_text(
        f"📅 *Posts de hoy ({now_mty.strftime('%d/%m')}):* {len(posts)} post{'s' if len(posts) > 1 else ''}",
        parse_mode="Markdown",
    )
    await _send_posts_list(update.message, posts, mty_tz)


async def cmd_dia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        await _deny(update)
        return

    args = context.args
    if args:
        fecha_str = args[0]
        await _show_day_posts(update.message, fecha_str)
    else:
        _awaiting_dia.add(update.effective_user.id)
        await update.message.reply_text(
            "📅 ¿Qué día quieres consultar?\n"
            "Envía la fecha en formato *DD/MM* o *DD/MM/AAAA*\n"
            "Ejemplo: `25/03` o `25/03/2026`",
            parse_mode="Markdown",
        )


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
            .where(ScheduledPost.status.in_(["scheduled", "approval_pending", "radar_slot"]))
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

    for p in posts[:30]:
        sched_mty = None
        if p.scheduled_at:
            sched = datetime.fromisoformat(str(p.scheduled_at)).replace(tzinfo=timezone.utc)
            sched_mty = sched.astimezone(mty_tz)
        preview = (p.linkedin_text or "")[:100].replace("\n", " ")
        when = sched_mty.strftime("%d/%m %H:%M") if sched_mty else "sin slot"
        state = "Aprobación abierta" if p.status == "approval_pending" else "Programado"
        await update.message.reply_text(
            f"*{state} · #{p.id}*\nSlot original: {when}\n{preview}…",
            reply_markup=_post_keyboard(p.id, p.status),
            parse_mode="Markdown",
        )


async def cmd_articulos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Escanea los likes pendientes (skipped) y los posts programados para
    identificar artículos largos de X que pueden tener contenido incompleto.
    Permite re-procesar los que son artículos.
    """
    if not _authorized(update):
        await _deny(update)
        return

    from sqlalchemy import select
    from ..database import AsyncSessionLocal
    from ..models import XLikedTweet, ScheduledPost

    wait_msg = await update.message.reply_text("🔍 Buscando artículos de X entre tus likes y posts programados…")

    # 1. Likes skipped (nunca procesados) — candidatos a ser artículos
    async with AsyncSessionLocal() as db:
        skipped_result = await db.execute(
            select(XLikedTweet)
            .where(XLikedTweet.status == "skipped")
            .order_by(XLikedTweet.id.desc())
            .limit(50)
        )
        skipped = skipped_result.scalars().all()

        # 2. Posts programados (aún no publicados)
        sched_result = await db.execute(
            select(ScheduledPost)
            .where(ScheduledPost.status == "scheduled")
            .order_by(ScheduledPost.scheduled_at)
        )
        scheduled = sched_result.scalars().all()

    if not skipped and not scheduled:
        await wait_msg.edit_text("📭 No hay likes skipped ni posts programados para revisar.")
        return

    lines = [
        f"📰 *Análisis de artículos de X*\n\n"
        f"Likes no procesados (skipped): *{len(skipped)}*\n"
        f"Posts programados pendientes: *{len(scheduled)}*\n\n"
        f"Los artículos de X se reconocen por su URL normal pero tienen contenido largo.\n\n"
        f"Para re-procesar un like skipped, envíame su URL directamente.\n"
        f"Para ver posts programados usa /hoy o /pendientes.\n\n"
        f"*Últimos likes sin procesar:*"
    ]

    await wait_msg.edit_text("\n".join(lines), parse_mode="Markdown")

    # Mostrar los últimos likes skipped con botón para procesar
    shown = 0
    for liked in skipped[:10]:
        if not liked.tweet_url:
            continue
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton(
                f"▶️ Procesar este like",
                callback_data=f"proc_liked:{liked.id}",
            )
        ]])
        await update.message.reply_text(
            f"🔗 {liked.tweet_url}\n_ID: {liked.tweet_id} | Autor: {liked.tweet_author}_",
            reply_markup=keyboard,
            parse_mode="Markdown",
        )
        shown += 1

    if not shown:
        await update.message.reply_text("No hay likes skipped con URL disponible.")
    elif len(skipped) > 10:
        await update.message.reply_text(
            f"_Mostrando 10 de {len(skipped)} likes sin procesar._",
            parse_mode="Markdown",
        )


# ── Mensajes de texto (detección de URL de tweet o modo edición) ──────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        await _deny(update)
        return

    user_id = update.effective_user.id
    text = update.message.text or ""

    # Una respuesta a la tarjeta identifica el post aunque existan varias
    # aprobaciones abiertas o el bot se haya reiniciado.
    reply_text = ""
    if update.message.reply_to_message:
        reply_text = (
            update.message.reply_to_message.text
            or update.message.reply_to_message.caption
            or ""
        )
    reply_match = re.search(r"Post\s+#(\d+)", reply_text, flags=re.IGNORECASE)
    reply_is_approval = "aprob" in reply_text.casefold() or "radar listo" in reply_text.casefold()
    if reply_match and reply_is_approval:
        await _handle_radar_revision_text(
            update,
            text,
            post_id=int(reply_match.group(1)),
        )
        return

    if user_id in _awaiting_radar_revision:
        await _handle_radar_revision_text(update, text)
        return

    # Modo edición de preview pendiente (antes de publicar/programar)
    if user_id in _awaiting_edit_preview:
        await _handle_edit_preview_text(update, text)
        return

    # Modo edición de post programado
    if user_id in _awaiting_edit:
        await _handle_edit_text(update, text)
        return

    # Modo edición de sugerencia para comentario
    if user_id in _awaiting_comment_edit:
        await _handle_comment_edit_text(update, text)
        return

    # Modo reprogramar post
    if user_id in _awaiting_reschedule:
        await _handle_reschedule_text(update, text)
        return

    # Modo consulta por día
    if user_id in _awaiting_dia:
        _awaiting_dia.discard(user_id)
        await _show_day_posts(update.message, text.strip())
        return

    urls = _URL_RE.findall(text)
    x_post_url = next((url for url in urls if is_x_post_url(url)), None)
    if x_post_url:
        await _process_tweet_url(update, context, x_post_url)
        return

    if urls:
        await _process_generic_url(update, context, urls[0])
        return

    await update.message.reply_text(
        "Envíame un URL de tweet o cualquier artículo/noticia web para generar un post de LinkedIn.\n\n"
        "Ejemplos:\n"
        "• https://x.com/usuario/status/12345\n"
        "• https://x.com/usuario/article/12345\n"
        "• https://techcrunch.com/articulo\n\n"
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
        if not post or post.status not in {"scheduled", "approval_pending"}:
            await update.message.reply_text("⚠️ El post ya no está disponible para editar.")
            return
        post.linkedin_text = new_text.strip()
        post.manual_edited_at = datetime.utcnow()
        post.manual_edited_via = "telegram"
        if post.media_type == "generate":
            post.media_type = "none"
            post.generated_image_path = None
        status = post.status
        await db.commit()

    char_count = len(new_text.strip())
    reply_markup = _radar_approval_keyboard(post_id) if status == "approval_pending" else None
    suffix = "\n\nPuedes aprobarlo cuando quede listo." if status == "approval_pending" else ""
    await update.message.reply_text(
        f"✅ *Post #{post_id} actualizado* ({char_count}/{_LI_CHAR_LIMIT} chars){suffix}",
        reply_markup=reply_markup,
        parse_mode="Markdown",
    )


def _append_revision_note(previous: str | None, instruction: str) -> str:
    notes = [line.strip() for line in (previous or "").splitlines() if line.strip()]
    cleaned = instruction.strip()
    if cleaned and cleaned.casefold() not in {line.casefold() for line in notes}:
        notes.append(cleaned)
    return "\n".join(notes)[-5000:]


async def _handle_radar_revision_text(
    update: Update,
    instructions: str,
    *,
    post_id: int | None = None,
):
    """Reescribe un radar pendiente aplicando instrucciones naturales de Telegram."""
    from sqlalchemy import select

    from ..database import AsyncSessionLocal
    from ..models import AppSettings, ScheduledPost
    from .editorial_learning import get_editorial_learning_profile
    from .post_generator import revise_linkedin_post_from_instructions

    user_id = update.effective_user.id
    if post_id is None:
        post_id = _awaiting_radar_revision.pop(user_id, None)
    else:
        _awaiting_radar_revision.pop(user_id, None)

    if not post_id:
        await update.message.reply_text("No pude identificar qué publicación quieres cambiar.")
        return
    if not instructions.strip():
        await update.message.reply_text("La instrucción está vacía. La publicación sigue pendiente.")
        return

    status_msg = await update.message.reply_text(
        f"Aplicando tus cambios al post #{post_id}…"
    )

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(ScheduledPost).where(ScheduledPost.id == post_id))
        post = result.scalar_one_or_none()
        if not post or post.status != "approval_pending":
            await status_msg.edit_text(
                f"El post #{post_id} ya no está pendiente de aprobación."
            )
            return

        cfg_result = await db.execute(select(AppSettings).where(AppSettings.id == 1))
        cfg = cfg_result.scalar_one_or_none()
        custom_prompt = cfg.custom_prompt if cfg else None
        original_post = post.linkedin_text or ""
        source_url = post.tweet_url or ""
        previous_notes = post.editorial_revision_notes or ""
        source_summary = "\n".join(
            part
            for part in (
                f"Autor o fuente: {post.tweet_author}" if post.tweet_author else "",
                post.tweet_text or "",
                post.error_message or "",
            )
            if part
        )
        try:
            editorial_profile = await get_editorial_learning_profile(db)
        except Exception as exc:
            logger.warning("Telegram: no se pudo cargar memoria editorial: %s", exc)
            editorial_profile = ""

    try:
        revised = await revise_linkedin_post_from_instructions(
            original_post=original_post,
            source_summary=source_summary,
            source_url=source_url,
            instructions=instructions.strip(),
            previous_instructions=previous_notes,
            editorial_profile=editorial_profile,
            language=settings.post_language or "es",
            custom_prompt=custom_prompt,
        )
    except Exception as exc:
        logger.exception("Telegram: revisión del post %s falló", post_id)
        await status_msg.edit_text(
            f"No pude aplicar los cambios al post #{post_id}: {exc}\n"
            "La aprobación sigue abierta y el borrador anterior no cambió."
        )
        return

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(ScheduledPost).where(ScheduledPost.id == post_id))
        post = result.scalar_one_or_none()
        if not post or post.status != "approval_pending":
            await status_msg.edit_text(
                f"El post #{post_id} cambió de estado mientras preparaba la revisión. "
                "No sobrescribí el texto ni la acción que elegiste."
            )
            return

        post.linkedin_text = revised
        post.editorial_revision_notes = _append_revision_note(
            previous_notes,
            instructions,
        )
        post.manual_edited_at = datetime.utcnow()
        post.manual_edited_via = "telegram_revision"
        if post.media_type == "generate":
            post.media_type = "none"
            post.generated_image_path = None
        source_url = post.tweet_url or ""
        source_label = post.tweet_author or "Fuente elegida por radar"
        media_type = post.media_type or "none"
        radar_reason = post.error_message or ""
        await db.commit()

    try:
        await status_msg.delete()
    except Exception:
        pass
    await notify_radar_approval(
        post_id=post_id,
        linkedin_text=revised,
        scheduled_at_str="",
        source_url=source_url,
        source_label=source_label,
        media_type=media_type,
        radar_reason=radar_reason,
    )


# ── Helpers posts por día ─────────────────────────────────────────────────

def _post_keyboard(post_id: int, status: str) -> InlineKeyboardMarkup:
    """Teclado inline para un post en la lista /hoy o /dia."""
    rows = [[InlineKeyboardButton("👁 Ver completo", callback_data=f"view_post:{post_id}")]]
    if status == "scheduled":
        rows.append([
            InlineKeyboardButton("✏️ Editar", callback_data=f"edit_pre:{post_id}"),
            InlineKeyboardButton("📅 Cambiar fecha", callback_data=f"reschedule:{post_id}"),
        ])
        rows.append([InlineKeyboardButton("❌ Cancelar post", callback_data=f"cancel:{post_id}")])
    elif status == "approval_pending":
        rows.extend(_radar_approval_keyboard(post_id).inline_keyboard)
    elif status == "radar_slot":
        rows.append([InlineKeyboardButton("❌ Cancelar radar", callback_data=f"cancel:{post_id}")])
    return InlineKeyboardMarkup(rows)


def _radar_approval_keyboard(post_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Aprobar", callback_data=f"radar_approve:{post_id}"),
            InlineKeyboardButton("✏️ Pedir cambios", callback_data=f"edit_pre:{post_id}"),
        ],
        [
            InlineKeyboardButton("🔄 Buscar otra", callback_data=f"radar_regen:{post_id}"),
            InlineKeyboardButton("❌ Cancelar", callback_data=f"cancel_pre:{post_id}"),
        ],
    ])


async def _send_posts_list(msg, posts, mty_tz):
    """Envía cada post como mensaje individual con botones de acción."""
    from datetime import datetime, timezone

    icons = {
        "scheduled": "⏰",
        "published": "✅",
        "failed": "❌",
        "approval_pending": "🟡",
        "radar_slot": "📡",
    }
    for p in posts:
        sched = datetime.fromisoformat(str(p.scheduled_at)).replace(tzinfo=timezone.utc)
        sched_mty = sched.astimezone(mty_tz)
        icon = icons.get(p.status, "❓")
        preview = (p.linkedin_text or "Radar editorial pendiente")[:120].replace("\n", " ")
        keyboard = _post_keyboard(p.id, p.status) if p.status in ("scheduled", "published", "failed", "approval_pending", "radar_slot") else None
        await msg.reply_text(
            f"{icon} *{sched_mty.strftime('%H:%M')}* — {preview}…",
            reply_markup=keyboard,
            parse_mode="Markdown",
        )


async def _show_day_posts(msg, fecha_str: str):
    """Muestra posts de una fecha específica (formato DD/MM o DD/MM/AAAA)."""
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo
    from sqlalchemy import select
    from ..database import AsyncSessionLocal
    from ..models import ScheduledPost

    mty_tz = ZoneInfo("America/Monterrey")

    # Parsear fecha
    fecha_str = fecha_str.strip()
    target_date = None
    for fmt in ("%d/%m/%Y", "%d/%m", "%d-%m-%Y", "%d-%m"):
        try:
            parsed = datetime.strptime(fecha_str, fmt)
            if fmt in ("%d/%m", "%d-%m"):
                parsed = parsed.replace(year=datetime.now(mty_tz).year)
            target_date = parsed
            break
        except ValueError:
            continue

    if not target_date:
        await msg.reply_text(
            "⚠️ No entendí esa fecha. Usa formato *DD/MM* o *DD/MM/AAAA*.\nEjemplo: `25/03` o `25/03/2026`",
            parse_mode="Markdown",
        )
        return

    target_mty = target_date.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=mty_tz)
    day_start = target_mty.astimezone(timezone.utc).replace(tzinfo=None)
    day_end = target_mty.replace(hour=23, minute=59, second=59).astimezone(timezone.utc).replace(tzinfo=None)

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ScheduledPost)
            .where(ScheduledPost.status.in_(["scheduled", "published", "failed", "approval_pending", "radar_slot"]))
            .where(ScheduledPost.scheduled_at >= day_start)
            .where(ScheduledPost.scheduled_at <= day_end)
            .order_by(ScheduledPost.scheduled_at)
        )
        posts = result.scalars().all()

    label = target_mty.strftime("%d/%m/%Y")
    if not posts:
        await msg.reply_text(f"📭 No hay posts para el *{label}*.", parse_mode="Markdown")
        return

    await msg.reply_text(
        f"📅 *Posts del {label}:* {len(posts)} post{'s' if len(posts) > 1 else ''}",
        parse_mode="Markdown",
    )
    await _send_posts_list(msg, posts, mty_tz)


async def _do_view_post(query, post_id: int):
    """Muestra el texto completo de un post programado/publicado."""
    from sqlalchemy import select
    from ..database import AsyncSessionLocal
    from ..models import ScheduledPost
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo

    mty_tz = ZoneInfo("America/Monterrey")
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(ScheduledPost).where(ScheduledPost.id == post_id))
        post = result.scalar_one_or_none()

    if not post:
        await query.message.reply_text("⚠️ Post no encontrado.")
        return

    sched = datetime.fromisoformat(str(post.scheduled_at)).replace(tzinfo=timezone.utc)
    sched_mty = sched.astimezone(mty_tz)
    full_text = post.linkedin_text or ""
    char_count = len(full_text)

    status_label = {
        "scheduled": "⏰ programado",
        "published": "✅ publicado",
        "approval_pending": "🟡 pendiente de aprobación",
        "radar_slot": "📡 radar pendiente",
        "failed": "❌ falló",
    }.get(post.status, post.status)
    header = (
        f"📄 *Post #{post_id}* — {sched_mty.strftime('%d/%m %H:%M')} — "
        f"{status_label}\n"
        f"_{char_count}/{_LI_CHAR_LIMIT} chars_\n\n"
    )

    keyboard = None
    if post.status == "scheduled":
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✏️ Editar texto", callback_data=f"edit_pre:{post_id}"),
                InlineKeyboardButton("📅 Cambiar fecha", callback_data=f"reschedule:{post_id}"),
            ],
            [InlineKeyboardButton("❌ Cancelar post", callback_data=f"cancel:{post_id}")],
        ])
    elif post.status == "approval_pending":
        keyboard = _radar_approval_keyboard(post_id)
    elif post.status == "radar_slot":
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Cancelar radar", callback_data=f"cancel:{post_id}")],
        ])

    # Enviar en chunks si es muy largo
    if len(header) + len(full_text) <= 4000:
        await query.message.reply_text(
            header + full_text,
            reply_markup=keyboard,
            parse_mode="Markdown",
        )
    else:
        await query.message.reply_text(header, parse_mode="Markdown")
        for i in range(0, len(full_text), 4000):
            is_last = (i + 4000) >= len(full_text)
            await query.message.reply_text(
                full_text[i:i + 4000],
                reply_markup=keyboard if is_last else None,
            )


async def _do_reschedule_start(query, post_id: int):
    """Entra en modo espera de nueva fecha para reprogramar un post."""
    from sqlalchemy import select
    from ..database import AsyncSessionLocal
    from ..models import ScheduledPost
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo

    mty_tz = ZoneInfo("America/Monterrey")
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(ScheduledPost).where(ScheduledPost.id == post_id))
        post = result.scalar_one_or_none()

    if not post or post.status != "scheduled":
        await query.message.reply_text("⚠️ Este post ya no está programado.")
        return

    sched = datetime.fromisoformat(str(post.scheduled_at)).replace(tzinfo=timezone.utc)
    sched_mty = sched.astimezone(mty_tz)

    user_id = query.from_user.id
    _awaiting_reschedule[user_id] = post_id

    await query.message.reply_text(
        f"📅 *Reprogramar post #{post_id}*\n\n"
        f"Fecha actual: *{sched_mty.strftime('%d/%m/%Y %H:%M')}*\n\n"
        f"Envía la nueva fecha y hora:\n"
        f"• `DD/MM HH:MM` — mismo año\n"
        f"• `DD/MM/AAAA HH:MM` — con año\n"
        f"• `HH:MM` — solo cambiar hora (mismo día)\n\n"
        f"Ejemplo: `28/03 09:30`",
        parse_mode="Markdown",
    )


async def _handle_reschedule_text(update: Update, new_text: str):
    """Parsea la nueva fecha/hora y reprograma el post."""
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo
    from sqlalchemy import select
    from ..database import AsyncSessionLocal
    from ..models import ScheduledPost
    from ..services.scheduler_service import schedule_post, cancel_scheduled_post

    user_id = update.effective_user.id
    post_id = _awaiting_reschedule.pop(user_id)
    mty_tz = ZoneInfo("America/Monterrey")
    text = new_text.strip()

    # Obtener fecha actual del post para usar como base si solo se da hora
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(ScheduledPost).where(ScheduledPost.id == post_id))
        post = result.scalar_one_or_none()
        if not post or post.status != "scheduled":
            await update.message.reply_text("⚠️ El post ya no está programado.")
            return
        current_sched = datetime.fromisoformat(str(post.scheduled_at)).replace(tzinfo=timezone.utc).astimezone(mty_tz)

    new_dt = None
    for fmt in ("%d/%m/%Y %H:%M", "%d/%m %H:%M", "%H:%M"):
        try:
            parsed = datetime.strptime(text, fmt)
            if fmt == "%H:%M":
                # Solo hora: usar mismo día que el post actual
                new_dt = current_sched.replace(hour=parsed.hour, minute=parsed.minute, second=0, microsecond=0)
            elif fmt == "%d/%m %H:%M":
                new_dt = parsed.replace(year=datetime.now(mty_tz).year, second=0, microsecond=0, tzinfo=mty_tz)
            else:
                new_dt = parsed.replace(second=0, microsecond=0, tzinfo=mty_tz)
            break
        except ValueError:
            continue

    if not new_dt:
        _awaiting_reschedule[user_id] = post_id  # devolver al modo espera
        await update.message.reply_text(
            "⚠️ No entendí esa fecha. Usa:\n"
            "• `DD/MM HH:MM` — ej: `28/03 09:30`\n"
            "• `DD/MM/AAAA HH:MM` — ej: `28/03/2026 09:30`\n"
            "• `HH:MM` — solo cambiar hora",
            parse_mode="Markdown",
        )
        return

    new_dt_utc = new_dt.astimezone(timezone.utc).replace(tzinfo=None)

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(ScheduledPost).where(ScheduledPost.id == post_id))
        post = result.scalar_one_or_none()
        if not post or post.status != "scheduled":
            await update.message.reply_text("⚠️ El post ya no está programado.")
            return
        cancel_scheduled_post(post_id)
        post.scheduled_at = new_dt_utc
        await db.commit()
        schedule_post(post_id, new_dt_utc)

    await update.message.reply_text(
        f"✅ *Post #{post_id} reprogramado* para el "
        f"*{new_dt.strftime('%d/%m/%Y a las %H:%M')}* (Monterrey)",
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
    from ..services.x_scraper import is_arxiv_paper, scrape_tweet

    # Paso 1: Analizando tweet
    wait_msg = await update.message.reply_text("🔍 Analizando tweet…")

    try:
        tweet = await scrape_tweet(url)
    except Exception as e:
        await wait_msg.edit_text(f"❌ No pude extraer el tweet:\n`{e}`", parse_mode="Markdown")
        return

    # Notificar si es un artículo largo de X
    if tweet.is_article:
        await wait_msg.edit_text(
            "📰 Artículo largo de X detectado — extrayendo contenido completo…\n"
            "🤖 Generando post con IA…"
        )
    else:
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

    if is_arxiv_paper(tweet.paper_info) and tweet.pdf_url:
        media_type = "paper_image"
    elif tweet.has_video:
        media_type = "video"
    elif tweet.pdf_url:
        media_type = "document"
    elif tweet.images:
        media_type = "image"
    else:
        media_type = "none"

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
        "is_article": tweet.is_article,
    }

    await _show_preview(wait_msg, post_data, edit=True)


async def _process_generic_url(
    update: Update, context: ContextTypes.DEFAULT_TYPE, url: str
):
    """Extrae contenido de cualquier URL web y genera un post de LinkedIn."""
    from sqlalchemy import select

    from ..database import AsyncSessionLocal
    from ..models import AppSettings
    from ..services.url_scraper import UrlContent, scrape_url
    from ..services.post_generator import generate_linkedin_post_from_url_content
    from ..services.x_scraper import arxiv_pdf_url, fetch_paper_info

    wait_msg = await update.message.reply_text("🔍 Analizando contenido del enlace…")

    paper_info = None
    pdf_url = arxiv_pdf_url(url)
    if pdf_url:
        paper_info = await fetch_paper_info(url)

    try:
        if paper_info:
            content = UrlContent(
                url=url,
                title=paper_info.get("title", ""),
                text=paper_info.get("abstract", ""),
                author=", ".join(paper_info.get("authors", [])[:3]),
                images=[],
                source_domain="arxiv.org",
            )
        else:
            content = await scrape_url(url)
    except Exception as e:
        await wait_msg.edit_text(
            f"❌ No pude acceder al enlace:\n`{e}`", parse_mode="Markdown"
        )
        return

    if not content.text and not content.title:
        await wait_msg.edit_text(
            "⚠️ No se pudo extraer contenido útil de ese enlace. "
            "Prueba con otro URL o envía el texto manualmente."
        )
        return

    await wait_msg.edit_text("🤖 Generando post con IA…")

    async with AsyncSessionLocal() as db:
        cfg_result = await db.execute(select(AppSettings).where(AppSettings.id == 1))
        cfg = cfg_result.scalar_one_or_none()
        custom_prompt = cfg.custom_prompt if cfg else None

    try:
        linkedin_text = await generate_linkedin_post_from_url_content(
            url_content=content,
            language=settings.post_language or "es",
            custom_prompt=custom_prompt,
        )
    except Exception as e:
        await wait_msg.edit_text(
            f"❌ Error generando el post:\n`{e}`", parse_mode="Markdown"
        )
        return

    if linkedin_text.startswith("[NO_PUBLICAR]"):
        reason = linkedin_text.split(":", 1)[-1].strip()
        await wait_msg.edit_text(
            f"⚠️ Este contenido no es publicable:\n_{reason}_",
            parse_mode="Markdown",
        )
        return

    # Determinar tipo de media: arXiv como imagen del paper, imagenes reales del sitio o texto sin adjunto.
    if paper_info and pdf_url:
        media_type = "paper_image"
    elif content.images:
        media_type = "image"
    else:
        media_type = "none"

    post_data = {
        "tweet_url": url,  # reutilizamos el campo tweet_url para la fuente
        "tweet_text": (content.title or content.text[:200]),
        "tweet_author": content.author or content.source_domain or "",
        "linkedin_text": linkedin_text,
        "media_type": media_type,
        "image_urls": content.images or [],
        "use_first_image": media_type == "image",
        "pdf_url": pdf_url,
        "document_title": paper_info.get("title", "Documento") if paper_info else "Documento",
    }

    await _show_preview(wait_msg, post_data, edit=True)


def _build_media_summary(post_data: dict) -> str:
    """Resumen de la multimedia que se adjuntará al publicar."""
    media_type = post_data["media_type"]
    lines = []

    # Indicador de artículo largo de X
    if post_data.get("is_article"):
        lines.append("📰 *Tipo:* Artículo largo de X (contenido completo extraído)")

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

    elif media_type == "paper_image":
        lines.append("📑 *Multimedia:* Primera página del paper como imagen")
        title = post_data.get("document_title", "")
        pdf_url = post_data.get("pdf_url", "")
        if title:
            lines.append(f"   └ Título: {title}")
        if pdf_url:
            lines.append(f"   └ PDF: {pdf_url}")

    elif media_type == "image":
        image_urls = post_data.get("image_urls") or []
        n = len(image_urls)
        source_label = "de la fuente" if not post_data.get("tweet_url", "").startswith("https://x.com") and not post_data.get("tweet_url", "").startswith("https://twitter.com") else "del tweet"
        lines.append(f"🖼️ *Multimedia:* {n} imagen{'es' if n != 1 else ''} {source_label}")
        for i, url in enumerate(image_urls[:4], 1):
            lines.append(f"   └ [{i}] {url}")
        if n > 4:
            lines.append(f"   └ … y {n - 4} más")

    elif media_type == "generate":
        lines.append("📝 *Multimedia:* Sin adjunto")

    else:
        lines.append("📝 *Multimedia:* Sin adjunto")

    return "\n".join(lines)


async def _show_preview(msg, post_data: dict, edit: bool = False):
    """Muestra (o edita) el mensaje de preview con botones de acción."""
    from telegram.error import BadRequest as TgBadRequest

    icons = {"video": "🎥", "document": "📄", "paper_image": "📑", "image": "🖼️", "generate": "📝", "none": "📝"}
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

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("📅 Programar", callback_data="sched:0"),
        InlineKeyboardButton("🚀 Publicar ahora", callback_data="pub:0"),
    ], [
        InlineKeyboardButton("🔄 Regenerar", callback_data="regen:0"),
        InlineKeyboardButton("🗑️ Descartar", callback_data="disc:0"),
    ]])

    async def _send(txt: str, parse_md: bool):
        pm = "Markdown" if parse_md else None
        if edit:
            return await msg.edit_text(txt, reply_markup=keyboard, parse_mode=pm)
        else:
            return await msg.reply_text(txt, reply_markup=keyboard, parse_mode=pm)

    try:
        preview_msg = await _send(text, parse_md=True)
    except TgBadRequest:
        # El texto del post tiene caracteres especiales que rompen el parser Markdown
        # de Telegram (p.ej. * o _ no balanceados). Reintentamos sin parse_mode.
        logger.warning("_show_preview: Markdown parse error, retrying without parse_mode")
        plain = (
            f"{media_icon} Preview del post:\n\n"
            f"{linkedin_text[:_TG_BODY_LIMIT]}\n\n"
            f"{char_bar} caracteres\n\n"
            f"{media_summary.replace('*', '').replace('_', '')}"
        )
        preview_msg = await _send(plain, parse_md=False)

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
    logger.info("Callback Telegram recibido: %s", data.split(":", 1)[0])

    try:
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
        elif data.startswith("radar_approve:"):
            await _do_approve_radar(query, int(data.split(":")[1]))
        elif data.startswith("radar_regen:"):
            await _do_regenerate_radar(query, int(data.split(":")[1]))
        elif data.startswith("view_post:"):
            await _do_view_post(query, int(data.split(":")[1]))
        elif data.startswith("reschedule:"):
            await _do_reschedule_start(query, int(data.split(":")[1]))
        elif data.startswith("proc_liked:"):
            await _do_process_liked(query, int(data.split(":")[1]))
        elif data.startswith("comment_pub:"):
            await _do_publish_comment_reply(query, int(data.split(":")[1]))
        elif data.startswith("comment_edit:"):
            await _do_edit_comment_reply(query, int(data.split(":")[1]))
        elif data.startswith("comment_dismiss:"):
            await _do_dismiss_comment_reply(query, int(data.split(":")[1]))
        else:
            await query.message.reply_text("⚠️ No reconocí ese botón. Intenta con /pendientes.")
    except Exception as exc:
        logger.exception("Callback Telegram falló para %s", data.split(":", 1)[0])
        await query.message.reply_text(f"❌ Error procesando el botón: {exc}")


async def _do_process_liked(query, liked_id: int):
    """Re-procesa un liked tweet marcado como 'skipped', extrayendo contenido completo (incluyendo artículos)."""
    from sqlalchemy import select
    from ..database import AsyncSessionLocal
    from ..models import XLikedTweet
    from ..services.x_likes_monitor import process_liked_tweet

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(XLikedTweet).where(XLikedTweet.id == liked_id))
        liked = result.scalar_one_or_none()

    if not liked:
        await query.message.reply_text("⚠️ Like no encontrado.")
        return

    if liked.status not in ("skipped", "failed"):
        await query.message.reply_text(
            f"ℹ️ Este like ya tiene estado '{liked.status}'. Solo se pueden re-procesar los 'skipped' o 'failed'."
        )
        return

    await query.edit_message_reply_markup(None)
    status_msg = await query.message.reply_text(
        f"⏳ Procesando tweet {liked.tweet_id}…\n"
        f"_Esto puede tomar hasta 30 segundos mientras se extrae el contenido._",
        parse_mode="Markdown",
    )

    # Cambiar estado a processing antes de procesar
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(XLikedTweet).where(XLikedTweet.id == liked_id))
        liked_row = result.scalar_one_or_none()
        if liked_row:
            liked_row.status = "processing"
            liked_row.error_message = None
            await db.commit()

    try:
        await process_liked_tweet(liked.tweet_id, liked.tweet_url, liked.tweet_author)
    except Exception as e:
        await status_msg.edit_text(f"❌ Error procesando el tweet:\n`{e}`", parse_mode="Markdown")
        return

    # Verificar resultado
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(XLikedTweet).where(XLikedTweet.id == liked_id))
        updated = result.scalar_one_or_none()

    if updated and updated.status == "processed" and updated.post_id:
        await status_msg.edit_text(
            f"✅ Tweet procesado y programado como *Post #{updated.post_id}*",
            parse_mode="Markdown",
        )
    elif updated and updated.status == "rejected":
        await status_msg.edit_text(
            f"⚠️ Tweet rechazado (no publicable):\n_{updated.error_message}_",
            parse_mode="Markdown",
        )
    else:
        error = updated.error_message if updated else "desconocido"
        await status_msg.edit_text(
            f"❌ No se pudo procesar el tweet.\nError: `{error}`",
            parse_mode="Markdown",
        )


async def _do_quick_cmd(query, cmd: str):
    """Ejecuta un comando desde los botones inline del /start."""
    fake_update = query.message
    if cmd == "hoy":
        from datetime import datetime
        from zoneinfo import ZoneInfo
        now_mty = datetime.now(ZoneInfo("America/Monterrey"))
        await _show_day_posts(fake_update, now_mty.strftime("%d/%m/%Y"))

    elif cmd == "pendientes":
        from datetime import datetime, timezone
        from zoneinfo import ZoneInfo
        from sqlalchemy import case, select
        from ..database import AsyncSessionLocal
        from ..models import ScheduledPost

        mty_tz = ZoneInfo("America/Monterrey")
        async with AsyncSessionLocal() as db:
            result = await db.execute(
            select(ScheduledPost)
            .where(ScheduledPost.status.in_(["scheduled", "approval_pending", "radar_slot"]))
            .order_by(
                case((ScheduledPost.status == "approval_pending", 0), else_=1),
                ScheduledPost.scheduled_at,
            )
            )
            posts = result.scalars().all()

        if not posts:
            await fake_update.reply_text("📭 No hay posts programados pendientes.")
            return

        await fake_update.reply_text(
            f"📋 *{len(posts)} post{'s' if len(posts) > 1 else ''} en cola:*",
            parse_mode="Markdown",
        )
        for p in posts[:30]:
            sched_mty = None
            if p.scheduled_at:
                sched = datetime.fromisoformat(str(p.scheduled_at)).replace(tzinfo=timezone.utc)
                sched_mty = sched.astimezone(mty_tz)
            preview = (p.linkedin_text or "")[:100].replace("\n", " ")
            when = sched_mty.strftime("%d/%m %H:%M") if sched_mty else "sin slot"
            state = "Aprobación abierta" if p.status == "approval_pending" else "Programado"
            await fake_update.reply_text(
                f"*{state} · #{p.id}*\nSlot original: {when}\n{preview}…",
                reply_markup=_post_keyboard(p.id, p.status),
                parse_mode="Markdown",
            )

    elif cmd == "status":
        from datetime import datetime, timezone
        from zoneinfo import ZoneInfo
        from sqlalchemy import select, func
        from ..database import AsyncSessionLocal
        from ..models import ScheduledPost
        from .linkedin_auth import LinkedInAuthError, ensure_valid_linkedin_token, load_linkedin_token
        from .scheduler_service import scheduler

        mty_tz = ZoneInfo("America/Monterrey")
        now_mty = datetime.now(mty_tz)
        today_start = now_mty.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc).replace(tzinfo=None)
        today_end = now_mty.replace(hour=23, minute=59, second=59).astimezone(timezone.utc).replace(tzinfo=None)

        async with AsyncSessionLocal() as db:
            token = await load_linkedin_token(db)
            li_note = ""
            if not token:
                li_status = "❌ Desconectado"
            else:
                try:
                    await ensure_valid_linkedin_token(db)
                    li_status = "✅ Conectado"
                except LinkedInAuthError as exc:
                    li_status = "⚠️ Reconexión requerida"
                    li_note = f"\n🔐 Acción: {exc}\n"

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
            f"{li_note}"
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
            "1. Envía un URL de post de X (`/status/` o `/article/`) *o cualquier artículo web*\n"
            "2. El bot extrae el contenido y genera el post de LinkedIn con IA\n"
            "3. Si no hay imagen real, se publica sin adjunto y con mejor frase ancla\n"
            "4. Elige: *Programar* / *Publicar ahora* / *Regenerar* / *Descartar*\n\n"
            "*Comandos:*\n"
            "/hoy — posts de hoy con opciones de edición\n"
            "/dia [DD/MM] — posts de cualquier día\n"
            "/pendientes — todos los posts en cola\n"
            "/articulos — busca artículos largos de X entre tus likes pendientes\n"
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
    """Regenera el post con IA usando la misma fuente (tweet o URL genérica)."""
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

    await query.edit_message_reply_markup(None)
    await query.edit_message_text("🤖 Regenerando post con IA…")

    async with AsyncSessionLocal() as db:
        cfg_result = await db.execute(select(AppSettings).where(AppSettings.id == 1))
        cfg = cfg_result.scalar_one_or_none()
        custom_prompt = cfg.custom_prompt if cfg else None

    source_url = post_data["tweet_url"]
    is_tweet = is_x_post_url(source_url)

    try:
        if is_tweet:
            from ..services.x_scraper import scrape_tweet
            from ..services.post_generator import generate_linkedin_post
            tweet = await scrape_tweet(source_url)
            linkedin_text = await generate_linkedin_post(
                tweet=tweet,
                language=settings.post_language or "es",
                custom_prompt=custom_prompt,
            )
        else:
            from ..services.url_scraper import scrape_url
            from ..services.post_generator import generate_linkedin_post_from_url_content
            url_content = await scrape_url(source_url)
            linkedin_text = await generate_linkedin_post_from_url_content(
                url_content=url_content,
                language=settings.post_language or "es",
                custom_prompt=custom_prompt,
            )
    except Exception as e:
        await query.edit_message_text(f"❌ Error regenerando:\n`{e}`", parse_mode="Markdown")
        return

    if linkedin_text.startswith("[NO_PUBLICAR]"):
        reason = linkedin_text.split(":", 1)[-1].strip()
        await query.edit_message_text(
            f"⚠️ Este contenido no es publicable:\n_{reason}_",
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

    icons = {"video": "🎥", "document": "📄", "paper_image": "📑", "image": "🖼️", "generate": "📝", "none": "📝"}
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

    try:
        await query.edit_message_reply_markup(None)
    except Exception as exc:
        logger.warning("No pude quitar teclado radar #%s antes de aprobar: %s", post_id, exc)

    async with AsyncSessionLocal() as db:
        run_at = await get_next_auto_slot(db)
        media_type = "none" if post_data["media_type"] == "generate" else post_data["media_type"]
        post = ScheduledPost(
            tweet_url=post_data["tweet_url"],
            tweet_text=post_data["tweet_text"],
            tweet_author=post_data["tweet_author"],
            linkedin_text=post_data["linkedin_text"],
            image_urls=post_data["image_urls"],
            status="scheduled",
            scheduled_at=run_at,
            use_first_image=post_data["use_first_image"],
            media_type=media_type,
            pdf_url=post_data.get("pdf_url"),
            document_title=post_data.get("document_title", "Documento"),
            manual_edited_at=datetime.utcnow() if post_data.get("manual_edited") else None,
            manual_edited_via=post_data.get("manual_edited_via") if post_data.get("manual_edited") else None,
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
    from ..models import ScheduledPost
    from ..services.linkedin_auth import LinkedInAuthError, get_linkedin_client_from_db
    from ..services.post_generator import (
        download_pdf,
        download_tweet_video,
        render_pdf_first_page_image,
    )

    await query.edit_message_reply_markup(None)
    status_msg = await query.message.reply_text("⏳ Publicando en LinkedIn…")

    async with AsyncSessionLocal() as db:
        try:
            li_client = await get_linkedin_client_from_db(db)
        except LinkedInAuthError as exc:
            await status_msg.edit_text(
                f"❌ {exc}"
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
        elif media_type == "paper_image" and post_data.get("pdf_url"):
            generated_image_bytes = await render_pdf_first_page_image(post_data["pdf_url"])
            if not generated_image_bytes:
                logger.warning("No se pudo renderizar PDF como imagen, usando documento")
                media_type = "document"
                document_bytes = await download_pdf(post_data["pdf_url"])
        elif media_type == "generate":
            media_type = "none"

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


async def _do_approve_radar(query, post_id: int):
    from datetime import timedelta, timezone
    from zoneinfo import ZoneInfo

    from sqlalchemy import select

    from ..database import AsyncSessionLocal
    from ..models import ScheduledPost
    from ..services.scheduler_service import schedule_post

    await query.edit_message_reply_markup(None)

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(ScheduledPost).where(ScheduledPost.id == post_id))
        post = result.scalar_one_or_none()
        if not post or post.status != "approval_pending":
            await query.message.reply_text("⚠️ Este radar ya no está pendiente de aprobación.")
            return

        approved_at = datetime.utcnow()
        publish_delay = max(int(settings.editorial_radar_publish_delay_minutes or 30), 1)
        run_at = approved_at + timedelta(minutes=publish_delay)
        post.scheduled_at = run_at

        if post.media_type == "generate":
            post.media_type = "none"
            post.generated_image_path = None
        post.status = "scheduled"
        post.error_message = None
        post.manual_edited_at = approved_at
        post.manual_edited_via = post.manual_edited_via or "telegram_approval"
        await db.commit()

    schedule_post(post_id, run_at)
    mty_tz = ZoneInfo("America/Mexico_City")
    run_at_mty = run_at.replace(tzinfo=timezone.utc).astimezone(mty_tz)
    await query.message.reply_text(
        f"✅ Post #{post_id} aprobado y programado para las "
        f"*{run_at_mty.strftime('%H:%M')}* (CDMX), "
        f"{settings.editorial_radar_publish_delay_minutes or 30} minutos después de aprobarlo.",
        parse_mode="Markdown",
    )


async def _do_regenerate_radar(query, post_id: int):
    from datetime import timezone
    from zoneinfo import ZoneInfo

    await query.edit_message_reply_markup(None)
    status_msg = await query.message.reply_text("📡 Buscando otra fuente para este slot…")

    try:
        from .editorial_radar import prepare_radar_post

        await prepare_radar_post(post_id, force=True)
    except Exception as exc:
        await status_msg.edit_text(f"❌ El radar no pudo preparar otra opción:\n`{exc}`", parse_mode="Markdown")
        return

    from sqlalchemy import select

    from ..database import AsyncSessionLocal
    from ..models import ScheduledPost

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(ScheduledPost).where(ScheduledPost.id == post_id))
        post = result.scalar_one_or_none()
        if not post:
            await status_msg.edit_text("⚠️ Ya no encontré ese post radar.")
            return
        scheduled_at_str = ""
        if post.scheduled_at:
            sched_mty = post.scheduled_at.replace(tzinfo=timezone.utc).astimezone(ZoneInfo("America/Mexico_City"))
            scheduled_at_str = sched_mty.strftime("%H:%M")

    try:
        await status_msg.delete()
    except Exception:
        pass
    await notify_radar_approval(
        post_id=post.id,
        linkedin_text=post.linkedin_text or "",
        scheduled_at_str=scheduled_at_str,
        source_url=post.tweet_url or "",
        source_label=post.tweet_author or "",
        media_type=post.media_type or "none",
        radar_reason=post.error_message or "",
    )


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
        if not post or post.status not in {"scheduled", "approval_pending", "radar_slot", "failed"}:
            await query.edit_message_reply_markup(None)
            await query.message.reply_text("⚠️ Este post ya no se puede cancelar desde Telegram.")
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
    post_data["manual_edited"] = True
    post_data["manual_edited_via"] = "telegram_preview"
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
        if not post or post.status not in {"scheduled", "approval_pending"}:
            await query.edit_message_reply_markup(None)
            await query.message.reply_text("⚠️ Este post ya no está disponible para editar.")
            return
        full_text = post.linkedin_text or ""
        status = post.status

    user_id = query.from_user.id
    if status == "approval_pending":
        _awaiting_radar_revision[user_id] = post_id
        await query.message.reply_text(
            f"Cambios para el post #{post_id}\n\n"
            "Escribe qué quieres ajustar. Por ejemplo: haz el inicio más directo, "
            "reduce la extensión y elimina la pregunta final.\n\n"
            "También puedes responder directamente a cualquier tarjeta de aprobación "
            "para que el cambio se aplique a esa publicación."
        )
        return

    _awaiting_edit[user_id] = post_id

    await query.edit_message_reply_markup(None)
    await query.message.reply_text(
        f"✏️ *Modo edición — Post #{post_id}*\n\n"
        f"Texto actual:\n\n`{full_text}`\n\n"
        f"Envía el nuevo texto en tu próximo mensaje.\n"
        f"_(Envía cualquier URL de tweet para cancelar y empezar de nuevo)_",
        parse_mode="Markdown",
    )


# ── Respuestas a comentarios de LinkedIn ───────────────────────────────────

async def _do_edit_comment_reply(query, comment_id: int):
    from sqlalchemy import select

    from ..database import AsyncSessionLocal
    from ..models import LinkedInComment

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(LinkedInComment).where(LinkedInComment.id == comment_id))
        comment = result.scalar_one_or_none()
        if not comment:
            await query.edit_message_reply_markup(None)
            await query.message.reply_text("⚠️ Ya no encontré ese comentario en la base local.")
            return

    _awaiting_comment_edit[query.from_user.id] = comment_id
    await query.edit_message_reply_markup(None)
    await query.message.reply_text(
        "Modo edición - Respuesta a comentario\n\n"
        f"Texto actual:\n\n{comment.suggested_reply or ''}\n\n"
        "Envía tu nueva respuesta en el próximo mensaje.",
    )


async def _handle_comment_edit_text(update: Update, new_text: str):
    from ..services.linkedin_comments import update_comment_suggested_reply

    user_id = update.effective_user.id
    comment_id = _awaiting_comment_edit.pop(user_id)
    cleaned = new_text.strip()
    if not cleaned:
        await update.message.reply_text("⚠️ La respuesta está vacía. Edición cancelada.")
        return

    comment = await update_comment_suggested_reply(comment_id, cleaned)
    if not comment:
        await update.message.reply_text("⚠️ Ya no encontré ese comentario en la base local.")
        return

    await update.message.reply_text(
        "Respuesta actualizada\n\n"
        f"Comentario de {comment.commenter_name}:\n"
        f"{comment.comment_text[:500]}\n\n"
        f"Sugerencia:\n{comment.suggested_reply}",
        reply_markup=_comment_reply_keyboard(comment.id),
    )


async def _do_publish_comment_reply(query, comment_id: int):
    from ..services.linkedin_comments import publish_comment_reply

    await query.edit_message_reply_markup(None)
    status_msg = await query.message.reply_text("⏳ Publicando respuesta en LinkedIn…")

    try:
        result = await publish_comment_reply(comment_id)
    except Exception as exc:
        await status_msg.edit_text(
            f"❌ No pude publicar la respuesta.\n{str(exc)[:500]}",
        )
        await query.message.reply_text(
            "Puedes volver a intentar, editar la respuesta o dejarla pendiente.",
            reply_markup=_comment_reply_keyboard(comment_id),
        )
        return

    if result.get("already_published"):
        await status_msg.edit_text(
            "✅ Esta respuesta ya estaba publicada en LinkedIn.\n\n"
            f"{result['reply_text']}",
        )
        return

    await status_msg.edit_text(
        "✅ Respuesta publicada en LinkedIn.\n\n"
        f"{result['reply_text']}",
    )


async def _do_dismiss_comment_reply(query, comment_id: int):
    from ..services.linkedin_comments import dismiss_comment_reply

    comment = await dismiss_comment_reply(comment_id)
    await query.edit_message_reply_markup(None)
    if not comment:
        await query.message.reply_text("⚠️ Ya no encontré ese comentario en la base local.")
        return
    await query.message.reply_text("⏭️ Respuesta omitida. El comentario queda atendido por ahora.")


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

        media_icons = {
            "video": "🎥 Video",
            "document": "📄 PDF",
            "paper_image": "📑 Primera página del paper",
            "image": "🖼️ Imagen",
            "generate": "📝 Sin multimedia",
            "none": "📝 Sin multimedia",
        }
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


async def notify_radar_approval(
    *,
    post_id: int,
    linkedin_text: str,
    scheduled_at_str: str,
    source_url: str,
    source_label: str = "",
    media_type: str = "none",
    radar_reason: str = "",
):
    """Pide aprobacion humana para un post elegido por el radar editorial."""
    if not _application or not settings.telegram_user_id:
        return

    media_labels = {
        "video": "Video de la fuente",
        "document": "PDF",
        "paper_image": "Primera página del paper",
        "image": "Imagen real de la fuente",
        "generate": "Sin adjunto",
        "none": "Sin adjunto",
    }
    media_line = media_labels.get(media_type or "none", "Sin adjunto")
    safe_post = html.escape(_truncate_text_naturally(linkedin_text or "", 2600))
    safe_source = html.escape(source_url or "")
    safe_label = html.escape(source_label or "Fuente elegida por radar")
    safe_reason = html.escape(_truncate_text_naturally(radar_reason or "", 500))
    source_link = (
        f'<a href="{html.escape(source_url, quote=True)}">{safe_label}</a>'
        if source_url.startswith("http")
        else safe_label
    )

    slot_line = (
        f"\n<i>Slot editorial original: {html.escape(scheduled_at_str)}</i>"
        if scheduled_at_str
        else ""
    )
    message = (
        f"<b>📡 Radar listo · Post #{post_id}</b>{slot_line}\n"
        "<b>La aprobación queda abierta sin vencimiento.</b>\n"
        "Cuando lo apruebes, se publicará 30 minutos después. "
        "Para pedir cambios, usa el botón o responde a este mensaje.\n\n"
        f"{safe_post}\n\n"
        f"<b>Fuente:</b> {source_link}\n"
        f"<b>Multimedia:</b> {html.escape(media_line)}"
    )
    if safe_reason:
        message += f"\n<b>Criterio:</b> {safe_reason}"

    try:
        await _application.bot.send_message(
            chat_id=settings.telegram_user_id,
            text=message,
            reply_markup=_radar_approval_keyboard(post_id),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    except Exception as e:
        logger.warning(f"Notificación Telegram (aprobación radar) falló: {e}")


async def notify_new_linkedin_comment(
    *,
    comment_id: int,
    post_id: int,
    commenter_name: str,
    comment_text: str,
    suggested_reply: str,
    post_url: str,
    post_preview: str,
) -> int | None:
    if not _application or not settings.telegram_user_id:
        return None

    safe_comment = _truncate_text_naturally(comment_text, 1600)
    safe_reply = _truncate_text_naturally(_sanitize_comment_reply_preview(suggested_reply), 900)
    message = (
        f"<b>💬 Nuevo comentario en tu post #{post_id}</b>\n\n"
        f"<b>De:</b> {html.escape(commenter_name)}\n"
        f"<b>Comentó:</b>\n{html.escape(safe_comment)}\n\n"
        f"<b>Sugerencia de respuesta:</b>\n{html.escape(safe_reply)}"
    )
    if post_url:
        message += f"\n\n<a href=\"{html.escape(post_url, quote=True)}\">Ver post</a>"
    elif post_preview:
        message += f"\n\n<i>Post:</i> {html.escape(post_preview[:180])}…"

    try:
        sent = await _application.bot.send_message(
            chat_id=settings.telegram_user_id,
            text=message,
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=_comment_reply_keyboard(comment_id),
        )
        return sent.message_id
    except Exception as e:
        logger.warning(f"Notificación Telegram (comentario LinkedIn) falló: {e}")
        return None


async def notify_linkedin_comment_gap(
    *,
    post_id: int,
    total_count: int,
    visible_count: int,
    unseen_count: int,
    post_url: str,
    post_preview: str,
):
    if not _application or not settings.telegram_user_id:
        return

    text = (
        f"<b>👀 Movimiento nuevo en comentarios del post #{post_id}</b>\n\n"
        f"LinkedIn marca <b>{total_count}</b> comentarios, pero el scraper visible solo pudo leer <b>{visible_count}</b>.\n"
        f"Quedan aproximadamente <b>{unseen_count}</b> por revisar manualmente.\n\n"
        f"<i>Esto suele pasar en hilos viejos o muy cargados.</i>"
    )
    if post_url:
        text += f"\n\n<a href=\"{html.escape(post_url, quote=True)}\">Ver post</a>"
    elif post_preview:
        text += f"\n\n<i>Post:</i> {html.escape(post_preview[:180])}…"

    try:
        await _application.bot.send_message(
            chat_id=settings.telegram_user_id,
            text=text,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    except Exception as e:
        logger.warning(f"Notificación Telegram (gap de comentarios) falló: {e}")


# ── Lifecycle ───────────────────────────────────────────────────────────────

async def start_bot():
    """Inicializa y arranca el bot. Llamar desde el lifespan de FastAPI."""
    global _application

    if _application is not None:
        logger.info("El bot de Telegram ya estaba inicializado; omitiendo arranque duplicado")
        return

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
    _application.add_handler(CommandHandler("dia", cmd_dia))
    _application.add_handler(CommandHandler("pendientes", cmd_pendientes))
    _application.add_handler(CommandHandler("status", cmd_status))
    _application.add_handler(CommandHandler("articulos", cmd_articulos))
    _application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )
    _application.add_handler(CallbackQueryHandler(handle_callback))
    _application.add_error_handler(_handle_telegram_error)

    await _application.initialize()
    await _application.bot.delete_webhook(drop_pending_updates=False)
    await _application.start()
    await _application.updater.start_polling(drop_pending_updates=False)

    logger.info(
        f"Bot de Telegram iniciado (usuario autorizado: {settings.telegram_user_id})"
    )


def is_bot_running() -> bool:
    if _application is None:
        return False

    try:
        app_running = bool(getattr(_application, "running", False))
        updater = getattr(_application, "updater", None)
        updater_running = bool(getattr(updater, "running", False)) if updater else False
        return app_running and updater_running
    except Exception:
        return False


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
