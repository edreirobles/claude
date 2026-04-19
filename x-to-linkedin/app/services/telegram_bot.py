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
# Modo reprogramar: user_id → post_id
_awaiting_reschedule: dict[int, int] = {}
# Modo consulta por día: users esperando escribir una fecha
_awaiting_dia: set[int] = set()
# Modo espera de ID de post para actualizar métricas
_awaiting_metric_id: set[int] = set()
# Modo espera de ID de post para generar imagen
_awaiting_imagen_id: set[int] = set()
# Modo edición del prompt personalizado de Claude
_awaiting_prompt: set[int] = set()

# Regex para detectar URLs de X / Twitter
_TWEET_RE = re.compile(
    r"https?://(?:www\.)?(?:x\.com|twitter\.com)/\S+/status/\d+",
    re.IGNORECASE,
)

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
            InlineKeyboardButton("📅 Hoy", callback_data="cmd:hoy"),
            InlineKeyboardButton("📋 Pendientes", callback_data="cmd:pendientes"),
            InlineKeyboardButton("📚 Historial", callback_data="cmd:historial"),
        ],
        [
            InlineKeyboardButton("📊 Estado", callback_data="cmd:status"),
            InlineKeyboardButton("📈 Analíticas", callback_data="cmd:analiticas"),
            InlineKeyboardButton("🔄 Métricas", callback_data="cmd:metricas"),
        ],
        [
            InlineKeyboardButton("🔍 Monitor X", callback_data="cmd:monitor"),
            InlineKeyboardButton("⚙️ Prompt IA", callback_data="cmd:prompt"),
            InlineKeyboardButton("📦 Exportar", callback_data="cmd:exportar"),
        ],
        [
            InlineKeyboardButton("📖 Ayuda completa", callback_data="cmd:help"),
        ],
    ])
    await update.message.reply_text(
        "👋 *X → LinkedIn Bot*\n\n"
        "Envíame un URL de tweet *o cualquier artículo/noticia web* y lo convierto en un post de LinkedIn.\n\n"
        "*¿Qué puedo hacer?*\n"
        "🔗 Generar posts desde tweets o artículos\n"
        "📅 Programar publicaciones (5 AM / 4 PM Monterrey)\n"
        "🚀 Publicar inmediatamente en LinkedIn\n"
        "📈 Ver analíticas y métricas de engagement\n"
        "🎨 Generar imágenes con IA para tus posts\n"
        "🔍 Monitorear likes de X y auto-publicar\n"
        "⚙️ Personalizar el prompt de generación\n"
        "📦 Exportar todo tu historial en CSV\n\n"
        "Usa los botones o escribe un comando. 👇",
        parse_mode="Markdown",
        reply_markup=keyboard,
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        await _deny(update)
        return
    await update.message.reply_text(
        "📖 *Referencia completa de comandos*\n\n"
        "*── Generar contenido ──*\n"
        "Envía cualquier URL (tweet o artículo) → genera post → elige acción\n\n"
        "*── Ver posts ──*\n"
        "/hoy — posts de hoy con botones de edición\n"
        "/dia `[DD/MM]` — posts de cualquier día\n"
        "/pendientes — todos los posts en cola\n"
        "/historial `[N]` — últimos N posts publicados (default 5, max 20)\n\n"
        "*── Publicar y programar ──*\n"
        "Al generar un post: botones *Programar* / *Publicar ahora*\n"
        "Los posts se programan en slots: *5 AM* y *4 PM* (Monterrey)\n"
        "En /hoy o /pendientes: botones editar, cambiar fecha, cancelar\n\n"
        "*── Imágenes ──*\n"
        "/imagen `<post_id>` — genera imagen IA para un post programado\n\n"
        "*── Métricas y analíticas ──*\n"
        "/analiticas — dashboard completo: KPIs, engagement, top posts\n"
        "/metricas `[post_id]` — actualiza métricas de un post o de todos\n\n"
        "*── Monitor de X/Twitter ──*\n"
        "/monitor — estado del monitor de likes + disparar chequeo\n"
        "/articulos — likes skipped que podrían ser artículos largos\n\n"
        "*── Configuración ──*\n"
        "/prompt — ver/editar el prompt personalizado de Claude\n"
        "/reordenar — reorganiza la cola sin huecos (5 AM / 4 PM)\n\n"
        "*── Datos ──*\n"
        "/exportar — descarga CSV con todo el historial + métricas\n\n"
        "*── Sistema ──*\n"
        "/status — estado general (LinkedIn, scheduler, cola)\n"
        "/start — menú principal",
        parse_mode="Markdown",
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


# ── Nuevos comandos ────────────────────────────────────────────────────────

async def cmd_analiticas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Dashboard de analíticas: KPIs, engagement, top posts."""
    if not _authorized(update):
        await _deny(update)
        return

    from sqlalchemy import select
    from ..database import AsyncSessionLocal
    from ..models import ScheduledPost

    wait_msg = await update.message.reply_text("📈 Calculando analíticas…")

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(ScheduledPost))
        posts = result.scalars().all()

    published = [p for p in posts if p.status == "published"]
    posts_with_metrics = [p for p in published if p.li_likes is not None or p.li_impressions is not None]

    total_published = len(published)
    total_likes = sum(p.li_likes or 0 for p in published)
    total_comments = sum(p.li_comments or 0 for p in published)
    total_impressions = sum(p.li_impressions or 0 for p in published)
    total_clicks = sum(getattr(p, "li_clicks", None) or 0 for p in published)
    total_shares = sum(getattr(p, "li_shares", None) or 0 for p in published)

    avg_likes = round(total_likes / len(posts_with_metrics), 1) if posts_with_metrics else 0
    engagement_numerator = total_likes + total_comments + total_clicks
    engagement_rate = round(engagement_numerator / total_impressions * 100, 2) if total_impressions > 0 else 0

    media_icons = {"video": "🎥", "document": "📄", "image": "🖼️", "generate": "🎨"}
    media_counts: dict = {}
    for p in published:
        k = p.media_type or "auto"
        media_counts[k] = media_counts.get(k, 0) + 1

    text = (
        f"📈 *Analíticas de LinkedIn*\n\n"
        f"📊 *KPIs Generales:*\n"
        f"  📝 Posts publicados: *{total_published}*\n"
        f"  📊 Con métricas: *{len(posts_with_metrics)}*\n"
        f"  ❤️ Likes totales: *{total_likes:,}*\n"
        f"  💬 Comentarios: *{total_comments:,}*\n"
        f"  👁️ Impresiones: *{total_impressions:,}*\n"
        f"  🖱️ Clicks: *{total_clicks:,}*\n"
        f"  🔄 Compartidos: *{total_shares:,}*\n"
        f"  📈 Engagement rate: *{engagement_rate}%*\n"
        f"  💝 Promedio likes/post: *{avg_likes}*\n\n"
    )

    if media_counts:
        text += "🗂️ *Por tipo de media:*\n"
        for k, v in sorted(media_counts.items(), key=lambda x: -x[1]):
            icon = media_icons.get(k, "📝")
            text += f"  {icon} {k}: {v}\n"
        text += "\n"

    top_posts = sorted(
        [p for p in published if p.li_likes is not None],
        key=lambda p: (p.li_likes or 0) + (p.li_comments or 0) + (getattr(p, "li_clicks", None) or 0),
        reverse=True,
    )[:5]

    if top_posts:
        text += "🏆 *Top 5 por engagement:*\n\n"
        for i, p in enumerate(top_posts, 1):
            engagement = (p.li_likes or 0) + (p.li_comments or 0) + (getattr(p, "li_clicks", None) or 0)
            preview = (p.linkedin_text or "")[:60].replace("\n", " ")
            text += (
                f"*{i}.* {preview}…\n"
                f"   ❤️{p.li_likes or 0}  💬{p.li_comments or 0}  "
                f"👁️{p.li_impressions or 0}  🏅{engagement}\n\n"
            )

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("🔄 Actualizar todas las métricas", callback_data="metrics_all:"),
    ]])

    try:
        await wait_msg.edit_text(text, parse_mode="Markdown", reply_markup=keyboard)
    except Exception:
        await wait_msg.edit_text(text.replace("*", "").replace("_", ""), reply_markup=keyboard)


async def cmd_metricas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Actualiza métricas de un post concreto o de todos."""
    if not _authorized(update):
        await _deny(update)
        return

    args = context.args
    if args and args[0].isdigit():
        await _do_refresh_single_metrics(update.message, int(args[0]))
        return

    user_id = update.effective_user.id
    _awaiting_metric_id.add(user_id)

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("🔄 Actualizar TODOS los posts", callback_data="metrics_all:"),
    ]])
    await update.message.reply_text(
        "📊 *Actualizar métricas*\n\n"
        "Envía el *ID del post* para actualizar sus métricas,\n"
        "o usa el botón para actualizar todos:\n\n"
        "_Ejemplo: `42`_",
        parse_mode="Markdown",
        reply_markup=keyboard,
    )


