# =============================================================================
# BAYESIAN MODEL WEIGHT TRACKER
# =============================================================================
#
# Verfolgt die Performance jedes Wetter-Forecast-Modells anhand des Log Score.
# Gewichte werden nach jeder Market-Resolution geupdatet.
#
# Log Score: log(p) wenn Ereignis eintritt, log(1-p) wenn nicht
# Exponential weight update: w_new = w_old * exp(lr * log_score)
#
# Gewichte werden in data/model_weights.json persistiert.
# Initial-Gewichte sind gleich (1.0 pro Modell).
#
# =============================================================================

import json
import logging
import math
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# Dateipfad fuer persistierte Gewichte
PROJECT_ROOT = Path(__file__).parent.parent
WEIGHTS_FILE = PROJECT_ROOT / "data" / "model_weights.json"

# Bekannte Modell-Namen
KNOWN_MODELS = [
    "open_meteo",
    "open_meteo_gfs",
    "met_norway",
    "openweather",
    "openweather_gfs",
    "tomorrow_io",
    "noaa",
    "noaa_gfs",
]

# Learning Rate fuer Gewichts-Update
LEARNING_RATE: float = 0.01

# Minimum- und Maximum-Gewicht (verhindert Kollaps auf ein Modell)
MIN_WEIGHT: float = 0.1
MAX_WEIGHT: float = 5.0


def _default_weights() -> Dict[str, float]:
    """Erstelle initiale Gleichgewichte fuer alle Modelle."""
    return {model: 1.0 for model in KNOWN_MODELS}


def load_weights() -> Dict[str, float]:
    """
    Lade gespeicherte Modell-Gewichte.

    Returns:
        Dict mapping model_name -> weight (1.0 = Normalgewicht)
    """
    if not WEIGHTS_FILE.exists():
        logger.info("Keine gespeicherten Gewichte gefunden, nutze Gleichgewichte")
        return _default_weights()

    try:
        with open(WEIGHTS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        weights = data.get("weights", {})
        # Fehlende Modelle mit 1.0 initialisieren
        defaults = _default_weights()
        for model in defaults:
            if model not in weights:
                weights[model] = 1.0
        return weights
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Gewichte konnten nicht geladen werden: {e}")
        return _default_weights()


def save_weights(weights: Dict[str, float], metadata: Optional[dict] = None) -> bool:
    """
    Speichere Modell-Gewichte.

    Args:
        weights: Dict mapping model_name -> weight
        metadata: Optionale Metadaten (z.B. Update-Statistiken)

    Returns:
        True wenn erfolgreich
    """
    try:
        WEIGHTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "updated_at": datetime.now().isoformat(),
            "weights": {k: round(v, 6) for k, v in weights.items()},
            "normalized": _normalize_weights(weights),
            "metadata": metadata or {},
        }
        with open(WEIGHTS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except OSError as e:
        logger.error(f"Gewichte konnten nicht gespeichert werden: {e}")
        return False


def _normalize_weights(weights: Dict[str, float]) -> Dict[str, float]:
    """Normalisiere Gewichte sodass Summe = Anzahl Modelle."""
    total = sum(weights.values())
    n = len(weights)
    if total <= 0:
        return {k: 1.0 for k in weights}
    return {k: round(v / total * n, 4) for k, v in weights.items()}


def log_score(forecast_prob: float, outcome: int) -> float:
    """
    Berechne den Log Score fuer eine Vorhersage.

    Log Score: reward for confident correct prediction.
    - log(p) wenn Ereignis eintritt (outcome=1)
    - log(1-p) wenn Ereignis nicht eintritt (outcome=0)

    Clipping auf [-10, 0] um Extremwerte zu vermeiden.

    Args:
        forecast_prob: Vorhergesagte Wahrscheinlichkeit (0.001 bis 0.999)
        outcome: Tatsaechliches Ergebnis (1 = eingetreten, 0 = nicht)

    Returns:
        Log Score (negativ, 0 = perfekt, -10 = sehr schlecht)
    """
    p = max(0.001, min(0.999, forecast_prob))
    if outcome == 1:
        score = math.log(p)
    else:
        score = math.log(1.0 - p)
    return max(-10.0, score)


def update_weights(
    weights: Dict[str, float],
    model_forecasts: Dict[str, float],
    outcome: int,
    learning_rate: float = LEARNING_RATE,
) -> Dict[str, float]:
    """
    Update Modell-Gewichte basierend auf Log Score Performance.

    Exponential weight update:
    w_new = w_old * exp(lr * log_score)

    Modelle die korrekt und confident waren werden belohnt,
    Modelle die falsch lagen werden bestraft.

    Args:
        weights: Aktuelle Gewichte
        model_forecasts: Dict mapping model_name -> forecast_probability
        outcome: Tatsaechliches Ergebnis (1 oder 0)
        learning_rate: Lernrate (0.01 = konservativ)

    Returns:
        Updated Gewichte
    """
    new_weights = dict(weights)
    updates = {}

    for model, forecast_prob in model_forecasts.items():
        if model not in new_weights:
            new_weights[model] = 1.0

        ls = log_score(forecast_prob, outcome)
        update_factor = math.exp(learning_rate * ls)
        old_w = new_weights[model]
        new_w = old_w * update_factor

        # Clip auf [MIN_WEIGHT, MAX_WEIGHT]
        new_w = max(MIN_WEIGHT, min(MAX_WEIGHT, new_w))
        new_weights[model] = new_w
        updates[model] = {
            "old_weight": round(old_w, 4),
            "log_score": round(ls, 4),
            "update_factor": round(update_factor, 4),
            "new_weight": round(new_w, 4),
        }

    logger.info(
        f"Gewichts-Update: outcome={outcome}, "
        f"models={list(model_forecasts.keys())}"
    )
    logger.debug(f"Gewichts-Details: {updates}")

    return new_weights


def get_normalized_weights() -> Dict[str, float]:
    """
    Lade und normalisiere Gewichte fuer den Ensemble-Builder.

    Returns:
        Normalisierte Gewichte (Summe = Anzahl Modelle)
    """
    weights = load_weights()
    return _normalize_weights(weights)


def record_resolution(
    model_forecasts: Dict[str, float],
    outcome: int,
    market_id: str = "",
) -> Dict[str, float]:
    """
    Verarbeite eine Market-Resolution und update Modell-Gewichte.

    Args:
        model_forecasts: Dict mapping model_name -> forecast_prob
        outcome: 1 = YES gewonnen, 0 = NO gewonnen
        market_id: Optional Market-ID fuer Logging

    Returns:
        Updated Gewichte
    """
    current_weights = load_weights()
    new_weights = update_weights(current_weights, model_forecasts, outcome)

    metadata = {
        "last_market_id": market_id,
        "last_outcome": outcome,
        "models_updated": list(model_forecasts.keys()),
    }
    save_weights(new_weights, metadata)

    logger.info(
        f"Resolution fuer {market_id}: outcome={outcome}, "
        f"Gewichte gespeichert in {WEIGHTS_FILE}"
    )
    return new_weights
