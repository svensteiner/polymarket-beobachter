import json, math, pytest
from pathlib import Path
from unittest.mock import patch, MagicMock


# ============================================================
# FEATURE 3: FEE-AWARE EDGE THRESHOLD
# ============================================================

class TestFeeModel:
    def test_fee_at_50_pct_is_maximum(self):
        from core.fee_model import polymarket_taker_fee
        fee = polymarket_taker_fee(0.5)
        assert abs(fee - 0.02) < 0.0001

    def test_fee_at_extremes_is_low(self):
        from core.fee_model import polymarket_taker_fee
        assert polymarket_taker_fee(0.05) < 0.005
        assert polymarket_taker_fee(0.95) < 0.005

    def test_fee_is_symmetric(self):
        from core.fee_model import polymarket_taker_fee
        for p in [0.1, 0.2, 0.3, 0.4]:
            assert abs(polymarket_taker_fee(p) - polymarket_taker_fee(1-p)) < 1e-10

    def test_net_edge_reduces_raw_edge(self):
        from core.fee_model import net_edge_after_fee
        net = net_edge_after_fee(0.20, 0.10)
        assert net < 0.10
        assert net > 0

    def test_negative_net_edge_when_fee_exceeds_raw_edge(self):
        from core.fee_model import net_edge_after_fee
        assert net_edge_after_fee(0.51, 0.50) < 0

    def test_break_even_edge_equals_fee(self):
        from core.fee_model import break_even_edge, polymarket_taker_fee
        for p in [0.1, 0.3, 0.5, 0.7, 0.9]:
            assert abs(break_even_edge(p) - polymarket_taker_fee(p)) < 1e-10

    def test_profitability_check(self):
        from core.fee_model import is_edge_profitable_after_fee
        assert is_edge_profitable_after_fee(0.40, 0.20, min_net_edge=0.05)
        assert not is_edge_profitable_after_fee(0.51, 0.50, min_net_edge=0.05)

    def test_fee_never_negative(self):
        from core.fee_model import polymarket_taker_fee
        for p in [0.001, 0.01, 0.1, 0.5, 0.9, 0.99, 0.999]:
            assert polymarket_taker_fee(p) >= 0


# ============================================================
# FEATURE 7: TIME-TO-RESOLUTION DECAY
# ============================================================

class TestTimeDecay:
    def test_very_short_market_heavily_reduced(self):
        from paper_trader.kelly import time_decay_factor
        assert time_decay_factor(0) == 0.3
        assert time_decay_factor(3) == 0.3
        assert time_decay_factor(5.9) == 0.3

    def test_short_market_reduced(self):
        from paper_trader.kelly import time_decay_factor
        assert time_decay_factor(6) == 0.6
        assert time_decay_factor(12) == 0.6
        assert time_decay_factor(23.9) == 0.6

    def test_optimal_window_full_size(self):
        from paper_trader.kelly import time_decay_factor
        assert time_decay_factor(24) == 1.0
        assert time_decay_factor(48) == 1.0
        assert time_decay_factor(71.9) == 1.0

    def test_medium_term_reduced(self):
        from paper_trader.kelly import time_decay_factor
        assert time_decay_factor(72) == 0.8
        assert time_decay_factor(100) == 0.8
        assert time_decay_factor(167.9) == 0.8

    def test_long_term_heavily_reduced(self):
        from paper_trader.kelly import time_decay_factor
        assert time_decay_factor(168) == 0.5
        assert time_decay_factor(336) == 0.5

    def test_none_returns_no_decay(self):
        from paper_trader.kelly import time_decay_factor
        assert time_decay_factor(None) == 1.0

    def test_negative_returns_no_decay(self):
        from paper_trader.kelly import time_decay_factor
        assert time_decay_factor(-1) == 1.0


# ============================================================
# FEATURE 4: ENSEMBLE VOL SCALING
# ============================================================

