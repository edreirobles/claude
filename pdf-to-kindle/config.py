"""Persistent local config stored in config.json (never committed)."""

import json
from pathlib import Path
from typing import Any

CONFIG_PATH = Path(__file__).parent / "config.json"

DEFAULTS: dict[str, Any] = {
    "kindle_email": "",
    "sender_email": "",
    "sender_password": "",
    "smtp_preset": "Gmail",
    "smtp_host": "smtp.gmail.com",
    "smtp_port": 587,
}


def load() -> dict[str, Any]:
    if CONFIG_PATH.exists():
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            return {**DEFAULTS, **data}
        except Exception:
            pass
    return dict(DEFAULTS)


def save(cfg: dict[str, Any]) -> None:
    CONFIG_PATH.write_text(
        json.dumps(cfg, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def is_configured(cfg: dict[str, Any]) -> bool:
    return bool(
        cfg.get("kindle_email")
        and cfg.get("sender_email")
        and cfg.get("sender_password")
        and cfg.get("smtp_host")
    )
