"""
Fetcher de precios USD/MXN
Fuente primaria: Yahoo Finance (yfinance)
Fuente de respaldo: Banxico (tipo de cambio oficial)
"""
import yfinance as yf
import pandas as pd
import requests
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


def fetch_current_price() -> float | None:
    """Precio actual USD/MXN (cuántos pesos vale 1 dólar)."""
    try:
        ticker = yf.Ticker("MXN=X")
        data = ticker.history(period="1d", interval="1m")
        if not data.empty:
            return float(data["Close"].iloc[-1])
    except Exception as e:
        logger.warning(f"Yahoo Finance falló para precio actual: {e}")

    # Respaldo: Banxico tipo de cambio FIX
    return _fetch_banxico_fix()


def fetch_historical(days: int = 365) -> pd.DataFrame:
    """
    Histórico diario de USD/MXN.
    Retorna DataFrame con columnas: timestamp, open, high, low, close, volume
    """
    end   = datetime.now()
    start = end - timedelta(days=days)

    try:
        df = yf.download("MXN=X", start=start, end=end, interval="1d", progress=False)
        if df.empty:
            raise ValueError("DataFrame vacío de Yahoo Finance")

        df = df.reset_index()
        df.columns = [c.lower() if isinstance(c, str) else c[0].lower() for c in df.columns]
        df = df.rename(columns={"date": "timestamp"})
        df["timestamp"] = df["timestamp"].astype(str).str[:10]

        for col in ["open", "high", "low", "close", "volume"]:
            if col not in df.columns:
                df[col] = None

        df["close"] = pd.to_numeric(df["close"], errors="coerce")
        df = df.dropna(subset=["close"])
        df = df[["timestamp", "open", "high", "low", "close", "volume"]]

        logger.info(f"Histórico descargado: {len(df)} días")
        return df

    except Exception as e:
        logger.error(f"Error descargando histórico: {e}")
        return pd.DataFrame()


def fetch_intraday(interval: str = "1h", days: int = 7) -> pd.DataFrame:
    """Precios intradiarios para análisis de corto plazo."""
    try:
        df = yf.download("MXN=X", period=f"{days}d", interval=interval, progress=False)
        if df.empty:
            return pd.DataFrame()

        df = df.reset_index()
        df.columns = [c.lower() if isinstance(c, str) else c[0].lower() for c in df.columns]
        df = df.rename(columns={"datetime": "timestamp", "date": "timestamp"})
        df["close"] = pd.to_numeric(df["close"], errors="coerce")
        df = df.dropna(subset=["close"])
        return df

    except Exception as e:
        logger.error(f"Error descargando intradiario: {e}")
        return pd.DataFrame()


def _fetch_banxico_fix() -> float | None:
    """
    Tipo de cambio FIX del Banco de México.
    Documentación: https://www.banxico.org.mx/SieAPIRest/service/v1/
    Requiere token gratuito de Banxico (variable BANXICO_TOKEN).
    """
    import os
    token = os.getenv("BANXICO_TOKEN", "")
    if not token:
        logger.warning("BANXICO_TOKEN no configurado, saltando respaldo Banxico")
        return None

    try:
        url = f"https://www.banxico.org.mx/SieAPIRest/service/v1/series/SF43718/datos/oportuno"
        headers = {"Bmx-Token": token}
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        valor = data["bmx"]["series"][0]["datos"][0]["dato"]
        return float(valor)
    except Exception as e:
        logger.error(f"Banxico FIX falló: {e}")
        return None


def get_macro_context() -> dict:
    """
    Contexto macroeconómico para la señal fundamental.
    Por ahora calcula la tendencia de 30 días del USD/MXN.
    """
    df = fetch_historical(days=90)
    if df.empty or len(df) < 30:
        return {"trend_30d": 0.0, "volatility_30d": 0.0}

    closes = pd.to_numeric(df["close"], errors="coerce").dropna()
    pct_30d = (closes.iloc[-1] - closes.iloc[-30]) / closes.iloc[-30]
    vol_30d = closes.pct_change().tail(30).std()

    return {
        "trend_30d":     float(pct_30d),       # positivo = dólar se ha apreciado
        "volatility_30d": float(vol_30d),
        "price_now":     float(closes.iloc[-1]),
        "price_30d_ago": float(closes.iloc[-30]),
    }