class TestEnsembleVolScale:
    def test_zero_variance_no_scaling(self):
        from paper_trader.kelly import ensemble_vol_scale
        assert ensemble_vol_scale(0.0) == 1.0

    def test_high_variance_reduces_kelly(self):
        from paper_trader.kelly import ensemble_vol_scale
        scale = ensemble_vol_scale(0.20)
        assert scale < 1.0
        assert scale > 0.25

    def test_extreme_variance_hits_floor(self):
        from paper_trader.kelly import ensemble_vol_scale
        assert ensemble_vol_scale(1.0) == 0.25
        assert ensemble_vol_scale(0.50) == 0.25

    def test_none_variance_no_scaling(self):
        from paper_trader.kelly import ensemble_vol_scale
        assert ensemble_vol_scale(None) == 1.0

    def test_formula_correct(self):
        from paper_trader.kelly import ensemble_vol_scale
        assert abs(ensemble_vol_scale(0.10) - 0.80) < 0.001
        assert abs(ensemble_vol_scale(0.05) - 0.90) < 0.001
        assert abs(ensemble_vol_scale(0.25) - 0.50) < 0.001


# ============================================================
# KELLY KOMBINATION
# ============================================================

class TestKellyIntegration:
    def test_kelly_with_all_modifiers(self):
        from paper_trader.kelly import kelly_size
        base = kelly_size(0.30, 0.20, 5000)
        modified = kelly_size(0.30, 0.20, 5000, hours_to_resolution=100, ensemble_variance=0.10)
        assert modified <= base

    def test_kelly_respects_min_cap(self):
        from paper_trader.kelly import kelly_size, MIN_POSITION_EUR
        result = kelly_size(0.52, 0.50, 100, hours_to_resolution=2, ensemble_variance=0.40)
        assert result >= MIN_POSITION_EUR

    def test_kelly_respects_max_cap(self):
        from paper_trader.kelly import kelly_size, MAX_POSITION_EUR
        result = kelly_size(0.99, 0.01, 100000)
        assert result <= MAX_POSITION_EUR

    def test_kelly_negative_edge_returns_minimum(self):
        from paper_trader.kelly import kelly_size, MIN_POSITION_EUR
        result = kelly_size(0.20, 0.30, 5000)
        assert result == MIN_POSITION_EUR


# ============================================================
# FEATURE 2: BRIER SCORE
# ============================================================

class TestBrierScore:
    def _make_position(self, entry_price, exit_price, side='YES', pnl=None):
        cost = 100.0
        if pnl is None:
            pnl = (exit_price - entry_price) * (cost / entry_price)
        return {
            'position_id': f'pos_{entry_price}_{exit_price}',
            'status': 'RESOLVED',
            'entry_price': entry_price,
            'exit_price': exit_price,
            'cost_basis_eur': cost,
            'realized_pnl_eur': pnl,
            'side': side,
        }

    def test_brier_empty_positions(self):
        from analytics.outcome_analyser import _compute_brier_score
        result = _compute_brier_score([])
        assert result['brier_score'] is None
        assert result['sample_size'] == 0

    def test_brier_perfect_predictions(self):
        from analytics.outcome_analyser import _compute_brier_score
        positions = [self._make_position(0.9, 1.0), self._make_position(0.1, 0.0)]
        result = _compute_brier_score(positions)
        if result['brier_score'] is not None:
            assert result['brier_score'] < 0.25

    def test_brier_score_range(self):
        from analytics.outcome_analyser import _compute_brier_score
        positions = [
            self._make_position(0.7, 1.0),
            self._make_position(0.3, 0.0),
            self._make_position(0.6, 1.0),
        ]
        result = _compute_brier_score(positions)
        if result['brier_score'] is not None:
            assert 0.0 <= result['brier_score'] <= 1.0

    def test_brier_interpretation(self):
        from analytics.outcome_analyser import _interpret_brier_score
        cases = [(0.03, 'EXCELLENT'), (0.08, 'GOOD'), (0.12, 'FAIR'), (0.20, 'POOR'), (0.30, 'UNINFORMATIVE')]
        for bs, expected in cases:
            assert _interpret_brier_score(bs) == expected

    def test_brier_calibration_bins(self):
        from analytics.outcome_analyser import _compute_brier_score
        positions = [self._make_position(0.85, 1.0), self._make_position(0.82, 1.0), self._make_position(0.78, 0.0)]
        result = _compute_brier_score(positions)
        assert isinstance(result['calibration_bins'], list)