async def cmd_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Muestra y permite editar el prompt personalizado de Claude."""
    if not _authorized(update):
        await _deny(update)
        return

    from sqlalchemy import select
    from ..database import AsyncSessionLocal
    from ..models import AppSettings
    from ..services.post_generator import SYSTEM_PROMPT_ES

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(AppSettings).where(AppSettings.id == 1))
        cfg = result.scalar_one_or_none()
        custom_prompt = cfg.custom_prompt if cfg else None

    if custom_prompt:
        prompt_preview = custom_prompt[:500] + ("…" if len(custom_prompt) > 500 else "")
        status_text = (
            f"✅ *Prompt personalizado activo*\n\n"
            f"`{prompt_preview}`\n\n"
            f"_{len(custom_prompt)} caracteres_"
        )
    else:
        default_preview = SYSTEM_PROMPT_ES[:400] + "…"
        status_text = (
            f"📝 *Usando prompt por defecto*\n\n"
            f"`{default_preview}`"
        )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Editar prompt", callback_data="prompt_edit:")],
        [InlineKeyboardButton("🔄 Restaurar por defecto", callback_data="prompt_reset:")],
    ])

    try:
        await update.message.reply_text(status_text, parse_mode="Markdown", reply_markup=keyboard)
    except Exception:
        await update.message.reply_text(
            status_text.replace("`", "").replace("*", "").replace("_", ""),
            reply_markup=keyboard,
        )


async def cmd_imagen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Genera una imagen con IA para un post programado."""
    if not _authorized(update):
        await _deny(update)
        return

    args = context.args
    if args and args[0].isdigit():
        await _do_gen_image(update.message, int(args[0]))
        return

    user_id = update.effective_user.id
    _awaiting_imagen_id.add(user_id)
    await update.message.reply_text(
        "🎨 *Generar imagen con IA*\n\n"
        "Envía el *ID del post* programado para el que quieres generar una imagen:\n"
        "_Ejemplo: `42`_\n\n"
        "Solo funciona con posts en estado *programado*.",
        parse_mode="Markdown",
    )


