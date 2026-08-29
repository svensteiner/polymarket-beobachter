"""Unit tests for analytics.basket_arbitrage — model-free dutch-book detection."""

from analytics import basket_arbitrage as ba


# --------------------------- parsing --------------------------- #
def test_parse_family_key_exact_point():
    key = ba.parse_family_key("Will the lowest temperature in Ankara be 12°C on August 29?")
    assert key == ("ankara", "lowest", "august 29")


def test_parse_family_key_highest_and_fahrenheit():
    key = ba.parse_family_key("Will the highest temperature in Miami be 95F on July 4?")
    assert key == ("miami", "highest", "july 4")


def test_parse_family_key_excludes_boundary_buckets():
    assert ba.parse_family_key("Will the lowest temperature in Ankara be 18°C or below on August 29?") is None


def test_parse_family_key_ranking_family():
    k1 = ba.parse_family_key("Will 2026 be the hottest year on record?")
    k2 = ba.parse_family_key("Will 2026 be the second-hottest year on record?")
    k3 = ba.parse_family_key("Will 2026 rank as the sixth-hottest year on record?")
    assert k1 == ("2026", "yearrank_hottest", "on record")
    assert k1 == k2 == k3          # all ranks of 2026 group into one family
    # different year is a different family
    assert ba.parse_family_key("Will 2027 be the hottest year on record?") != k1


def test_parse_family_key_rejects_unrelated():
    assert ba.parse_family_key("Will the Republican Party control the Senate?") is None
    assert ba.parse_family_key("Will a hurricane make landfall in Florida?") is None


# --------------------------- grouping --------------------------- #
def test_group_families_groups_same_city_metric_date():
    markets = [
        {"market_id": "1", "title": "Will the lowest temperature in Ankara be 11°C on August 29?", "p": 0.11},
        {"market_id": "2", "title": "Will the lowest temperature in Ankara be 12°C on August 29?", "p": 0.16},
        {"market_id": "3", "title": "Will the highest temperature in Miami be 95F on July 4?", "p": 0.30},
    ]
    fam = ba.group_families(markets, price_fn=lambda c: c["p"])
    assert len(fam) == 2
    assert len(fam[("ankara", "lowest", "august 29")]) == 2


# --------------------------- fill-aware net --------------------------- #
def test_fill_aware_positive_when_cheap_and_full():
    # 3 buckets, all fillable cheaply -> risk-free net positive
    legs = [
        ba.BasketLeg("a", "q", 0.5, real_no_ask=0.5, fee=0.0),
        ba.BasketLeg("b", "q", 0.5, real_no_ask=0.5, fee=0.0),
        ba.BasketLeg("c", "q", 0.3, real_no_ask=0.3, fee=0.0),
    ]
    cost, payoff, net, full, reason = ba.evaluate_fill_aware(legs)
    assert full is True
    assert payoff == 2                      # n-1
    assert abs(cost - 1.3) < 1e-9
    assert abs(net - 0.7) < 1e-9            # 2 - 1.3
    assert net > 0


def test_fill_aware_not_fillable_when_leg_missing():
    legs = [
        ba.BasketLeg("a", "q", 0.5, real_no_ask=0.5),
        ba.BasketLeg("b", "q", 0.5, real_no_ask=None),   # empty book
    ]
    cost, payoff, net, full, reason = ba.evaluate_fill_aware(legs)
    assert full is False
    assert net is None
    assert "not_fully_fillable" in reason


def test_fill_aware_negative_when_illiquid_asks_expensive():
    # near-certain-NO buckets cost ~0.99 to buy NO -> basket net negative
    legs = [
        ba.BasketLeg("a", "q", 0.62, real_no_ask=0.42, fee=0.0),
        ba.BasketLeg("b", "q", 0.001, real_no_ask=0.999, fee=0.0),
        ba.BasketLeg("c", "q", 0.001, real_no_ask=0.999, fee=0.0),
    ]
    cost, payoff, net, full, reason = ba.evaluate_fill_aware(legs)
    assert full is True
    assert payoff == 2
    assert net < 0                          # 2 - 2.418 < 0 -> mirage


# --------------------------- end-to-end scan (injected book) --------------------------- #
def _mk(mid, temp, p):
    return {"market_id": mid, "title": f"Will the lowest temperature in Testville be {temp}°C on May 1?", "p": p}


class _Book:
    def __init__(self, ask, depth=100.0):
        self.no_best_ask = ask
        self.ask_depth_shares = depth


def test_scan_flags_overpriced_and_marks_actionable_when_fillable_cheap():
    # sum(YES)=1.20 (overpriced); all legs fillable cheaply -> actionable
    markets = [_mk("1", 10, 0.40), _mk("2", 11, 0.40), _mk("3", 12, 0.40)]
    books = {"1": _Book(0.60), "2": _Book(0.60), "3": _Book(0.60)}
    opps = ba.scan(markets, price_fn=lambda c: c["p"],
                   book_fn=lambda mid: books[mid], fee_fn=lambda p: 0.0)
    assert len(opps) == 1
    o = opps[0]
    assert round(o.yes_sum, 3) == 1.200
    assert o.fully_fillable is True
    # cost = 1.8, payoff = 2 -> net +0.2 -> actionable
    assert o.actionable is True
    assert o.real_net_profit > 0


def test_scan_marks_not_actionable_when_books_empty():
    markets = [_mk("1", 10, 0.40), _mk("2", 11, 0.40), _mk("3", 12, 0.40)]

    class _Empty:
        no_best_ask = None
        ask_depth_shares = None

    opps = ba.scan(markets, price_fn=lambda c: c["p"],
                   book_fn=lambda mid: _Empty(), fee_fn=lambda p: 0.0)
    assert len(opps) == 1
    assert opps[0].actionable is False
    assert opps[0].fully_fillable is False


def test_scan_ignores_balanced_family():
    # sum(YES)=1.00 -> no dutch book
    markets = [_mk("1", 10, 0.34), _mk("2", 11, 0.33), _mk("3", 12, 0.33)]
    opps = ba.scan(markets, price_fn=lambda c: c["p"], book_fn=None, fee_fn=lambda p: 0.0)
    assert opps == []


def test_scan_ignores_dead_family():
    # all near-zero placeholder prices -> dead market, skip
    markets = [_mk("1", 10, 0.001), _mk("2", 11, 0.001), _mk("3", 12, 0.001)]
    opps = ba.scan(markets, price_fn=lambda c: c["p"], book_fn=None, fee_fn=lambda p: 0.0)
    assert opps == []