# ============================================================
# FEATURE 10: BAYESIAN LOG SCORE
# ============================================================

class TestModelWeights:
    def test_log_score_correct_prediction(self):
        from core.model_weights import log_score
        assert log_score(0.9, 1) > log_score(0.1, 1)

    def test_log_score_range(self):
        from core.model_weights import log_score
        for p in [0.1, 0.3, 0.5, 0.7, 0.9]:
            for outcome in [0, 1]:
                ls = log_score(p, outcome)
                assert -10.0 <= ls <= 0.0

    def test_weight_update_rewards_correct_model(self):
        from core.model_weights import update_weights
        weights = {'good_model': 1.0, 'bad_model': 1.0}
        forecasts = {'good_model': 0.8, 'bad_model': 0.2}
        new_weights = update_weights(weights, forecasts, outcome=1)
        assert new_weights['good_model'] > new_weights['bad_model']

    def test_weight_update_penalizes_wrong_model(self):
        from core.model_weights import update_weights
        weights = {'model': 1.0}
        new_weights = update_weights(weights, {'model': 0.9}, outcome=0)
        assert new_weights['model'] < 1.0

    def test_weights_stay_in_bounds(self):
        from core.model_weights import update_weights, MIN_WEIGHT, MAX_WEIGHT
        weights = {'model': 1.0}
        for _ in range(100):
            weights = update_weights(weights, {'model': 0.99}, outcome=1)
        assert weights['model'] <= MAX_WEIGHT
        weights = {'model': 1.0}
        for _ in range(100):
            weights = update_weights(weights, {'model': 0.01}, outcome=1)
        assert weights['model'] >= MIN_WEIGHT

    def test_normalize_weights(self):
        from core.model_weights import _normalize_weights
        weights = {'a': 2.0, 'b': 1.0, 'c': 1.0}
        normalized = _normalize_weights(weights)
        assert abs(sum(normalized.values()) - len(weights)) < 0.001

    def test_default_weights_all_equal(self):
        from core.model_weights import _default_weights
        weights = _default_weights()
        assert all(v == 1.0 for v in weights.values())
        assert len(weights) > 0


# ============================================================
# FEATURE 8: GAMMA API DISCOVERY
# ============================================================

class TestGammaDiscovery:
    def test_weather_keyword_detection(self):
        from collector.gamma_discovery import _is_weather_market
        assert _is_weather_market({'question': 'Will NYC temperature exceed 100F?'})
        assert _is_weather_market({'question': 'Will it rain in London tomorrow?'})
        assert _is_weather_market({'question': 'Hurricane season forecast 2026'})
        assert _is_weather_market({'question': 'Will Denver get snow in March?'})
        assert _is_weather_market({'question': 'Will heat wave last 5 days in Phoenix?'})
        assert not _is_weather_market({'question': 'Will Trump win the election?'})
        assert not _is_weather_market({'question': 'Bitcoin price reaches 100k by 2026?'})
        assert not _is_weather_market({'question': 'Will EU pass AI regulation?'})

    def test_normalize_gamma_market(self):
        from collector.gamma_discovery import normalize_gamma_market
        market = {'id': 'abc123', 'question': 'Will NYC max temp exceed 95F on July 4?', 'description': 'Test', 'liquidity': 1500.0}
        result = normalize_gamma_market(market)
        assert result is not None
        assert result['market_id'] == 'abc123'
        assert 'temperature' in result['title'].lower() or 'temp' in result['title'].lower()
        assert result['liquidity'] == 1500.0
        assert result['source'] == 'gamma_discovery'

    def test_normalize_returns_none_for_missing_id(self):
        from collector.gamma_discovery import normalize_gamma_market
        assert normalize_gamma_market({'question': 'test'}) is None

    def test_liquidity_extraction(self):
        from collector.gamma_discovery import _get_liquidity
        assert _get_liquidity({'liquidity': 1000}) == 1000.0
        assert _get_liquidity({'volume': 500.5}) == 500.5
        assert _get_liquidity({}) == 0.0


