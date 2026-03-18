"""Heartbeat-Writer fuer das polymarket-beobachter Dashboard.

Schreibt nach jedem Zyklusdurchlauf eine JSON-Datei in logs/heartbeat.json.
Das Format ist kompatibel mit dem aktienbot-Format, damit das Dashboard
beider Projekte dieselbe Parsing-Logik verwenden kann.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from shared.control_events import append_control_event

logger = logging.getLogger("polymarket.heartbeat")

# Pfad zur Heartbeat-Datei (relativ zum Projektroot)
_PROJECT_ROOT = Path(__file__).parent.parent
_HEARTBEAT_FILE = _PROJECT_ROOT / "logs" / "heartbeat.json"


def write_heartbeat(
    status: str = "running",
    detail: str = "",
    extra: Optional[dict] = None,
) -> None:
    """Schreibt Heartbeat-JSON fuer das Dashboard.

    Args:
        status:  Statusstring, z.B. "running", "idle", "error"
        detail:  Kurze Beschreibung des aktuellen Schritts
        extra:   Optionale Zusatzfelder (run_count, consecutive_errors, etc.)
    """
    try:
        payload = {
            "status": status,
            "detail": detail,
            "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "extra": extra or {},
        }

        # Atomares Schreiben via .tmp → rename (verhindert halbgeschriebene Dateien)
        _HEARTBEAT_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _HEARTBEAT_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(_HEARTBEAT_FILE)
        append_control_event(
            "heartbeat",
            component="orchestrator",
            status=status,
            level="INFO",
            message=detail,
            metrics=extra or {},
        )

    except Exception as e:
        # Heartbeat-Fehler sollen den Hauptprozess nie stoppen
        logger.warning("Fehler beim Heartbeat schreiben: %s", e)