async def cmd_reordenar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reorganiza la cola de posts en slots 5 AM / 4 PM sin huecos."""
    if not _authorized(update):
        await _deny(update)
        return

    from sqlalchemy import select, func
    from ..database import AsyncSessionLocal
    from ..models import ScheduledPost

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(func.count()).select_from(ScheduledPost).where(ScheduledPost.status == "scheduled")
        )
        count = result.scalar()

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Confirmar", callback_data="reordenar_confirm:"),
            InlineKeyboardButton("❌ Cancelar", callback_data="reordenar_cancel:"),
        ]
    ])
    await update.message.reply_text(
        f"📅 *Reordenar cola de posts*\n\n"
        f"Hay *{count}* posts programados en cola.\n\n"
        f"Esto los reorganizará en slots consecutivos de *5 AM* y *4 PM* (Monterrey) "
        f"sin huecos entre ellos.\n\n"
        f"¿Confirmar?",
        parse_mode="Markdown",
        reply_markup=keyboard,
    )


async def cmd_monitor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Muestra el estado del monitor de X/Twitter y permite disparar una verificación."""
    if not _authorized(update):
        await _deny(update)
        return

    from sqlalchemy import select, func
    from ..database import AsyncSessionLocal
    from ..models import XLikedTweet

    s = settings
    configured = bool(s.x_auth_token)

    async with AsyncSessionLocal() as db:
        total_r = await db.execute(select(func.count()).select_from(XLikedTweet))
        total = total_r.scalar()

        proc_r = await db.execute(
            select(func.count()).select_from(XLikedTweet).where(XLikedTweet.status == "processed")
        )
        processed = proc_r.scalar()

        skip_r = await db.execute(
            select(func.count()).select_from(XLikedTweet).where(XLikedTweet.status == "skipped")
        )
        skipped = skip_r.scalar()

        fail_r = await db.execute(
            select(func.count()).select_from(XLikedTweet).where(XLikedTweet.status == "failed")
        )
        failed = fail_r.scalar()

        rej_r = await db.execute(
            select(func.count()).select_from(XLikedTweet).where(XLikedTweet.status == "rejected")
        )
        rejected = rej_r.scalar()

        from sqlalchemy import desc
        recent_r = await db.execute(
            select(XLikedTweet)
            .where(XLikedTweet.status != "skipped")
            .order_by(desc(XLikedTweet.id))
            .limit(5)
        )
        recent = recent_r.scalars().all()

    config_status = "✅ Configurado" if configured else "❌ No configurado (X_AUTH_TOKEN)"
    interval = getattr(s, "x_check_interval_minutes", 15) or 15
    username = getattr(s, "x_username", "") or "—"

    text = (
        f"🔍 *Monitor de X/Twitter*\n\n"
        f"⚙️ Estado: {config_status}\n"
        f"👤 Usuario: @{username}\n"
        f"⏱️ Intervalo: cada *{interval}* minutos\n\n"
        f"📊 *Estadísticas de likes:*\n"
        f"  📥 Total detectados: *{total}*\n"
        f"  ✅ Procesados: *{processed}*\n"
        f"  ❌ Rechazados: *{rejected}*\n"
        f"  ⏭️ Omitidos (semilla): *{skipped}*\n"
        f"  💥 Fallidos: *{failed}*\n"
    )

    if recent:
        status_icons = {"processed": "✅", "skipped": "⏭️", "failed": "💥", "rejected": "🚫", "processing": "⏳"}
        text += "\n*Últimos 5 procesados:*\n"
        for t in recent:
            icon = status_icons.get(t.status, "❓")
            author = f"@{t.tweet_author}" if t.tweet_author else "desconocido"
            text += f"  {icon} {author}\n"

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("▶️ Verificar ahora", callback_data="monitor_check:"),
    ]])

    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=keyboard)


