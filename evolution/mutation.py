# =============================================================================
# MUTATION & CROSSOVER
# =============================================================================
#
# Erzeugt neue Agenten aus bestehenden durch:
# - Mutation: Zufaellige Parameteraenderung (+-10-25% pro Param)
# - Crossover: Mischung zweier Eltern-Agenten
#
# =============================================================================

from __future__ import annotations

import json
import random
import uuid
from pathlib import Path
from typing import Dict, List, Optional

from evolution.agent import Agent, PARAM_RANGES, DEFAULT_PARAMS

PROJECT_ROOT = Path(__file__).parent.parent
HINTS_FILE = PROJECT_ROOT / "data" / "evolution" / "strategy_hints.json"


def _load_strategy_hints() -> Dict[str, dict]:
    """Lade Mutations-Hints vom Strategy Agent (falls vorhanden)."""
    if not HINTS_FILE.exists():
        return {}
    try:
        return json.loads(HINTS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def mutate(
    parent: Agent,
    generation: int,
    mutation_rate: float = 0.4,
    mutation_strength: float = 0.15,
    use_strategy_hints: bool = True,
) -> Agent:
    """
    Erstelle mutierten Nachfolger eines Agenten.

    Args:
        parent: Eltern-Agent
        generation: Neue Generation
        mutation_rate: Wahrscheinlichkeit dass ein Parameter mutiert (0.4 = 40%)
        mutation_strength: Max relative Aenderung pro Mutation (0.15 = +-15%)
        use_strategy_hints: Ob Strategy-Agent-Hints genutzt werden sollen

    Returns:
        Neuer Agent mit mutierten Parametern
    """
    hints = _load_strategy_hints() if use_strategy_hints else {}
    new_params = {}
    mutations_applied = 0
    hint_notes = []

    for key, (low, high) in PARAM_RANGES.items():
        current = parent.params.get(key, DEFAULT_PARAMS.get(key, (low + high) / 2))

        if random.random() < mutation_rate:
            spread = (high - low) * mutation_strength

            # Strategy-Hint anwenden: Gauss-Mittelwert in Hint-Richtung verschieben
            hint = hints.get(key)
            if hint and hint.get("direction") in ("up", "down"):
                strength = float(hint.get("strength", 0.5))
                bias = spread * strength
                if hint["direction"] == "up":
                    delta = random.gauss(bias, spread)
                else:
                    delta = random.gauss(-bias, spread)
                hint_notes.append(f"{key}:{hint['direction']}")
            else:
                # Standard: Gauss'sche Mutation um aktuellen Wert
                delta = random.gauss(0, spread)

            new_val = current + delta
            new_val = max(low, min(high, new_val))
            new_params[key] = round(new_val, 4)
            mutations_applied += 1
        else:
            new_params[key] = round(current, 4)

    hint_suffix = f" [hints: {','.join(hint_notes)}]" if hint_notes else ""
    child = Agent(
        agent_id=f"AG-{uuid.uuid4().hex[:8].upper()}",
        generation=generation,
        params=new_params,
        parent_ids=[parent.agent_id],
        notes=f"Mutiert von {parent.agent_id} ({mutations_applied} Params){hint_suffix}",
    )
    return child


def crossover(
    parent_a: Agent,
    parent_b: Agent,
    generation: int,
) -> Agent:
    """
    Erstelle Hybrid-Agent aus zwei Eltern (Crossover).

    Fuer jeden Parameter wird zufaellig der Wert von Elternteil A oder B
    ausgewaehlt (Uniform Crossover).

    Args:
        parent_a: Erster Eltern-Agent (bevorzugt der besser bewertete)
        parent_b: Zweiter Eltern-Agent
        generation: Neue Generation

    Returns:
        Hybrid-Agent
    """
    new_params = {}
    inherited_from = {"a": 0, "b": 0}

    for key in PARAM_RANGES:
        val_a = parent_a.params.get(key, DEFAULT_PARAMS.get(key, 0))
        val_b = parent_b.params.get(key, DEFAULT_PARAMS.get(key, 0))

        # Elternteil A hat 60% Gewicht (meist der bessere)
        if random.random() < 0.60:
            new_params[key] = round(val_a, 4)
            inherited_from["a"] += 1
        else:
            new_params[key] = round(val_b, 4)
            inherited_from["b"] += 1

    child = Agent(
        agent_id=f"AG-{uuid.uuid4().hex[:8].upper()}",
        generation=generation,
        params=new_params,
        parent_ids=[parent_a.agent_id, parent_b.agent_id],
        notes=(
            f"Crossover: {parent_a.agent_id}({inherited_from['a']}) x "
            f"{parent_b.agent_id}({inherited_from['b']})"
        ),
    )
    return child


def elite_mutate(parent: Agent, generation: int) -> Agent:
    """
    Leichte Mutation fuer Elite-Agenten (weniger aggressiv).
    Erhält die meisten guten Parameter, verändert nur 1-2.
    """
    return mutate(parent, generation, mutation_rate=0.2, mutation_strength=0.08)
