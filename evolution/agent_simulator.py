# =============================================================================
# EVOLUTION AGENT SIMULATOR
# =============================================================================
#
# Simuliert Paper-Trades fuer jeden Evolutions-Agenten unabhaengig voneinander.
# Jeder Agent filtert Proposals nach seinen eigenen Parametern und baut
# eine individuelle Trade-History auf.
#
# Wird vom Orchestrator nach Step 3 (Proposals) aufgerufen:
#   simulate_agents_entry(proposals)   → neue Positionen
#   simulate_agents_close()            → Positionen schliessen wenn aufgeloest
#
# =============================================================================

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
AGENTS_DIR = PROJECT_ROOT / "data" / "evolution" / "agents"

# Kapital pro Agent (muss mit population.py CAPITAL_PER_AGENT uebereinstimmen)
CAPITAL_PER_AGENT = 625.0
MAX_POSITION_EUR = 125.0   # 20% des Agent-Kapitals
MIN_POSITION_EUR = 5.0


# =============================================================================
# KAPITAL-HELPERS
# =============================================================================

def _load_agent_capital(agent_id: str) -> Dict[str, Any]:
    cap_file = AGENTS_DIR / agent_id / "capital.json"
    if cap_file.exists():
        try:
            return json.loads(cap_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    # Default
    return {
        "agent_id": agent_id,
        "total_capital_eur": CAPITAL_PER_AGENT,
        "available_capital_eur": CAPITAL_PER_AGENT,
        "allocated_capital_eur": 0.0,
        "max_positions": 5,
        "max_position_size_eur": MAX_POSITION_EUR,
    }


def _save_agent_capital(agent_id: str, cap: Dict[str, Any]) -> None:
    cap_file = AGENTS_DIR / agent_id / "capital.json"
    cap_file.parent.mkdir(parents=True, exist_ok=True)
    with open(cap_file, "w", encoding="utf-8") as f:
        json.dump(cap, f, indent=2)


# =============================================================================
# POSITIONS-HELPERS
# =============================================================================

def _load_agent_positions(agent_id: str) -> List[Dict[str, Any]]:
    pos_file = AGENTS_DIR / agent_id / "paper_positions.jsonl"
    if not pos_file.exists():
        return []
    positions = []
    try:
        for line in pos_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    positions.append(json.loads(line))
                except Exception:
                    pass
    except Exception as e:
        logger.debug(f"[AGENT-SIM] Positionen fuer {agent_id} nicht lesbar: {e}")
    return positions


def _append_position(agent_id: str, position: Dict[str, Any]) -> None:
    pos_file = AGENTS_DIR / agent_id / "paper_positions.jsonl"
    pos_file.parent.mkdir(parents=True, exist_ok=True)
    with open(pos_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(position, ensure_ascii=False) + "\n")


def _update_position(agent_id: str, position_id: str, updates: Dict[str, Any]) -> None:
    """Ueberschreibt eine Position in der JSONL-Datei mit aktualisierten Feldern."""
    pos_file = AGENTS_DIR / agent_id / "paper_positions.jsonl"
    if not pos_file.exists():
        return
    lines = pos_file.read_text(encoding="utf-8").splitlines()
    new_lines = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            pos = json.loads(line)
            if pos.get("position_id") == position_id:
                pos.update(updates)
            new_lines.append(json.dumps(pos, ensure_ascii=False))
        except Exception:
            new_lines.append(line)
    pos_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def _open_positions(agent_id: str) -> List[Dict[str, Any]]:
    return [p for p in _load_agent_positions(agent_id) if p.get("status") == "OPEN"]


def _is_duplicate(agent_id: str, market_id: str) -> bool:
    """Prueft ob bereits eine offene Position fuer diesen Markt existiert."""
    for pos in _open_positions(agent_id):
        if pos.get("market_id") == market_id:
            return True
    return False


# =============================================================================
# ENTRY SIMULATION
# =============================================================================

def simulate_agents_entry() -> Dict[str, int]:
    """
    Simuliert Eintraege fuer alle aktiven Agenten.
    Liest aktuelle Proposals direkt aus dem Intake-System
    (identisch zu dem was der globale Paper Trader sieht).

    Returns:
        Dict agent_id -> Anzahl eingegangener Positionen
    """
    try:
        from evolution.population import Population
        pop = Population.load()
        agents = pop.active_agents()
    except Exception as e:
        logger.debug(f"[AGENT-SIM] Population nicht ladbar: {e}")
        return {}

    if not agents:
        return {}

    # Proposals aus dem Intake laden (gleiche Quelle wie globaler Paper Trader)
    try:
        from paper_trader.intake import get_eligible_proposals
        proposals = get_eligible_proposals()
    except Exception as e:
        logger.debug(f"[AGENT-SIM] Proposals nicht ladbar: {e}")
        return {}

    # Nur TRADE-Proposals mit positiver Edge
    tradeable = [p for p in proposals if getattr(p, "decision", "") == "TRADE" and getattr(p, "edge", 0) > 0]
    if not tradeable:
        logger.debug("[AGENT-SIM] Keine handelbaren Proposals")
        return {}

    results: Dict[str, int] = {}

    for agent in agents:
        entered = _simulate_agent_entry(agent, tradeable)
        results[agent.agent_id] = entered
        if entered > 0:
            logger.info(f"[AGENT-SIM] {agent.agent_id}: {entered} neue Positionen")

    return results


def _simulate_agent_entry(agent: Any, proposals: List[Any]) -> int:
    """Verarbeitet Proposals fuer einen einzelnen Agenten."""
    params = agent.params
    min_edge = float(params.get("min_edge", 0.12))
    min_edge_abs = float(params.get("min_edge_absolute", 0.05))
    max_odds = float(params.get("max_odds", 0.35))
    kelly = float(params.get("kelly_fraction", 0.25))
    min_liquidity = float(params.get("min_liquidity", 50.0))
    confidence_mult = float(params.get("medium_confidence_multiplier", 1.25))

    cap = _load_agent_capital(agent.agent_id)
    available = float(cap.get("available_capital_eur", 0))
    max_pos = int(cap.get("max_positions", 5))
    max_size = float(cap.get("max_position_size_eur", MAX_POSITION_EUR))

    open_pos = _open_positions(agent.agent_id)
    if len(open_pos) >= max_pos:
        return 0  # Maximale Positionsanzahl erreicht

    entered = 0

    for proposal in proposals:
        edge_raw = float(getattr(proposal, "edge", 0))
        implied_prob = float(getattr(proposal, "implied_probability", 0))
        market_id = getattr(proposal, "market_id", "")
        confidence = getattr(proposal, "confidence_level", "LOW")

        # Proposals speichern edge als Prozentzahl (z.B. 21.2 = 21.2%).
        # Agent-Params sind als Ratio (z.B. 0.12 = 12%). Normalisieren:
        edge = edge_raw / 100.0

        # Agent-spezifische Filter
        if edge < min_edge:
            continue
        if edge < min_edge_abs:
            continue
        if implied_prob > max_odds:
            continue

        # Liquiditaets-Check aus core_criteria
        core = getattr(proposal, "core_criteria", None)
        if core is not None and not getattr(core, "liquidity_ok", True):
            continue

        # Kein Duplicate
        if _is_duplicate(agent.agent_id, market_id):
            continue

        # Positionslimit
        if len(open_pos) + entered >= max_pos:
            break

        # Kapital-Check
        if available < MIN_POSITION_EUR:
            break

        # Kelly-Sizing: Kapital × Kelly × Edge (edge als Ratio 0-1)
        # Bei MEDIUM Confidence: Edge mit Multiplikator skalieren
        effective_edge = edge
        if confidence == "MEDIUM":
            effective_edge = edge * confidence_mult
        elif confidence == "LOW":
            effective_edge = edge * 0.5

        # Kelly Criterion: f = edge / (1/p - 1) vereinfacht zu f = edge * kelly_fraction
        raw_size = available * kelly * effective_edge
        size_eur = min(max(raw_size, MIN_POSITION_EUR), max_size, available)
        size_eur = round(size_eur, 2)

        if size_eur < MIN_POSITION_EUR:
            continue

        # Position anlegen
        position_id = f"AGSIM-{agent.agent_id[:8]}-{uuid.uuid4().hex[:8].upper()}"
        position = {
            "position_id": position_id,
            "agent_id": agent.agent_id,
            "proposal_id": getattr(proposal, "proposal_id", ""),
            "market_id": market_id,
            "market_question": getattr(proposal, "market_question", ""),
            "side": "YES",  # Agenten handeln immer die YES-Seite (Long-Edge)
            "status": "OPEN",
            "entry_time": datetime.now().isoformat(),
            "entry_price": implied_prob,
            "entry_edge": edge_raw,
            "model_probability": float(getattr(proposal, "model_probability", 0)),
            "cost_basis_eur": size_eur,
            "exit_time": None,
            "exit_price": None,
            "exit_reason": None,
            "realized_pnl_eur": None,
            "pnl_pct": None,
            "governance_notice": "AGENT SIMULATION - Paper only. No real funds.",
        }
        _append_position(agent.agent_id, position)

        # Kapital abziehen
        available -= size_eur
        cap["available_capital_eur"] = round(available, 2)
        cap["allocated_capital_eur"] = round(
            float(cap.get("total_capital_eur", CAPITAL_PER_AGENT)) - available, 2
        )
        entered += 1

    if entered > 0:
        _save_agent_capital(agent.agent_id, cap)

    return entered


# =============================================================================
# CLOSE SIMULATION
# =============================================================================

def simulate_agents_close() -> Dict[str, int]:
    """
    Schliesst Agenten-Positionen fuer aufgeloeste Maerkte.
    Nutzt denselben Snapshot-Client wie der globale Paper Trader.

    Returns:
        Dict agent_id -> Anzahl geschlossener Positionen
    """
    try:
        from evolution.population import Population
        pop = Population.load()
        agents = pop.active_agents()
    except Exception as e:
        logger.debug(f"[AGENT-SIM] Population nicht ladbar: {e}")
        return {}

    if not agents:
        return {}

    # Alle offenen Positionen aller Agenten sammeln → welche market_ids muessen gecheckt werden?
    all_market_ids: set = set()
    for agent in agents:
        for pos in _open_positions(agent.agent_id):
            all_market_ids.add(pos.get("market_id", ""))
    all_market_ids.discard("")

    if not all_market_ids:
        return {}

    # Snapshots laden
    try:
        from paper_trader.snapshot_client import get_market_snapshots
        snapshots = get_market_snapshots(list(all_market_ids))
    except Exception as e:
        logger.debug(f"[AGENT-SIM] Snapshots nicht ladbar: {e}")
        return {}

    # Aufgeloeste Maerkte extrahieren
    resolved: Dict[str, str] = {}
    for market_id, snap in snapshots.items():
        if getattr(snap, "is_resolved", False):
            outcome = str(getattr(snap, "resolved_outcome", "UNKNOWN")).upper()
            resolved[market_id] = outcome

    if not resolved:
        return {}

    results: Dict[str, int] = {}
    for agent in agents:
        closed = _simulate_agent_close(agent, resolved)
        results[agent.agent_id] = closed
        if closed > 0:
            logger.info(f"[AGENT-SIM] {agent.agent_id}: {closed} Positionen geschlossen")

    return results


def _simulate_agent_close(agent: Any, resolved: Dict[str, str]) -> int:
    """Schliesst aufgeloeste Positionen fuer einen Agenten."""
    open_positions = _open_positions(agent.agent_id)
    cap = _load_agent_capital(agent.agent_id)
    available = float(cap.get("available_capital_eur", 0))
    closed = 0

    for pos in open_positions:
        market_id = pos.get("market_id", "")
        if market_id not in resolved:
            continue

        outcome = resolved[market_id]
        side = pos.get("side", "YES")
        cost = float(pos.get("cost_basis_eur", 0))
        entry_price = float(pos.get("entry_price", 0))

        # P&L berechnen
        if outcome == "YES" and side == "YES":
            # Gewinn: Contracts × (1 - entry_price) - entry_price
            # Vereinfacht: cost / entry_price × (1 - entry_price)
            if entry_price > 0:
                contracts = cost / entry_price
                gross = contracts * 1.0  # resolves at 1.0
                pnl = gross - cost
            else:
                pnl = 0.0
        elif outcome == "NO" and side == "YES":
            # Verlust: gesamter Einsatz verloren
            pnl = -cost
        elif outcome == "VOID":
            pnl = 0.0
        else:
            # Unbekannt: konservativ als Verlust werten
            pnl = -cost * 0.5

        pnl_pct = (pnl / cost * 100) if cost > 0 else 0.0

        updates = {
            "status": "RESOLVED",
            "exit_time": datetime.now().isoformat(),
            "exit_price": 1.0 if outcome == "YES" else 0.0,
            "exit_reason": f"RESOLUTION_{outcome}",
            "realized_pnl_eur": round(pnl, 4),
            "pnl_pct": round(pnl_pct, 2),
        }
        _update_position(agent.agent_id, pos["position_id"], updates)

        # Kapital zurueck
        available += cost + pnl
        closed += 1

    if closed > 0:
        cap["available_capital_eur"] = round(available, 2)
        cap["allocated_capital_eur"] = round(
            float(cap.get("total_capital_eur", CAPITAL_PER_AGENT)) - available, 2
        )
        _save_agent_capital(agent.agent_id, cap)

    return closed
