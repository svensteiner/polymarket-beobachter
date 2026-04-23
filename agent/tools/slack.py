"""Slack — Benachrichtigungen via Incoming Webhook senden.

Konfiguration (.env):
    SLACK_WEBHOOK_URL=https://hooks.slack.com/services/T.../B.../...

Direktnutzung:
    from tools.slack import send
    send("Deployment erfolgreich abgeschlossen.")
"""

import json
import logging
import os
from urllib import request, error

logger = logging.getLogger("slack")


def send(message: str, username: str = None, icon_emoji: str = ":robot_face:") -> bool:
    """Sendet eine Nachricht via Slack Webhook. Gibt True bei Erfolg zurück."""
    webhook_url = os.getenv("SLACK_WEBHOOK_URL", "")
    if not webhook_url:
        logger.warning("Slack nicht konfiguriert (SLACK_WEBHOOK_URL fehlt)")
        return False

    payload: dict = {"text": message, "icon_emoji": icon_emoji}
    if username:
        payload["username"] = username

    data = json.dumps(payload).encode("utf-8")

    try:
        req = request.Request(
            webhook_url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except error.HTTPError as e:
        logger.error(f"Slack HTTP-Fehler: {e.code} {e.reason}")
        return False
    except Exception as e:
        logger.error(f"Slack-Fehler: {e}")
        return False
