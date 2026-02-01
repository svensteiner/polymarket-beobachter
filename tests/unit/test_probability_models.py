# =============================================================================
# UNIT TESTS - HONEST PROBABILITY MODELS
# =============================================================================
#
# These tests verify that the probability model interface:
# 1. NEVER returns fake/hardcoded probabilities
# 2. Properly marks unsupported markets as invalid
# 3. Enforces all invariants (valid estimate requires assumption, data sources)
# 4. Edge calculation fails gracefully when prerequisites not met
#
# =============================================================================

import pytest
from datetime import datetime

from core.probability_models import (
    HonestProbabilityEstimate,
    ModelConfidence,
    ModelType,
    UnsupportedModel,
    ProbabilityModelRouter,
    calculate_edge,
    get_honest_estimate,
)


class TestHonestProbabilityEstimate:
    """Tests for the HonestProbabilityEstimate dataclass."""

    def test_valid_estimate_requires_probability(self):
        """Valid estimate must have probability."""
        with pytest.raises(ValueError, match="valid=True but probability is None"):
            HonestProbabilityEstimate(
                valid=True,
                probability=None,
                confidence=ModelConfidence.HIGH,
                assumption="Test assumption",
                data_sources=["test_source"],
            )

    def test_valid_estimate_requires_assumption(self):
        """Valid estimate must have assumption."""
        with pytest.raises(ValueError, match="valid=True but no assumption provided"):
            HonestProbabilityEstimate(
                valid=True,
                probability=0.5,
                confidence=ModelConfidence.HIGH,
                assumption=None,
                data_sources=["test_source"],
            )

    def test_valid_estimate_requires_data_sources(self):
        """Valid estimate must have data sources."""
        with pytest.raises(ValueError, match="valid=True but no data_sources provided"):
            HonestProbabilityEstimate(
                valid=True,
                probability=0.5,
                confidence=ModelConfidence.HIGH,
                assumption="Test assumption",
                data_sources=[],
            )

    def test_valid_estimate_requires_non_none_confidence(self):
        """Valid estimate must have confidence != NONE."""
        with pytest.raises(ValueError, match="valid=True but confidence is NONE"):
            HonestProbabilityEstimate(
                valid=True,
                probability=0.5,
                confidence=ModelConfidence.NONE,
                assumption="Test assumption",
                data_sources=["test_source"],
            )

    def test_valid_estimate_probability_in_range(self):
        """Valid estimate probability must be in [0, 1]."""
        with pytest.raises(ValueError, match="probability.*not in"):
            HonestProbabilityEstimate(
                valid=True,
                probability=1.5,  # Out of range
                confidence=ModelConfidence.HIGH,
                assumption="Test assumption",
                data_sources=["test_source"],
            )

    def test_invalid_estimate_clears_probability(self):
        """Invalid estimate should have probability cleared."""
        estimate = HonestProbabilityEstimate(
            valid=False,
            probability=0.5,  # Will be cleared
            confidence=ModelConfidence.HIGH,  # Will be reset to NONE
        )
        assert estimate.probability is None
        assert estimate.confidence == ModelConfidence.NONE

    def test_invalid_factory_method(self):
        """Test the invalid() factory method."""
        estimate = HonestProbabilityEstimate.invalid(
            reason="Test reason",
            model_type=ModelType.UNSUPPORTED,
            warnings=["Warning 1"],
        )
        assert estimate.valid is False
        assert estimate.probability is None
        assert estimate.confidence == ModelConfidence.NONE
        assert estimate.reasoning == "Test reason"
        assert "Warning 1" in estimate.warnings

    def test_valid_estimate_success(self):
        """Test creating a valid estimate with all required fields."""
        estimate = HonestProbabilityEstimate(
            valid=True,
            probability=0.65,
            probability_low=0.55,
            probability_high=0.75,
            confidence=ModelConfidence.HIGH,
            model_type=ModelType.WEATHER,
            assumption="Temperature follows normal distribution around forecast",
            data_sources=["tomorrow_io_forecast", "noaa_historical"],
        )
        assert estimate.valid is True
        assert estimate.probability == 0.65
        assert estimate.confidence == ModelConfidence.HIGH

    def test_to_dict_serialization(self):
        """Test serialization to dictionary."""
        estimate = HonestProbabilityEstimate.invalid(
            reason="Test",
            model_type=ModelType.UNSUPPORTED,
        )
        d = estimate.to_dict()
        assert d["valid"] is False
        assert d["probability"] is None
        assert d["confidence"] == "NONE"
        assert d["model_type"] == "UNSUPPORTED"


