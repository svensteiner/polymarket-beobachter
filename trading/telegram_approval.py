# =============================================================================
# TELEGRAM TRADE APPROVAL
# =============================================================================
#
# Human-in-the-Loop: Jeder Live-Trade muss via Telegram bestaetigt werden.
#
# Flow:
# 1. Bot findet Trade-Gelegenheit
# 2. Sendet Telegram mit Details + Inline-Buttons
# 3. Wartet auf Antwort (max 5 Minuten)
# 4. Fuehrt nur bei APPROVE aus
#
# =============================================================================

import os
import json
import time
import logging
import requests
from typing import Dict, Any, Optional, Tuple
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.parent


class TelegramApproval:
    """
    Trade-Bestaetigung via Telegram.

    Sendet Inline-Keyboard mit APPROVE/REJECT Buttons.
    Wartet auf Callback und fuehrt Trade nur bei Bestaetigung aus.
    """

    APPROVAL_TIMEOUT = 300  # 5 Minuten
    POLL_INTERVAL = 5       # 5 Sekunden

    def __init__(self):
        self.token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID")
        self.api_url = f"https://api.telegram.org/bot{self.token}"

        # Pending approvals storage
        self.pending_file = BASE_DIR / "data" / "pending_approvals.json"
        self.pending_file.parent.mkdir(parents=True, exist_ok=True)

        # Track last update_id to avoid duplicate processing
        self.last_update_id = self._load_last_update_id()

    def _load_last_update_id(self) -> int:
        """Load last processed update ID."""
        state_file = BASE_DIR / "data" / "telegram_state.json"
        if state_file.exists():
            try:
                data = json.loads(state_file.read_text())
                return data.get("last_update_id", 0)
            except:
                pass
        return 0

    def _save_last_update_id(self, update_id: int):
        """Save last processed update ID."""
        state_file = BASE_DIR / "data" / "telegram_state.json"
        state_file.write_text(json.dumps({"last_update_id": update_id}))

    def request_approval(
        self,
        proposal: Dict[str, Any],
        trade_id: str,
    ) -> Tuple[bool, str]:
        """
        Sende Trade-Anfrage und warte auf Bestaetigung.

        Args:
            proposal: Trade-Proposal mit allen Details
            trade_id: Eindeutige Trade-ID

        Returns:
            (approved, reason) - True wenn bestaetigt
        """
        if not self.token or not self.chat_id:
            logger.warning("Telegram nicht konfiguriert - ueberspringe Approval")
            return False, "Telegram nicht konfiguriert"

        # Format trade details
        market = proposal.get("market_question", "Unbekannt")[:50]
        direction = proposal.get("direction", "BUY_YES")
        edge = proposal.get("edge", 0)
        model_prob = proposal.get("model_probability", 0)
        market_prob = proposal.get("market_probability", 0)
        position_size = proposal.get("position_size_eur", 0)

        # Edge reason from forecast
        reason = proposal.get("edge_reason", "")
        forecast_summary = proposal.get("forecast_summary", "")
        confidence = proposal.get("confidence", "MEDIUM")
        city = proposal.get("city", "")
        threshold = proposal.get("threshold", "")

        # Build reason text
        reason_text = ""
        if forecast_summary:
            reason_text = f"\n🌡️ *Forecast:* {forecast_summary}"
        if reason:
            reason_text += f"\n💡 *Grund:* {reason}"
        if not reason_text:
            # Generate automatic reason
            if model_prob > market_prob:
                reason_text = f"\n💡 *Grund:* Wetter-Modell erwartet hoehere Wahrscheinlichkeit als Markt"
            else:
                reason_text = f"\n💡 *Grund:* Wetter-Modell erwartet niedrigere Wahrscheinlichkeit als Markt"

        message = f"""🔔 TRADE-ANFRAGE

📊 Markt: {market}...
🏙️ Stadt: {city if city else 'N/A'}
📈 Richtung: {direction}
💰 Betrag: {position_size:.2f} EUR

📉 Markt-Preis: {market_prob:.1%}
🎯 Modell-Preis: {model_prob:.1%}
✨ Edge: {edge:.1%}
🎚️ Konfidenz: {confidence}
{reason_text}

⏰ Timeout: 5 Minuten
🆔 ID: {trade_id[:8]}

Klicke APPROVE oder REJECT unten!"""

        # Send message with inline keyboard
        keyboard = {
            "inline_keyboard": [
                [
                    {"text": "✅ APPROVE", "callback_data": f"approve_{trade_id[:8]}"},
                    {"text": "❌ REJECT", "callback_data": f"reject_{trade_id[:8]}"}
                ]
            ]
        }

        try:
            resp = requests.post(
                f"{self.api_url}/sendMessage",
                json={
                    "chat_id": self.chat_id,
                    "text": message,
                    "reply_markup": keyboard,
                },
                timeout=10,
            )

            if not resp.ok:
                logger.error(f"Telegram send failed: {resp.text}")
                return False, "Telegram Fehler"

            msg_data = resp.json()
            message_id = msg_data.get("result", {}).get("message_id")

            logger.info(f"Trade-Anfrage gesendet: {trade_id[:8]}")

        except Exception as e:
            logger.error(f"Telegram error: {e}")
            return False, f"Telegram Fehler: {e}"

        # Wait for response
        start_time = time.time()
        short_id = trade_id[:8]

        while time.time() - start_time < self.APPROVAL_TIMEOUT:
            decision = self._check_for_decision(short_id)

            if decision == "approve":
                self._send_confirmation(f"✅ Trade {short_id} APPROVED - wird ausgefuehrt!")
                return True, "Bestaetigt via Telegram"

            elif decision == "reject":
                self._send_confirmation(f"❌ Trade {short_id} REJECTED - abgebrochen.")
                return False, "Abgelehnt via Telegram"

            time.sleep(self.POLL_INTERVAL)

        # Timeout
        self._send_confirmation(f"⏰ Trade {short_id} TIMEOUT - keine Antwort nach 5 Min.")
        return False, "Timeout - keine Antwort"

    def _check_for_decision(self, short_id: str) -> Optional[str]:
        """
        Pruefe Telegram Updates auf Entscheidung.

        Returns:
            "approve", "reject", or None
        """
        try:
            resp = requests.get(
                f"{self.api_url}/getUpdates",
                params={
                    "offset": self.last_update_id + 1,
                    "timeout": 1,
                },
                timeout=10,
            )

            if not resp.ok:
                return None

            updates = resp.json().get("result", [])

            for update in updates:
                update_id = update.get("update_id", 0)
                self.last_update_id = max(self.last_update_id, update_id)
                self._save_last_update_id(self.last_update_id)

                # Check callback query (button press)
                callback = update.get("callback_query", {})
                if callback:
                    data = callback.get("data", "")

                    # Answer callback to remove loading state
                    callback_id = callback.get("id")
                    if callback_id:
                        requests.post(
                            f"{self.api_url}/answerCallbackQuery",
                            json={"callback_query_id": callback_id},
                            timeout=5,
                        )

                    if data == f"approve_{short_id}":
                        return "approve"
                    elif data == f"reject_{short_id}":
                        return "reject"

                # Check text message (command)
                message = update.get("message", {})
                text = message.get("text", "")

                if text == f"/approve_{short_id}":
                    return "approve"
                elif text == f"/reject_{short_id}":
                    return "reject"

            return None

        except Exception as e:
            logger.error(f"Error checking updates: {e}")
            return None

    def _send_confirmation(self, message: str):
        """Sende Bestaetigungs-Nachricht."""
        try:
            requests.post(
                f"{self.api_url}/sendMessage",
                json={"chat_id": self.chat_id, "text": message},
                timeout=10,
            )
        except:
            pass


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

