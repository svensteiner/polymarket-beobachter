"""
Action Executor — schreibt genehmigte Agentic-Aktionen in JSON-Dateien.

Effekte:
  pause_city    → data/agent_city_cooldowns.json  (Simulator liest die Datei)
  tighten_risk  → output/agent_proposals.json     (User-Review beim naechsten Check)

Niemals schreibt dieser Modul in config/weather.yaml oder andere Live-Configs.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from .state import ActionProposal

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).parent.parent
_COOLDOWNS_PATH = _PROJECT_ROOT / "data" / "agent_city_cooldowns.json"
_PROPOSALS_PATH = _PROJECT_ROOT / "output" / "agent_proposals.json"


# =============================================================================
# PUBLIC API
# =============================================================================


def execute_approved_actions(approved: List[ActionProposal], base_dir: Path | None = None) -> Dict[str, Any]:
    """
    Fuehrt genehmigte nicht-read-only Aktionen aus.

    Returns:
        Summary dict mit ausgefuehrten und uebersprungenen Aktionen.
    """
    root = base_dir or _PROJECT_ROOT
    executed: List[str] = []
    skipped: List[str] = []

    for proposal in approved:
        if proposal.status == "APPROVED_READ_ONLY":
            skipped.append(proposal.action_type)
            continue
        try:
            if proposal.action_type == "pause_city":
                _execute_pause_city(proposal, root)
                executed.append(proposal.action_type)
            elif proposal.action_type == "tighten_risk":
                _execute_tighten_risk(proposal, root)
                executed.append(proposal.action_type)
            else:
                skipped.append(proposal.action_type)
        except Exception as exc:
            logger.warning("ActionExecutor: %s fehlgeschlagen — %s", proposal.action_type, exc)
            skipped.append(proposal.action_type)

    if executed:
        logger.info("ActionExecutor: ausgefuehrt=%s", executed)
    return {"executed": executed, "skipped": skipped}


# =============================================================================
# PAUSE_CITY
# =============================================================================


def _execute_pause_city(proposal: ActionProposal, root: Path) -> None:
    """
    Traegt Staedte aus dem Proposal in data/agent_city_cooldowns.json ein.
    Der Simulator prueft diese Datei bei jedem Entry (zusaetzlich zu WEAK_PERFORMANCE_CITIES).
    """
    cities: List[str] = proposal.params.get("cities", [])
    if not cities:
        logger.debug("pause_city: keine Staedte im Proposal, nichts zu tun")
        return

    cooldowns_path = root / "data" / "agent_city_cooldowns.json"
    cooldowns = _load_json(cooldowns_path, {"cooldowns": {}})

    now_iso = datetime.now(timezone.utc).isoformat()
    changed = False
    for city in cities:
        key = city.lower().strip()
        if key and key not in cooldowns["cooldowns"]:
            cooldowns["cooldowns"][key] = {
                "added_at": now_iso,
                "reason": "agent_pause_city",
                "proposal_id": proposal.action_type,
                "trades_since": 0,
            }
            logger.info("pause_city: %s auf Cooldown gesetzt (%s)", key, now_iso)
            changed = True

    if changed:
        cooldowns_path.parent.mkdir(parents=True, exist_ok=True)
        cooldowns_path.write_text(
            json.dumps(cooldowns, ensure_ascii=False, indent=2), encoding="utf-8"
        )


def get_agent_cooldown_cities(root: Path | None = None) -> frozenset:
    """
    Gibt alle aktuell im Agent-Cooldown befindlichen Staedte zurueck (lowercase).
    Wird vom Simulator aufgerufen, um dynamische Stadtbloecke zu pruefen.
    """
    path = (root or _PROJECT_ROOT) / "data" / "agent_city_cooldowns.json"
    data = _load_json(path, {"cooldowns": {}})
    return frozenset(data.get("cooldowns", {}).keys())


def lift_city_cooldown(city: str, root: Path | None = None) -> bool:
    """
    Entfernt eine Stadt aus dem Agent-Cooldown (wenn >= 10 Trades mit >= 50 % WR).
    Gibt True zurueck wenn entfernt, False wenn nicht gefunden.
    """
    path = (root or _PROJECT_ROOT) / "data" / "agent_city_cooldowns.json"
    data = _load_json(path, {"cooldowns": {}})
    key = city.lower().strip()
    if key not in data["cooldowns"]:
        return False
    del data["cooldowns"][key]
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("pause_city: Cooldown fuer %s aufgehoben", key)
    return True


# =============================================================================
# TIGHTEN_RISK
# =============================================================================


def _execute_tighten_risk(proposal: ActionProposal, root: Path) -> None:
    """
    Schreibt einen konkreten Parameter-Vorschlag nach output/agent_proposals.json.
    Sichtbar beim naechsten User-Check; wird NICHT automatisch angewendet.
    """
    proposals_path = root / "output" / "agent_proposals.json"
    existing = _load_json(proposals_path, {"proposals": []})

    now_iso = datetime.now(timezone.utc).isoformat()
    entry = {
        "type": "tighten_risk",
        "created_at": now_iso,
        "status": "pending_review",
        "rationale": proposal.rationale,
        "evidence": proposal.evidence,
        "priority": proposal.priority,
        "params": proposal.params,
        "suggested_changes": {
            "min_edge_relative": "raise to 0.45 (currently 0.40)",
            "max_entry_price": "lower to 0.70 (currently 0.75 in DEFENSIVE)",
            "kelly_fraction": "lower to 0.20 (currently 0.25)",
        },
    }
    existing["proposals"].append(entry)
    # Keep only the 20 most recent proposals
    existing["proposals"] = existing["proposals"][-20:]

    proposals_path.parent.mkdir(parents=True, exist_ok=True)
    proposals_path.write_text(
        json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.info("tighten_risk: Proposal nach %s geschrieben", proposals_path)


# =============================================================================
# HELPERS
# =============================================================================


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default
