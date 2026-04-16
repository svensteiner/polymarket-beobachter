# =============================================================================
# SIGNAL-TO-PROPOSAL ADAPTER
# =============================================================================
#
# Converts signals from specialized engines (Weather, Arbitrage) into
# analysis dicts that the ProposalGenerator can consume.
#
# This is the WIRING between isolated signal engines and the paper trader.
# Signals become proposals, proposals get reviewed, eligible ones paper-trade.
#
# GOVERNANCE:
# - Read-only on signals (does not modify signal logs)
# - Creates proposals with source tracking (model_type identifies origin)
# - All proposals still go through ReviewGate before paper trading
#
# =============================================================================

import logging
from typing import Optional

logger = logging.getLogger(__name__)


# =============================================================================
# WEATHER SIGNAL ADAPTER
# =============================================================================


def weather_observation_to_proposal(observation) -> Optional["Proposal"]:
    """
    Convert a WeatherObservation to a Proposal for the ProposalGenerator.

    Args:
        observation: WeatherObservation object from weather_engine

    Returns:
        Proposal object or None if observation is not actionable.
    """
    from proposals.models import Proposal, ProposalCoreCriteria, generate_proposal_id
    from datetime import datetime, timezone

    # Only process OBSERVE actions (edge detected)
    from core.weather_signal import ObservationAction
    if observation.action != ObservationAction.OBSERVE:
        return None

    market_id = observation.market_id
    if not market_id:
        return None

    model_prob = float(observation.model_probability)
    market_prob = float(observation.market_probability)
    edge = float(observation.edge)

    # OBSERVE kann sowohl starke YES- als auch starke NO-Fehlbewertungen bedeuten.
    # Der Paper-Trader waehlt spaeter ueber proposal.edge > 0 => YES, sonst NO.
    if abs(edge) <= 0:
        return None

    # Sanity-Check: Edge > 1.5 (150% relativ) ist verdaechtig → wahrscheinlich Modell-Fehler
    if edge > 1.5:
        logger.warning(f"[SANITY] Edge {edge:.3f} > 150% fuer market {market_id} - uebersprungen")
        return None

    # Create core criteria (all pass for weather observations with edge)
    core_criteria = ProposalCoreCriteria(
        liquidity_ok=True,
        volume_ok=True,
        time_to_resolution_ok=True,
        data_quality_ok=True,
    )

    # Map confidence
    confidence = getattr(observation.confidence, "value", observation.confidence) or "MEDIUM"
    if confidence not in ("LOW", "MEDIUM", "HIGH"):
        confidence = "MEDIUM"

    # Build justification
    city = getattr(observation, 'city', 'Unknown')
    forecast_f = getattr(observation, 'forecast_temperature_f', None)
    threshold_f = getattr(observation, 'threshold_temperature_f', None)

    implied_side = "YES" if edge > 0 else "NO"
    justification = f"Weather model for {city} ({implied_side})"
    if forecast_f and threshold_f:
        justification += f": Forecast {forecast_f}°F vs threshold {threshold_f}°F"

    # Collect ensemble quality warnings for downstream filtering
    warnings_list = []
    ensemble_variance = getattr(observation, "ensemble_variance", None)
    if ensemble_variance is not None:
        justification += f" | variance={ensemble_variance:.4f}"
        if ensemble_variance > 0.08:
            warnings_list.append(
                f"HIGH_VARIANCE:{ensemble_variance:.4f} (threshold 0.08)"
            )
    ensemble_source_count = getattr(observation, "ensemble_source_count", None)
    if ensemble_source_count is not None and ensemble_source_count < 2:
        warnings_list.append(
            f"LOW_SOURCE_COUNT:{ensemble_source_count} (min 2 required)"
        )

    # Pull optional enrichment fields from observation
    hours_to_res = getattr(observation, "hours_to_resolution", None)
    ens_variance = getattr(observation, "ensemble_variance", None)

    # Create proposal
    proposal = Proposal(
        proposal_id=generate_proposal_id(),
        timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") + "Z",
        market_id=market_id,
        market_question=observation.event_description or f"Weather: {city}",
        decision="TRADE",
        implied_probability=market_prob,
        model_probability=model_prob,
        edge=edge,
        core_criteria=core_criteria,
        warnings=tuple(warnings_list),
        confidence_level=confidence,
        justification_summary=justification,
        hours_to_resolution=hours_to_res,
        ensemble_variance=ens_variance,
    )

    return proposal



