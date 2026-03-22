"""
Script para ejecutar el backtest completo.

Uso:
  python backtest/run.py              # últimos 365 días
  python backtest/run.py --days 730   # últimos 2 años
  python backtest/run.py --chart      # genera gráfica equity_curve.png
"""
import sys
import os
import argparse
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from data.fetcher import fetch_historical
from backtest.engine import run_backtest
from backtest.metrics import compute_metrics, format_metrics_report
from config import INITIAL_CAPITAL_MXN

logging.basicConfig(level=logging.WARNING)


def main():
    parser = argparse.ArgumentParser(description="Backtest USD/MXN Trading Agent")
    parser.add_argument("--days",    type=int,  default=365, help="Días de histórico (default: 365)")
    parser.add_argument("--capital", type=float, default=INITIAL_CAPITAL_MXN, help="Capital inicial MXN")
    parser.add_argument("--chart",   action="store_true", help="Genera gráfica PNG")
    parser.add_argument("--csv",     action="store_true", help="Exporta trades a CSV")
    args = parser.parse_args()

    print(f"\n🔄 Descargando {args.days} días de datos USD/MXN...")
    df = fetch_historical(days=args.days)

    if df.empty:
        print("❌ No se pudieron obtener datos históricos.")
        print("   Verifica tu conexión a internet e intenta de nuevo.")
        sys.exit(1)

    print(f"✅ {len(df)} días descargados ({df['timestamp'].iloc[0]} → {df['timestamp'].iloc[-1]})")
    print(f"   Precio inicial: {df['close'].iloc[0]:.4f} | Precio final: {df['close'].iloc[-1]:.4f}")
    print(f"\n⚙️  Ejecutando backtest con capital inicial: {args.capital:.2f} MXN...")

    result = run_backtest(df, initial_capital=args.capital)
    metrics = compute_metrics(result, initial_capital=args.capital)

    # Reporte en consola
    report = format_metrics_report(metrics)
    # Limpiar markdown para consola
    clean = report.replace("*", "").replace("`", "")
    print("\n" + clean)

    # Últimas 5 operaciones
    if result.trades:
        print("\n📋 Últimas 5 operaciones:")
        print(f"  {'Fecha':<12} {'Acción':<10} {'USD':>8} {'MXN':>10} {'Precio':>8}")
        print("  " + "─" * 52)
        for t in result.trades[-5:]:
            print(f"  {t['date']:<12} {t['action']:<10} {t['usd']:>8.4f} {t['mxn']:>10.2f} {t['price']:>8.4f}")

    # Buy & Hold para comparar
    if not df.empty:
        p0 = float(df["close"].iloc[0])
        p1 = float(df["close"].iloc[-1])
        usd_bh  = args.capital / p0
        val_bh  = usd_bh * p1
        ret_bh  = (val_bh - args.capital) / args.capital * 100
        agent_ret = metrics.get("total_return_pct", 0)
        icon = "🏆" if agent_ret > ret_bh else "📉"
        print(f"\n{icon} Comparación Buy & Hold:")
        print(f"   Agente:    {agent_ret:+.2f}%")
        print(f"   Buy&Hold:  {ret_bh:+.2f}%")
        print(f"   Alpha:     {agent_ret - ret_bh:+.2f}%")

    # Exportar CSV
    if args.csv:
        trades_df = pd.DataFrame(result.trades)
        path = "backtest/trades.csv"
        trades_df.to_csv(path, index=False)
        print(f"\n📄 Trades exportados: {path}")

    # Gráfica
    if args.chart:
        _plot_equity(result, df, args.capital)

    return metrics


def _plot_equity(result, df_prices, initial_capital: float):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates

        eq = result.equity_curve
        dates = pd.to_datetime(eq.index)

        # Buy & Hold
        p0 = float(df_prices["close"].iloc[0])
        bh_values = df_prices.set_index("timestamp")["close"].astype(float)
        bh_values = (initial_capital / p0) * bh_values
        bh_dates  = pd.to_datetime(bh_values.index)

        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), sharex=False)
        fig.suptitle("Backtest Trading Agent USD/MXN", fontsize=14, fontweight="bold")

        # Equity curve
        ax1.plot(dates, eq.values, label="Agente", color="#2196F3", linewidth=2)
        ax1.plot(bh_dates, bh_values.values, label="Buy & Hold", color="#FF9800",
                 linewidth=1.5, linestyle="--", alpha=0.8)
        ax1.axhline(y=initial_capital, color="gray", linestyle=":", alpha=0.5)
        ax1.set_ylabel("Valor (MXN)")
        ax1.legend()
        ax1.grid(True, alpha=0.3)

        # Marcar trades
        for t in result.trades:
            td = pd.to_datetime(t["date"])
            if t["action"] == "BUY":
                ax1.axvline(x=td, color="green", alpha=0.2, linewidth=1)
            elif t["action"].startswith("SELL"):
                ax1.axvline(x=td, color="red", alpha=0.2, linewidth=1)

        # Precio USD/MXN
        all_dates = pd.to_datetime(df_prices["timestamp"])
        ax2.plot(all_dates, df_prices["close"].astype(float),
                 color="#9C27B0", linewidth=1.5)
        ax2.set_ylabel("USD/MXN")
        ax2.set_xlabel("Fecha")
        ax2.grid(True, alpha=0.3)

        plt.tight_layout()
        path = "backtest/equity_curve.png"
        plt.savefig(path, dpi=150, bbox_inches="tight")
        plt.close()
        print(f"\n📊 Gráfica guardada: {path}")

    except ImportError:
        print("\n⚠️  matplotlib no instalado. Corre: pip install matplotlib")


if __name__ == "__main__":
    main()
