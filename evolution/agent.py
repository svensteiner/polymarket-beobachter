# =============================================================================
# EVOLUTION AGENT
# =============================================================================
#
# Ein Agent repraesentiert einen Parametersatz der im Paper-Trading
# konkurriert. Jeder Agent hat:
# - Eigene Parameter (MIN_EDGE, Kelly, TP/SL etc.)
# - Eigenes Kapital-Tracking
# - Eigene Trade-History
# - Fitness-Score basierend auf Performance
#
# =============================================================================

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List

PROJECT_ROOT = Path(__file__).parent.parent
AGENTS_DIR = PROJECT_ROOT / "data" / "evolution" / "agents"


# =============================================================================
# PARAMETER RANGES (fuer Mutation/Validierung)
# =============================================================================

PARAM_RANGES: Dict[str, tuple] = {
    "min_edge":                    (0.06, 0.30),   # 6% - 30% relativer Edge
    "min_edge_absolute":           (0.02, 0.12),   # 2% - 12% absoluter Edge
    "kelly_fraction":              (0.10, 0.50),   # 10% - 50% Kelly
    "max_odds":                    (0.20, 0.55),   # 20% - 55% Max Market Price
    "take_profit_pct":             (0.08, 0.30),   # 8% - 30% Take-Profit
    "stop_loss_pct":               (0.10, 0.45),   # 10% - 45% Stop-Loss (positiv = Verlust)
    "avg_down_threshold_pct":      (0.05, 0.25),   # 5% - 25% Nachkauf-Trigger
    "variance_threshold":          (0.05, 0.35),   # Ensemble-Varianz-Schwelle
    "medium_confidence_multiplier":(1.0,  2.5),    # Edge-Multiplikator bei MEDIUM Konfidenz
    "min_liquidity":               (30.0, 500.0),  # Min USD Liquidity
}

# Standard-Parameter (aktuell verwendete Werte)
DEFAULT_PARAMS: Dict[str, float] = {
    "min_edge":                    0.12,
    "min_edge_absolute":           0.05,
    "kelly_fraction":              0.25,
    "max_odds":                    0.35,
    "take_profit_pct":             0.15,
    "stop_loss_pct":               0.25,
    "avg_down_threshold_pct":      0.10,
    "variance_threshold":          0.15,
    "medium_confidence_multiplier":1.25,
    "min_liquidity":               50.0,
}


@dataclass
class AgentFitness:
    """Fitness-Score eines Agenten."""
    profit_factor: float = 0.0
    win_rate: float = 0.0
    brier_score: Optional[float] = None
    total_pnl_eur: float = 0.0
    total_trades: int = 0
    pipeline_runs: int = 0
    composite_score: float = 0.0  # Haupt-Fitness (hoeher = besser)
    computed_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Agent:
    """
    Ein Evolutions-Agent mit eigenem Parametersatz.

    Jeder Agent konkurriert im Paper-Trading und wird nach Performance bewertet.
    """
    agent_id: str
    generation: int
    params: Dict[str, float]
    fitness: AgentFitness = field(default_factory=AgentFitness)
    parent_ids: List[str] = field(default_factory=list)
    created_at: str = ""
    status: str = "ACTIVE"  # ACTIVE, ELIMINATED, CHAMPION
    notes: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()

    @classmethod
    def create_default(cls, generation: int = 0) -> "Agent":
        """Erstelle Agenten mit Standard-Parametern."""
        return cls(
            agent_id=f"AG-{uuid.uuid4().hex[:8].upper()}",
            generation=generation,
            params=dict(DEFAULT_PARAMS),
        )

    @classmethod
    def create_random(cls, generation: int = 0, seed_params: Optional[Dict] = None) -> "Agent":
        """Erstelle Agenten mit zufaelligen Parametern innerhalb der Ranges."""
        import random
        params = {}
        base = seed_params or DEFAULT_PARAMS
        for key, (low, high) in PARAM_RANGES.items():
            if seed_params:
                # Nahe an Seed-Parametern starten (+-20%)
                center = base.get(key, (low + high) / 2)
                spread = (high - low) * 0.20
                val = center + random.uniform(-spread, spread)
            else:
                val = random.uniform(low, high)
            params[key] = round(max(low, min(high, val)), 4)
        return cls(
            agent_id=f"AG-{uuid.uuid4().hex[:8].upper()}",
            generation=generation,
            params=params,
        )

    def get_param(self, key: str) -> float:
        """Hole Parameter mit Fallback auf Default."""
        return self.params.get(key, DEFAULT_PARAMS.get(key, 0.0))

    def positions_file(self) -> Path:
        """Pfad zur positions JSONL Datei dieses Agenten."""
        return AGENTS_DIR / self.agent_id / "paper_positions.jsonl"

    def capital_file(self) -> Path:
        """Pfad zur Kapital-Datei dieses Agenten."""
        return AGENTS_DIR / self.agent_id / "capital.json"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "generation": self.generation,
            "params": self.params,
            "fitness": self.fitness.to_dict(),
            "parent_ids": self.parent_ids,
            "created_at": self.created_at,
            "status": self.status,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Agent":
        fitness_data = data.get("fitness", {})
        fitness = AgentFitness(
            profit_factor=fitness_data.get("profit_factor", 0.0),
            win_rate=fitness_data.get("win_rate", 0.0),
            brier_score=fitness_data.get("brier_score"),
            total_pnl_eur=fitness_data.get("total_pnl_eur", 0.0),
            total_trades=fitness_data.get("total_trades", 0),
            pipeline_runs=fitness_data.get("pipeline_runs", 0),
            composite_score=fitness_data.get("composite_score", 0.0),
            computed_at=fitness_data.get("computed_at", ""),
        )
        return cls(
            agent_id=data["agent_id"],
            generation=data.get("generation", 0),
            params=data.get("params", dict(DEFAULT_PARAMS)),
            fitness=fitness,
            parent_ids=data.get("parent_ids", []),
            created_at=data.get("created_at", ""),
            status=data.get("status", "ACTIVE"),
            notes=data.get("notes", ""),
        )

    def save(self) -> None:
        """Persistiere diesen Agenten."""
        agent_dir = AGENTS_DIR / self.agent_id
        agent_dir.mkdir(parents=True, exist_ok=True)
        with open(agent_dir / "agent.json", "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)

    @classmethod
    def load(cls, agent_id: str) -> Optional["Agent"]:
        """Lade Agenten aus Datei."""
        path = AGENTS_DIR / agent_id / "agent.json"
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return cls.from_dict(json.load(f))
        except Exception:
            return None