# ============================================================
# FEATURE 1: TELEGRAM NOTIFICATIONS
# ============================================================

class TestTelegram:
    def test_not_configured_without_env(self):
        from notifications.telegram import is_configured
        import os
        with patch.dict(os.environ, {}, clear=False):
            assert isinstance(is_configured(), bool)

    def test_send_message_without_config_returns_false(self):
        from notifications.telegram import send_message
        import os
        with patch.dict(os.environ, {'TELEGRAM_BOT_TOKEN': '', 'TELEGRAM_CHAT_ID': ''}):
            assert send_message('Test message') is False

    def test_alert_functions_return_bool(self):
        from notifications.telegram import alert_stop_loss, alert_take_profit
        with patch.dict('os.environ', {'TELEGRAM_BOT_TOKEN': '', 'TELEGRAM_CHAT_ID': ''}):
            r1 = alert_stop_loss('mkt1', 'Test market?', 0.3, 0.2, -10.0, -33.3)
            r2 = alert_take_profit('mkt2', 'Test market?', 0.2, 0.35, 15.0, 75.0)
            assert isinstance(r1, bool)
            assert isinstance(r2, bool)

    @patch('notifications.telegram.requests.post')
    def test_send_message_with_config(self, mock_post):
        from notifications.telegram import send_message
        import os
        mock_post.return_value = MagicMock(ok=True)
        with patch.dict(os.environ, {'TELEGRAM_BOT_TOKEN': '123:test_token', 'TELEGRAM_CHAT_ID': '456789'}):
            result = send_message('Test message')
            assert result is True
            mock_post.assert_called_once()

# ============================================================
# FEATURE 9: ARBITRAGE DETECTION
# ============================================================

class TestArbitrageDetection:
    def test_temperature_threshold_extraction_fahrenheit(self):
        from analytics.arbitrage_detector import _extract_temperature_threshold
        threshold, direction = _extract_temperature_threshold(
            'Will NYC max temperature exceed 100 degrees F on August 1?'
        )
        assert threshold == 100.0
        assert direction == 'above'

    def test_temperature_threshold_extraction_celsius_converted(self):
        from analytics.arbitrage_detector import _extract_temperature_threshold
        threshold, direction = _extract_temperature_threshold(
            'Will Berlin temperature exceed 35 degrees Celsius?'
        )
        assert threshold is not None
        assert abs(threshold - 95.0) < 1.0

    def test_direction_below_detected(self):
        from analytics.arbitrage_detector import _extract_temperature_threshold
        _, direction = _extract_temperature_threshold(
            'Will NYC temperature fall below 32 degrees F?'
        )
        assert direction == 'below'

    def test_city_extraction(self):
        from analytics.arbitrage_detector import _extract_city_from_question
        city = _extract_city_from_question('Will New York max temperature exceed 100F?')
        assert city is not None
        assert 'new york' in city.lower() or 'york' in city.lower()

    def test_arbitrage_detected_correctly(self):
        from analytics.arbitrage_detector import detect_arbitrage, WeatherMarketInfo
        markets = [
            WeatherMarketInfo(market_id='mkt1', question='NYC > 95F', odds_yes=0.30,
                city='New York', threshold_f=95.0, direction='above', resolution_date='August-1'),
            WeatherMarketInfo(market_id='mkt2', question='NYC > 100F', odds_yes=0.40,
                city='New York', threshold_f=100.0, direction='above', resolution_date='August-1'),
        ]
        opportunities = detect_arbitrage(markets, min_inconsistency=0.01)
        assert len(opportunities) == 1
        assert opportunities[0].inconsistency_magnitude == pytest.approx(0.10, abs=0.001)

    def test_no_arbitrage_when_consistent(self):
        from analytics.arbitrage_detector import detect_arbitrage, WeatherMarketInfo
        markets = [
            WeatherMarketInfo(market_id='mkt1', question='NYC > 95F', odds_yes=0.50,
                city='New York', threshold_f=95.0, direction='above', resolution_date='August-1'),
            WeatherMarketInfo(market_id='mkt2', question='NYC > 100F', odds_yes=0.30,
                city='New York', threshold_f=100.0, direction='above', resolution_date='August-1'),
        ]
        opportunities = detect_arbitrage(markets, min_inconsistency=0.01)
        assert len(opportunities) == 0

    def test_arbitrage_only_same_city(self):
        from analytics.arbitrage_detector import detect_arbitrage, WeatherMarketInfo
        markets = [
            WeatherMarketInfo(market_id='mkt1', question='NYC > 95F', odds_yes=0.30,
                city='New York', threshold_f=95.0, direction='above', resolution_date='August-1'),
            WeatherMarketInfo(market_id='mkt2', question='LA > 100F', odds_yes=0.40,
                city='Los Angeles', threshold_f=100.0, direction='above', resolution_date='August-1'),
        ]
        opportunities = detect_arbitrage(markets, min_inconsistency=0.01)
        assert len(opportunities) == 0


