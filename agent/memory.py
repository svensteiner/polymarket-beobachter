"""Memory — Persistente Agenten-Erinnerung.

Dual-Memory-System:
  - Arbeitsgedächtnis (RAM): aktuelle Session, geht verloren beim Neustart
  - Langzeitgedächtnis (JSON): bleibt über Sessions erhalten

Verwendung:
    from memory import Memory
    mem = Memory()

    mem.save("actions", {"type": "post", "result": "ok"})
    mem.save("learnings", {"insight": "Posts morgens performen besser"})

    actions_today = mem.today("actions")
    all_learnings = mem.load("learnings", limit=20)
    count = mem.count_today("actions", type="post")
"""

import json
import logging
from datetime import datetime, date
from pathlib import Path
from typing import Any

logger = logging.getLogger("memory")

STATE_DIR = Path(__file__).parent / "state"
STATE_DIR.mkdir(exist_ok=True)

MAX_ENTRIES_PER_KEY = 1000  # Max Einträge pro Key bevor alte gelöscht werden


class Memory:
    def __init__(self):
        self._working: dict[str, list] = {}  # RAM (Session)

    # ── Langzeitgedächtnis (JSON) ──────────────────────────────────────

    def save(self, key: str, data: Any) -> None:
        """Speichert einen Eintrag dauerhaft (mit Timestamp)."""
        entries = self._load_raw(key)
        base = {"timestamp": datetime.now().isoformat(), "date": date.today().isoformat()}
        extra = data if isinstance(data, dict) else {"value": data}
        entries.append({**base, **extra})
        # Alte Einträge trimmen
        if len(entries) > MAX_ENTRIES_PER_KEY:
            entries = entries[-MAX_ENTRIES_PER_KEY:]
        self._save_raw(key, entries)

    def load(self, key: str, limit: int = 50) -> list:
        """Lädt die letzten N Einträge für einen Key."""
        entries = self._load_raw(key)
        return entries[-limit:] if limit else entries

    def today(self, key: str, **filters) -> list:
        """Alle heutigen Einträge, optional mit Filter."""
        today_str = date.today().isoformat()
        entries = [e for e in self._load_raw(key) if e.get("date") == today_str]
        for k, v in filters.items():
            entries = [e for e in entries if e.get(k) == v]
        return entries

    def count_today(self, key: str, **filters) -> int:
        """Zählt heutige Einträge."""
        return len(self.today(key, **filters))

    def done_today(self, key: str, **filters) -> bool:
        """Wurde das heute schon gemacht? (Duplikat-Check)"""
        return self.count_today(key, **filters) > 0

    def last(self, key: str) -> dict | None:
        """Letzter Eintrag für einen Key."""
        entries = self._load_raw(key)
        return entries[-1] if entries else None

    def clear(self, key: str) -> None:
        """Löscht alle Einträge für einen Key."""
        self._save_raw(key, [])

    # ── Arbeitsgedächtnis (RAM) ────────────────────────────────────────

    def set_working(self, key: str, value: Any) -> None:
        """Setzt temporären Wert (geht beim Neustart verloren)."""
        self._working[key] = value

    def get_working(self, key: str, default: Any = None) -> Any:
        """Liest temporären Wert."""
        return self._working.get(key, default)

    def push_working(self, key: str, value: Any) -> None:
        """Fügt Wert zu temporärer Liste hinzu."""
        if key not in self._working:
            self._working[key] = []
        self._working[key].append(value)

    def all_working(self, key: str) -> list:
        """Gibt gesamte temporäre Liste zurück."""
        return self._working.get(key, [])

    # ── Metriken ──────────────────────────────────────────────────────

    def log_metric(self, metric: str, value: float, unit: str = "") -> None:
        """Speichert einen numerischen Messwert."""
        self.save("metrics", {"metric": metric, "value": value, "unit": unit})

    def avg_metric(self, metric: str, days: int = 7) -> float | None:
        """Durchschnitt eines Metrics über die letzten N Tage."""
        from datetime import timedelta
        cutoff = (date.today() - timedelta(days=days)).isoformat()
        entries = [
            e for e in self._load_raw("metrics")
            if e.get("metric") == metric and e.get("date", "") >= cutoff
        ]
        if not entries:
            return None
        return sum(e["value"] for e in entries) / len(entries)

    # ── Intern ────────────────────────────────────────────────────────

    def _load_raw(self, key: str) -> list:
        path = STATE_DIR / f"{key}.json"
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning(f"Fehler beim Laden von {key}: {e}")
        return []

    def _save_raw(self, key: str, data: list) -> None:
        path = STATE_DIR / f"{key}.json"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def summary(self) -> dict:
        """Gibt Überblick über alle gespeicherten Keys."""
        files = list(STATE_DIR.glob("*.json"))
        result = {}
        for f in files:
            try:
                entries = json.loads(f.read_text(encoding="utf-8"))
                result[f.stem] = {
                    "total": len(entries),
                    "today": sum(1 for e in entries if e.get("date") == date.today().isoformat()),
                    "last": entries[-1].get("timestamp", "?") if entries else None,
                }
            except Exception:
                pass
        return result
