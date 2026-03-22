"""
SQLite storage: portfolio, trades, price history, signals
"""
import sqlite3
import json
from datetime import datetime
from pathlib import Path


def get_connection(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: str):
    conn = get_connection(db_path)
    c = conn.cursor()

    c.executescript("""
        CREATE TABLE IF NOT EXISTS portfolio (
            id          INTEGER PRIMARY KEY,
            timestamp   TEXT NOT NULL,
            mxn_balance REAL NOT NULL,
            usd_balance REAL NOT NULL,
            usd_price   REAL NOT NULL,
            total_mxn   REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS trades (
            id          INTEGER PRIMARY KEY,
            timestamp   TEXT NOT NULL,
            action      TEXT NOT NULL,  -- BUY | SELL
            usd_amount  REAL NOT NULL,
            mxn_amount  REAL NOT NULL,
            price       REAL NOT NULL,
            reason      TEXT,
            paper       INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS prices (
            id          INTEGER PRIMARY KEY,
            timestamp   TEXT NOT NULL,
            open        REAL,
            high        REAL,
            low         REAL,
            close       REAL NOT NULL,
            volume      REAL,
            UNIQUE(timestamp)
        );

        CREATE TABLE IF NOT EXISTS signals (
            id              INTEGER PRIMARY KEY,
            timestamp       TEXT NOT NULL,
            rsi             REAL,
            macd            REAL,
            macd_signal     REAL,
            bb_upper        REAL,
            bb_lower        REAL,
            bb_mid          REAL,
            mean_rev_score  REAL,
            final_score     REAL,
            decision        TEXT,
            signals_json    TEXT
        );
    """)

    conn.commit()
    conn.close()


def save_portfolio_snapshot(db_path: str, mxn: float, usd: float, price: float):
    total = mxn + usd * price
    conn = get_connection(db_path)
    conn.execute(
        "INSERT INTO portfolio (timestamp, mxn_balance, usd_balance, usd_price, total_mxn) VALUES (?,?,?,?,?)",
        (datetime.utcnow().isoformat(), mxn, usd, price, total)
    )
    conn.commit()
    conn.close()
    return total


def save_trade(db_path: str, action: str, usd_amount: float, mxn_amount: float,
               price: float, reason: str, paper: bool = True):
    conn = get_connection(db_path)
    conn.execute(
        "INSERT INTO trades (timestamp, action, usd_amount, mxn_amount, price, reason, paper) VALUES (?,?,?,?,?,?,?)",
        (datetime.utcnow().isoformat(), action, usd_amount, mxn_amount, price, reason, int(paper))
    )
    conn.commit()
    conn.close()


def save_prices(db_path: str, rows: list[dict]):
    conn = get_connection(db_path)
    conn.executemany(
        "INSERT OR IGNORE INTO prices (timestamp, open, high, low, close, volume) VALUES (?,?,?,?,?,?)",
        [(r["timestamp"], r["open"], r["high"], r["low"], r["close"], r["volume"]) for r in rows]
    )
    conn.commit()
    conn.close()


def save_signal(db_path: str, signals: dict, final_score: float, decision: str):
    conn = get_connection(db_path)
    conn.execute("""
        INSERT INTO signals
            (timestamp, rsi, macd, macd_signal, bb_upper, bb_lower, bb_mid,
             mean_rev_score, final_score, decision, signals_json)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
    """, (
        datetime.utcnow().isoformat(),
        signals.get("rsi_value"),
        signals.get("macd_value"),
        signals.get("macd_signal_value"),
        signals.get("bb_upper"),
        signals.get("bb_lower"),
        signals.get("bb_mid"),
        signals.get("mean_rev_score"),
        final_score,
        decision,
        json.dumps(signals)
    ))
    conn.commit()
    conn.close()


def get_last_portfolio(db_path: str) -> dict | None:
    conn = get_connection(db_path)
    row = conn.execute(
        "SELECT * FROM portfolio ORDER BY id DESC LIMIT 1"
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_trade_history(db_path: str, limit: int = 20) -> list[dict]:
    conn = get_connection(db_path)
    rows = conn.execute(
        "SELECT * FROM trades ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_price_history(db_path: str, days: int = 60) -> list[dict]:
    conn = get_connection(db_path)
    rows = conn.execute(
        "SELECT * FROM prices ORDER BY timestamp DESC LIMIT ?", (days,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in reversed(rows)]
