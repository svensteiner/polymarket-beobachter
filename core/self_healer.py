# =============================================================================
# SELF-HEALER: Automatische Fehlererkennung und Korrektur
# =============================================================================
#
# Erkennt und repariert haeufige Probleme automatisch:
# 1. Forecast-Daten-Validierung (Garbage-in Garbage-out verhindern)
# 2. Kapital-Reconciliation (allocated vs. tatsaechlich offen)
# 3. Stale/Zombie Position Detection
# 4. Model-Probability Sanity Checks
# 5. Pipeline Health + Error-Pattern Detection
#
# Wird nach jedem Pipeline-Run aufgerufen.
# =============================================================================

import json
import logging
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------
# FORECAST VALIDATION
# -----------------------------------------------------------------------

# Reasonable temperature ranges in Fahrenheit
TEMP_MIN_F = -80.0   # Record: -89.4°C = -128.9°F (Antarctic), but -80 covers all cities
TEMP_MAX_F = 140.0   # Record: 56.7°C = 134°F (Death Valley), +6 buffer
# Reasonable daily high ranges per broad region
TEMP_DAILY_HIGH_MIN_F = -40.0
TEMP_DAILY_HIGH_MAX_F = 135.0


def validate_forecast_temperature(temp_f: float, city: str = "") -> Tuple[bool, str]:
    """
    Validate that a forecast temperature is within reasonable bounds.

    Returns:
        (is_valid, reason)
    """
    if temp_f is None:
        return False, "Temperature is None"

    if not isinstance(temp_f, (int, float)):
        return False, f"Temperature is not numeric: {type(temp_f)}"

    if temp_f != temp_f:  # NaN check
        return False, "Temperature is NaN"

    if temp_f < TEMP_MIN_F or temp_f > TEMP_MAX_F:
        return False, f"Temperature {temp_f:.1f}°F out of range [{TEMP_MIN_F}, {TEMP_MAX_F}]"

    return True, "OK"


def validate_ensemble_members(member_temps: List[float], city: str = "") -> Tuple[bool, str]:
    """
    Validate ensemble member temperatures for consistency.

    Checks:
    - All within reasonable range
    - Spread not impossibly large (>60°F = something wrong with data)
    - At least 5 members
    """
    if not member_temps or len(member_temps) < 5:
        return False, f"Too few ensemble members: {len(member_temps) if member_temps else 0}"

    for i, t in enumerate(member_temps):
        valid, reason = validate_forecast_temperature(t, city)
        if not valid:
            return False, f"Member {i}: {reason}"

    spread = max(member_temps) - min(member_temps)
    if spread > 60.0:
        return False, f"Ensemble spread {spread:.1f}°F impossibly large"

    return True, "OK"


def validate_probability(prob: float, context: str = "") -> Tuple[bool, str]:
    """Validate a probability value is reasonable."""
    if prob is None:
        return False, "Probability is None"
    if not isinstance(prob, (int, float)):
        return False, f"Probability is not numeric: {type(prob)}"
    if prob != prob:  # NaN
        return False, "Probability is NaN"
    if prob < 0.0 or prob > 1.0:
        return False, f"Probability {prob} out of [0, 1]"
    return True, "OK"


# -----------------------------------------------------------------------
# CAPITAL RECONCILIATION
# -----------------------------------------------------------------------