async def cmd_historial(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Muestra los últimos N posts publicados con métricas."""
    if not _authorized(update):
        await _deny(update)
        return

    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo
    from sqlalchemy import select, desc
    from ..database import AsyncSessionLocal
    from ..models import ScheduledPost

    args = context.args
    n = 5
    if args and args[0].isdigit():
        n = min(int(args[0]), 20)

    mty_tz = ZoneInfo("America/Monterrey")

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ScheduledPost)
            .where(ScheduledPost.status == "published")
            .order_by(desc(ScheduledPost.published_at))
            .limit(n)
        )
        posts = result.scalars().all()

    if not posts:
        await update.message.reply_text("📭 No hay posts publicados aún.")
        return

    await update.message.reply_text(
        f"📚 *Últimos {len(posts)} posts publicados:*",
        parse_mode="Markdown",
    )

    for p in posts:
        pub_str = ""
        if p.published_at:
            pub_dt = datetime.fromisoformat(str(p.published_at)).replace(tzinfo=timezone.utc)
            pub_mty = pub_dt.astimezone(mty_tz)
            pub_str = pub_mty.strftime("%d/%m/%Y %H:%M")

        preview = (p.linkedin_text or "")[:100].replace("\n", " ")
        metrics_line = ""
        if p.li_likes is not None:
            metrics_line = (
                f"\n   ❤️ {p.li_likes}  💬 {p.li_comments or 0}  "
                f"👁️ {p.li_impressions or 0}  🖱️ {getattr(p, 'li_clicks', None) or 0}"
            )

        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton(f"📊 Métricas #{p.id}", callback_data=f"metrics_post:{p.id}"),
            InlineKeyboardButton("👁 Ver", callback_data=f"view_post:{p.id}"),
        ]])

        await update.message.reply_text(
            f"✅ *{pub_str}* — Post #{p.id}\n{preview}…{metrics_line}",
            reply_markup=keyboard,
            parse_mode="Markdown",
        )


async def cmd_exportar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Genera y envía el historial completo como archivo CSV."""
    if not _authorized(update):
        await _deny(update)
        return

    import csv
    import io
    from datetime import datetime
    from sqlalchemy import select, desc
    from ..database import AsyncSessionLocal
    from ..models import ScheduledPost

    wait_msg = await update.message.reply_text("📦 Generando exportación CSV…")

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ScheduledPost).order_by(desc(ScheduledPost.created_at))
        )
        posts = result.scalars().all()

    if not posts:
        await wait_msg.edit_text("📭 No hay posts para exportar.")
        return

    fields = [
        "id", "created_at", "tweet_url", "tweet_author", "tweet_text",
        "linkedin_text", "status", "source", "scheduled_at", "published_at",
        "linkedin_post_id", "media_type", "use_first_image", "pdf_url",
        "document_title", "error_message", "li_likes", "li_comments",
        "li_impressions", "li_clicks", "li_shares",
    ]

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for p in posts:
        writer.writerow({
            "id": p.id,
            "created_at": p.created_at,
            "tweet_url": p.tweet_url or "",
            "tweet_author": p.tweet_author or "",
            "tweet_text": (p.tweet_text or "")[:200],
            "linkedin_text": (p.linkedin_text or "")[:500],
            "status": p.status,
            "source": getattr(p, "source", "manual"),
            "scheduled_at": p.scheduled_at or "",
            "published_at": p.published_at or "",
            "linkedin_post_id": p.linkedin_post_id or "",
            "media_type": p.media_type or "",
            "use_first_image": p.use_first_image,
            "pdf_url": p.pdf_url or "",
            "document_title": p.document_title or "",
            "error_message": p.error_message or "",
            "li_likes": p.li_likes if p.li_likes is not None else "",
            "li_comments": p.li_comments if p.li_comments is not None else "",
            "li_impressions": p.li_impressions if p.li_impressions is not None else "",
            "li_clicks": getattr(p, "li_clicks", None) or "",
            "li_shares": getattr(p, "li_shares", None) or "",
        })

    output.seek(0)
    csv_bytes = output.getvalue().encode("utf-8-sig")  # BOM para Excel
    csv_file = io.BytesIO(csv_bytes)
    filename = f"publicaciones_{datetime.utcnow().strftime('%Y%m%d')}.csv"

    await wait_msg.delete()
    await update.message.reply_document(
        document=csv_file,
        filename=filename,
        caption=f"📊 *{len(posts)} posts exportados*\n_{filename}_",
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

    # Modo reprogramar post
    if user_id in _awaiting_reschedule:
        await _handle_reschedule_text(update, text)
        return

    # Modo consulta por día
    if user_id in _awaiting_dia:
        _awaiting_dia.discard(user_id)
        await _show_day_posts(update.message, text.strip())
        return

    # Modo espera de ID de post para métricas
    if user_id in _awaiting_metric_id:
        _awaiting_metric_id.discard(user_id)
        stripped = text.strip()
        if stripped.isdigit():
            await _do_refresh_single_metrics(update.message, int(stripped))
        else:
            await update.message.reply_text("⚠️ Envía solo el número de ID del post. Ejemplo: `42`", parse_mode="Markdown")
        return

    # Modo espera de ID de post para generar imagen
    if user_id in _awaiting_imagen_id:
        _awaiting_imagen_id.discard(user_id)
        stripped = text.strip()
        if stripped.isdigit():
            await _do_gen_image(update.message, int(stripped))
        else:
            await update.message.reply_text("⚠️ Envía solo el número de ID del post. Ejemplo: `42`", parse_mode="Markdown")
        return

    # Modo edición del prompt de Claude
    if user_id in _awaiting_prompt:
        await _handle_prompt_text(update, text)
        return

    tweet_match = _TWEET_RE.search(text)
    if tweet_match:
        await _process_tweet_url(update, context, tweet_match.group(0))
        return

    url_match = _URL_RE.search(text)
    if url_match:
        await _process_generic_url(update, context, url_match.group(0))
        return

    await update.message.reply_text(
        "Envíame un URL de tweet o cualquier artículo/noticia web para generar un post de LinkedIn.\n\n"
        "Ejemplos:\n"
        "• https://x.com/usuario/status/12345\n"
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


async def _handle_prompt_text(update: Update, new_text: str):
    """Guarda el nuevo prompt personalizado de Claude."""
    from sqlalchemy import select
    from ..database import AsyncSessionLocal
    from ..models import AppSettings

    user_id = update.effective_user.id
    _awaiting_prompt.discard(user_id)

    if not new_text.strip():
        await update.message.reply_text("⚠️ El prompt está vacío. Cambio cancelado.")
        return

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(AppSettings).where(AppSettings.id == 1))
        cfg = result.scalar_one_or_none()
        if cfg:
            cfg.custom_prompt = new_text.strip()
        else:
            cfg = AppSettings(id=1, custom_prompt=new_text.strip())
            db.add(cfg)
        await db.commit()

    await update.message.reply_text(
        f"✅ *Prompt personalizado guardado* ({len(new_text.strip())} chars)\n\n"
        f"Se usará en las próximas generaciones de posts.",
        parse_mode="Markdown",
    )


async def _do_refresh_single_metrics(msg, post_id: int):
    """Actualiza métricas de un post publicado específico."""
    from datetime import datetime
    from sqlalchemy import select
    from ..database import AsyncSessionLocal
    from ..models import ScheduledPost, LinkedInToken
    from ..services.linkedin_client import LinkedInClient

    wait = await msg.reply_text(f"📊 Actualizando métricas del post #{post_id}…")

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(ScheduledPost).where(ScheduledPost.id == post_id))
        post = result.scalar_one_or_none()
        if not post:
            await wait.edit_text(f"⚠️ Post #{post_id} no encontrado.")
            return
        if post.status != "published":
            await wait.edit_text(
                f"⚠️ El post #{post_id} no está publicado (estado: *{post.status}*).",
                parse_mode="Markdown",
            )
            return
        if not post.linkedin_post_id:
            await wait.edit_text(f"⚠️ El post #{post_id} no tiene ID de LinkedIn guardado.")
            return

        token_result = await db.execute(select(LinkedInToken).limit(1))
        token = token_result.scalar_one_or_none()
        if not token:
            await wait.edit_text("❌ LinkedIn no está conectado.")
            return

        li_client = LinkedInClient(token.access_token, token.person_urn)
        try:
            metrics = await li_client.get_post_metrics(post.linkedin_post_id)
        except Exception as e:
            await wait.edit_text(f"❌ Error obteniendo métricas:\n`{e}`", parse_mode="Markdown")
            return

        if metrics.get("likes") is not None:
            post.li_likes = metrics["likes"]
        if metrics.get("comments") is not None:
            post.li_comments = metrics["comments"]
        if metrics.get("impressions") is not None:
            post.li_impressions = metrics["impressions"]
        if metrics.get("clicks") is not None:
            post.li_clicks = metrics["clicks"]
        if metrics.get("shares") is not None:
            post.li_shares = metrics["shares"]
        post.metrics_updated_at = datetime.utcnow()
        await db.commit()
        await db.refresh(post)

    await wait.edit_text(
        f"✅ *Métricas actualizadas — Post #{post_id}*\n\n"
        f"❤️ Likes: *{post.li_likes or 0}*\n"
        f"💬 Comentarios: *{post.li_comments or 0}*\n"
        f"👁️ Impresiones: *{post.li_impressions or 0}*\n"
        f"🖱️ Clicks: *{getattr(post, 'li_clicks', None) or 0}*\n"
        f"🔄 Compartidos: *{getattr(post, 'li_shares', None) or 0}*",
        parse_mode="Markdown",
    )


