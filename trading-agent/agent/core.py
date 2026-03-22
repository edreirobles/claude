"""
Core del agente autónomo de trading USD/MXN

Loop principal:
  1. Cada día a las 9am CST: análisis completo + decisión
  2. Cada hora: check de stop-loss / take-profit
  3. Telegram: comandos en tiempo real
"""
import logging
import asyncio
import sys
import os
from datetime import datetime
import pytz
import schedule
import time

# Asegurar que el directorio raíz está en el path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import (
    DB_PATH, LOG_PATH, TIMEZONE, DAILY_ANALYSIS_TIME,
    HISTORICAL_DAYS, PAPER_TRADING, TELEGRAM_BOT_TOKEN,
)
from storage.db import init_db, save_signal, get_price_history, save_prices
from data.fetcher import fetch_historical, fetch_current_price, get_macro_context
from strategy.signals import compute_final_signal
from agent.portfolio import Portfolio
from agent.telegram_bot import (
    build_application, set_agent_state, notify,
    format_trade_notification, format_daily_report,
)

import sys as _sys
if hasattr(_sys.stdout, "reconfigure"):
    _sys.stdout.reconfigure(encoding="utf-8")
if hasattr(_sys.stderr, "reconfigure"):
    _sys.stderr.reconfigure(encoding="utf-8")

_fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
_file_handler   = logging.FileHandler(LOG_PATH, encoding="utf-8")
_stream_handler = logging.StreamHandler(_sys.stdout)
_file_handler.setFormatter(_fmt)
_stream_handler.setFormatter(_fmt)
logging.basicConfig(level=logging.INFO, handlers=[_file_handler, _stream_handler])
logger = logging.getLogger(__name__)

# Estado global
_state = {
    "paused":      False,
    "portfolio":   None,
    "last_signal": None,
    "last_price":  None,
}


def run_daily_analysis():
    """Análisis completo diario: descarga datos, calcula señales, ejecuta si corresponde."""
    if _state["paused"]:
        logger.info("Agente pausado, saltando análisis diario")
        return

    logger.info("═" * 50)
    logger.info("ANÁLISIS DIARIO INICIADO")
    tz   = pytz.timezone(TIMEZONE)
    now  = datetime.now(tz)
    logger.info(f"Hora: {now.strftime('%Y-%m-%d %H:%M %Z')}")

    # 1. Precio actual
    price = fetch_current_price()
    if not price:
        msg = "⚠️ No se pudo obtener el precio actual de USD/MXN"
        logger.error(msg)
        notify(msg)
        return

    _state["last_price"] = price
    logger.info(f"Precio USD/MXN: {price:.4f}")

    # 2. Histórico
    df_hist = fetch_historical(days=HISTORICAL_DAYS)
    if df_hist.empty:
        logger.error("Sin datos históricos, abortando análisis")
        return

    save_prices(DB_PATH, df_hist.to_dict("records"))

    # 3. Contexto macro
    macro = get_macro_context()
    logger.info(f"Macro: tendencia 30d = {macro.get('trend_30d', 0)*100:+.2f}%")

    # 4. Señales
    signal_result = compute_final_signal(df_hist, macro)
    _state["last_signal"] = signal_result
    save_signal(DB_PATH, signal_result["signals"], signal_result["score"], signal_result["decision"])

    logger.info(f"Score final: {signal_result['score']:.3f} → {signal_result['decision']}")
    logger.info(signal_result["reasoning"])

    # 5. Ejecución
    portfolio: Portfolio = _state["portfolio"]
    trade_result = None

    if signal_result["decision"] == "BUY":
        trade_result = portfolio.buy_usd(
            score=signal_result["score"],
            price=price,
            reason=signal_result["reasoning"],
            regime=signal_result["signals"].get("regime", "NEUTRAL"),
        )
    elif signal_result["decision"] == "SELL":
        trade_result = portfolio.sell_usd(
            score=signal_result["score"],
            price=price,
            reason=signal_result["reasoning"],
        )

    # 6. Notificación Telegram
    status = portfolio.status(price)
    set_agent_state({
        "paused":      _state["paused"],
        "last_signal": signal_result,
        "last_price":  price,
        "portfolio":   portfolio,
    })

    if trade_result:
        notify(format_trade_notification(trade_result))

    report = format_daily_report(signal_result, status)
    notify(report)
    logger.info("Análisis diario completado")