def reconcile_capital(base_dir: Path) -> Dict[str, Any]:
    """
    Reconcile capital_config.json against actual open positions.

    Fixes:
    - allocated_capital_eur doesn't match sum of open position costs
    - available_capital_eur doesn't match initial - allocated - realized losses

    Returns dict with changes made.
    """
    changes = {"reconciled": False, "fixes": []}

    config_path = base_dir / "data" / "capital_config.json"
    positions_path = base_dir / "paper_trader" / "logs" / "paper_positions.jsonl"

    if not config_path.exists() or not positions_path.exists():
        return changes

    try:
        with open(config_path) as f:
            config = json.load(f)

        # Load positions
        positions = []
        with open(positions_path) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        positions.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue

        # Deduplicate: keep latest version per position_id
        pos_map = {}
        for p in positions:
            pid = p.get("position_id", "")
            if pid:
                pos_map[pid] = p
        positions = list(pos_map.values())

        # Calculate actual allocated capital from OPEN positions,
        # accounting for partial exits tracked in tp_state.json
        open_positions = [p for p in positions if p.get("status") == "OPEN"]
        tp_state = {}
        try:
            tp_state_path = base_dir / "data" / "tp_state.json"
            if tp_state_path.exists():
                with open(tp_state_path) as tp_f:
                    tp_state = json.load(tp_f)
        except Exception:
            pass
        actual_allocated = 0.0
        for p in open_positions:
            cost = p.get("cost_basis_eur", 0.0)
            pid = p.get("position_id", "")
            exited_fraction = 0.0
            tp_entry = tp_state.get(pid, {})
            if isinstance(tp_entry, dict):
                exited_fraction = float(tp_entry.get("exited_fraction", 0.0))
            actual_allocated += cost * max(0.0, 1.0 - exited_fraction)

        # Calculate actual realized PnL from CLOSED positions
        closed_positions = [p for p in positions if p.get("status") in ("CLOSED", "RESOLVED")]
        actual_pnl = sum(p.get("realized_pnl_eur", 0.0) for p in closed_positions)

        stored_allocated = config.get("allocated_capital_eur", 0.0)
        stored_available = config.get("available_capital_eur", 0.0)
        stored_pnl = config.get("realized_pnl_eur", 0.0)
        initial = config.get("initial_capital_eur", 271.0)

        # Check allocated
        alloc_diff = abs(actual_allocated - stored_allocated)
        if alloc_diff > 0.01:
            changes["fixes"].append(
                f"allocated: {stored_allocated:.2f} -> {actual_allocated:.2f} (diff: {alloc_diff:.2f})"
            )
            config["allocated_capital_eur"] = actual_allocated

        # Check PnL
        pnl_diff = abs(actual_pnl - stored_pnl)
        if pnl_diff > 0.01:
            changes["fixes"].append(
                f"realized_pnl: {stored_pnl:.2f} -> {actual_pnl:.2f} (diff: {pnl_diff:.2f})"
            )
            config["realized_pnl_eur"] = actual_pnl

        # Recalculate available
        correct_available = initial - actual_allocated + actual_pnl
        avail_diff = abs(correct_available - stored_available)
        if avail_diff > 0.01:
            changes["fixes"].append(
                f"available: {stored_available:.2f} -> {correct_available:.2f} (diff: {avail_diff:.2f})"
            )
            config["available_capital_eur"] = max(0.0, correct_available)

        if changes["fixes"]:
            config["last_updated"] = datetime.now(timezone.utc).isoformat()
            config["last_updated_reason"] = f"SELF-HEAL reconciliation: {'; '.join(changes['fixes'])}"

            # Atomic write
            tmp_path = str(config_path) + ".tmp"
            with open(tmp_path, "w") as f:
                json.dump(config, f, indent=2)
            os.replace(tmp_path, str(config_path))

            changes["reconciled"] = True
            logger.warning(f"SELF-HEAL Capital Reconciliation: {changes['fixes']}")
        else:
            logger.debug("Capital reconciliation: OK, no changes needed")

    except Exception as e:
        logger.error(f"Capital reconciliation failed: {e}")
        changes["error"] = str(e)

    return changes


# -----------------------------------------------------------------------
# ZOMBIE POSITION DETECTION
# -----------------------------------------------------------------------

def detect_zombie_positions(base_dir: Path, max_age_hours: int = 120) -> List[Dict]:
    """
    Find positions that are OPEN but should have been closed.

    Zombies:
    - OPEN positions older than max_age_hours
    - OPEN positions whose market has already resolved
    """
    zombies = []
    positions_path = base_dir / "paper_trader" / "logs" / "paper_positions.jsonl"

    if not positions_path.exists():
        return zombies

    try:
        positions = []
        with open(positions_path) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        positions.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue

        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=max_age_hours)

        for p in positions:
            if p.get("status") != "OPEN":
                continue

            entry_time_str = p.get("entry_time", "")
            try:
                entry_time = datetime.fromisoformat(entry_time_str)
                if entry_time.tzinfo is None:
                    entry_time = entry_time.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                continue

            if entry_time < cutoff:
                zombies.append({
                    "position_id": p.get("position_id"),
                    "market_question": p.get("market_question", "?")[:80],
                    "age_hours": (now - entry_time).total_seconds() / 3600,
                    "cost_basis_eur": p.get("cost_basis_eur", 0),
                })

    except Exception as e:
        logger.error(f"Zombie detection failed: {e}")

    if zombies:
        logger.warning(f"SELF-HEAL: {len(zombies)} zombie positions detected (>{max_age_hours}h old)")

    return zombies