async def _do_refresh_all_metrics(msg):
    """Actualiza métricas de todos los posts publicados con ID de LinkedIn."""
    from datetime import datetime
    from sqlalchemy import select
    from ..database import AsyncSessionLocal
    from ..models import ScheduledPost, LinkedInToken
    from ..services.linkedin_client import LinkedInClient

    wait = await msg.reply_text("🔄 Actualizando métricas de todos los posts publicados…")

    async with AsyncSessionLocal() as db:
        token_result = await db.execute(select(LinkedInToken).limit(1))
        token = token_result.scalar_one_or_none()
        if not token:
            await wait.edit_text("❌ LinkedIn no está conectado.")
            return

        result = await db.execute(
            select(ScheduledPost)
            .where(ScheduledPost.status == "published")
            .where(ScheduledPost.linkedin_post_id.isnot(None))
            .where(ScheduledPost.linkedin_post_id != "")
        )
        posts = result.scalars().all()

        if not posts:
            await wait.edit_text("📭 No hay posts publicados con ID de LinkedIn.")
            return

        li_client = LinkedInClient(token.access_token, token.person_urn)
        refreshed = 0
        failed = 0
        for post in posts:
            try:
                metrics = await li_client.get_post_metrics(post.linkedin_post_id)
                if metrics.get("likes") is not None:
                    post.li_likes = metrics["likes"]
                if metrics.get("comments") is not None:
                    post.li_comments = metrics["comments"]
                if metrics.get("impressions") is not None:
                    post.li_impressions = metrics["impressions"]
                if metrics.get("clicks") is not None:
                    post.li_clicks = metrics["clicks"]
                if metrics.get("shares") is not None:
                    post.li_shares = metrics["shares"]
                post.metrics_updated_at = datetime.utcnow()
                refreshed += 1
            except Exception as e:
                logger.warning(f"[Bot RefreshAll] Post {post.id}: {e}")
                failed += 1

        await db.commit()

    await wait.edit_text(
        f"✅ *Métricas actualizadas*\n\n"
        f"📊 Actualizados: *{refreshed}*\n"
        f"❌ Fallidos: *{failed}*\n"
        f"📋 Total: *{len(posts)}*",
        parse_mode="Markdown",
    )


