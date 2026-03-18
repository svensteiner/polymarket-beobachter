from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class ActionSpec:
    key: str
    title: str
    read_only: bool
    cooldown_runs: int
    description: str


ACTION_REGISTRY: Dict[str, ActionSpec] = {
    "tighten_risk": ActionSpec(
        key="tighten_risk",
        title="Risk enger ziehen",
        read_only=True,
        cooldown_runs=2,
        description="Empfiehlt strengere Entry- oder Sizing-Regeln im naechsten Sprint.",
    ),
    "pause_city": ActionSpec(
        key="pause_city",
        title="Stadt-Cooldown",
        read_only=True,
        cooldown_runs=4,
        description="Empfiehlt einen temporaeren Cooldown fuer schwaechelnde Staedte.",
    ),
    "audit_entry_guardrails": ActionSpec(
        key="audit_entry_guardrails",
        title="Entry-Guardrails auditieren",
        read_only=True,
        cooldown_runs=1,
        description="Prueft auffaellige Entries auf Regelverletzungen oder blinde Flecken.",
    ),
    "start_shadow_experiment": ActionSpec(
        key="start_shadow_experiment",
        title="Shadow-Experiment vorbereiten",
        read_only=True,
        cooldown_runs=3,
        description="Bereitet einen Paralleltest fuer alternative Regeln vor.",
    ),
    "revert_last_change": ActionSpec(
        key="revert_last_change",
        title="Rollback pruefen",
        read_only=True,
        cooldown_runs=2,
        description="Markiert eine juengste Aenderung als Rollback-Kandidat.",
    ),
}

