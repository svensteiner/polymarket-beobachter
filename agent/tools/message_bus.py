"""MessageBus — Kommunikations-System zwischen Agenten.

Ermöglicht asynchrone Nachrichten zwischen CMO, CTO, CSO und anderen Agenten.
Jeder Agent kann senden und empfangen. Nachrichten werden in einer shared
JSON-Datei gespeichert und bleiben bis zur Verarbeitung erhalten.

Verwendung:
    from tools.message_bus import MessageBus

    bus = MessageBus(agent_name="cmo")

    # Nachricht an CTO senden
    bus.send(to="cto", msg_type="deploy_request", content={
        "reason": "Neue Website-Inhalte ready",
        "priority": "high"
    })

    # Eigene Nachrichten lesen
    messages = bus.receive()
    for msg in messages:
        print(f"Von {msg['from']}: {msg['content']}")
        bus.mark_read(msg['id'])

    # Ungelesene zählen
    count = bus.unread_count()
"""

import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("message_bus")

# Shared Bus-Datei — liegt im agents/-Elternordner (oder lokal bei Standalone)
_DEFAULT_BUS_FILE = Path(__file__).parent.parent / "state" / "message_bus.json"


class MessageBus:
    """Einfacher JSON-basierter Message Bus für Agent-zu-Agent-Kommunikation."""

    def __init__(self, agent_name: str, bus_file: Path = None):
        self.agent = agent_name
        self.bus_file = bus_file or _DEFAULT_BUS_FILE
        self.bus_file.parent.mkdir(parents=True, exist_ok=True)

    # ── Senden ────────────────────────────────────────────────────────────

    def send(self, to: str, msg_type: str, content: Any,
             priority: str = "normal") -> dict:
        """Sendet eine Nachricht an einen anderen Agenten.

        Args:
            to:       Empfänger-Agent ("cto", "cmo", "cso", "all")
            msg_type: Nachrichtentyp ("deploy_request", "content_ready", "alert", ...)
            content:  Nachrichteninhalt (dict oder string)
            priority: "low" | "normal" | "high" | "urgent"

        Returns:
            Die erstellte Nachricht (mit ID)
        """
        msg = {
            "id": str(uuid.uuid4())[:8],
            "from": self.agent,
            "to": to,
            "type": msg_type,
            "content": content,
            "priority": priority,
            "timestamp": datetime.now().isoformat(),
            "read": False,
        }

        messages = self._load()
        messages.append(msg)
        self._save(messages)

        logger.info(f"[Bus] {self.agent} → {to}: {msg_type} (id={msg['id']})")
        return msg

    # ── Empfangen ──────────────────────────────────────────────────────────

    def receive(self, unread_only: bool = True) -> list[dict]:
        """Lädt alle Nachrichten an diesen Agenten.

        Args:
            unread_only: Nur ungelesene Nachrichten (Standard: True)

        Returns:
            Liste von Nachrichten, neueste zuerst
        """
        messages = self._load()
        result = [
            m for m in messages
            if (m.get("to") == self.agent or m.get("to") == "all")
            and (not unread_only or not m.get("read", False))
        ]
        # Sortiere: urgent zuerst, dann nach Timestamp
        priority_order = {"urgent": 0, "high": 1, "normal": 2, "low": 3}
        result.sort(key=lambda m: (priority_order.get(m.get("priority", "normal"), 2), m.get("timestamp", "")))
        return result

    def receive_all(self) -> list[dict]:
        """Alle Nachrichten (auch gelesene)."""
        return self.receive(unread_only=False)

    def unread_count(self) -> int:
        return len(self.receive(unread_only=True))

    # ── Status verwalten ───────────────────────────────────────────────────

    def mark_read(self, msg_id: str) -> None:
        """Markiert eine Nachricht als gelesen."""
        messages = self._load()
        for m in messages:
            if m.get("id") == msg_id:
                m["read"] = True
                m["read_at"] = datetime.now().isoformat()
                break
        self._save(messages)

    def mark_all_read(self) -> int:
        """Markiert alle eigenen Nachrichten als gelesen. Gibt Anzahl zurück."""
        messages = self._load()
        count = 0
        for m in messages:
            if (m.get("to") == self.agent or m.get("to") == "all") and not m.get("read"):
                m["read"] = True
                m["read_at"] = datetime.now().isoformat()
                count += 1
        self._save(messages)
        return count

    # ── Broadcast ─────────────────────────────────────────────────────────

    def broadcast(self, msg_type: str, content: Any, priority: str = "normal") -> dict:
        """Sendet eine Nachricht an ALLE Agenten."""
        return self.send("all", msg_type, content, priority)

    # ── Gesendete Nachrichten ─────────────────────────────────────────────

    def sent_messages(self, limit: int = 20) -> list[dict]:
        """Alle von diesem Agenten gesendeten Nachrichten."""
        messages = self._load()
        sent = [m for m in messages if m.get("from") == self.agent]
        return sent[-limit:]

    # ── Cleanup ────────────────────────────────────────────────────────────

    def cleanup(self, max_age_days: int = 7) -> int:
        """Löscht gelesene Nachrichten älter als N Tage."""
        from datetime import timedelta
        cutoff = (datetime.now() - timedelta(days=max_age_days)).isoformat()
        messages = self._load()
        before = len(messages)
        messages = [
            m for m in messages
            if not m.get("read") or m.get("timestamp", "") > cutoff
        ]
        self._save(messages)
        removed = before - len(messages)
        if removed:
            logger.info(f"[Bus] Cleanup: {removed} alte Nachrichten entfernt")
        return removed

    # ── Intern ────────────────────────────────────────────────────────────

    def _load(self) -> list:
        if self.bus_file.exists():
            try:
                return json.loads(self.bus_file.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning(f"Bus-Datei Ladefehler: {e}")
        return []

    def _save(self, messages: list) -> None:
        # Max 500 Nachrichten im Bus halten
        if len(messages) > 500:
            messages = messages[-500:]
        self.bus_file.write_text(
            json.dumps(messages, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
