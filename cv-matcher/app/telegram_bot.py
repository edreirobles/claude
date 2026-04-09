import asyncio
import logging
import os
import uuid
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from app import telegram_db

logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
FREE_LIMIT = int(os.environ.get("FREE_GENERATIONS_LIMIT", 3))

# Conversation states
WAITING_JOB, WAITING_LANG, WAITING_CV = range(3)

LANG_OPTIONS = [
    ("auto", "🌐 Auto (idioma de la vacante)"),
    ("es",   "🇪🇸 Español"),
    ("en",   "🇺🇸 English"),
    ("fr",   "🇫🇷 Français"),
    ("pt",   "🇧🇷 Português"),
    ("de",   "🇩🇪 Deutsch"),
]


# ── Helpers ────────────────────────────────────────────────────────────────────

def _status_line(profile: dict) -> str:
    plan = profile.get("plan", "free")
    if plan == "monthly":
        return "✅ Plan mensual activo"
    if plan == "credits":
        n = profile.get("credits", 0)
        return f"🎫 {n} crédito(s) disponible(s)"
    remaining = FREE_LIMIT - profile.get("free_generations_used", 0)
    if remaining > 0:
        return f"🆓 {remaining} generación(es) gratis restante(s)"
    return "❌ Sin generaciones disponibles — usa /comprar"


def _paywall_text() -> str:
    app_url = os.environ.get("APP_URL", "")
    p_cv  = os.environ.get("PRICE_CREDITS_DISPLAY", "$2")
    p_mo  = os.environ.get("PRICE_MONTHLY_DISPLAY", "$5/mes")
    return (
        "⛔ *Agotaste tus generaciones gratuitas.*\n\n"
        f"💳 *Opciones:*\n"
        f"• CV individual — {p_cv}\n"
        f"• Plan mensual (10 CVs) — {p_mo}\n\n"
        f"Paga aquí de forma segura:\n{app_url}"
    )


# ── Command handlers ────────────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    profile = telegram_db.get_or_create_profile(user.id, user.username)
    await update.message.reply_text(
        f"👋 Hola *{user.first_name}*\\!\n\n"
        "Soy *CV Matcher* — adapto tu CV a cualquier vacante en ~60 segundos\\. "
        "Sin inventar nada, solo refraseando lo que ya tienes\\.\n\n"
        f"📊 {_status_line(profile)}\n\n"
        "Envía /generar para empezar\\.",
        parse_mode="MarkdownV2",
    )


async def cmd_generar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    profile = telegram_db.get_or_create_profile(user.id, user.username)
    can, _ = telegram_db.can_generate(profile)
    if not can:
        await update.message.reply_text(_paywall_text(), parse_mode="Markdown")
        return ConversationHandler.END

    await update.message.reply_text(
        "📋 *Paso 1 / 3*\n\n"
        "Envíame el *link de la vacante* o pega el *texto del puesto* aquí 👇",
        parse_mode="Markdown",
    )
    return WAITING_JOB