async def _do_gen_image(msg, post_id: int):
    """Genera una imagen IA para un post programado y la guarda."""
    import io
    import os
    from sqlalchemy import select
    from ..database import AsyncSessionLocal
    from ..models import ScheduledPost
    from ..services.post_generator import generate_nano_banana_image

    wait = await msg.reply_text(
        f"🎨 Generando imagen para post #{post_id}…\n_(puede tomar 15-30 segundos)_",
        parse_mode="Markdown",
    )

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(ScheduledPost).where(ScheduledPost.id == post_id))
        post = result.scalar_one_or_none()

        if not post:
            await wait.edit_text(f"⚠️ Post #{post_id} no encontrado.")
            return
        if post.status not in ("scheduled", "pending"):
            await wait.edit_text(
                f"⚠️ Solo se puede generar imagen para posts *programados* (estado actual: {post.status}).",
                parse_mode="Markdown",
            )
            return

        linkedin_text = post.linkedin_text or ""

    try:
        image_bytes = await generate_nano_banana_image(linkedin_text)
    except Exception as e:
        await wait.edit_text(f"❌ Error generando imagen:\n`{e}`", parse_mode="Markdown")
        return

    if not image_bytes:
        await wait.edit_text("❌ No se pudo generar la imagen. Todos los servicios fallaron.")
        return

    images_dir = os.path.join("static", "generated_images")
    os.makedirs(images_dir, exist_ok=True)
    image_filename = f"{post_id}.jpg"
    image_path = os.path.join(images_dir, image_filename)
    with open(image_path, "wb") as f:
        f.write(image_bytes)

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(ScheduledPost).where(ScheduledPost.id == post_id))
        post = result.scalar_one_or_none()
        if post:
            post.generated_image_path = f"/static/generated_images/{image_filename}"
            post.media_type = "generate"
            await db.commit()

    await wait.delete()
    await msg.reply_photo(
        photo=io.BytesIO(image_bytes),
        caption=f"✅ *Imagen generada para Post #{post_id}*\nSe usará al publicar en LinkedIn.",
        parse_mode="Markdown",
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
    return InlineKeyboardMarkup(rows)


async def _send_posts_list(msg, posts, mty_tz):
    """Envía cada post como mensaje individual con botones de acción."""
    from datetime import datetime, timezone

    icons = {"scheduled": "⏰", "published": "✅", "failed": "❌"}
    for p in posts:
        sched = datetime.fromisoformat(str(p.scheduled_at)).replace(tzinfo=timezone.utc)
        sched_mty = sched.astimezone(mty_tz)
        icon = icons.get(p.status, "❓")
        preview = (p.linkedin_text or "")[:120].replace("\n", " ")
        keyboard = _post_keyboard(p.id, p.status) if p.status in ("scheduled", "published", "failed") else None
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
            .where(ScheduledPost.status.in_(["scheduled", "published", "failed"]))
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

    header = (
        f"📄 *Post #{post_id}* — {sched_mty.strftime('%d/%m %H:%M')} — "
        f"{'⏰ programado' if post.status == 'scheduled' else '✅ publicado' if post.status == 'published' else post.status}\n"
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
    from ..services.x_scraper import scrape_tweet

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
    from ..services.url_scraper import scrape_url
    from ..services.post_generator import generate_linkedin_post_from_url_content

    wait_msg = await update.message.reply_text("🔍 Analizando contenido del enlace…")

    try:
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

    # Determinar tipo de media: imágenes del sitio o generar
    if content.images:
        media_type = "image"
    else:
        media_type = "generate"

    post_data = {
        "tweet_url": url,  # reutilizamos el campo tweet_url para la fuente
        "tweet_text": (content.title or content.text[:200]),
        "tweet_author": content.author or content.source_domain or "",
        "linkedin_text": linkedin_text,
        "media_type": media_type,
        "image_urls": content.images or [],
        "use_first_image": media_type == "image",
        "pdf_url": None,
        "document_title": "Documento",
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
        lines.append("🎨 *Multimedia:* Sin imagen/video — Nano Banana Pro generará una imagen con IA")

    else:
        lines.append("📝 *Multimedia:* Sin adjunto")

    return "\n".join(lines)


async def _show_preview(msg, post_data: dict, edit: bool = False):
    """Muestra (o edita) el mensaje de preview con botones de acción."""
    from telegram.error import BadRequest as TgBadRequest

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
    elif data.startswith("view_post:"):
        await _do_view_post(query, int(data.split(":")[1]))
    elif data.startswith("reschedule:"):
        await _do_reschedule_start(query, int(data.split(":")[1]))
    elif data.startswith("proc_liked:"):
        await _do_process_liked(query, int(data.split(":")[1]))
    # ── Nuevos callbacks ──
    elif data == "metrics_all:":
        await _do_refresh_all_metrics(query.message)
    elif data.startswith("metrics_post:"):
        await _do_refresh_single_metrics(query.message, int(data.split(":")[1]))
    elif data == "monitor_check:":
        await _do_monitor_check(query)
    elif data == "prompt_edit:":
        await _do_prompt_edit(query)
    elif data == "prompt_reset:":
        await _do_prompt_reset(query)
    elif data == "reordenar_confirm:":
        await _do_reordenar_confirm(query)
    elif data == "reordenar_cancel:":
        await query.edit_message_reply_markup(None)
        await query.message.reply_text("❌ Reordenamiento cancelado.")


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
            "📖 *Referencia completa de comandos*\n\n"
            "*── Generar contenido ──*\n"
            "Envía cualquier URL → genera post → elige acción\n\n"
            "*── Ver posts ──*\n"
            "/hoy — posts de hoy\n"
            "/dia `[DD/MM]` — posts de cualquier día\n"
            "/pendientes — todos los posts en cola\n"
            "/historial `[N]` — últimos N publicados\n\n"
            "*── Métricas ──*\n"
            "/analiticas — dashboard completo\n"
            "/metricas `[post_id]` — actualizar métricas\n\n"
            "*── Monitor X ──*\n"
            "/monitor — estado del monitor de likes\n"
            "/articulos — likes sin procesar\n\n"
            "*── Configuración ──*\n"
            "/prompt — ver/editar prompt de Claude\n"
            "/imagen `<id>` — generar imagen para un post\n"
            "/reordenar — reorganizar la cola\n\n"
            "*── Datos ──*\n"
            "/exportar — descargar CSV completo\n\n"
            "*── Sistema ──*\n"
            "/status — estado general",
            parse_mode="Markdown",
        )
    elif cmd == "analiticas":
        fake_msg = query.message
        # Reutilizar la lógica de cmd_analiticas
        from sqlalchemy import select
        from ..database import AsyncSessionLocal
        from ..models import ScheduledPost

        async with AsyncSessionLocal() as db:
            result = await db.execute(select(ScheduledPost))
            posts = result.scalars().all()

        published = [p for p in posts if p.status == "published"]
        posts_with_metrics = [p for p in published if p.li_likes is not None or p.li_impressions is not None]
        total_published = len(published)
        total_likes = sum(p.li_likes or 0 for p in published)
        total_comments = sum(p.li_comments or 0 for p in published)
        total_impressions = sum(p.li_impressions or 0 for p in published)
        total_clicks = sum(getattr(p, "li_clicks", None) or 0 for p in published)
        avg_likes = round(total_likes / len(posts_with_metrics), 1) if posts_with_metrics else 0
        engagement_numerator = total_likes + total_comments + total_clicks
        engagement_rate = round(engagement_numerator / total_impressions * 100, 2) if total_impressions > 0 else 0

        text = (
            f"📈 *Analíticas de LinkedIn*\n\n"
            f"📝 Posts publicados: *{total_published}*\n"
            f"❤️ Likes totales: *{total_likes:,}*\n"
            f"💬 Comentarios: *{total_comments:,}*\n"
            f"👁️ Impresiones: *{total_impressions:,}*\n"
            f"📈 Engagement rate: *{engagement_rate}%*\n"
            f"💝 Promedio likes/post: *{avg_likes}*\n"
        )
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("🔄 Actualizar todas las métricas", callback_data="metrics_all:"),
        ]])
        await fake_msg.reply_text(text, parse_mode="Markdown", reply_markup=kb)

    elif cmd == "metricas":
        await _do_refresh_all_metrics(query.message)

    elif cmd == "monitor":
        fake_update = type("FakeUpdate", (), {"message": query.message, "effective_user": query.from_user})()
        await cmd_monitor(fake_update, None)

    elif cmd == "prompt":
        fake_update = type("FakeUpdate", (), {"message": query.message, "effective_user": query.from_user})()
        await cmd_prompt(fake_update, None)

    elif cmd == "exportar":
        fake_update = type("FakeUpdate", (), {"message": query.message, "effective_user": query.from_user})()
        await cmd_exportar(fake_update, None)

    elif cmd == "historial":
        fake_update = type("FakeUpdate", (), {"message": query.message, "effective_user": query.from_user})()
        await cmd_historial(fake_update, None)


