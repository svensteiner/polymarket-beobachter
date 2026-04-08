# =============================================================================
# LLM STRATEGY ANALYST - GPT-5.4 mini Post-Run Analyse
# =============================================================================
#
# Nach jedem N-ten Pipeline-Run analysiert GPT-5.4 mini:
# - Performance-Trends (Win-Rate, P&L, Drawdown)
# - Offene Positionen (sind die noch gut?)
# - Verbesserungsvorschlaege fuer Strategie-Parameter
#
# Ergebnis wird in output/llm_strategy_analysis.json gespeichert.
# =============================================================================

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Du bist ein quantitativer Strategie-Analyst fuer ein Wetter-Betting-System auf Polymarket.

Analysiere die Performance-Daten und gib konkrete Empfehlungen als JSON:

{
  "overall_assessment": "HEALTHY" | "CONCERNING" | "CRITICAL",
  "win_rate_trend": "improving" | "stable" | "declining" | "insufficient_data",
  "key_findings": ["Liste der wichtigsten Erkenntnisse"],
  "open_position_risks": ["Risiken bei offenen Positionen"],
  "parameter_suggestions": [
    {
      "parameter": "Name",
      "current_value": "aktuell",
      "suggested_value": "vorgeschlagen",
      "reasoning": "warum"
    }
  ],
  "action_items": ["Konkrete naechste Schritte"],
  "live_readiness_pct": 0-100
}

Sei ehrlich und datengetrieben. Keine Spekulationen ohne Datenbasis.
live_readiness_pct = Wie bereit ist der Bot fuer Live-Trading (0=garnicht, 100=sofort)."""


# Rate-Limit: Max alle 10 Runs (150 Min)
_ANALYSIS_INTERVAL_RUNS = 10
_LAST_ANALYSIS_RUN = 0


def should_run_analysis(run_count: int) -> bool:
    """Pruefe ob Analyse faellig ist."""
    global _LAST_ANALYSIS_RUN
    if run_count - _LAST_ANALYSIS_RUN >= _ANALYSIS_INTERVAL_RUNS:
        return True
    return False


def run_strategy_analysis(
    base_dir: Path,
    run_summary: Dict[str, Any],
    run_count: int = 0,
) -> Optional[Dict]:
    """
    Fuehre LLM-Strategie-Analyse durch.

    Args:
        base_dir: Projekt-Basisverzeichnis
        run_summary: Zusammenfassung des letzten Runs
        run_count: Aktueller Run-Zaehler

    Returns:
        Analyse-Ergebnis oder None
    """
    global _LAST_ANALYSIS_RUN

    try:
        from .llm_client import llm_json_call
    except ImportError:
        return None

    # Daten sammeln
    data_context = _build_analysis_context(base_dir, run_summary)
    if not data_context:
        return None

    prompt = f"""Analysiere diese Paper-Trading Performance:

{data_context}