_approval_system: Optional[TelegramApproval] = None


def get_approval_system() -> TelegramApproval:
    """Get global approval system instance."""
    global _approval_system
    if _approval_system is None:
        _approval_system = TelegramApproval()
    return _approval_system


def request_trade_approval(
    proposal: Dict[str, Any],
    trade_id: str,
) -> Tuple[bool, str]:
    """
    Frage via Telegram ob Trade ausgefuehrt werden soll.

    Args:
        proposal: Trade-Details
        trade_id: Eindeutige ID

    Returns:
        (approved, reason)
    """
    return get_approval_system().request_approval(proposal, trade_id)


def quick_approval_test():
    """Test the approval system."""
    test_proposal = {
        "market_question": "Will temperature in Berlin exceed 20C tomorrow?",
        "direction": "BUY_YES",
        "edge": 0.15,
        "model_probability": 0.65,
        "market_probability": 0.50,
        "position_size_eur": 25.0,
    }

    import uuid
    trade_id = str(uuid.uuid4())

    print(f"Sending test approval request... (ID: {trade_id[:8]})")
    approved, reason = request_trade_approval(test_proposal, trade_id)
    print(f"Result: approved={approved}, reason={reason}")


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(BASE_DIR))

    # Load env
    env_file = BASE_DIR / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                key, val = line.split("=", 1)
                os.environ.setdefault(key.strip(), val.strip())

    quick_approval_test()