async def _do_monitor_check(query):
    """Dispara una verificación inmediata de likes en X."""
    await query.edit_message_reply_markup(None)
    wait = await query.message.reply_text("🔍 Verificando likes de X ahora…\n_(puede tardar 30-60 segundos)_", parse_mode="Markdown")

    try:
        from ..services.x_likes_monitor import check_and_process_likes
        await check_and_process_likes()
        await wait.edit_text("✅ *Verificación completada.*\nUsa /monitor para ver el estado actualizado.", parse_mode="Markdown")
    except Exception as e:
        await wait.edit_text(f"❌ Error durante la verificación:\n`{e}`", parse_mode="Markdown")


async def _do_prompt_edit(query):
    """Entra en modo edición del prompt personalizado de Claude."""
    user_id = query.from_user.id
    _awaiting_prompt.add(user_id)
    await query.edit_message_reply_markup(None)
    await query.message.reply_text(
        "✏️ *Editar prompt de Claude*\n\n"
        "Envía el nuevo prompt en tu próximo mensaje.\n"
        "Este texto reemplazará al prompt del sistema para generar posts.\n\n"
        "_Envía cualquier URL para cancelar y volver al modo normal._",
        parse_mode="Markdown",
    )


async def _do_prompt_reset(query):
    """Elimina el prompt personalizado y restaura el default."""
    from sqlalchemy import select
    from ..database import AsyncSessionLocal
    from ..models import AppSettings

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(AppSettings).where(AppSettings.id == 1))
        cfg = result.scalar_one_or_none()
        if cfg:
            cfg.custom_prompt = None
            await db.commit()

    await query.edit_message_reply_markup(None)
    await query.message.reply_text(
        "✅ *Prompt restablecido al default del sistema.*\n\n"
        "Las próximas generaciones usarán el prompt original.",
        parse_mode="Markdown",
    )