Gib eine detaillierte Strategie-Analyse als JSON."""

    # Versuche JSON-Call, bei Fehler normalen Call mit manuellem Parse
    result = llm_json_call(prompt, system=SYSTEM_PROMPT, max_tokens=800, temperature=0.2)

    if result is None:
        # Fallback: normaler Call
        try:
            from .llm_client import llm_call
            raw = llm_call(prompt, system=SYSTEM_PROMPT, max_tokens=800, temperature=0.2)
            if raw:
                import re
                json_match = re.search(r'\{[\s\S]*\}', raw)
                if json_match:
                    result = json.loads(json_match.group())
        except Exception:
            pass

    if result is None:
        logger.debug("LLM Strategy Analysis fehlgeschlagen")
        return None

    _LAST_ANALYSIS_RUN = run_count

    # Ergebnis speichern
    result["timestamp"] = datetime.now(timezone.utc).isoformat()
    result["run_count"] = run_count

    output_path = base_dir / "output" / "llm_strategy_analysis.json"
    try:
        with open(output_path, "w") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        logger.info(
            f"LLM Strategy Analysis: {result.get('overall_assessment', '?')} | "
            f"Live-Readiness: {result.get('live_readiness_pct', '?')}%"
        )
    except Exception as e:
        logger.warning(f"Strategy Analysis speichern fehlgeschlagen: {e}")

    return result


def _build_analysis_context(base_dir: Path, run_summary: Dict) -> str:
    """Baue Kontext fuer die LLM-Analyse."""
    parts = []

    # 1. Kapital-Status
    try:
        with open(base_dir / "data" / "capital_config.json") as f:
            cap = json.load(f)
        parts.append(
            f"KAPITAL: {cap.get('available_capital_eur', 0):.0f} EUR frei, "
            f"{cap.get('allocated_capital_eur', 0):.0f} EUR allokiert, "
            f"PnL: {cap.get('realized_pnl_eur', 0):.2f} EUR"
        )
    except Exception:
        pass

    # 2. Positionen
    try:
        positions_path = base_dir / "paper_trader" / "logs" / "paper_positions.jsonl"
        positions = []
        with open(positions_path) as f:
            for line in f:
                if line.strip():
                    try:
                        positions.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue

        open_pos = [p for p in positions if p.get("status") == "OPEN"]
        closed_pos = [p for p in positions if p.get("status") in ("CLOSED", "RESOLVED")]

        # Nur echte Trades (kein Self-Heal)
        real_closed = [
            p for p in closed_pos
            if "SELF-HEAL" not in str(p.get("exit_reason", ""))
            and "MODEL_FIX" not in str(p.get("exit_reason", ""))
        ]

        parts.append(f"POSITIONEN: {len(open_pos)} offen, {len(real_closed)} echte geschlossene Trades")

        if real_closed:
            wins = [p for p in real_closed if (p.get("realized_pnl_eur") or 0) > 0]
            losses = [p for p in real_closed if (p.get("realized_pnl_eur") or 0) < 0]
            total_pnl = sum(p.get("realized_pnl_eur", 0) for p in real_closed)
            win_rate = len(wins) / len(real_closed) * 100 if real_closed else 0

            parts.append(
                f"PERFORMANCE: Win-Rate {win_rate:.0f}% ({len(wins)}W/{len(losses)}L), "
                f"Total PnL: {total_pnl:.2f} EUR"
            )

            # Exit-Gruende
            reasons = {}
            for p in real_closed:
                r = p.get("exit_reason", "unknown")
                reasons[r] = reasons.get(r, 0) + 1
            parts.append(f"EXIT-GRUENDE: {reasons}")

        # Offene Positionen Detail
        if open_pos:
            parts.append("OFFENE POSITIONEN:")
            for p in open_pos[:5]:
                q = p.get("market_question", "?")[:60]
                parts.append(
                    f"  {p.get('side','?')} @ {p.get('entry_price',0):.4f} | "
                    f"model_p={p.get('model_probability',0):.4f} | "
                    f"{p.get('cost_basis_eur',0):.0f} EUR | {q}"
                )
    except Exception:
        pass

    # 3. Run-Summary
    if run_summary:
        parts.append(
            f"LETZTER RUN: {run_summary.get('edge_observations', 0)} Edge-Signale, "
            f"Drawdown: {run_summary.get('drawdown_pct', 0):.1f}%, "
            f"Health: {run_summary.get('bot_health_status', '?')}"
        )

    # 4. Strategie-Parameter
    try:
        import yaml
        with open(base_dir / "config" / "weather.yaml") as f:
            config = yaml.safe_load(f)
        parts.append(
            f"PARAMETER: MIN_EDGE={config.get('MIN_EDGE', '?')}, "
            f"MAX_ODDS={config.get('MAX_ODDS', '?')}, "
            f"MIN_TIME_TO_RESOLUTION={config.get('MIN_TIME_TO_RESOLUTION_HOURS', '?')}h"
        )
    except Exception:
        pass

    return "\n".join(parts)