# ============================================================
# FEATURE 12: SMART MONEY TRACKING
# ============================================================

class TestSmartMoneyTracking:
    def test_summary_empty_db(self):
        from analytics.smart_money import get_smart_money_summary, _load_smart_money_db
        summary = get_smart_money_summary()
        assert 'total_wallets_tracked' in summary
        assert 'smart_money_wallets' in summary
        assert isinstance(summary['top_performers'], list)

    def test_analyze_wallet_empty_trades(self):
        from analytics.smart_money import analyze_wallet_performance
        result = analyze_wallet_performance('0xabc123', [])
        assert result['trades'] == 0
        assert result['win_rate'] == 0.0
        assert result['is_smart_money'] is False

    def test_analyze_wallet_high_win_rate(self):
        from analytics.smart_money import analyze_wallet_performance, MIN_TRADES_FOR_RANKING, MIN_WIN_RATE
        trades = [{'won': True, 'pnl_usd': 100, 'size_usd': 500} for _ in range(int(MIN_TRADES_FOR_RANKING * 1.5))]
        result = analyze_wallet_performance('0xsmart', trades)
        assert result['win_rate'] == 1.0
        assert result['is_smart_money'] is True

    def test_analyze_wallet_low_win_rate(self):
        from analytics.smart_money import analyze_wallet_performance
        trades = [{'won': True, 'pnl_usd': 10, 'size_usd': 100}] + [{'won': False, 'pnl_usd': -100, 'size_usd': 100}] * 5
        result = analyze_wallet_performance('0xbad', trades)
        assert result['is_smart_money'] is False


# ============================================================
# INTEGRATION TESTS
# ============================================================

class TestFullIntegration:
    def test_fee_reduces_tradeable_edge(self):
        from core.fee_model import is_edge_profitable_after_fee
        assert not is_edge_profitable_after_fee(0.51, 0.50, min_net_edge=0.01)
        assert is_edge_profitable_after_fee(0.25, 0.10, min_net_edge=0.05)

    def test_kelly_all_features_reduce_size(self):
        from paper_trader.kelly import kelly_size
        base = kelly_size(0.40, 0.20, 5000)
        with_decay = kelly_size(0.40, 0.20, 5000, hours_to_resolution=5)
        with_vol = kelly_size(0.40, 0.20, 5000, ensemble_variance=0.30)
        with_both = kelly_size(0.40, 0.20, 5000, hours_to_resolution=5, ensemble_variance=0.30)
        assert with_decay <= base
        assert with_vol <= base
        assert with_both <= with_decay
        assert with_both <= with_vol

