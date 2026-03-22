"""
Métricas de performance del backtest

Referencias académicas:
  - Sharpe Ratio:    Sharpe, W.F. (1966). "Mutual Fund Performance". Journal of Business.
  - Sortino Ratio:   Sortino & van der Meer (1991). "Downside Risk". Journal of Portfolio Mgmt.
  - Max Drawdown:    Magdon-Ismail & Atiya (2004). "Maximum Drawdown". Risk Magazine.
  - Calmar Ratio:    Young (1991). "Calmar Ratio: A Smoother Tool". Futures Magazine.
  - Profit Factor:   Ratio ganancia bruta / pérdida bruta (estándar industria).
"""
import pandas as pd
import numpy as np
from backtest.engine import BacktestResult
from config import INITIAL_CAPITAL_MXN


def compute_metrics(result: BacktestResult, initial_capital: float = INITIAL_CAPITAL_MXN) -> dict:
    eq   = result.equity_curve
    trades = result.trades

    if eq.empty:
        return {}

    # ── Retornos ─────────────────────────────────────────────────────────────
    final_value   = float(eq.iloc[-1])
    total_return  = (final_value - initial_capital) / initial_capital
    n_days        = len(eq)
    annual_return = (1 + total_return) ** (252 / n_days) - 1

    daily_returns = eq.pct_change().dropna()

    # ── Sharpe Ratio (asumiendo rf = 0, par de divisas) ──────────────────────
    sharpe = (daily_returns.mean() / daily_returns.std() * np.sqrt(252)
              if daily_returns.std() > 0 else 0.0)

    # ── Sortino Ratio (solo penaliza retornos negativos) ─────────────────────
    downside = daily_returns[daily_returns < 0].std()
    sortino  = (daily_returns.mean() / downside * np.sqrt(252)
                if downside > 0 else 0.0)

    # ── Maximum Drawdown ─────────────────────────────────────────────────────
    rolling_max = eq.cummax()
    drawdowns   = (eq - rolling_max) / rolling_max
    max_dd      = float(drawdowns.min())

    # ── Calmar Ratio ─────────────────────────────────────────────────────────
    calmar = annual_return / abs(max_dd) if max_dd != 0 else 0.0

    # ── Métricas de trades ───────────────────────────────────────────────────
    buy_trades  = [t for t in trades if t["action"] == "BUY"]
    sell_trades = [t for t in trades if t["action"].startswith("SELL")]

    # Emparejar compras con ventas para calcular P&L por operación
    pnl_per_trade = _compute_pnl_per_trade(trades)

    wins   = [p for p in pnl_per_trade if p > 0]
    losses = [p for p in pnl_per_trade if p <= 0]

    win_rate     = len(wins) / len(pnl_per_trade) if pnl_per_trade else 0.0
    avg_win      = np.mean(wins)   if wins   else 0.0
    avg_loss     = np.mean(losses) if losses else 0.0
    profit_factor= (sum(wins) / abs(sum(losses))
                    if losses and sum(losses) != 0 else float("inf"))

    # ── Expectancy (Van Tharp) ────────────────────────────────────────────────
    expectancy = win_rate * avg_win + (1 - win_rate) * avg_loss

    return {
        # Rendimiento
        "initial_capital_mxn": initial_capital,
        "final_value_mxn":     final_value,
        "total_return_pct":    total_return * 100,
        "annual_return_pct":   annual_return * 100,
        "n_days":              n_days,

        # Riesgo
        "sharpe_ratio":        sharpe,
        "sortino_ratio":       sortino,
        "max_drawdown_pct":    max_dd * 100,
        "calmar_ratio":        calmar,
        "volatility_annual":   float(daily_returns.std() * np.sqrt(252) * 100),

        # Trades
        "total_trades":        len(pnl_per_trade),
        "total_buys":          len(buy_trades),
        "total_sells":         len(sell_trades),
        "win_rate_pct":        win_rate * 100,
        "avg_win_mxn":         avg_win,
        "avg_loss_mxn":        avg_loss,
        "profit_factor":       profit_factor,
        "expectancy_mxn":      expectancy,
    }


def _compute_pnl_per_trade(trades: list) -> list[float]:
    """
    Empareja cada compra con su venta correspondiente (FIFO)
    y calcula el P&L en MXN.
    """
    pnl_list = []
    buy_queue = []  # (usd_amount, mxn_spent)

    for t in sorted(trades, key=lambda x: x["date"]):
        if t["action"] == "BUY":
            buy_queue.append((t["usd"], t["mxn"]))

        elif t["action"].startswith("SELL") and buy_queue:
            usd_to_match = t["usd"]
            mxn_received = t["mxn"]

            # Calcular cuánto costaron esos USD (FIFO)
            cost = 0.0
            remaining = usd_to_match
            while buy_queue and remaining > 1e-8:
                b_usd, b_mxn = buy_queue[0]
                if b_usd <= remaining:
                    cost      += b_mxn
                    remaining -= b_usd
                    buy_queue.pop(0)
                else:
                    frac  = remaining / b_usd
                    cost += b_mxn * frac
                    buy_queue[0] = (b_usd - remaining, b_mxn * (1 - frac))
                    remaining = 0

            pnl_list.append(mxn_received - cost)

    return pnl_list


def format_metrics_report(metrics: dict) -> str:
    """Formatea las métricas como texto legible para Telegram y consola."""
    ret_icon = "🟢" if metrics["total_return_pct"] > 0 else "🔴"
    sh_icon  = "✅" if metrics["sharpe_ratio"] > 1 else ("⚠️" if metrics["sharpe_ratio"] > 0 else "❌")

    return f"""
📊 *BACKTEST USD/MXN — Resultados*
{'─'*32}
💰 Capital inicial:   {metrics['initial_capital_mxn']:.2f} MXN
{ret_icon} Capital final:     {metrics['final_value_mxn']:.2f} MXN
{ret_icon} Retorno total:     {metrics['total_return_pct']:+.2f}%
📈 Retorno anual:     {metrics['annual_return_pct']:+.2f}%
📅 Período:           {metrics['n_days']} días

*Riesgo:*
{sh_icon} Sharpe Ratio:      {metrics['sharpe_ratio']:.3f}
   Sortino Ratio:     {metrics['sortino_ratio']:.3f}
   Calmar Ratio:      {metrics['calmar_ratio']:.3f}
📉 Max Drawdown:      {metrics['max_drawdown_pct']:.2f}%
   Volatilidad anual: {metrics['volatility_annual']:.2f}%

*Operaciones ({metrics['total_trades']} completas):*
   Win Rate:          {metrics['win_rate_pct']:.1f}%
   Profit Factor:     {metrics['profit_factor']:.2f}
   Ganancia media:    +{metrics['avg_win_mxn']:.2f} MXN
   Pérdida media:     {metrics['avg_loss_mxn']:.2f} MXN
   Expectancy:        {metrics['expectancy_mxn']:+.2f} MXN/op
{'─'*32}
*Interpretación:*
  Sharpe > 1 → estrategia buena
  Profit Factor > 1.5 → rentable
  Win Rate > 50% → más aciertos que fallos
""".strip()
