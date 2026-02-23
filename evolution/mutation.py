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

import random
import uuid
from typing import Dict, List, Optional

from evolution.agent import Agent, PARAM_RANGES, DEFAULT_PARAMS


def mutate(
    parent: Agent,
    generation: int,
    mutation_rate: float = 0.4,
    mutation_strength: float = 0.15,
) -> Agent:
    """
    Erstelle mutierten Nachfolger eines Agenten.

    Args:
        parent: Eltern-Agent
        generation: Neue Generation
        mutation_rate: Wahrscheinlichkeit dass ein Parameter mutiert (0.4 = 40%)
        mutation_strength: Max relative Aenderung pro Mutation (0.15 = +-15%)

    Returns:
        Neuer Agent mit mutierten Parametern
    """
    new_params = {}
    mutations_applied = 0

    for key, (low, high) in PARAM_RANGES.items():
        current = parent.params.get(key, DEFAULT_PARAMS.get(key, (low + high) / 2))

        if random.random() < mutation_rate:
            # Gauss'sche Mutation um aktuellen Wert
            spread = (high - low) * mutation_strength
            delta = random.gauss(0, spread)
            new_val = current + delta
            # In Range clippen
            new_val = max(low, min(high, new_val))
            new_params[key] = round(new_val, 4)
            mutations_applied += 1
        else:
            new_params[key] = round(current, 4)

    child = Agent(
        agent_id=f"AG-{uuid.uuid4().hex[:8].upper()}",
        generation=generation,
        params=new_params,
        parent_ids=[parent.agent_id],
        notes=f"Mutiert von {parent.agent_id} ({mutations_applied} Params geaendert)",
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