async def _do_reordenar_confirm(query):
    """Ejecuta el reordenamiento de la cola de posts."""
    await query.edit_message_reply_markup(None)
    wait = await query.message.reply_text("📅 Reordenando la cola de posts…")

    try:
        from ..services.x_likes_monitor import repack_schedule
        result = await repack_schedule()
        moved = result.get("moved", 0)
        total = result.get("total", 0)
        await wait.edit_text(
            f"✅ *Cola reordenada*\n\n"
            f"📋 Posts en cola: *{total}*\n"
            f"🔀 Slots ajustados: *{moved}*\n\n"
            f"Usa /pendientes para ver el nuevo orden.",
            parse_mode="Markdown",
        )
    except Exception as e:
        await wait.edit_text(f"❌ Error reordenando:\n`{e}`", parse_mode="Markdown")


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
    is_tweet = bool(_TWEET_RE.match(source_url))

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
    _application.add_handler(CommandHandler("dia", cmd_dia))
    _application.add_handler(CommandHandler("pendientes", cmd_pendientes))
    _application.add_handler(CommandHandler("status", cmd_status))
    _application.add_handler(CommandHandler("articulos", cmd_articulos))
    _application.add_handler(CommandHandler("analiticas", cmd_analiticas))
    _application.add_handler(CommandHandler("metricas", cmd_metricas))
    _application.add_handler(CommandHandler("prompt", cmd_prompt))
    _application.add_handler(CommandHandler("imagen", cmd_imagen))
    _application.add_handler(CommandHandler("reordenar", cmd_reordenar))
    _application.add_handler(CommandHandler("monitor", cmd_monitor))
    _application.add_handler(CommandHandler("historial", cmd_historial))
    _application.add_handler(CommandHandler("exportar", cmd_exportar))
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
