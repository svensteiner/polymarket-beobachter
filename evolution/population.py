# =============================================================================
# POPULATION MANAGER
# =============================================================================
from __future__ import annotations
import json
import logging
import random
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any
from evolution.agent import Agent, AGENTS_DIR
from evolution.fitness import compute_fitness
from evolution.mutation import mutate, crossover, elite_mutate

logger = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).parent.parent
POPULATION_FILE = PROJECT_ROOT / "data" / "evolution" / "population.json"
HISTORY_FILE = PROJECT_ROOT / "data" / "evolution" / "history.jsonl"
DEFAULT_POPULATION_SIZE = 8
CAPITAL_PER_AGENT = 625.0
EVOLUTION_TRIGGER_RUNS = 50


class Population:
    """Verwaltet die Agenten-Population."""

    def __init__(self):
        self.agents: List[Agent] = []
        self.generation: int = 0
        self.total_runs: int = 0
        self.last_evolution: Optional[str] = None
        self.champion_id: Optional[str] = None

    def initialize(self, size: int = DEFAULT_POPULATION_SIZE) -> None:
        """Initialisiere neue Population."""
        logger.info(f"Initialisiere neue Population (Groesse={size}, Generation=0)")
        default_agent = Agent.create_default(generation=0)
        default_agent.notes = "Baseline (aktuelle Standard-Parameter)"
        self.agents = [default_agent]
        for i in range(size - 1):
            agent = Agent.create_random(generation=0)
            agent.notes = f"Initial Random #{i+1}"
            self.agents.append(agent)
        self.generation = 0
        self.total_runs = 0
        for agent in self.agents:
            self._init_agent_capital(agent)
            agent.save()
        self.save()
        logger.info(f"Population initialisiert: {[a.agent_id for a in self.agents]}")

    def _init_agent_capital(self, agent: Agent) -> None:
        """Initialisiere Kapital-Datei fuer neuen Agenten."""
        cap_file = agent.capital_file()
        cap_file.parent.mkdir(parents=True, exist_ok=True)
        if not cap_file.exists():
            capital = {
                "agent_id": agent.agent_id,
                "total_capital_eur": CAPITAL_PER_AGENT,
                "available_capital_eur": CAPITAL_PER_AGENT,
                "allocated_capital_eur": 0.0,
                "max_positions": 5,
                "max_position_size_eur": min(125.0, CAPITAL_PER_AGENT * 0.20),
                "initialized_at": datetime.now().isoformat(),
            }
            with open(cap_file, "w", encoding="utf-8") as f:
                json.dump(capital, f, indent=2)

    def score_all(self) -> None:
        for agent in self.active_agents():
            fitness = compute_fitness(agent, pipeline_runs=self.total_runs)
            agent.fitness = fitness
            agent.save()
            logger.info(f"Agent {agent.agent_id}: PF={fitness.profit_factor:.3f} WR={fitness.win_rate:.1%} Score={fitness.composite_score:.4f}")

    def active_agents(self) -> List[Agent]:
        return [a for a in self.agents if a.status == "ACTIVE"]

    def sorted_by_fitness(self) -> List[Agent]:
        active = self.active_agents()
        return sorted(active, key=lambda a: a.fitness.composite_score, reverse=True)

    def evolve(self) -> Dict[str, Any]:
        """Fuehre einen Evolutions-Schritt durch."""
        self.generation += 1
        logger.info(f"=== EVOLUTION Generation {self.generation} ===")
        self.score_all()
        ranked = self.sorted_by_fitness()
        if len(ranked) < 2:
            logger.warning("Zu wenig Agenten fuer Evolution")
            return {"status": "SKIPPED", "reason": "too_few_agents"}
        stats = {
            "generation": self.generation,
            "timestamp": datetime.now().isoformat(),
            "agents_before": len(ranked),
            "rankings": [
                {
                    "rank": i + 1,
                    "agent_id": a.agent_id,
                    "score": a.fitness.composite_score,
                    "trades": a.fitness.total_trades,
                    "pf": a.fitness.profit_factor,
                    "wr": a.fitness.win_rate,
                }
                for i, a in enumerate(ranked)
            ],
        }
        champion = ranked[0]
        if champion.fitness.total_trades >= 3:
            champion.status = "CHAMPION"
            self.champion_id = champion.agent_id
            logger.info(f"Champion: {champion.agent_id} (Score={champion.fitness.composite_score:.4f})")
        n_eliminate = min(2, max(0, len(ranked) - 3))
        eliminated = []
        for agent in ranked[-n_eliminate:]:
            if agent.fitness.total_trades < 3:
                logger.info(f"Agent {agent.agent_id} verschont ({agent.fitness.total_trades} Trades)")
                continue
            agent.status = "ELIMINATED"
            agent.save()
            eliminated.append(agent.agent_id)
            logger.info(f"ELIMINIERT: {agent.agent_id} Score={agent.fitness.composite_score:.4f}")
        stats["eliminated"] = eliminated
        new_agents = []
        top_agents = [a for a in ranked[:3] if a.fitness.composite_score > 0]
        if top_agents:
            elite_child = elite_mutate(top_agents[0], self.generation)
            self._init_agent_capital(elite_child)
            elite_child.save()
            new_agents.append(elite_child)
            logger.info(f"NEU (Elite-Mutation): {elite_child.agent_id} <- {top_agents[0].agent_id}")
        if len(top_agents) >= 2:
            cross_child = crossover(top_agents[0], top_agents[1], self.generation)
            self._init_agent_capital(cross_child)
            cross_child.save()
            new_agents.append(cross_child)
            logger.info(f"NEU (Crossover): {cross_child.agent_id} <- {top_agents[0].agent_id} x {top_agents[1].agent_id}")
        if len(top_agents) >= 2:
            random_parent = random.choice(top_agents[1:])
            random_child = mutate(random_parent, self.generation, mutation_rate=0.5, mutation_strength=0.20)
            self._init_agent_capital(random_child)
            random_child.save()
            new_agents.append(random_child)
            logger.info(f"NEU (Mutation): {random_child.agent_id} <- {random_parent.agent_id}")
        self.agents = [a for a in self.agents if a.status != "ELIMINATED"]
        self.agents.extend(new_agents)
        stats["new_agents"] = [a.agent_id for a in new_agents]
        stats["agents_after"] = len(self.active_agents())
        if champion.fitness.total_trades >= 3:
            self._export_champion_params(champion)
        self.last_evolution = datetime.now().isoformat()
        self.save()
        self._log_to_history(stats)
        logger.info(f"Evolution: {len(eliminated)} eliminiert, {len(new_agents)} neu, Pop={len(self.active_agents())}")
        return stats

    def _export_champion_params(self, champion: Agent) -> None:
        """Exportiere Champion-Parameter als JSON-Datei."""
        try:
            out_file = PROJECT_ROOT / "output" / "champion_params.json"
            out_file.parent.mkdir(parents=True, exist_ok=True)
            export = {
                "agent_id": champion.agent_id,
                "generation": champion.generation,
                "fitness": champion.fitness.to_dict(),
                "params": champion.params,
                "exported_at": datetime.now().isoformat(),
                "note": "Champion-Parameter koennen in config/weather.yaml uebernommen werden",
            }
            with open(out_file, "w", encoding="utf-8") as f:
                json.dump(export, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"Champion-Export fehlgeschlagen: {e}")

    def increment_runs(self) -> int:
        self.total_runs += 1
        if self.total_runs % EVOLUTION_TRIGGER_RUNS == 0:
            logger.info(f"Evolution-Trigger: {self.total_runs} Runs erreicht")
        return self.total_runs

    def save(self) -> None:
        """Persistiere Population-State."""
        POPULATION_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "generation": self.generation,
            "total_runs": self.total_runs,
            "last_evolution": self.last_evolution,
            "champion_id": self.champion_id,
            "agent_ids": [a.agent_id for a in self.agents],
            "updated_at": datetime.now().isoformat(),
        }
        with open(POPULATION_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    @classmethod
    def load(cls):
        """Lade Population aus Datei."""
        pop = cls()
        if not POPULATION_FILE.exists():
            logger.info("Keine Population gefunden - initialisiere neu")
            pop.initialize()
            return pop
        try:
            with open(POPULATION_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            pop.generation = data.get("generation", 0)
            pop.total_runs = data.get("total_runs", 0)
            pop.last_evolution = data.get("last_evolution")
            pop.champion_id = data.get("champion_id")
            for agent_id in data.get("agent_ids", []):
                agent = Agent.load(agent_id)
                if agent:
                    pop.agents.append(agent)
            if not pop.agents:
                logger.warning("Keine Agenten geladen - initialisiere neu")
                pop.initialize()
        except Exception as e:
            logger.error(f"Population konnte nicht geladen werden: {e}")
            pop.initialize()
        return pop

    def _log_to_history(self, stats: Dict) -> None:
        try:
            HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(HISTORY_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(stats, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def print_status(self) -> None:
        """Drucke aktuellen Population-Status."""
        ranked = self.sorted_by_fitness()
        sep = "=" * 65
        dash = "-" * 60
        print("\n" + sep)
        print(f"  EVOLUTION STATUS | Generation {self.generation} | Runs: {self.total_runs}")
        no_champ = "noch keiner"
        print(f"  Agenten: {len(self.active_agents())} aktiv | Champion: {self.champion_id or no_champ}")
        print(sep)
        print("  {:<5} {:<15} {:>7} {:>6} {:>6} {:>7} {:>4}".format(
            "Rang", "Agent-ID", "Score", "PF", "WR", "Trades", "Gen"))
        print("  " + dash)
        for i, agent in enumerate(ranked):
            fit = agent.fitness
            cm = " *" if agent.agent_id == self.champion_id else ""
            print("  {:<5} {:<15} {:>7.4f} {:>6.2f} {:>6.1%} {:>7} {:>4}{}".format(
                i+1, agent.agent_id, fit.composite_score, fit.profit_factor,
                fit.win_rate, fit.total_trades, agent.generation, cm))
        print(sep + "\n")
