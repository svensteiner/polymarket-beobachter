#!/usr/bin/env python3
"""
Telegram Bot - Benachrichtigungen und Status-Abfragen.

GOVERNANCE:
===========
- Telegram ist INFORMATION ONLY
- Keine Approve/Deny Buttons
- Keine Live-Parameter-Änderungen
- Nur Lese-Zugriff auf System-Status

USAGE:
    from shared.telegram_bot import send_message, start_listener

SETUP:
    1. Erstelle Bot bei @BotFather
    2. Setze TELEGRAM_BOT_TOKEN in .env
    3. Setze TELEGRAM_CHAT_ID in .env (nutze /chatid um ID zu finden)
"""

from __future__ import annotations

import atexit
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv

# =============================================================================
# CONFIGURATION
# =============================================================================

logger = logging.getLogger("telegram")

# Polling state
_last_update_id = 0
_polling_thread: Optional[threading.Thread] = None
_polling_active = False
_lock_acquired = False


def _project_root() -> Path:
    """Get project root directory."""
    return Path(__file__).parent.parent


def _results_dir() -> Path:
    """Get results directory."""
    return _project_root() / "data"


def _lock_path() -> Path:
    """Path to telegram polling lock file."""
    return _results_dir() / ".telegram.lock"


# =============================================================================
# ENVIRONMENT HELPERS
# =============================================================================

def _load_env() -> None:
    """Load environment variables from .env file."""
    env_file = _project_root() / ".env"
    if env_file.exists():
        load_dotenv(env_file)


def _get_token() -> Optional[str]:
    """Get Telegram bot token from environment."""
    _load_env()
    return os.getenv("TELEGRAM_BOT_TOKEN") or None


def _get_chat_ids() -> set[str]:
    """Get allowed chat IDs from environment."""
    _load_env()
    raw = os.getenv("TELEGRAM_CHAT_ID", "") or ""
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    return set(parts)


def _is_enabled() -> bool:
    """Check if Telegram is enabled."""
    raw = os.getenv("TELEGRAM_ENABLED", "1")
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _is_polling_enabled() -> bool:
    """Check if Telegram polling is enabled."""
    raw = os.getenv("TELEGRAM_POLLING_ENABLED", "1")
    return raw.strip().lower() in ("1", "true", "yes", "on")


# =============================================================================
# LOCK MANAGEMENT (nur ein Prozess darf pollen)
# =============================================================================

