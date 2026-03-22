"""
Integración con Telegram.
El agente envía reportes automáticos y acepta comandos del usuario.

Comandos disponibles:
  /status   → estado actual del portafolio
  /signal   → última señal calculada
  /trades   → últimas 5 operaciones
  /pause    → pausar el agente
  /resume   → reanudar el agente
  /report   → reporte completo del día
"""
import logging
import asyncio
from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, ContextTypes
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

logger = logging.getLogger(__name__)

# Estado global del agente (compartido con core.py)
_agent_state = {"paused": False, "last_signal": None, "portfolio": None}


def set_agent_state(state: dict):
    _agent_state.update(state)


async def send_message(text: str, parse_mode: str = "Markdown"):
    """Envía un mensaje al chat configurado."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram no configurado (falta BOT_TOKEN o CHAT_ID)")
        return
    try:
        bot = Bot(token=TELEGRAM_BOT_TOKEN)
        await bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=text,
            parse_mode=parse_mode,
        )
    except Exception as e:
        logger.error(f"Error enviando mensaje Telegram: {e}")


def notify(text: str):
    """Wrapper síncrono para enviar mensajes desde código no-async."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(send_message(text))
        else:
            loop.run_until_complete(send_message(text))
    except Exception as e:
        logger.error(f"notify() falló: {e}")


def format_trade_notification(trade: dict) -> str:
    action = trade.get("action", "")
    icon   = "🟢" if action == "BUY" else "🔴"
    price  = trade.get("price", 0)

    if action == "BUY":
        return (
            f"{icon} *COMPRA EJECUTADA*\n"
            f"💵 USD comprados: `{trade.get('usd_received', 0):.4f}`\n"
            f"💴 MXN gastados: `{trade.get('mxn_spent', 0):.2f}`\n"
            f"📈 Precio: `{price:.4f} MXN/USD`\n"
            f"💰 Balance MXN: `{trade.get('mxn_balance', 0):.2f}`\n"
            f"💰 Balance USD: `{trade.get('usd_balance', 0):.4f}`\n"
            f"📊 Total: `{trade.get('total_mxn', 0):.2f} MXN`"
        )
    else:
        return (
            f"{icon} *VENTA EJECUTADA*\n"
            f"💵 USD vendidos: `{trade.get('usd_sold', 0):.4f}`\n"
            f"💴 MXN recibidos: `{trade.get('mxn_received', 0):.2f}`\n"
            f"📈 Precio: `{price:.4f} MXN/USD`\n"
            f"💰 Balance MXN: `{trade.get('mxn_balance', 0):.2f}`\n"
            f"💰 Balance USD: `{trade.get('usd_balance', 0):.4f}`\n"
            f"📊 Total: `{trade.get('total_mxn', 0):.2f} MXN`"
        )


def format_daily_report(signal_result: dict, portfolio_status: dict) -> str:
    score    = signal_result.get("score", 0)
    decision = signal_result.get("decision", "HOLD")
    reason   = signal_result.get("reasoning", "")

    pnl      = portfolio_status.get("pnl_mxn", 0)
    pnl_pct  = portfolio_status.get("pnl_pct", 0)
    dd       = portfolio_status.get("drawdown_pct", 0)
    mode     = "📝 PAPER" if portfolio_status.get("paper_trading") else "🔴 REAL"

    icon_decision = {"BUY": "🟢", "SELL": "🔴", "HOLD": "⏸️"}.get(decision, "❓")

    return (
        f"📊 *REPORTE DIARIO USD/MXN* {mode}\n"
        f"{'─'*30}\n"
        f"{icon_decision} Decisión: *{decision}* (score: `{score:.3f}`)\n\n"
        f"*Análisis técnico:*\n{reason}\n\n"
        f"{'─'*30}\n"
        f"*Portafolio:*\n"
        f"  MXN: `{portfolio_status.get('mxn_balance', 0):.2f}`\n"
        f"  USD: `{portfolio_status.get('usd_balance', 0):.4f}`\n"
        f"  Precio: `{portfolio_status.get('usd_price', 0):.4f}`\n"
        f"  Total: `{portfolio_status.get('total_mxn', 0):.2f} MXN`\n"
        f"  P&L: `{pnl:+.2f} MXN ({pnl_pct:+.2f}%)`\n"
        f"  Drawdown: `{dd:.2f}%`"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Handlers de comandos
# ─────────────────────────────────────────────────────────────────────────────

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    p = _agent_state.get("portfolio")
    if not p:
        await update.message.reply_text("No hay datos de portafolio aún.")
        return
    price = _agent_state.get("last_price", 0)
    status = p.status(price)
    pnl    = status.get("pnl_mxn", 0)
    await update.message.reply_text(
        f"💼 *Portafolio actual*\n"
        f"MXN: `{status['mxn_balance']:.2f}`\n"
        f"USD: `{status['usd_balance']:.4f}`\n"
        f"Precio USD/MXN: `{price:.4f}`\n"
        f"Total: `{status['total_mxn']:.2f} MXN`\n"
        f"P&L: `{pnl:+.2f} MXN ({status['pnl_pct']:+.2f}%)`",
        parse_mode="Markdown"
    )


async def cmd_signal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sig = _agent_state.get("last_signal")
    if not sig:
        await update.message.reply_text("Sin señales calculadas aún.")
        return
    await update.message.reply_text(
        f"📡 *Última señal*\n"
        f"Score: `{sig['score']:.3f}`\n"
        f"Decisión: *{sig['decision']}*\n\n"
        f"{sig.get('reasoning', '')}",
        parse_mode="Markdown"
    )


async def cmd_pause(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _agent_state["paused"] = True
    await update.message.reply_text("⏸️ Agente pausado. Usa /resume para continuar.")


async def cmd_resume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _agent_state["paused"] = False
    await update.message.reply_text("▶️ Agente reanudado.")


async def cmd_trades(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from storage.db import get_trade_history
    from config import DB_PATH
    trades = get_trade_history(DB_PATH, limit=5)
    if not trades:
        await update.message.reply_text("Sin operaciones registradas.")
        return
    lines = ["📋 *Últimas 5 operaciones:*\n"]
    for t in trades:
        icon = "🟢" if t["action"] == "BUY" else "🔴"
        lines.append(f"{icon} {t['action']} {t['usd_amount']:.4f} USD @ {t['price']:.4f} ({t['timestamp'][:10]})")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 *Trading Agent USD/MXN*\n\n"
        "/status  → Portafolio actual\n"
        "/signal  → Última señal\n"
        "/trades  → Últimas operaciones\n"
        "/pause   → Pausar agente\n"
        "/resume  → Reanudar agente\n"
        "/report  → Reporte completo",
        parse_mode="Markdown"
    )


async def cmd_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sig = _agent_state.get("last_signal")
    p   = _agent_state.get("portfolio")
    price = _agent_state.get("last_price", 0)
    if not sig or not p:
        await update.message.reply_text("Aún no hay datos suficientes para el reporte.")
        return
    text = format_daily_report(sig, p.status(price))
    await update.message.reply_text(text, parse_mode="Markdown")


def build_application() -> Application:
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("status",  cmd_status))
    app.add_handler(CommandHandler("signal",  cmd_signal))
    app.add_handler(CommandHandler("pause",   cmd_pause))
    app.add_handler(CommandHandler("resume",  cmd_resume))
    app.add_handler(CommandHandler("trades",  cmd_trades))
    app.add_handler(CommandHandler("report",  cmd_report))
    app.add_handler(CommandHandler("help",    cmd_help))
    app.add_handler(CommandHandler("start",   cmd_help))
    return app
