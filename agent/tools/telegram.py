"""Telegram — Benachrichtigungen senden.

Konfiguration (.env):
    TELEGRAM_BOT_TOKEN=123456:ABC-...
    TELEGRAM_CHAT_ID=-1001234567890

Direktnutzung:
    from tools.telegram import send
    send("Pipeline abgeschlossen: 3 Trades, +12.50 EUR")
"""

import json
import logging
import os
from urllib import request, error

logger = logging.getLogger("telegram")


def send(message: str, parse_mode: str = "HTML") -> bool:
    """Sendet eine Nachricht via Telegram Bot. Gibt True bei Erfolg zurück."""
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        logger.warning("Telegram nicht konfiguriert (TELEGRAM_BOT_TOKEN oder TELEGRAM_CHAT_ID fehlt)")
        return False

    payload = json.dumps({
        "chat_id": chat_id,
        "text": message,
        "parse_mode": parse_mode,
    }).encode("utf-8")

    try:
        req = request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except error.HTTPError as e:
        logger.error(f"Telegram HTTP-Fehler: {e.code} {e.reason}")
        return False
    except Exception as e:
        logger.error(f"Telegram-Fehler: {e}")
        return False