async def received_job(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    ctx.user_data["job_input"] = text
    ctx.user_data["job_is_url"] = text.startswith("http")

    keyboard = [[InlineKeyboardButton(label, callback_data=f"lang:{code}")]
                for code, label in LANG_OPTIONS]
    await update.message.reply_text(
        "🌐 *Paso 2 / 3*\n\n¿En qué idioma quieres el CV?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )
    return WAITING_LANG


async def received_lang(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    lang_code = query.data.split(":")[1]
    ctx.user_data["output_language"] = lang_code
    label = next((l for c, l in LANG_OPTIONS if c == lang_code), "Auto")

    await query.edit_message_text(
        f"✅ Idioma: {label}\n\n"
        "📎 *Paso 3 / 3*\n\n"
        "Envíame tu CV en *PDF* o *Word (.docx)*",
        parse_mode="Markdown",
    )
    return WAITING_CV


async def received_cv(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    doc = update.message.document

    if not doc:
        await update.message.reply_text("Por favor adjunta el archivo como documento (PDF o Word).")
        return WAITING_CV

    fname = doc.file_name or ""
    if not (fname.lower().endswith(".pdf") or fname.lower().endswith(".docx")):
        await update.message.reply_text("❌ Solo acepto PDF o Word (.docx). Intenta de nuevo.")
        return WAITING_CV

    profile = telegram_db.get_or_create_profile(user.id, user.username)
    can, _ = telegram_db.can_generate(profile)
    if not can:
        await update.message.reply_text(_paywall_text(), parse_mode="Markdown")
        return ConversationHandler.END

    msg = await update.message.reply_text("⏳ Descargando tu CV...")
    local_path = None

    try:
        # Download CV file
        uploads = Path("uploads")
        uploads.mkdir(exist_ok=True)
        tg_file = await doc.get_file()
        suffix = Path(fname).suffix
        local_path = uploads / f"tg_{user.id}_{doc.file_unique_id}{suffix}"
        await tg_file.download_to_drive(str(local_path))

        # Parse CV text
        from app.cv_parser import parse_cv
        cv_text = parse_cv(str(local_path))

        # Scrape URL or use raw text
        job_input = ctx.user_data.get("job_input", "")
        if ctx.user_data.get("job_is_url"):
            await msg.edit_text("🔍 Leyendo la vacante...")
            from app.job_scraper import scrape_job_url
            scrape_result = await scrape_job_url(job_input)
            job_description = scrape_result.get("text") or scrape_result.get("content") or job_input
        else:
            job_description = job_input

        output_language = ctx.user_data.get("output_language", "auto")
        gen_id = str(uuid.uuid4())

        await msg.edit_text("🤖 Adaptando tu CV con IA... (~30 seg)")

        # Generate adapted CV
        from app.cv_generator import generate_adapted_cv
        result = await generate_adapted_cv(cv_text, job_description, gen_id, output_language)

        cv_data = result.get("cv_data", {})
        pdf_path = Path(result.get("pdf_path", ""))

        if not pdf_path.exists():
            raise FileNotFoundError("PDF no encontrado")

        # Consume credit
        telegram_db.consume_credit(user.id, profile)

        # Save to history
        telegram_db.save_generation(
            telegram_user_id=user.id,
            gen_id=gen_id,
            job_text=job_input,
            job_title=cv_data.get("job_title_applied"),
            company=cv_data.get("company_applied"),
            pdf_path=str(pdf_path),
            output_language=output_language,
        )

        # Refresh profile for updated status
        updated_profile = telegram_db.get_or_create_profile(user.id, user.username)
        job_title = cv_data.get("job_title_applied") or "—"
        company   = cv_data.get("company_applied") or "—"

        await msg.delete()
        with open(pdf_path, "rb") as f:
            await update.message.reply_document(
                document=f,
                filename=f"CV_{job_title}.pdf",
                caption=(
                    f"✅ *¡Tu CV está listo\\!*\n\n"
                    f"📌 Puesto: {job_title}\n"
                    f"🏢 Empresa: {company}\n\n"
                    f"📊 {_status_line(updated_profile)}\n\n"
                    "Usa /generar para crear otro\\."
                ),
                parse_mode="MarkdownV2",
            )

    except Exception as e:
        logger.exception("Error generating CV for Telegram user %s", user.id)
        await msg.edit_text(
            "❌ Ocurrió un error al generar tu CV. Intenta de nuevo con /generar.\n"
            "Asegúrate de que el archivo no esté protegido con contraseña."
        )

    finally:
        if local_path and local_path.exists():
            local_path.unlink(missing_ok=True)

    return ConversationHandler.END


async def cmd_historial(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    gens = telegram_db.get_history(user.id)
    if not gens:
        await update.message.reply_text(
            "📭 Aún no tienes CVs generados\\. Usa /generar para empezar\\.",
            parse_mode="MarkdownV2",
        )
        return

    lines = ["📚 *Tus últimos CVs:*\n"]
    for i, g in enumerate(gens, 1):
        title   = g.get("job_title") or "Sin título"
        company = g.get("company") or "—"
        date    = (g.get("created_at") or "")[:10]
        lines.append(f"{i}\\. *{title}* en {company} \\({date}\\)")

    await update.message.reply_text("\n".join(lines), parse_mode="MarkdownV2")


async def cmd_plan(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    profile = telegram_db.get_or_create_profile(user.id, user.username)
    await update.message.reply_text(
        f"📊 *Tu plan actual:*\n\n{_status_line(profile)}\n\nUsa /comprar para más generaciones\\.",
        parse_mode="MarkdownV2",
    )


async def cmd_comprar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    app_url  = os.environ.get("APP_URL", "")
    p_cv     = os.environ.get("PRICE_CREDITS_DISPLAY", "$2")
    p_mo     = os.environ.get("PRICE_MONTHLY_DISPLAY", "$5/mes")
    keyboard = [
        [InlineKeyboardButton(f"💳 CV individual ({p_cv})", url=app_url)],
        [InlineKeyboardButton(f"⭐ Plan mensual ({p_mo})", url=app_url)],
    ]
    await update.message.reply_text(
        f"💰 *Opciones de pago:*\n\n"
        f"• CV individual — {p_cv} (1 generación)\n"
        f"• Plan mensual — {p_mo} (10 CVs/mes)\n\n"
        "Paga de forma segura con Stripe:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )


async def cmd_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Cancelado. Usa /generar cuando quieras.")
    return ConversationHandler.END


async def fallback_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "No entendí eso. Comandos disponibles:\n\n"
        "/generar — crear un nuevo CV\n"
        "/historial — ver tus CVs anteriores\n"
        "/plan — ver tu plan actual\n"
        "/comprar — adquirir más generaciones"
    )


# ── Bot assembly ───────────────────────────────────────────────────────────────

def build_application() -> Application | None:
    if not TELEGRAM_TOKEN:
        return None

    ptb = Application.builder().token(TELEGRAM_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("generar", cmd_generar)],
        states={
            WAITING_JOB:  [MessageHandler(filters.TEXT & ~filters.COMMAND, received_job)],
            WAITING_LANG: [CallbackQueryHandler(received_lang, pattern="^lang:")],
            WAITING_CV:   [MessageHandler(filters.Document.ALL, received_cv)],
        },
        fallbacks=[CommandHandler("cancel", cmd_cancel)],
    )

    ptb.add_handler(CommandHandler("start",     cmd_start))
    ptb.add_handler(CommandHandler("historial", cmd_historial))
    ptb.add_handler(CommandHandler("plan",      cmd_plan))
    ptb.add_handler(CommandHandler("comprar",   cmd_comprar))
    ptb.add_handler(conv)
    ptb.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, fallback_text))

    return ptb


async def run_bot():
    """Run the Telegram bot in polling mode alongside FastAPI."""
    ptb = build_application()
    if not ptb:
        logger.info("TELEGRAM_BOT_TOKEN not set — bot disabled.")
        return

    logger.info("Starting Telegram bot...")
    await ptb.initialize()
    await ptb.start()
    await ptb.updater.start_polling(drop_pending_updates=True)
    logger.info("Telegram bot is running.")

    try:
        await asyncio.get_event_loop().create_future()  # run forever
    except asyncio.CancelledError:
        pass
    finally:
        await ptb.updater.stop()
        await ptb.stop()
        await ptb.shutdown()
