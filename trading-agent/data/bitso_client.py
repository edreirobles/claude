"""
Cliente para la API de Bitso - Operaciones reales de USD/MXN

Documentación oficial: https://developers.bitso.com/bitso-api/docs
Par: mxn_usd (en Bitso el par es mxn_usd, base=MXN, quote=USD)

Autenticación: HMAC-SHA256
  signature = HMAC-SHA256(nonce + http_method + request_path + json_payload)
"""
import hashlib
import hmac
import json
import time
import requests
import logging
from config import BITSO_API_KEY, BITSO_API_SECRET

logger = logging.getLogger(__name__)

BASE_URL = "https://api.bitso.com/v3"
BOOK    = "mxn_usd"   # En Bitso: major=MXN, minor=USD → comprar USD = vender MXN


class BitsoClient:
    def __init__(self):
        self.key    = BITSO_API_KEY
        self.secret = BITSO_API_SECRET

    def _sign(self, method: str, path: str, payload: str = "") -> dict:
        nonce     = str(int(time.time() * 1000))
        message   = nonce + method.upper() + path + payload
        signature = hmac.new(
            self.secret.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return {
            "Authorization": f"Bitso {self.key}:{nonce}:{signature}",
            "Content-Type":  "application/json",
        }

    def _get(self, path: str) -> dict:
        headers = self._sign("GET", path)
        resp    = requests.get(BASE_URL + path, headers=headers, timeout=10)
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, payload: dict) -> dict:
        body    = json.dumps(payload)
        headers = self._sign("POST", path, body)
        resp    = requests.post(BASE_URL + path, headers=headers, data=body, timeout=10)
        resp.raise_for_status()
        return resp.json()

    def _delete(self, path: str) -> dict:
        headers = self._sign("DELETE", path)
        resp    = requests.delete(BASE_URL + path, headers=headers, timeout=10)
        resp.raise_for_status()
        return resp.json()

    # ── Mercado ───────────────────────────────────────────────────────────────

    def get_ticker(self) -> dict:
        """Precio actual del par mxn_usd."""
        resp = requests.get(f"{BASE_URL}/ticker?book={BOOK}", timeout=10)
        resp.raise_for_status()
        data = resp.json()["payload"]
        return {
            "last":  float(data["last"]),   # último precio
            "bid":   float(data["bid"]),    # mejor compra (tú vendes acá)
            "ask":   float(data["ask"]),    # mejor venta  (tú compras acá)
            "high":  float(data["high"]),
            "low":   float(data["low"]),
            "volume":float(data["volume"]),
        }

    def get_order_book(self) -> dict:
        resp = requests.get(f"{BASE_URL}/order_book?book={BOOK}", timeout=10)
        resp.raise_for_status()
        return resp.json()["payload"]

    # ── Cuenta ───────────────────────────────────────────────────────────────

    def get_balances(self) -> dict:
        """Balances de MXN y USD en Bitso."""
        data = self._get("/balance/")["payload"]["balances"]
        result = {}
        for b in data:
            if b["currency"] in ("mxn", "usd"):
                result[b["currency"]] = {
                    "available": float(b["available"]),
                    "locked":    float(b["locked"]),
                    "total":     float(b["total"]),
                }
        return result

    # ── Órdenes ──────────────────────────────────────────────────────────────

    def buy_usd(self, mxn_amount: float) -> dict | None:
        """
        Compra USD gastando mxn_amount MXN.
        Usa orden de mercado (market order) para ejecución inmediata.

        En Bitso, para comprar USD (minor) con MXN (major):
          side = "buy", type = "market", minor = mxn_amount
        """
        logger.info(f"[BITSO] Orden de COMPRA: {mxn_amount:.2f} MXN")
        try:
            payload = {
                "book":  BOOK,
                "side":  "buy",
                "type":  "market",
                "minor": f"{mxn_amount:.2f}",  # MXN a gastar
            }
            resp = self._post("/orders/", payload)
            order_id = resp["payload"]["oid"]
            logger.info(f"[BITSO] Orden creada: {order_id}")
            return resp["payload"]
        except Exception as e:
            logger.error(f"[BITSO] Error en compra: {e}")
            return None

    def sell_usd(self, usd_amount: float) -> dict | None:
        """
        Vende usd_amount USD a MXN.
        Orden de mercado.

        En Bitso, para vender USD:
          side = "sell", type = "market", major = usd_amount
        """
        logger.info(f"[BITSO] Orden de VENTA: {usd_amount:.4f} USD")
        try:
            payload = {
                "book":  BOOK,
                "side":  "sell",
                "type":  "market",
                "major": f"{usd_amount:.4f}",  # USD a vender
            }
            resp = self._post("/orders/", payload)
            order_id = resp["payload"]["oid"]
            logger.info(f"[BITSO] Orden creada: {order_id}")
            return resp["payload"]
        except Exception as e:
            logger.error(f"[BITSO] Error en venta: {e}")
            return None

    def get_order_status(self, order_id: str) -> dict:
        return self._get(f"/orders/{order_id}/")["payload"]

    def cancel_order(self, order_id: str) -> bool:
        try:
            self._delete(f"/orders/{order_id}/")
            return True
        except Exception as e:
            logger.error(f"[BITSO] Error cancelando orden {order_id}: {e}")
            return False

    def get_trades(self, limit: int = 10) -> list:
        """Últimas operaciones del usuario."""
        data = self._get(f"/user_trades/?book={BOOK}&limit={limit}")
        return data.get("payload", [])

    # ── Validaciones ─────────────────────────────────────────────────────────

    def validate_credentials(self) -> bool:
        """Verifica que las credenciales sean válidas."""
        try:
            self.get_balances()
            logger.info("[BITSO] Credenciales válidas")
            return True
        except Exception as e:
            logger.error(f"[BITSO] Credenciales inválidas: {e}")
            return False

    def get_min_amounts(self) -> dict:
        """Montos mínimos de operación para mxn_usd."""
        resp = requests.get(f"{BASE_URL}/available_books/", timeout=10)
        resp.raise_for_status()
        books = resp.json()["payload"]
        book_info = next((b for b in books if b["book"] == BOOK), None)
        if book_info:
            return {
                "min_amount": float(book_info.get("minimum_amount", 0)),
                "min_price":  float(book_info.get("minimum_price", 0)),
                "min_value":  float(book_info.get("minimum_value", 0)),
            }
        return {}
