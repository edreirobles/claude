"""
Motor de backtesting — Walk-Forward

Metodología:
  - Walk-forward para evitar lookahead bias: en cada día t,
    el agente solo ve datos hasta t-1 para calcular señales.
  - Simula exactamente la misma lógica de portfolio.py y signals.py.
  - No usa datos futuros en ningún punto.

Ref: Pardo, R. (2008). "The Evaluation and Optimization of Trading Strategies"
"""
import pandas as pd
import numpy as np
import logging
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategy.signals import compute_final_signal
from config import (
    INITIAL_CAPITAL_MXN, MAX_POSITION_PCT, MIN_TRADE_MXN,
    KELLY_FRACTION, STOP_LOSS_PCT, TAKE_PROFIT_PCT, MAX_DRAWDOWN_PCT,
    BUY_THRESHOLD, SELL_THRESHOLD,
    RSI_PERIOD, BB_PERIOD, MACD_SLOW,
)

logger = logging.getLogger(__name__)

# Mínimo de días necesarios para que todas las señales tengan datos
MIN_WARMUP = max(RSI_PERIOD, BB_PERIOD, MACD_SLOW) + 5  # ~31 días


class BacktestResult:
    def __init__(self, trades: list, equity_curve: pd.Series, daily: pd.DataFrame):
        self.trades       = trades           # lista de dicts con cada operación
        self.equity_curve = equity_curve     # valor total del portafolio por día
        self.daily        = daily            # DataFrame con señales y precios diarios


def run_backtest(df: pd.DataFrame, initial_capital: float = INITIAL_CAPITAL_MXN) -> BacktestResult:
    """
    Ejecuta el backtest sobre el DataFrame histórico.

    Args:
        df: DataFrame con columnas timestamp, open, high, low, close, volume
            ordenado de más antiguo a más reciente.
        initial_capital: Capital inicial en MXN.

    Returns:
        BacktestResult con trades, equity_curve y daily.
    """
    df = df.copy().reset_index(drop=True)
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df = df.dropna(subset=["close"]).reset_index(drop=True)

    n = len(df)
    if n < MIN_WARMUP + 10:
        raise ValueError(f"Necesitas al menos {MIN_WARMUP + 10} días de datos (tienes {n})")

    # Estado del portafolio
    mxn         = initial_capital
    usd         = 0.0
    peak_total  = initial_capital
    last_buy_price = None

    trades       = []
    equity_rows  = []
    daily_rows   = []

    for i in range(MIN_WARMUP, n):
        # Solo datos hasta el día anterior (walk-forward)
        window = df.iloc[:i].copy()
        price  = float(df.iloc[i]["close"])
        date   = str(df.iloc[i]["timestamp"])[:10]

        total  = mxn + usd * price

        # Macro context con los datos disponibles hasta hoy
        macro  = _compute_macro(window)

        # Señales
        result = compute_final_signal(window, macro)
        score  = result["score"]
        decision = result["decision"]

        # ── Stop-loss (wide, ATR-style para daily USD/MXN) ──────────────────
        # USD/MXN puede corregir 6-8% en tendencia → SL estrecho genera ruido
        # Usamos precio promedio ponderado de toda la posición como referencia
        if usd > 0 and last_buy_price:
            chg = (price - last_buy_price) / last_buy_price
            if chg < -STOP_LOSS_PCT:
                mxn_recv = usd * price
                trades.append(_trade("SELL_SL", usd, mxn_recv, price, date,
                                     f"Stop-loss {chg*100:.2f}%"))
                mxn += mxn_recv
                usd  = 0.0
                last_buy_price = None
                decision = "SELL_SL"

        # ── Drawdown máximo ──────────────────────────────────────────────────
        dd = (peak_total - total) / peak_total if peak_total > 0 else 0
        if dd > MAX_DRAWDOWN_PCT:
            if usd > 0:
                mxn_recv = usd * price
                trades.append(_trade("SELL_DD", usd, mxn_recv, price, date,
                                     f"Drawdown máximo {dd*100:.1f}%"))
                mxn += mxn_recv
                usd  = 0.0
                last_buy_price = None

        # ── Ejecutar señal ───────────────────────────────────────────────────
        # Posición binaria: o estás en MXN o en USD, nunca los dos.
        # Evita acumulación en tendencia bajista y simplifica el riesgo.
        regime = result["signals"].get("regime", "NEUTRAL")

        if decision == "BUY" and usd == 0 and mxn >= MIN_TRADE_MXN:
            # No comprar en régimen bajista (el precio sigue cayendo)
            if regime != "BEARISH":
                mxn_to_spend = min(_kelly_size(score, mxn), mxn)
                if mxn_to_spend >= MIN_TRADE_MXN:
                    usd_recv = mxn_to_spend / price
                    mxn -= mxn_to_spend
                    usd += usd_recv
                    last_buy_price = price
                    trades.append(_trade("BUY", usd_recv, mxn_to_spend, price, date,
                                         f"score={score:.3f} regime={regime}"))

        elif decision == "SELL" and usd > 0:
            usd_sell = usd
            mxn_recv = usd_sell * price
            usd  = 0.0
            mxn += mxn_recv
            last_buy_price = None
            trades.append(_trade("SELL", usd_sell, mxn_recv, price, date,
                                 f"score={score:.3f} regime={regime}"))

        total = mxn + usd * price
        peak_total = max(peak_total, total)

        equity_rows.append({"date": date, "total": total})
        daily_rows.append({
            "date":     date,
            "price":    price,
            "score":    score,
            "decision": decision,
            "mxn":      mxn,
            "usd":      usd,
            "total":    total,
        })

    equity_curve = pd.DataFrame(equity_rows).set_index("date")["total"]
    daily_df     = pd.DataFrame(daily_rows)

    return BacktestResult(trades=trades, equity_curve=equity_curve, daily=daily_df)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _compute_macro(df: pd.DataFrame) -> dict:
    closes = pd.to_numeric(df["close"], errors="coerce").dropna()
    if len(closes) < 30:
        return {"trend_30d": 0.0, "volatility_30d": 0.0}
    pct_30d = (closes.iloc[-1] - closes.iloc[-30]) / closes.iloc[-30]
    vol_30d = closes.pct_change().tail(30).std()
    return {
        "trend_30d":      float(pct_30d),
        "volatility_30d": float(vol_30d),
        "price_now":      float(closes.iloc[-1]),
    }


def _kelly_size(score: float, mxn_available: float) -> float:
    p = score
    q = 1.0 - p
    b = TAKE_PROFIT_PCT / STOP_LOSS_PCT
    kelly = max(0.0, (p * b - q) / b) * KELLY_FRACTION
    kelly = min(kelly, MAX_POSITION_PCT)
    return mxn_available * kelly


def _trade(action: str, usd: float, mxn: float, price: float, date: str, reason: str) -> dict:
    return {
        "date":   date,
        "action": action,
        "usd":    usd,
        "mxn":    mxn,
        "price":  price,
        "reason": reason,
    }
