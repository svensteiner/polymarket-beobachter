"""NotifyTool — Benachrichtigungen via Telegram oder Slack.

Aktivierung in .env:
    TELEGRAM_BOT_TOKEN=...
    TELEGRAM_CHAT_ID=...
    SLACK_WEBHOOK_URL=...

Verwendung (automatisch via Brain oder direkt):
    tool = NotifyTool()
    tool.run("Deployment abgeschlossen ✅")

Input-Format:
    "Nachricht"                     → sendet an alle konfigurierten Kanäle
    "telegram:Nachricht"            → nur Telegram
    "slack:Nachricht"               → nur Slack
"""

import logging

from tools.base_tool import BaseTool
from tools.slack import send as slack_send
from tools.telegram import send as telegram_send

logger = logging.getLogger("notify")


class NotifyTool(BaseTool):
    name = "notify"
    description = "Sendet eine Benachrichtigung via Telegram oder Slack. Input: Nachrichtentext."

    def run(self, input: str) -> str:
        channel = "all"
        message = input.strip()

        if ":" in input and input.split(":", 1)[0].lower() in ("telegram", "slack"):
            channel, message = input.split(":", 1)
            channel = channel.lower().strip()
            message = message.strip()

        results = []

        if channel in ("all", "telegram"):
            ok = telegram_send(message)
            results.append(f"Telegram: {'✅ gesendet' if ok else '❌ nicht konfiguriert oder Fehler'}")

        if channel in ("all", "slack"):
            ok = slack_send(message)
            results.append(f"Slack: {'✅ gesendet' if ok else '❌ nicht konfiguriert oder Fehler'}")

        if not results:
            return "FEHLER: Kein Kanal konfiguriert"

        return " | ".join(results)