class TestUnsupportedModel:
    """Tests for the UnsupportedModel."""

    def test_detects_political_markets(self):
        """Political markets should be detected as unsupported."""
        model = UnsupportedModel()

        political_markets = [
            {"title": "Will Trump win the 2024 election?"},
            {"title": "Will Biden resign before 2025?"},
            {"title": "Will the Senate pass this bill?"},
            {"title": "Republican victory in midterms"},
        ]

        for market in political_markets:
            assert model.can_estimate(market), f"Should detect: {market['title']}"
            estimate = model.estimate(market)
            assert estimate.valid is False
            assert estimate.confidence == ModelConfidence.NONE

    def test_detects_entertainment_markets(self):
        """Entertainment markets should be detected as unsupported."""
        model = UnsupportedModel()

        entertainment_markets = [
            {"title": "GTA VI released before June 2026?"},
            {"title": "Will Rihanna release an album in 2025?"},
            {"title": "Netflix stock above $500?"},
            {"title": "Taylor Swift Grammy win?"},
        ]

        for market in entertainment_markets:
            assert model.can_estimate(market), f"Should detect: {market['title']}"
            estimate = model.estimate(market)
            assert estimate.valid is False
            assert "No defensible probabilistic model" in estimate.reasoning

    def test_detects_sports_markets(self):
        """Sports markets should be detected as unsupported."""
        model = UnsupportedModel()

        sports_markets = [
            {"title": "NBA Finals winner 2025"},
            {"title": "Super Bowl champion"},
            {"title": "World Cup soccer finals"},
        ]

        for market in sports_markets:
            assert model.can_estimate(market), f"Should detect: {market['title']}"
            estimate = model.estimate(market)
            assert estimate.valid is False

    def test_detects_crypto_markets(self):
        """Crypto price markets should be detected as unsupported."""
        model = UnsupportedModel()

        crypto_markets = [
            {"title": "Bitcoin above $100k by end of year?"},
            {"title": "Ethereum price below $2000?"},
            {"title": "BTC/ETH ratio"},
        ]

        for market in crypto_markets:
            assert model.can_estimate(market), f"Should detect: {market['title']}"
            estimate = model.estimate(market)
            assert estimate.valid is False

    def test_estimate_includes_warnings(self):
        """Unsupported estimate should include helpful warnings."""
        model = UnsupportedModel()
        market = {"title": "GTA VI before Christmas?", "category": "Entertainment"}

        estimate = model.estimate(market)

        assert "Market direction: UNKNOWN" in estimate.warnings
        assert "No edge calculation possible" in estimate.warnings


class TestProbabilityModelRouter:
    """Tests for the probability model router."""

    def test_router_returns_invalid_for_unsupported(self):
        """Router should return invalid estimate for unsupported markets."""
        router = ProbabilityModelRouter()

        market = {
            "market_id": "test_123",
            "title": "Will Trump tweet about this?",
            "category": "Politics",
        }

        estimate = router.estimate(market)
        assert estimate.valid is False
        assert estimate.model_type == ModelType.UNSUPPORTED

    def test_convenience_function(self):
        """Test the get_honest_estimate convenience function."""
        market = {
            "title": "GTA VI release date speculation",
            "category": "Entertainment",
        }

        estimate = get_honest_estimate(market)
        assert estimate.valid is False


