"""Tests for analytics.city_skill — per-city model-vs-market skill + significance."""

from analytics import city_skill as cs


def _obs(mid, city, model_p, market_p, h=24.0):
    return {"market_id": mid, "city": city, "model_probability": model_p,
            "market_probability": market_p, "hours_to_resolution": h}


def test_paired_t_positive_when_model_consistently_better():
    # consistently positive with real variance -> large positive t
    diffs = [0.1, 0.0] * 30           # mean 0.05, sd>0, n=60
    t = cs._paired_t(diffs)
    assert t is not None and t > 2


def test_paired_t_none_for_zero_variance():
    # constant diffs -> variance 0 -> t undefined (must not divide by zero)
    assert cs._paired_t([0.05] * 60) is None


def test_paired_t_none_for_tiny_sample():
    assert cs._paired_t([0.1]) is None


def test_city_not_eligible_without_significance():
    # 40 markets, model marginally better but noisy -> not eligible (n<50 anyway)
    obs, res = [], {}
    for i in range(40):
        outcome = i % 2
        obs.append(_obs(str(i), "Ankara", model_p=0.5, market_p=0.5))
        res[str(i)] = outcome
    rep = cs.compute_city_skill(obs, res)
    ank = next(c for c in rep["cities"] if c["city"] == "Ankara")
    assert ank["forward_eligible"] is False
    assert rep["eligible_cities"] == []


def test_city_eligible_when_large_significant_and_hitrate():
    # 80 markets: model tracks outcome (two quality levels -> variance in diffs),
    # market fixed at 0.5 (worse Brier, worse hit) -> genuine significant edge.
    obs, res = [], {}
    for i in range(80):
        outcome = i % 2
        if i % 4 < 2:
            model_p = 0.9 if outcome == 1 else 0.1
        else:
            model_p = 0.7 if outcome == 1 else 0.3
        market_p = 0.5
        obs.append(_obs(str(i), "Testville", model_p=model_p, market_p=market_p))
        res[str(i)] = outcome
    rep = cs.compute_city_skill(obs, res)
    tv = next(c for c in rep["cities"] if c["city"] == "Testville")
    assert tv["n"] == 80
    assert tv["t_stat"] > 2
    assert tv["model_hit_rate"] > tv["market_hit_rate"]
    assert tv["forward_eligible"] is True
    assert "Testville" in rep["eligible_cities"]


def test_dedupe_keeps_nearest_lead():
    # two observations of the same market; the one nearer 24h lead is used
    obs = [_obs("m", "C", 0.9, 0.5, h=48.0), _obs("m", "C", 0.1, 0.5, h=25.0)]
    res = {"m": 0}
    rep = cs.compute_city_skill(obs, res)
    c = rep["cities"][0]
    assert c["n"] == 1
    # nearer-lead obs had model_p=0.1 vs outcome 0 -> model better than market 0.5
    assert c["skill_vs_market"] > 0
