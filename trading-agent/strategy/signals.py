"""
Motor de señales de trading - USD/MXN

Estrategias implementadas con base académica:
─────────────────────────────────────────────
1. RSI (Relative Strength Index)
   Ref: Wilder, J.W. (1978). "New Concepts in Technical Trading Systems"
   Oversold (<30) → señal de compra | Overbought (>70) → señal de venta

2. MACD (Moving Average Convergence Divergence)
   Ref: Appel, G. (1979). "The Moving Average Convergence-Divergence Method"
   Cruce alcista → compra | Cruce bajista → venta

3. Bandas de Bollinger
   Ref: Bollinger, J. (2002). "Bollinger on Bollinger Bands"
   Precio < banda inferior → compra | Precio > banda superior → venta

4. Mean Reversion (Ornstein-Uhlenbeck)
   Ref: Ornstein & Uhlenbeck (1930), aplicado en: Avellaneda & Lee (2010)
   "Statistical Arbitrage in the US Equities Market"
   Z-score de la distancia a la media → reversión esperada

5. Macro Trend
   Tendencia de 30 días como filtro de dirección del mercado
"""
import pandas as pd
import numpy as np
import logging
from config import (
    RSI_PERIOD, RSI_OVERSOLD, RSI_OVERBOUGHT,
    MACD_FAST, MACD_SLOW, MACD_SIGNAL,
    BB_PERIOD, BB_STD,
    MR_LOOKBACK_DAYS,
    SIGNAL_WEIGHTS,
    BUY_THRESHOLD, SELL_THRESHOLD,
    TREND_SMA_FAST, TREND_SMA_SLOW,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# 1. RSI
# ─────────────────────────────────────────────────────────────────────────────

def compute_rsi(closes: pd.Series, period: int = RSI_PERIOD) -> pd.Series:
    delta = closes.diff()
    gain  = delta.clip(lower=0)
    loss  = (-delta).clip(lower=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs  = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi


def rsi_signal(closes: pd.Series) -> tuple[float, dict]:
    """
    Retorna (score 0-1, metadata).
    1.0 = fuerte señal de compra | 0.0 = fuerte señal de venta
    """
    rsi = compute_rsi(closes)
    current = float(rsi.iloc[-1])

    if current < RSI_OVERSOLD:
        # Oversold → esperar rebote → comprar dólares (dólar barato en este contexto
        # significa que el tipo de cambio bajó, o sea el peso se fortaleció)
        score = 1.0 - (current / RSI_OVERSOLD) * 0.5   # [0.5, 1.0]
    elif current > RSI_OVERBOUGHT:
        # Overbought → dólar caro → vender
        score = 0.5 * (100 - current) / (100 - RSI_OVERBOUGHT)  # [0.0, 0.5]
    else:
        # Zona neutral → escalar linealmente
        score = 0.5 + (RSI_OVERSOLD + (RSI_OVERBOUGHT - RSI_OVERSOLD) / 2 - current) / \
                (RSI_OVERBOUGHT - RSI_OVERSOLD)
        score = max(0.0, min(1.0, score))

    return score, {"rsi_value": current, "rsi_oversold": RSI_OVERSOLD, "rsi_overbought": RSI_OVERBOUGHT}


# ─────────────────────────────────────────────────────────────────────────────
# 2. MACD
# ─────────────────────────────────────────────────────────────────────────────

def compute_macd(closes: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series]:
    fast    = closes.ewm(span=MACD_FAST, adjust=False).mean()
    slow    = closes.ewm(span=MACD_SLOW, adjust=False).mean()
    macd    = fast - slow
    signal  = macd.ewm(span=MACD_SIGNAL, adjust=False).mean()
    hist    = macd - signal
    return macd, signal, hist


def macd_signal_score(closes: pd.Series) -> tuple[float, dict]:
    macd, sig, hist = compute_macd(closes)
    current_hist  = float(hist.iloc[-1])
    previous_hist = float(hist.iloc[-2]) if len(hist) > 1 else 0.0

    # Cruce: histograma cambia de signo
    bullish_cross = previous_hist < 0 and current_hist > 0
    bearish_cross = previous_hist > 0 and current_hist < 0

    if bullish_cross:
        score = 0.85
    elif bearish_cross:
        score = 0.15
    elif current_hist > 0:
        # Momentum alcista, escalar por fuerza
        norm = min(abs(current_hist) / (closes.std() * 0.1 + 1e-9), 1.0)
        score = 0.5 + norm * 0.3
    else:
        norm = min(abs(current_hist) / (closes.std() * 0.1 + 1e-9), 1.0)
        score = 0.5 - norm * 0.3

    score = max(0.0, min(1.0, score))
    return score, {
        "macd_value":        float(macd.iloc[-1]),
        "macd_signal_value": float(sig.iloc[-1]),
        "macd_hist":         current_hist,
        "bullish_cross":     bullish_cross,
        "bearish_cross":     bearish_cross,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 3. Bollinger Bands
# ─────────────────────────────────────────────────────────────────────────────

def compute_bollinger(closes: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series]:
    mid   = closes.rolling(BB_PERIOD).mean()
    std   = closes.rolling(BB_PERIOD).std()
    upper = mid + BB_STD * std
    lower = mid - BB_STD * std
    return upper, mid, lower


def bollinger_signal(closes: pd.Series) -> tuple[float, dict]:
    upper, mid, lower = compute_bollinger(closes)
    price = float(closes.iloc[-1])
    u     = float(upper.iloc[-1])
    m     = float(mid.iloc[-1])
    l     = float(lower.iloc[-1])

    band_width = u - l
    if band_width == 0:
        return 0.5, {"bb_upper": u, "bb_mid": m, "bb_lower": l, "bb_pct": 0.5}

    # %B: posición del precio dentro de las bandas (0=banda inf, 1=banda sup)
    pct_b = (price - l) / band_width

    # %B bajo → precio cerca del suelo → señal de compra (dólar barato)
    score = 1.0 - pct_b   # invertido: bajo %B → alto score de compra
    score = max(0.0, min(1.0, score))

    return score, {
        "bb_upper":  u,
        "bb_mid":    m,
        "bb_lower":  l,
        "bb_pct_b":  float(pct_b),
        "price":     price,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 4. Mean Reversion (Ornstein-Uhlenbeck Z-score)
# ─────────────────────────────────────────────────────────────────────────────

def mean_reversion_signal(closes: pd.Series) -> tuple[float, dict]:
    """
    Z-score de la desviación del precio respecto a su media histórica.
    Z < -1.5 → dólar barato vs. su media → comprar
    Z >  1.5 → dólar caro → vender
    Ref: Avellaneda & Lee (2010)
    """
    window = min(MR_LOOKBACK_DAYS, len(closes) - 1)
    series = closes.tail(window + 1)

    mean = float(series.mean())
    std  = float(series.std())
    price = float(closes.iloc[-1])

    if std == 0:
        return 0.5, {"mean_rev_score": 0.0, "z_score": 0.0, "mean": mean}

    z = (price - mean) / std

    # Convertir z-score a score [0, 1]
    # z muy negativo → precio bajo → score alto (compra)
    # z muy positivo → precio alto → score bajo (venta)
    score = 0.5 - np.tanh(z * 0.7) * 0.5
    score = max(0.0, min(1.0, score))

    return score, {
        "mean_rev_score": score,
        "z_score":        float(z),
        "mean":           mean,
        "std":            std,
        "price":          price,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 5. Macro Trend
# ─────────────────────────────────────────────────────────────────────────────

def macro_trend_signal(macro_context: dict) -> tuple[float, dict]:
    """
    Si el dólar ha subido >3% en 30 días → tendencia alcista → score > 0.5
    Si bajó → tendencia bajista → score < 0.5
    Actúa como filtro de dirección.
    """
    trend = macro_context.get("trend_30d", 0.0)

    # Normalizar: ±5% → score entre 0.25 y 0.75
    score = 0.5 + np.tanh(trend * 10) * 0.25
    score = max(0.0, min(1.0, score))

    return score, {
        "macro_trend_30d": trend,
        "macro_score":     score,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Agregador: decisión final
# ─────────────────────────────────────────────────────────────────────────────

def trend_regime(closes: pd.Series) -> tuple[str, dict]:
    """
    Detecta el régimen del mercado usando cruce de SMAs.
    Ref: Elder, A. (1993). "Trading for a Living"

    BULLISH: precio > SMA20 > SMA50  → tendencia alcista fuerte
    NEUTRAL: precio entre SMAs        → mercado de rango
    BEARISH: precio < SMA20 < SMA50  → tendencia bajista

    En régimen BULLISH: bajar umbral de venta (mantener USD)
    En régimen BEARISH: bajar umbral de compra (ser cauteloso)
    """
    if len(closes) < TREND_SMA_SLOW + 1:
        return "NEUTRAL", {"regime": "NEUTRAL", "sma_fast": None, "sma_slow": None}

    sma_fast = float(closes.rolling(TREND_SMA_FAST).mean().iloc[-1])
    sma_slow = float(closes.rolling(TREND_SMA_SLOW).mean().iloc[-1])
    price    = float(closes.iloc[-1])

    if price > sma_fast and sma_fast > sma_slow:
        regime = "BULLISH"
    elif price < sma_fast and sma_fast < sma_slow:
        regime = "BEARISH"
    else:
        regime = "NEUTRAL"

    return regime, {"regime": regime, "sma_fast": sma_fast, "sma_slow": sma_slow}


def compute_final_signal(df: pd.DataFrame, macro_context: dict) -> dict:
    """
    Combina todas las señales con sus pesos y retorna la decisión final.
    Aplica filtro de régimen de tendencia para ajustar umbrales dinámicamente.

    Returns:
        {
            "score": float,        # 0 a 1
            "decision": str,       # BUY | SELL | HOLD
            "signals": dict,       # detalle de cada señal
            "reasoning": str,      # explicación en texto
        }
    """
    if len(df) < BB_PERIOD + 5:
        logger.warning("Datos insuficientes para calcular señales")
        return {"score": 0.5, "decision": "HOLD", "signals": {}, "reasoning": "Datos insuficientes"}

    closes = pd.to_numeric(df["close"], errors="coerce").dropna()

    s_rsi,  meta_rsi   = rsi_signal(closes)
    s_macd, meta_macd  = macd_signal_score(closes)
    s_bb,   meta_bb    = bollinger_signal(closes)
    s_mr,   meta_mr    = mean_reversion_signal(closes)
    s_mac,  meta_mac   = macro_trend_signal(macro_context)
    regime, meta_reg   = trend_regime(closes)

    w = SIGNAL_WEIGHTS
    final_score = (
        w["rsi"]            * s_rsi  +
        w["macd"]           * s_macd +
        w["bollinger"]      * s_bb   +
        w["mean_reversion"] * s_mr   +
        w["macro_trend"]    * s_mac
    )

    # Ajuste dinámico de umbrales según régimen
    # En tendencia alcista: más difícil vender, más fácil comprar
    # En tendencia bajista: más difícil comprar
    buy_thresh  = BUY_THRESHOLD
    sell_thresh = SELL_THRESHOLD
    if regime == "BULLISH":
        buy_thresh  -= 0.05   # 0.55 → comprar en más situaciones
        sell_thresh -= 0.08   # 0.24 → solo vender en señal muy fuerte
    elif regime == "BEARISH":
        buy_thresh  += 0.05   # 0.65 → ser más selectivo al comprar
        sell_thresh += 0.05   # 0.37 → vender más fácilmente

    if final_score > buy_thresh:
        decision = "BUY"
    elif final_score < sell_thresh:
        decision = "SELL"
    else:
        decision = "HOLD"

    signals = {
        **meta_rsi, **meta_macd, **meta_bb, **meta_mr, **meta_mac, **meta_reg,
        "score_rsi":    s_rsi,
        "score_macd":   s_macd,
        "score_bb":     s_bb,
        "score_mr":     s_mr,
        "score_macro":  s_mac,
        "buy_thresh":   buy_thresh,
        "sell_thresh":  sell_thresh,
    }

    reasoning = _build_reasoning(decision, final_score, signals)

    return {
        "score":     final_score,
        "decision":  decision,
        "signals":   signals,
        "reasoning": reasoning,
    }


def _build_reasoning(decision: str, score: float, signals: dict) -> str:
    regime_icon = {"BULLISH": "📈", "BEARISH": "📉", "NEUTRAL": "➡️"}.get(signals.get("regime", ""), "")
    lines = [f"Decisión: {decision} (score={score:.3f})",
             f"Régimen: {regime_icon} {signals.get('regime', 'N/A')} "
             f"(umbral compra={signals.get('buy_thresh', 0):.2f} / venta={signals.get('sell_thresh', 0):.2f})"]

    rsi = signals.get("rsi_value")
    if rsi:
        zone = "SOBREVENDIDO" if rsi < RSI_OVERSOLD else ("SOBRECOMPRADO" if rsi > RSI_OVERBOUGHT else "neutral")
        lines.append(f"• RSI {rsi:.1f} → {zone}")

    z = signals.get("z_score")
    if z is not None:
        lines.append(f"• Z-score mean reversion: {z:.2f} ({'dólar barato' if z < 0 else 'dólar caro'})")

    cross = signals.get("bullish_cross") or signals.get("bearish_cross")
    if signals.get("bullish_cross"):
        lines.append("• MACD: cruce alcista detectado")
    elif signals.get("bearish_cross"):
        lines.append("• MACD: cruce bajista detectado")

    pct_b = signals.get("bb_pct_b")
    if pct_b is not None:
        lines.append(f"• Bollinger %B: {pct_b:.2f} ({'bajo → compra' if pct_b < 0.2 else 'alto → venta' if pct_b > 0.8 else 'central'})")

    trend = signals.get("macro_trend_30d")
    if trend is not None:
        lines.append(f"• Tendencia 30d: {trend*100:+.2f}%")

    return "\n".join(lines)
