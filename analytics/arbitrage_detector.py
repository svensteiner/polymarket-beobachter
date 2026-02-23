# =============================================================================
# ARBITRAGE DETECTOR
# =============================================================================
#
# Erkennt logisch inkonsistente Wetter-Maerkte auf Polymarket.
#
# Beispiel fuer Inkonsistenz:
# - Market A: "NYC max temp > 30C" = 35% (wahrscheinlicher)
# - Market B: "NYC max temp > 25C" = 30% (weniger wahrscheinlich)
# Dies ist logisch unmoeglich: wenn 30C wahrscheinlicher ist als 25C,
# kann P(>30C) nicht hoeher sein als P(>25C).
#
# Solche Arbitrage-Chancen entstehen aus Liquiditaets-Ungleichgewichten
# und kurzfristigen Preis-Anomalien.
# =============================================================================

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class WeatherMarketInfo:
    market_id: str
    question: str
    odds_yes: float
    city: str
    threshold_f: Optional[float]
    direction: str
    resolution_date: Optional[str]


@dataclass
class ArbitrageOpportunity:
    market_id_lower: str
    market_id_higher: str
    question_lower: str
    question_higher: str
    threshold_lower_f: float
    threshold_higher_f: float
    odds_lower: float
    odds_higher: float
    city: str
    inconsistency_magnitude: float
    direction: str
    detected_at: str

    def to_dict(self) -> dict:
        return {
            "type": "ARBITRAGE_OPPORTUNITY",
            "city": self.city,
            "direction": self.direction,
            "threshold_lower_f": self.threshold_lower_f,
            "threshold_higher_f": self.threshold_higher_f,
            "odds_lower": self.odds_lower,
            "odds_higher": self.odds_higher,
            "inconsistency_magnitude": round(self.inconsistency_magnitude, 4),
            "market_id_lower": self.market_id_lower,
            "market_id_higher": self.market_id_higher,
            "question_lower": self.question_lower[:80],
            "question_higher": self.question_higher[:80],
            "detected_at": self.detected_at,
            "description": self._describe(),
        }

    def _describe(self) -> str:
        direction_word = "ueber" if self.direction == "above" else "unter"
        return (
            f"Inkonsistenz: P(temp>{self.threshold_higher_f:.0f}F) = {self.odds_higher:.1%} "
            f"> P(temp>{self.threshold_lower_f:.0f}F) = {self.odds_lower:.1%} "
            f"in {self.city}"
        )


def _extract_temperature_threshold(question: str) -> Tuple[Optional[float], str]:
    """
    Extrahiere Temperatur-Schwellenwert aus einer Market-Frage.

    Erkennt Patterns wie:
    - "exceed 100 degrees F"
    - "above 95 Fahrenheit"
    - "be at least 30 Celsius"
    - "below 32F"

    Returns:
        (threshold_in_fahrenheit, direction "above"/"below") oder (None, "")
    """
    q = question.lower()
    direction = "above"
    if any(kw in q for kw in ["below", "under", "less than", "not exceed", "cooler"]):
        direction = "below"

    patterns = [
        r"(\d+(?:\.\d+)?)\s*\u00b0?\s*fahrenheit",
        r"(\d+(?:\.\d+)?)\s*\u00b0?\s*[fF]\b",
        r"(\d+(?:\.\d+)?)\s*degrees?\s*[fF]\b",
        r"(\d+(?:\.\d+)?)\s*\u00b0?\s*celsius",
        r"(\d+(?:\.\d+)?)\s*\u00b0?\s*[cC]\b",
        r"(\d+(?:\.\d+)?)\s*degrees?\s*[cC]\b",
        r"(\d+(?:\.\d+)?)\s*degrees?",
        r"exceed[s]?\s+(\d+(?:\.\d+)?)",
        r"above\s+(\d+(?:\.\d+)?)",
        r"below\s+(\d+(?:\.\d+)?)",
        r"reach\s+(\d+(?:\.\d+)?)",
        r"at\s+least\s+(\d+(?:\.\d+)?)",
    ]

    for i, pattern in enumerate(patterns):
        m = re.search(pattern, q)
        if m:
            val = float(m.group(1))
            if "celsius" in pattern or r"\bc\b" in pattern.lower():
                val = val * 9 / 5 + 32
            elif i >= 6 and val < 50:
                val = val * 9 / 5 + 32
            return val, direction

    return None, direction


def _extract_city_from_question(question: str) -> Optional[str]:
    """Extrahiere Stadtname aus Markt-Frage."""
    known_cities = [
        "nyc", "new york city", "london", "new york", "seoul", "los angeles", "chicago", "miami",
        "denver", "phoenix", "seattle", "boston", "tokyo", "paris",
        "berlin", "sydney", "toronto", "houston", "atlanta", "dallas",
        "san francisco", "washington", "philadelphia", "buenos aires", "ankara",
    ]
    q_lower = question.lower()
    for city in known_cities:
        if city in q_lower:
            return city.title()
    m = re.search(r"\bin\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)", question)
    if m:
        return m.group(1)
    return None


def _extract_resolution_date(question: str) -> Optional[str]:
    """Extrahiere Aufloesungsdatum aus Frage (vereinfacht)."""
    months = r"(?:january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)"
    patterns = [
        rf"({months}\s+\d{{1,2}}(?:,\s*\d{{4}})?)",
        r"(\d{4}-\d{2}-\d{2})",
        r"(\d{1,2}/\d{1,2}/\d{2,4})",
    ]
    q_lower = question.lower()
    for pattern in patterns:
        m = re.search(pattern, q_lower)
        if m:
            return m.group(1)
    return None