class TestEdgeCalculation:
    """Tests for edge calculation."""

    def test_edge_requires_valid_estimate(self):
        """Edge calculation requires valid probability estimate."""
        invalid_estimate = HonestProbabilityEstimate.invalid(
            reason="Test",
            model_type=ModelType.UNSUPPORTED,
        )

        edge = calculate_edge(invalid_estimate, 0.5)
        assert edge.valid is False
        assert "probability estimate is invalid" in edge.reason

    def test_edge_requires_market_probability(self):
        """Edge calculation requires known market probability."""
        valid_estimate = HonestProbabilityEstimate(
            valid=True,
            probability=0.6,
            confidence=ModelConfidence.HIGH,
            assumption="Test assumption",
            data_sources=["test"],
        )

        edge = calculate_edge(valid_estimate, None)
        assert edge.valid is False
        assert "market probability is unknown" in edge.reason

    def test_edge_requires_valid_market_probability_range(self):
        """Market probability must be in (0, 1)."""
        valid_estimate = HonestProbabilityEstimate(
            valid=True,
            probability=0.6,
            confidence=ModelConfidence.HIGH,
            assumption="Test assumption",
            data_sources=["test"],
        )

        # Test with 0
        edge = calculate_edge(valid_estimate, 0.0)
        assert edge.valid is False

        # Test with 1
        edge = calculate_edge(valid_estimate, 1.0)
        assert edge.valid is False

        # Test with negative
        edge = calculate_edge(valid_estimate, -0.5)
        assert edge.valid is False

    def test_valid_edge_calculation(self):
        """Test valid edge calculation."""
        estimate = HonestProbabilityEstimate(
            valid=True,
            probability=0.65,
            confidence=ModelConfidence.HIGH,
            assumption="Test assumption",
            data_sources=["test"],
        )

        edge = calculate_edge(estimate, 0.50)
        assert edge.valid is True
        assert edge.edge == 0.15  # 0.65 - 0.50
        assert edge.edge_percent == 30.0  # (0.15 / 0.50) * 100
        assert edge.direction == "MARKET_TOO_LOW"

    def test_edge_direction_market_too_high(self):
        """Test edge direction when market is too high."""
        estimate = HonestProbabilityEstimate(
            valid=True,
            probability=0.40,
            confidence=ModelConfidence.HIGH,
            assumption="Test assumption",
            data_sources=["test"],
        )

        edge = calculate_edge(estimate, 0.60)
        assert edge.valid is True
        assert edge.edge < 0
        assert edge.direction == "MARKET_TOO_HIGH"

    def test_edge_direction_fair(self):
        """Test edge direction when market is fair."""
        estimate = HonestProbabilityEstimate(
            valid=True,
            probability=0.50,
            confidence=ModelConfidence.HIGH,
            assumption="Test assumption",
            data_sources=["test"],
        )

        edge = calculate_edge(estimate, 0.505)  # Very close
        assert edge.valid is True
        assert edge.direction == "FAIR"


class TestNoFakeEdges:
    """Tests to ensure no fake 10% edges remain."""

    def test_no_hardcoded_probability_in_unsupported(self):
        """Unsupported model should NEVER return hardcoded probability."""
        model = UnsupportedModel()

        # Test many different markets
        test_markets = [
            {"title": "Bitcoin above $100k?"},
            {"title": "GTA VI before June?"},
            {"title": "Trump wins election?"},
            {"title": "Lakers win NBA championship?"},
            {"title": "Rihanna album release?"},
        ]

        for market in test_markets:
            estimate = model.estimate(market)

            # CRITICAL: No probability should be returned
            assert estimate.probability is None, \
                f"Market '{market['title']}' returned probability when it shouldn't"

            # CRITICAL: valid must be False
            assert estimate.valid is False, \
                f"Market '{market['title']}' marked as valid when it shouldn't be"

            # CRITICAL: confidence must be NONE
            assert estimate.confidence == ModelConfidence.NONE, \
                f"Market '{market['title']}' has non-NONE confidence"

    def test_no_identical_probabilities_across_markets(self):
        """Different markets should not all return identical probabilities."""
        # This was the bug: all markets returned 0.6/0.5 = 10% edge

        router = ProbabilityModelRouter()

        markets = [
            {"title": "Market A about politics", "category": "Politics"},
            {"title": "Market B about sports", "category": "Sports"},
            {"title": "Market C about crypto", "category": "Crypto"},
        ]

        # All unsupported markets should return invalid (no probability)
        for market in markets:
            estimate = router.estimate(market)
            assert estimate.probability is None, \
                f"Unsupported market should not return probability"

    def test_edge_cannot_be_calculated_for_unsupported(self):
        """Edge should not be calculable for unsupported markets."""
        router = ProbabilityModelRouter()

        market = {"title": "Trump approval rating?", "category": "Politics"}
        estimate = router.estimate(market)

        # Try to calculate edge with fake market probability
        edge = calculate_edge(estimate, 0.5)

        # Edge should be INVALID because estimate is invalid
        assert edge.valid is False
        assert edge.edge is None


class TestModelIntegrity:
    """Tests for overall model integrity."""

    def test_probability_claim_requires_explanation(self):
        """Every probability must have an assumption explaining it."""
        # This test ensures we can't slip in probabilities without justification

        # Try to create valid estimate without assumption
        with pytest.raises(ValueError):
            HonestProbabilityEstimate(
                valid=True,
                probability=0.6,
                confidence=ModelConfidence.MEDIUM,
                assumption="",  # Empty assumption
                data_sources=["test"],
            )

    def test_data_sources_required_for_valid_estimate(self):
        """Valid estimates must cite data sources."""
        with pytest.raises(ValueError):
            HonestProbabilityEstimate(
                valid=True,
                probability=0.6,
                confidence=ModelConfidence.MEDIUM,
                assumption="Some assumption",
                data_sources=[],  # No data sources
            )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
