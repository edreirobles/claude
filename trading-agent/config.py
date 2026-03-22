"""
Trading Agent Configuration
USD/MXN - Monterrey, México
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ── Capital ──────────────────────────────────────────────────────────────────
INITIAL_CAPITAL_MXN = 1000.0       # Capital inicial en MXN
MAX_POSITION_PCT    = 0.80         # Máximo 80% del capital en una posición
MIN_TRADE_MXN       = 50.0         # Mínimo por operación (comisiones)

# ── Par de trading ───────────────────────────────────────────────────────────
TICKER              = "MXN=X"      # Yahoo Finance: USD/MXN
BASE_CURRENCY       = "MXN"
QUOTE_CURRENCY      = "USD"

# ── Horario de operación (zona horaria Monterrey = CST/CDT) ──────────────────
TIMEZONE            = "America/Monterrey"
DAILY_ANALYSIS_TIME = "09:00"      # Análisis diario a las 9am
INTRADAY_INTERVAL   = 60           # Minutos entre checks intradiarios

# ── Estrategia ───────────────────────────────────────────────────────────────
# Pesos de cada señal en la decisión final (deben sumar 1.0)
SIGNAL_WEIGHTS = {
    "rsi":              0.25,
    "macd":             0.20,
    "bollinger":        0.25,
    "mean_reversion":   0.20,
    "macro_trend":      0.10,
}

# Umbrales para ejecutar operaciones
BUY_THRESHOLD       = 0.55         # Score > 0.55 → COMPRAR USD
SELL_THRESHOLD      = 0.45         # Score < 0.45 → VENDER USD
NEUTRAL_ZONE        = (0.45, 0.55) # Zona de no operación

# RSI
RSI_PERIOD          = 14
RSI_OVERSOLD        = 30           # < 30 = oversold → comprar
RSI_OVERBOUGHT      = 70           # > 70 = overbought → vender

# MACD
MACD_FAST           = 12
MACD_SLOW           = 26
MACD_SIGNAL         = 9

# Bollinger Bands
BB_PERIOD           = 20
BB_STD              = 2.0

# Mean Reversion (Ornstein-Uhlenbeck)
MR_LOOKBACK_DAYS    = 60           # Ventana para calcular la media histórica

# ── Gestión de riesgo (Kelly Criterion) ─────────────────────────────────────
KELLY_FRACTION      = 0.25         # Kelly fraccional (25% del Kelly completo)
MAX_DRAWDOWN_PCT    = 0.15         # Stop total si drawdown > 15%
STOP_LOSS_PCT       = 0.03         # Stop loss por operación: 3%
TAKE_PROFIT_PCT     = 0.05         # Take profit: 5%

# ── Telegram ─────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN  = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID    = os.getenv("TELEGRAM_CHAT_ID", "")

# ── Modo de ejecución ────────────────────────────────────────────────────────
PAPER_TRADING       = True         # True = simulación | False = real (Bitso)
BITSO_API_KEY       = os.getenv("BITSO_API_KEY", "")
BITSO_API_SECRET    = os.getenv("BITSO_API_SECRET", "")

# ── Storage ──────────────────────────────────────────────────────────────────
DB_PATH             = "storage/trading.db"
LOG_PATH            = "logs/agent.log"
HISTORICAL_DAYS     = 365          # Días de histórico a descargar
