"""Governance — Action-Registry mit Cooldowns.

Verhindert Thrashing: der Agent kann dieselbe Aktion nicht beliebig oft
in kurzer Zeit wiederholen. Jede Aktion hat einen konfigurierbaren Cooldown.

Verwendung:
    from governance import Governor

    gov = Governor()
    gov.register("send_report",   cooldown_hours=24,  description="Tagesreport versenden")
    gov.register("post_social",   cooldown_minutes=60, description="Social-Media-Post")
    gov.register("tighten_config", cooldown_hours=2,  description="Konfiguration verschärfen")

    ok, reason = gov.can_act("send_report")
    if ok:
        gov.record("send_report", result="success", details="KW15-Report versendet")

    print(gov.status())
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger("governance")

STATE_DIR = Path(__file__).parent / "state"
STATE_DIR.mkdir(exist_ok=True)
_HISTORY_FILE = STATE_DIR / "governance.json"


class Governor:
    def __init__(self):
        self._registry: dict[str, dict] = {}
        self._history: list[dict] = self._load()

    # ── Registry ──────────────────────────────────────────────────────────

    def register(
        self,
        action: str,
        *,
        cooldown_hours: float = 0,
        cooldown_minutes: float = 0,
        description: str = "",
        max_per_day: Optional[int] = None,
    ) -> None:
        """Registriert eine Aktion mit Cooldown-Regeln."""
        total_minutes = cooldown_hours * 60 + cooldown_minutes
        self._registry[action] = {
            "description": description,
            "cooldown_minutes": total_minutes,
            "max_per_day": max_per_day,
        }

    # ── Checks ────────────────────────────────────────────────────────────

    def can_act(self, action: str) -> tuple[bool, str]:
        """Prüft ob eine Aktion jetzt erlaubt ist.

        Returns:
            (True, "") wenn erlaubt
            (False, Grund) wenn blockiert
        """
        rule = self._registry.get(action)
        if rule is None:
            return True, ""

        now = datetime.now()

        # Cooldown-Check
        cooldown_min = rule.get("cooldown_minutes", 0)
        if cooldown_min > 0:
            last = self._last_execution(action)
            if last is not None:
                elapsed = (now - last).total_seconds() / 60
                remaining = cooldown_min - elapsed
                if remaining > 0:
                    h, m = divmod(int(remaining), 60)
                    remaining_str = f"{h}h {m}m" if h else f"{m}m"
                    return False, (
                        f"'{action}' im Cooldown — noch {remaining_str} warten "
                        f"(letzte Ausführung: {last.strftime('%H:%M')})"
                    )

        # Max-per-day-Check
        max_day = rule.get("max_per_day")
        if max_day is not None:
            today_str = now.date().isoformat()
            count = sum(
                1 for e in self._history
                if e.get("action") == action and e.get("date") == today_str
            )
            if count >= max_day:
                return False, (
                    f"'{action}' heute bereits {count}× ausgeführt "
                    f"(Tageslimit: {max_day})"
                )

        return True, ""

    # ── Recording ─────────────────────────────────────────────────────────

    def record(self, action: str, result: str = "success", details: str = "") -> None:
        """Erfasst eine ausgeführte Aktion in der History."""
        now = datetime.now()
        entry = {
            "action": action,
            "timestamp": now.isoformat(),
            "date": now.date().isoformat(),
            "result": result,
            "details": details,
        }
        self._history.append(entry)
        # Nur letzte 500 Einträge behalten
        if len(self._history) > 500:
            self._history = self._history[-500:]
        self._save()
        logger.info(f"Governance: '{action}' aufgezeichnet ({result})")

    # ── Status ────────────────────────────────────────────────────────────

    def status(self) -> dict:
        """Gibt den aktuellen Status aller registrierten Aktionen zurück."""
        now = datetime.now()
        today_str = now.date().isoformat()
        result = {}

        for action, rule in self._registry.items():
            last = self._last_execution(action)
            cooldown_min = rule.get("cooldown_minutes", 0)
            ok, reason = self.can_act(action)

            today_count = sum(
                1 for e in self._history
                if e.get("action") == action and e.get("date") == today_str
            )

            result[action] = {
                "description": rule.get("description", ""),
                "can_act": ok,
                "block_reason": reason if not ok else None,
                "last_executed": last.strftime("%Y-%m-%d %H:%M") if last else None,
                "cooldown_minutes": cooldown_min,
                "today_count": today_count,
                "max_per_day": rule.get("max_per_day"),
            }

        return result

    def summary_text(self) -> str:
        """Kompakte Textdarstellung für Logs."""
        lines = []
        for action, info in self.status().items():
            icon = "✅" if info["can_act"] else "🔒"
            line = f"  {icon} {action}"
            if info["block_reason"]:
                line += f" — {info['block_reason']}"
            elif info["last_executed"]:
                line += f" (zuletzt: {info['last_executed']}, heute: {info['today_count']}×)"
            lines.append(line)
        return "\n".join(lines) if lines else "  (keine Aktionen registriert)"

    # ── Intern ────────────────────────────────────────────────────────────

    def _last_execution(self, action: str) -> Optional[datetime]:
        executions = [
            e for e in self._history if e.get("action") == action
        ]
        if not executions:
            return None
        try:
            return datetime.fromisoformat(executions[-1]["timestamp"])
        except Exception:
            return None

    def _load(self) -> list:
        if _HISTORY_FILE.exists():
            try:
                return json.loads(_HISTORY_FILE.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning(f"Governance-History konnte nicht geladen werden: {e}")
        return []

    def _save(self) -> None:
        _HISTORY_FILE.write_text(
            json.dumps(self._history, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