def check_stops():
    """Revisa stop-loss y take-profit intradiariamente."""
    if _state["paused"] or not _state["last_signal"]:
        return

    portfolio: Portfolio = _state["portfolio"]
    price = fetch_current_price()
    if not price:
        return

    _state["last_price"] = price

    # Check drawdown máximo (ya lo maneja portfolio.can_trade)
    dd = portfolio.drawdown(price)
    if dd > 0.10:  # Alerta si drawdown > 10%
        notify(f"⚠️ *Alerta drawdown*: {dd*100:.1f}%\nTotal: `{portfolio.total_mxn(price):.2f} MXN`")

    # Si tenemos USD y el precio bajó mucho (stop-loss)
    if portfolio.usd > 0:
        # Buscar el precio de la última compra
        from storage.db import get_trade_history
        trades = get_trade_history(DB_PATH, limit=10)
        last_buy = next((t for t in trades if t["action"] == "BUY"), None)

        if last_buy:
            entry_price = last_buy["price"]
            loss_pct    = (price - entry_price) / entry_price

            from config import STOP_LOSS_PCT, TAKE_PROFIT_PCT
            if loss_pct < -STOP_LOSS_PCT:
                reason = f"Stop-loss activado: pérdida de {loss_pct*100:.2f}%"
                logger.warning(reason)
                result = portfolio.sell_usd(score=0.1, price=price, reason=reason)
                if result:
                    notify(f"🛑 *STOP-LOSS*\n" + format_trade_notification(result))

            elif loss_pct > TAKE_PROFIT_PCT:
                reason = f"Take-profit activado: ganancia de {loss_pct*100:.2f}%"
                logger.info(reason)
                result = portfolio.sell_usd(score=0.2, price=price, reason=reason)
                if result:
                    notify(f"🎯 *TAKE-PROFIT*\n" + format_trade_notification(result))


def run_agent():
    """Inicializa y ejecuta el agente."""
    logger.info("TRADING AGENT USD/MXN - INICIANDO")
    logger.info(f"Modo: {'PAPER TRADING' if PAPER_TRADING else 'REAL (Bitso)'}")

    # Init DB
    init_db(DB_PATH)

    # Init portafolio
    portfolio = Portfolio()
    _state["portfolio"] = portfolio

    set_agent_state({
        "paused":      False,
        "portfolio":   portfolio,
        "last_signal": None,
        "last_price":  None,
    })

    notify(
        f"🤖 *Trading Agent iniciado*\n"
        f"Par: USD/MXN\n"
        f"Modo: {'📝 Paper Trading' if PAPER_TRADING else '🔴 Real (Bitso)'}\n"
        f"Capital: `{portfolio.mxn:.2f} MXN + {portfolio.usd:.4f} USD`\n"
        f"Análisis diario: {DAILY_ANALYSIS_TIME} CST\n"
        f"Usa /help para ver comandos disponibles."
    )

    # Ejecutar análisis inmediato al arrancar
    run_daily_analysis()

    # Programar análisis diario
    schedule.every().day.at(DAILY_ANALYSIS_TIME).do(run_daily_analysis)

    # Check de stops cada hora
    schedule.every(60).minutes.do(check_stops)

    # Telegram bot en hilo separado
    if TELEGRAM_BOT_TOKEN:
        logger.info("Iniciando bot de Telegram...")
        app = build_application()

        async def run_bot():
            await app.initialize()
            await app.start()
            await app.updater.start_polling(drop_pending_updates=True)
            logger.info("Bot Telegram activo")
            while True:
                schedule.run_pending()
                await asyncio.sleep(30)

        asyncio.run(run_bot())
    else:
        logger.warning("TELEGRAM_BOT_TOKEN no configurado, corriendo sin Telegram")
        while True:
            schedule.run_pending()
            time.sleep(30)


if __name__ == "__main__":
    run_agent()
