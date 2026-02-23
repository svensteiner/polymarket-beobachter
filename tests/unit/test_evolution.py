# =============================================================================
# TESTS Fuer EVOLUTION FRAMEWORK
# =============================================================================

import pytest
from evolution.agent import Agent, DEFAULT_PARAMS, PARAM_RANGES


class TestAgent:
    def test_default_agent_has_correct_params(self):
        a = Agent.create_default()
        assert a.params["min_edge"] == DEFAULT_PARAMS["min_edge"]
        assert a.generation == 0
        assert a.status == "ACTIVE"

    def test_random_agent_params_in_range(self):
        a = Agent.create_random()
        for key, (low, high) in PARAM_RANGES.items():
            val = a.params[key]
            assert low <= val <= high, f"{key}={val} out of range [{low},{high}]"

    def test_agent_serialization(self):
        a = Agent.create_default()
        d = a.to_dict()
        b = Agent.from_dict(d)
        assert b.agent_id == a.agent_id
        assert b.params == a.params

    def test_agent_id_unique(self):
        ids = {Agent.create_random().agent_id for _ in range(20)}
        assert len(ids) == 20


class TestMutation:
    def test_mutate_produces_new_agent(self):
        from evolution.mutation import mutate
        parent = Agent.create_default()
        child = mutate(parent, generation=1)
        assert child.agent_id != parent.agent_id
        assert parent.agent_id in child.parent_ids
        assert child.generation == 1

    def test_mutated_params_in_range(self):
        from evolution.mutation import mutate
        parent = Agent.create_default()
        for _ in range(20):
            child = mutate(parent, generation=1, mutation_rate=1.0)
            for key, (low, high) in PARAM_RANGES.items():
                assert low <= child.params[key] <= high

    def test_crossover_inherits_from_both(self):
        from evolution.mutation import crossover
        a = Agent.create_default()
        b = Agent.create_random()
        child = crossover(a, b, generation=1)
        assert a.agent_id in child.parent_ids
        assert b.agent_id in child.parent_ids
        for key in PARAM_RANGES:
            val = child.params[key]
            assert val == a.params[key] or val == b.params[key]

    def test_elite_mutate_small_changes(self):
        from evolution.mutation import elite_mutate
        parent = Agent.create_default()
        total_norm_diff = 0
        for _ in range(10):
            child = elite_mutate(parent, generation=1)
            for key, (low, high) in PARAM_RANGES.items():
                param_range = high - low
                norm_diff = abs(child.params[key] - parent.params[key]) / param_range
                total_norm_diff += norm_diff
        avg_norm_diff = total_norm_diff / (10 * len(PARAM_RANGES))
        # Elite mutation should change params by < 10% of their range on average
        assert avg_norm_diff < 0.10, f"Elite mutation too aggressive: avg_norm_diff={avg_norm_diff:.4f}"


class TestFitness:
    def test_fitness_empty_history(self):
        from evolution.fitness import compute_fitness
        agent = Agent.create_default()
        fitness = compute_fitness(agent, pipeline_runs=5)
        assert fitness.total_trades == 0
        assert fitness.composite_score == 0.0

    def test_composite_score_higher_with_better_pf(self):
        from evolution.fitness import _composite_score
        low = _composite_score(0.5, 0.40, 0.20, 10, 50)
        high = _composite_score(2.0, 0.60, 0.08, 10, 50)
        assert high > low

    def test_composite_penalizes_low_trades(self):
        from evolution.fitness import _composite_score
        few_trades = _composite_score(2.0, 0.60, 0.08, 2, 50)
        many_trades = _composite_score(2.0, 0.60, 0.08, 15, 50)
        assert few_trades < many_trades

    def test_composite_score_range(self):
        from evolution.fitness import _composite_score
        for pf in [0.0, 0.5, 1.0, 2.0, 5.0]:
            for wr in [0.0, 0.3, 0.5, 0.7, 1.0]:
                score = _composite_score(pf, wr, 0.10, 10, 50)
                assert 0.0 <= score <= 1.0, f"Score out of range: {score}"


class TestPopulation:
    def test_population_initialize(self, tmp_path, monkeypatch):
        from evolution import population as pop_module
        from evolution import agent as agent_module
        monkeypatch.setattr(pop_module, "POPULATION_FILE", tmp_path / "population.json")
        monkeypatch.setattr(pop_module, "HISTORY_FILE", tmp_path / "history.jsonl")
        monkeypatch.setattr(agent_module, "AGENTS_DIR", tmp_path / "agents")

        from evolution.population import Population
        pop = Population()
        pop.initialize(size=4)
        assert len(pop.agents) == 4
        assert pop.generation == 0
        assert pop.total_runs == 0

    def test_population_sorted_by_fitness(self, tmp_path, monkeypatch):
        from evolution import population as pop_module
        from evolution import agent as agent_module
        monkeypatch.setattr(pop_module, "POPULATION_FILE", tmp_path / "population.json")
        monkeypatch.setattr(pop_module, "HISTORY_FILE", tmp_path / "history.jsonl")
        monkeypatch.setattr(agent_module, "AGENTS_DIR", tmp_path / "agents")

        from evolution.population import Population
        pop = Population()
        pop.initialize(size=3)
        pop.agents[0].fitness.composite_score = 0.8
        pop.agents[1].fitness.composite_score = 0.3
        pop.agents[2].fitness.composite_score = 0.6
        ranked = pop.sorted_by_fitness()
        assert ranked[0].fitness.composite_score == 0.8
        assert ranked[-1].fitness.composite_score == 0.3