# -----------------------------------------------------------------------
# MODEL PROBABILITY SANITY CHECK
# -----------------------------------------------------------------------

def check_model_sanity(model_prob: float, market_prob: float,
                       event_type: str = "", band_width_f: float = None) -> Tuple[bool, str]:
    """
    Check if model probability makes sense relative to market probability.

    Red flags:
    - Model says P < 1% but market says P > 30% (model likely wrong)
    - Model says P > 99% but market says P < 70% (model likely wrong)
    - Extreme disagreement (>50% absolute) for non-extreme markets
    """
    valid_m, reason = validate_probability(model_prob, "model")
    if not valid_m:
        return False, reason
    valid_k, reason = validate_probability(market_prob, "market")
    if not valid_k:
        return False, reason

    abs_diff = abs(model_prob - market_prob)

    # Extreme disagreement check (verschärft)
    # Wenn Modell < 5% sagt aber Markt > 25%, ist das Modell wahrscheinlich falsch
    if model_prob < 0.05 and market_prob > 0.25:
        return False, f"Model P={model_prob:.4f} vs Market P={market_prob:.2f}: extreme under-estimation"

    # BUGFIX: Tighter check for near-zero model probabilities.
    # Model assigning <3% while market prices at >10% signals model error,
    # especially for narrow-band/exact markets where sigma=3.5°F is too wide.
    if model_prob < 0.03 and market_prob > 0.10:
        return False, (
            f"Model P={model_prob:.4f} vs Market P={market_prob:.2f}: "
            f"model near-zero while market non-trivial (likely sigma too wide for narrow band)"
        )

    if model_prob > 0.95 and market_prob < 0.50:
        return False, f"Model P={model_prob:.4f} vs Market P={market_prob:.2f}: extreme over-estimation"

    # General extreme disagreement: >40% absolute difference is suspicious
    if abs_diff > 0.40:
        return False, f"Model-Market disagreement {abs_diff:.0%} too large (model={model_prob:.4f} market={market_prob:.2f})"

    # For narrow bands, even smaller disagreements are suspicious
    if band_width_f is not None and band_width_f <= 5.0:
        if abs_diff > 0.20:
            return False, f"Narrow-band ({band_width_f:.0f}°F): {abs_diff:.0%} model-market disagreement too large"

    # Relative disagreement: if model is less than 20% of market value, model likely miscalibrated
    if market_prob > 0.05 and model_prob / market_prob < 0.20:
        return False, (
            f"Model P={model_prob:.4f} is only {model_prob/market_prob:.0%} of Market P={market_prob:.2f}: "
            f"extreme relative disagreement"
        )

    return True, "OK"


# -----------------------------------------------------------------------
# ERROR PATTERN DETECTION
# -----------------------------------------------------------------------

class ErrorPatternDetector:
    """Track error patterns across runs and trigger self-healing."""

    def __init__(self, base_dir: Path):
        self.state_file = base_dir / "data" / "error_patterns.json"
        self.state = self._load_state()

    def _load_state(self) -> Dict:
        if self.state_file.exists():
            try:
                with open(self.state_file) as f:
                    return json.load(f)
            except Exception:
                pass
        return {
            "consecutive_failures": 0,
            "last_failure_reason": None,
            "failure_categories": {},
            "last_success_time": None,
            "total_heals": 0,
        }

    def _save_state(self):
        try:
            tmp = str(self.state_file) + ".tmp"
            with open(tmp, "w") as f:
                json.dump(self.state, f, indent=2)
            os.replace(tmp, str(self.state_file))
        except Exception as e:
            logger.error(f"ErrorPatternDetector save failed: {e}")

    def record_success(self):
        """Record a successful pipeline run."""
        self.state["consecutive_failures"] = 0
        self.state["last_success_time"] = datetime.now(timezone.utc).isoformat()
        self._save_state()

    def record_failure(self, category: str, reason: str):
        """Record a pipeline failure."""
        self.state["consecutive_failures"] += 1
        self.state["last_failure_reason"] = reason
        cats = self.state["failure_categories"]
        cats[category] = cats.get(category, 0) + 1
        self._save_state()

    def should_trigger_heal(self) -> Tuple[bool, str]:
        """Check if we should trigger self-healing."""
        consec = self.state["consecutive_failures"]

        if consec >= 5:
            return True, f"5+ consecutive failures (last: {self.state['last_failure_reason']})"

        # Check if a specific category has too many failures
        for cat, count in self.state["failure_categories"].items():
            if count >= 10:
                return True, f"Category '{cat}' has {count} failures"

        return False, ""

    def record_heal(self, action: str):
        """Record that a self-healing action was taken."""
        self.state["total_heals"] = self.state.get("total_heals", 0) + 1
        self.state["failure_categories"] = {}  # Reset after heal
        logger.info(f"SELF-HEAL action #{self.state['total_heals']}: {action}")
        self._save_state()


