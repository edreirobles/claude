"""
Gestión del portafolio y cálculo de tamaño de posición (Kelly Criterion)

Ref: Kelly, J.L. (1956). "A New Interpretation of Information Rate"
     Bell System Technical Journal.

Kelly Criterion fraccional:
  f* = (p * b - q) / b   donde:
    p = probabilidad de ganar (estimada del score)
    q = 1 - p
    b = ratio reward/risk (take_profit / stop_loss)

  Se usa Kelly fraccional (25%) para reducir varianza.
"""
import logging
from config import (
    INITIAL_CAPITAL_MXN, MAX_POSITION_PCT, MIN_TRADE_MXN,
    KELLY_FRACTION, MAX_DRAWDOWN_PCT, STOP_LOSS_PCT, TAKE_PROFIT_PCT,
    PAPER_TRADING, DB_PATH,
)
from storage.db import save_portfolio_snapshot, save_trade, get_last_portfolio

logger = logging.getLogger(__name__)


class Portfolio:
    def __init__(self):
        last = get_last_portfolio(DB_PATH)
        if last:
            self.mxn = last["mxn_balance"]
            self.usd = last["usd_balance"]
            self._peak_total = last["total_mxn"]
            logger.info(f"Portafolio restaurado: {self.mxn:.2f} MXN + {self.usd:.4f} USD")
        else:
            self.mxn = INITIAL_CAPITAL_MXN
            self.usd = 0.0
            self._peak_total = INITIAL_CAPITAL_MXN
            logger.info(f"Portafolio nuevo: {self.mxn:.2f} MXN")

    def total_mxn(self, price: float) -> float:
        return self.mxn + self.usd * price

    def drawdown(self, price: float) -> float:
        total = self.total_mxn(price)
        return (self._peak_total - total) / self._peak_total if self._peak_total > 0 else 0.0

    def kelly_position_size(self, score: float, price: float) -> float:
        """
        Calcula cuántos MXN invertir en esta operación usando Kelly Criterion.
        score > 0.5 → compra (cuánto más alto, más confianza en la subida)
        """
        p = score          # probabilidad implícita de ganar
        q = 1.0 - p
        b = TAKE_PROFIT_PCT / STOP_LOSS_PCT  # reward / risk ratio

        kelly_full = (p * b - q) / b
        kelly_frac = kelly_full * KELLY_FRACTION

        # Nunca invertir más del máximo permitido
        kelly_frac = max(0.0, min(kelly_frac, MAX_POSITION_PCT))

        mxn_to_invest = self.mxn * kelly_frac
        return mxn_to_invest

    def can_trade(self, price: float) -> tuple[bool, str]:
        """Verifica condiciones de riesgo antes de operar."""
        dd = self.drawdown(price)
        if dd > MAX_DRAWDOWN_PCT:
            return False, f"Drawdown máximo alcanzado: {dd*100:.1f}%"
        if self.total_mxn(price) < MIN_TRADE_MXN:
            return False, "Capital insuficiente para operar"
        return True, "OK"

    def buy_usd(self, score: float, price: float, reason: str,
                regime: str = "NEUTRAL") -> dict | None:
        """Compra dólares con MXN. Posición binaria: no compra si ya tiene USD."""
        if self.usd > 0:
            logger.info("Ya tienes USD, no se abre otra posición")
            return None
        if regime == "BEARISH":
            logger.info("Régimen BEARISH: compra bloqueada")
            return None

        ok, msg = self.can_trade(price)
        if not ok:
            logger.warning(f"Compra bloqueada: {msg}")
            return None

        mxn_to_spend = self.kelly_position_size(score, price)
        if mxn_to_spend < MIN_TRADE_MXN:
            logger.info(f"Monto Kelly demasiado bajo ({mxn_to_spend:.2f} MXN), no se opera")
            return None

        mxn_to_spend = min(mxn_to_spend, self.mxn)

        if not PAPER_TRADING:
            from data.bitso_client import BitsoClient
            client = BitsoClient()
            order = client.buy_usd(mxn_to_spend)
            if not order:
                logger.error("Orden Bitso falló, abortando compra real")
                return None
            # Precio real de ejecución puede diferir; actualizamos con el de mercado
            logger.info(f"[BITSO] Orden ejecutada: {order}")

        usd_received = mxn_to_spend / price
        self.mxn -= mxn_to_spend
        self.usd += usd_received

        total = self.total_mxn(price)
        self._peak_total = max(self._peak_total, total)

        save_trade(DB_PATH, "BUY", usd_received, mxn_to_spend, price, reason, PAPER_TRADING)
        save_portfolio_snapshot(DB_PATH, self.mxn, self.usd, price)

        result = {
            "action":       "BUY",
            "mxn_spent":    mxn_to_spend,
            "usd_received": usd_received,
            "price":        price,
            "mxn_balance":  self.mxn,
            "usd_balance":  self.usd,
            "total_mxn":    total,
        }
        logger.info(f"COMPRA: {mxn_to_spend:.2f} MXN → {usd_received:.4f} USD @ {price:.4f}")
        return result

    def sell_usd(self, score: float, price: float, reason: str) -> dict | None:
        """Vende dólares a MXN."""
        ok, msg = self.can_trade(price)
        if not ok:
            logger.warning(f"Venta bloqueada: {msg}")
            return None

        if self.usd <= 0:
            logger.info("Sin USD para vender")
            return None

        # Vender posición completa: evita cascada de ventas parciales
        usd_to_sell = self.usd

        if not PAPER_TRADING:
            from data.bitso_client import BitsoClient
            client = BitsoClient()
            order = client.sell_usd(usd_to_sell)
            if not order:
                logger.error("Orden Bitso falló, abortando venta real")
                return None
            logger.info(f"[BITSO] Orden ejecutada: {order}")

        mxn_received  = usd_to_sell * price
        self.usd -= usd_to_sell
        self.mxn += mxn_received

        total = self.total_mxn(price)
        self._peak_total = max(self._peak_total, total)

        save_trade(DB_PATH, "SELL", usd_to_sell, mxn_received, price, reason, PAPER_TRADING)
        save_portfolio_snapshot(DB_PATH, self.mxn, self.usd, price)

        result = {
            "action":       "SELL",
            "usd_sold":     usd_to_sell,
            "mxn_received": mxn_received,
            "price":        price,
            "mxn_balance":  self.mxn,
            "usd_balance":  self.usd,
            "total_mxn":    total,
        }
        logger.info(f"VENTA: {usd_to_sell:.4f} USD → {mxn_received:.2f} MXN @ {price:.4f}")
        return result

    def status(self, price: float) -> dict:
        total = self.total_mxn(price)
        return {
            "mxn_balance":   self.mxn,
            "usd_balance":   self.usd,
            "usd_price":     price,
            "total_mxn":     total,
            "pnl_mxn":       total - INITIAL_CAPITAL_MXN,
            "pnl_pct":       (total - INITIAL_CAPITAL_MXN) / INITIAL_CAPITAL_MXN * 100,
            "drawdown_pct":  self.drawdown(price) * 100,
            "paper_trading": PAPER_TRADING,
        }
