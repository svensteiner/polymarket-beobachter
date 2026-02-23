# =============================================================================
# POLYMARKET FEE MODEL
# =============================================================================
#
# Polymarkets Taker-Fee ist nicht-linear.
# Bei p=0.5 (50% Markt): max Fee ~1.56%
# Bei p=0.1 oder p=0.9: Fee ~0.2%
#
# Formel: fee = 2% * p * (1-p) / 0.25
# (normalisiert auf max 2% bei p=0.5)
#
# Net Edge = Raw Edge - Taker Fee
# Nur wenn Net Edge > MIN_EDGE sollte getradet werden.
# =============================================================================

import logging

logger = logging.getLogger(__name__)

# Polymarket base taker fee rate (2%)
POLYMARKET_TAKER_FEE_RATE: float = 0.02


def polymarket_taker_fee(price: float) -> float:
    """
    Berechne die Polymarket Taker-Fee fuer einen gegebenen Marktpreis.

    Die Fee ist nicht-linear und haengt vom Marktpreis ab:
    - Bei p=0.50: Fee = 2.0% (Maximum)
    - Bei p=0.25: Fee = 1.5%
    - Bei p=0.10: Fee = 0.72%
    - Bei p=0.05: Fee = 0.38%

    Formel: fee = RATE * p * (1-p) / 0.25
    (normalisiert: bei p=0.5 gilt p*(1-p)=0.25 -> fee=RATE)

    Args:
        price: Marktpreis (0.01 bis 0.99)

    Returns:
        Fee als Dezimalzahl (z.B. 0.02 = 2%)
    """
    p = max(0.001, min(0.999, price))
    fee = POLYMARKET_TAKER_FEE_RATE * p * (1.0 - p) / 0.25
    return fee


def net_edge_after_fee(model_prob: float, market_prob: float) -> float:
    """
    Berechne den Netto-Edge nach Abzug der Polymarket Taker-Fee.

    Args:
        model_prob: Modell-Wahrscheinlichkeit (0.0 bis 1.0)
        market_prob: Markt-Wahrscheinlichkeit / Preis (0.0 bis 1.0)

    Returns:
        Netto-Edge (kann negativ sein wenn Fee > Raw Edge)
    """
    raw_edge = model_prob - market_prob
    fee = polymarket_taker_fee(market_prob)
    net = raw_edge - fee  # Netto-Edge nach Fee
    logger.debug(
        f"Fee-Aware Edge: raw={raw_edge:+.4f} fee={fee:.4f} net={net:+.4f} "
        f"(model={model_prob:.4f} market={market_prob:.4f})"
    )
    return net


def is_edge_profitable_after_fee(
    model_prob: float,
    market_prob: float,
    min_net_edge: float = 0.05,
) -> bool:
    """
    Pruefen ob Edge nach Fee noch profitabel ist.

    Args:
        model_prob: Modell-Wahrscheinlichkeit
        market_prob: Marktpreis
        min_net_edge: Minimum Netto-Edge (absolut)

    Returns:
        True wenn Netto-Edge >= min_net_edge
    """
    net = net_edge_after_fee(model_prob, market_prob)
    return net >= min_net_edge


def break_even_edge(market_prob: float) -> float:
    """
    Minimaler Raw-Edge der noetig ist um nach Fee Break-Even zu sein.

    Args:
        market_prob: Marktpreis

    Returns:
        Break-Even Raw-Edge (entspricht der Fee)
    """
    return polymarket_taker_fee(market_prob)