# -----------------------------------------------------------------------
# MAIN SELF-HEAL ORCHESTRATOR
# -----------------------------------------------------------------------

def run_self_heal(base_dir: Path, run_result: Optional[Dict] = None) -> Dict[str, Any]:
    """
    Run all self-healing checks after a pipeline run.

    Called from orchestrator after each run.

    Returns:
        Dict with all healing actions taken.
    """
    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "actions": [],
        "capital_reconciliation": None,
        "zombie_count": 0,
    }

    # 1. Capital Reconciliation (every run)
    try:
        recon = reconcile_capital(base_dir)
        report["capital_reconciliation"] = recon
        if recon.get("reconciled"):
            report["actions"].append(f"Capital reconciled: {recon['fixes']}")
    except Exception as e:
        logger.error(f"Self-heal capital reconciliation failed: {e}")

    # 2. Zombie Position Detection
    try:
        zombies = detect_zombie_positions(base_dir, max_age_hours=120)
        report["zombie_count"] = len(zombies)
        if zombies:
            report["actions"].append(f"Detected {len(zombies)} zombie positions")
            # Auto-close zombies at same threshold as detection (120h)
            _auto_close_zombies(base_dir, max_age_hours=120)
    except Exception as e:
        logger.error(f"Self-heal zombie detection failed: {e}")

    # 3. Error Pattern Check
    try:
        detector = ErrorPatternDetector(base_dir)
        if run_result:
            state = run_result.get("state", "OK")
            if state == "OK":
                detector.record_success()
            else:
                detector.record_failure(
                    category=state,
                    reason=run_result.get("summary", {}).get("bot_health_summary", "unknown")
                )

        should_heal, heal_reason = detector.should_trigger_heal()
        if should_heal:
            report["actions"].append(f"Error pattern trigger: {heal_reason}")
            detector.record_heal(heal_reason)
    except Exception as e:
        logger.error(f"Self-heal error pattern check failed: {e}")

    if report["actions"]:
        logger.info(f"SELF-HEAL completed: {len(report['actions'])} actions taken")
    else:
        logger.debug("Self-heal: no actions needed")

    return report


def _auto_close_zombies(base_dir: Path, max_age_hours: int = 168):
    """Auto-close zombie positions older than max_age_hours."""
    positions_path = base_dir / "paper_trader" / "logs" / "paper_positions.jsonl"
    if not positions_path.exists():
        return

    try:
        positions = []
        with open(positions_path) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        positions.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue

        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=max_age_hours)
        closed_count = 0

        for p in positions:
            if p.get("status") != "OPEN":
                continue

            entry_time_str = p.get("entry_time", "")
            try:
                entry_time = datetime.fromisoformat(entry_time_str)
                if entry_time.tzinfo is None:
                    entry_time = entry_time.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                continue

            if entry_time < cutoff:
                p["status"] = "CLOSED"
                p["exit_time"] = now.isoformat()
                p["exit_price"] = p.get("entry_price", 0.5)
                p["exit_reason"] = "SELF-HEAL: Zombie position auto-closed"
                p["realized_pnl_eur"] = 0.0
                p["pnl_pct"] = 0.0
                closed_count += 1

        if closed_count > 0:
            with open(positions_path, "w") as f:
                for p in positions:
                    f.write(json.dumps(p) + "\n")
            logger.warning(f"SELF-HEAL: Auto-closed {closed_count} zombie positions (>{max_age_hours}h)")

    except Exception as e:
        logger.error(f"Auto-close zombies failed: {e}")