def parse_market_info(
    market_id: str,
    question: str,
    odds_yes: float,
) -> Optional[WeatherMarketInfo]:
    """Parse Markt-Informationen fuer Arbitrage-Analyse."""
    threshold_f, direction = _extract_temperature_threshold(question)
    if threshold_f is None:
        return None
    city = _extract_city_from_question(question)
    if not city:
        return None
    res_date = _extract_resolution_date(question)
    return WeatherMarketInfo(
        market_id=market_id,
        question=question,
        odds_yes=odds_yes,
        city=city,
        threshold_f=threshold_f,
        direction=direction,
        resolution_date=res_date,
    )


def detect_arbitrage(
    markets: List[WeatherMarketInfo],
    min_inconsistency: float = 0.02,
) -> List[ArbitrageOpportunity]:
    """
    Erkennt Arbitrage-Moeglichkeiten in einer Liste von Wetter-Maerkten.

    Logische Constraint fuer "above" Maerkte:
    P(temp > high_threshold) <= P(temp > low_threshold)
    da der hoehere Schwellenwert schwieriger zu erreichen ist.

    Verletzung: P(temp > high_threshold) > P(temp > low_threshold) = Arbitrage

    Args:
        markets: Liste von WeatherMarketInfo Objekten
        min_inconsistency: Minimale Odds-Differenz um als Arbitrage zu gelten

    Returns:
        Liste von ArbitrageOpportunity Objekten
    """
    opportunities = []
    now = datetime.now().isoformat()

    groups: Dict[str, List[WeatherMarketInfo]] = {}
    for market in markets:
        res = market.resolution_date or "any"
        key = f"{market.city.lower()}_{market.direction}_{res}"
        if key not in groups:
            groups[key] = []
        groups[key].append(market)

    for group_key, group_markets in groups.items():
        if len(group_markets) < 2:
            continue
        sorted_markets = sorted(
            group_markets,
            key=lambda m: m.threshold_f if m.threshold_f else 0,
        )
        for i in range(len(sorted_markets)):
            for j in range(i + 1, len(sorted_markets)):
                lower = sorted_markets[i]
                higher = sorted_markets[j]
                if lower.threshold_f is None or higher.threshold_f is None:
                    continue
                if lower.direction != higher.direction:
                    continue
                if lower.direction == "above":
                    if higher.odds_yes > lower.odds_yes + min_inconsistency:
                        inconsistency = higher.odds_yes - lower.odds_yes
                        opp = ArbitrageOpportunity(
                            market_id_lower=lower.market_id,
                            market_id_higher=higher.market_id,
                            question_lower=lower.question,
                            question_higher=higher.question,
                            threshold_lower_f=lower.threshold_f,
                            threshold_higher_f=higher.threshold_f,
                            odds_lower=lower.odds_yes,
                            odds_higher=higher.odds_yes,
                            city=lower.city,
                            inconsistency_magnitude=inconsistency,
                            direction=lower.direction,
                            detected_at=now,
                        )
                        opportunities.append(opp)
                        logger.info(
                            f"ARBITRAGE: {lower.city} | "
                            f"P(>{higher.threshold_f:.0f}F)={higher.odds_yes:.1%} > "
                            f"P(>{lower.threshold_f:.0f}F)={lower.odds_yes:.1%} | "
                            f"delta={inconsistency:.2%}"
                        )
    return opportunities


def run_arbitrage_scan(
    candidates: List[Dict],
    output_file: str = "output/arbitrage_opportunities.json",
) -> List[ArbitrageOpportunity]:
    """
    Fuehre kompletten Arbitrage-Scan durch.

    Args:
        candidates: Liste von Market-Dicts (aus collector)
        output_file: Ausgabedatei

    Returns:
        Liste gefundener Moeglichkeiten
    """
    import json
    from pathlib import Path

    market_infos = []
    for c in candidates:
        market_id = c.get("market_id", "")
        question = c.get("title", c.get("question", ""))
        odds_yes = 0.5
        outcome_prices = c.get("outcomePrices")
        if outcome_prices:
            try:
                prices = json.loads(outcome_prices) if isinstance(outcome_prices, str) else outcome_prices
                if prices:
                    odds_yes = float(prices[0])
            except Exception:
                pass
        info = parse_market_info(market_id, question, odds_yes)
        if info:
            market_infos.append(info)

    logger.info(f"Arbitrage Scan: {len(market_infos)} parseable Maerkte von {len(candidates)}")
    opportunities = detect_arbitrage(market_infos)

    if opportunities:
        try:
            out_path = Path(output_file)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            result = {
                "scanned_at": datetime.now().isoformat(),
                "markets_scanned": len(market_infos),
                "opportunities_found": len(opportunities),
                "opportunities": [o.to_dict() for o in opportunities],
            }
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(result, f, indent=2, ensure_ascii=False)
            logger.info(f"Arbitrage: {len(opportunities)} Moeglichkeiten -> {output_file}")
        except OSError as e:
            logger.warning(f"Arbitrage-Output konnte nicht gespeichert werden: {e}")

    return opportunities