def _is_pid_alive(pid: int) -> bool:
    """Check if a process is running."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _acquire_lock() -> bool:
    """Acquire the polling lock."""
    lock_file = _lock_path()
    lock_file.parent.mkdir(parents=True, exist_ok=True)

    try:
        fd = os.open(str(lock_file), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return True
    except FileExistsError:
        try:
            raw = lock_file.read_text(encoding="utf-8").strip()
            pid = int(raw) if raw else -1
        except (OSError, ValueError):
            try:
                lock_file.unlink(missing_ok=True)
            except OSError:
                pass
            return _acquire_lock()

        if pid == os.getpid():
            return True
        if not _is_pid_alive(pid):
            try:
                lock_file.unlink(missing_ok=True)
            except OSError:
                pass
            return _acquire_lock()
        return False
    except OSError:
        return False


def _release_lock() -> None:
    """Release the polling lock."""
    lock_file = _lock_path()
    try:
        if not lock_file.exists():
            return
        raw = lock_file.read_text(encoding="utf-8").strip()
        pid = int(raw) if raw else -1
        if pid == os.getpid():
            lock_file.unlink(missing_ok=True)
    except (OSError, ValueError):
        pass


# =============================================================================
# MESSAGE SENDING
# =============================================================================

def send_message(text: str, important: bool = False) -> bool:
    """
    Send a Telegram message.

    Args:
        text: Message text
        important: If True, send even in minimal mode

    Returns:
        True if message was sent successfully
    """
    try:
        _load_env()

        if not _is_enabled():
            logger.debug("Telegram disabled")
            return False

        token = _get_token()
        chat_ids = _get_chat_ids()

        if not token or not chat_ids:
            logger.debug("Token or chat_id missing")
            return False

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        chat_id = next(iter(chat_ids))

        resp = requests.post(
            url,
            data={"chat_id": chat_id, "text": text},
            timeout=10
        )

        if resp.status_code == 200:
            logger.debug("Message sent successfully")
            return True
        else:
            logger.warning(f"sendMessage failed: {resp.status_code}")
            return False

    except Exception as e:
        logger.error(f"send_message error: {e}")
        return False


def send_alert(text: str) -> bool:
    """Send an important alert message."""
    return send_message(f"ALERT\n{text}", important=True)


def send_status(title: str, details: dict) -> bool:
    """Send a formatted status message."""
    lines = [title]
    for key, value in details.items():
        lines.append(f"{key}: {value}")
    return send_message("\n".join(lines))


# =============================================================================
# COMMAND HANDLING
# =============================================================================

def _load_proposals_summary() -> dict:
    """Load summary of pending proposals."""
    proposals_dir = _project_root() / "proposals"
    summary = {"total": 0, "pending": 0, "approved": 0}

    if not proposals_dir.exists():
        return summary

    for path in proposals_dir.glob("*.json"):
        if path.name.startswith("proposal_"):
            summary["total"] += 1
            summary["pending"] += 1

    approved_dir = proposals_dir / "approved"
    if approved_dir.exists():
        for path in approved_dir.glob("*.json"):
            summary["approved"] += 1

    return summary


def _load_paper_trader_status() -> dict:
    """Load paper trader status."""
    status_file = _project_root() / "data" / "paper_trader_status.json"
    try:
        if status_file.exists():
            with open(status_file, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _handle_command(command: str, chat_id: str) -> None:
    """Handle a Telegram command."""
    raw = (command or "").strip()
    first = (raw.split() or [""])[0]
    cmd = first.lower().split("@")[0].strip()

    response = ""

    if cmd in ("/start", "/help", "/hilfe"):
        response = (
            "POLYMARKET BEOBACHTER\n"
            "---\n"
            "/status - System Status\n"
            "/proposals - Offene Proposals\n"
            "/paper - Paper Trader Status\n"
            "/chatid - Chat-ID anzeigen"
        )

    elif cmd in ("/chatid", "/id"):
        allowed = _get_chat_ids()
        response = f"Chat-ID: {chat_id}\nErlaubt: {chat_id in allowed}"

    elif cmd in ("/status", "/s"):
        paper = _load_paper_trader_status()
        proposals = _load_proposals_summary()

        response = "STATUS\n"
        response += f"Proposals: {proposals['pending']} offen\n"

        if paper:
            response += f"Paper P/L: {paper.get('total_pnl', 0):.2f} EUR\n"
            response += f"Positionen: {paper.get('open_positions', 0)}"
        else:
            response += "Paper Trader: nicht aktiv"

    elif cmd in ("/proposals", "/prop"):
        proposals = _load_proposals_summary()
        response = (
            f"PROPOSALS\n"
            f"Offen: {proposals['pending']}\n"
            f"Genehmigt: {proposals['approved']}\n"
            f"Gesamt: {proposals['total']}\n"
            "---\n"
            "Review: python cockpit.py"
        )

    elif cmd in ("/paper", "/pt"):
        paper = _load_paper_trader_status()
        if paper:
            response = (
                f"PAPER TRADER\n"
                f"Kapital: {paper.get('capital', 0):.2f} EUR\n"
                f"P/L: {paper.get('total_pnl', 0):.2f} EUR\n"
                f"Positionen: {paper.get('open_positions', 0)}\n"
                f"Trades: {paper.get('total_trades', 0)}"
            )
        else:
            response = "Paper Trader nicht aktiv"

    else:
        response = f"Unbekannt: {cmd}\n/help fuer Hilfe"

    # Send response
    try:
        token = _get_token()
        if not token:
            return
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        requests.post(url, data={"chat_id": chat_id, "text": response}, timeout=10)
    except Exception as e:
        logger.warning(f"command response error: {e}")


# =============================================================================
# POLLING
# =============================================================================

def _poll_updates() -> None:
    """Poll Telegram for new messages."""
    global _last_update_id, _polling_active

    backoff = 1.0

    while _polling_active:
        try:
            token = _get_token()
            chat_ids = _get_chat_ids()

            if not token:
                time.sleep(5)
                continue

            url = f"https://api.telegram.org/bot{token}/getUpdates"
            params = {"offset": _last_update_id + 1, "timeout": 30}
            resp = requests.get(url, params=params, timeout=35)

            if resp.status_code == 200:
                backoff = 1.0
                data = resp.json()

                for update in data.get("result", []):
                    _last_update_id = update["update_id"]
                    message = update.get("message", {})
                    text = (message.get("text", "") or "").strip()
                    chat_id = str(message.get("chat", {}).get("id", ""))

                    # Only accept from allowed chats
                    if chat_id not in chat_ids:
                        continue

                    if text.startswith("/"):
                        _handle_command(text, chat_id)

            elif resp.status_code == 409:
                # Another process is polling
                logger.warning("409 Conflict - another poller active")
                time.sleep(60)

            else:
                logger.warning(f"getUpdates failed: {resp.status_code}")
                time.sleep(min(backoff, 30))
                backoff = min(backoff * 2, 30)

        except Exception as e:
            logger.warning(f"polling error: {e}")
            time.sleep(min(backoff, 30))
            backoff = min(backoff * 2, 30)


def _register_commands() -> None:
    """Register bot commands with Telegram for autocomplete."""
    token = _get_token()
    if not token:
        return

    commands = [
        {"command": "start", "description": "Hilfe anzeigen"},
        {"command": "help", "description": "Hilfe anzeigen"},
        {"command": "status", "description": "System Status"},
        {"command": "proposals", "description": "Offene Proposals"},
        {"command": "paper", "description": "Paper Trader Status"},
        {"command": "chatid", "description": "Chat-ID anzeigen"},
    ]

    try:
        url = f"https://api.telegram.org/bot{token}/setMyCommands"
        resp = requests.post(
            url,
            data={"commands": json.dumps(commands)},
            timeout=10
        )
        if resp.status_code == 200:
            logger.info("Bot commands registered")
    except Exception as e:
        logger.warning(f"Failed to register commands: {e}")


# =============================================================================
# PUBLIC API
# =============================================================================

def start_listener(caller: str = "unknown") -> bool:
    """
    Start the Telegram command listener.

    Args:
        caller: Identifier of the calling process

    Returns:
        True if listener was started
    """
    global _polling_thread, _polling_active, _lock_acquired

    _load_env()

    if not _is_polling_enabled():
        logger.info(f"Polling disabled (caller: {caller})")
        return False

    if not _is_enabled():
        logger.info("Telegram disabled")
        return False

    if not _get_token():
        logger.warning("TELEGRAM_BOT_TOKEN missing")
        return False

    if not _get_chat_ids():
        logger.warning("TELEGRAM_CHAT_ID missing")
        return False

    if _polling_thread and _polling_thread.is_alive():
        return True  # Already running

    if not _acquire_lock():
        logger.warning(f"Lock held by another process (caller: {caller})")
        return False

    _lock_acquired = True
    atexit.register(_release_lock)

    _register_commands()

    _polling_active = True
    _polling_thread = threading.Thread(target=_poll_updates, daemon=True)
    _polling_thread.start()

    logger.info(f"Telegram listener started (caller: {caller})")
    return True


def stop_listener() -> None:
    """Stop the Telegram command listener."""
    global _polling_active, _lock_acquired
    _polling_active = False
    if _lock_acquired:
        _lock_acquired = False
        _release_lock()


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("Testing Telegram Bot...")

    # Test message
    if send_message("Test vom Polymarket Beobachter"):
        print("Message sent!")
    else:
        print("Message failed - check .env")

    # Start listener
    print("Starting listener... (Ctrl+C to stop)")
    start_listener("test")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        stop_listener()
        print("Stopped.")
