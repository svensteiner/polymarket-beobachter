from __future__ import annotations

import json
import logging
from datetime import datetime
from enum import IntEnum
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class AgentPolicyEngine:
    """Builds an active entry policy from advisor output and segment analysis."""

    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.policy_path = self.base_dir / "data" / "agent_memory" / "active_policy.json"

    def build_and_save(self, summary: Dict[str, Any]) -> Dict[str, Any]:
        strategy_advice = self._load_json(self.base_dir / "output" / "strategy_advice.json", {})
        segment_analysis = self._load_json(self.base_dir / "output" / "segment_analysis.json", {})
        shadow_eligibility = self._load_json(self.base_dir / "output" / "shadow_eligibility.json", {})
        capital = self._load_json(self.base_dir / "data" / "capital_config.json", {})

        risk_flags = segment_analysis.get("risk_flags", {}) if isinstance(segment_analysis.get("risk_flags"), dict) else {}
        weak_cities = strategy_advice.get("weak_cities", []) if isinstance(strategy_advice.get("weak_cities"), list) else []
        risky_market_types = risk_flags.get("risky_market_types", []) if isinstance(risk_flags.get("risky_market_types"), list) else []

        policy_mode = "NORMAL"
        if summary.get("drawdown_recovery_mode") or summary.get("bot_health_guardrails_active"):
            policy_mode = "DEFENSIVE"
        if str(strategy_advice.get("mode", "")).lower() == "protect":
            policy_mode = "DEFENSIVE"

        city_cooldowns: List[str] = []
        city_cooldowns.extend(
            item.get("city", "")
            for item in weak_cities
            if _safe_float(item.get("total_pnl_eur")) <= -150.0
        )
        city_cooldowns.extend(risk_flags.get("suggested_city_cooldowns", []))
        city_cooldowns = sorted({item for item in city_cooldowns if item})

        blocked_price_bands = list(risk_flags.get("suggested_price_band_blocks", []))
        market_type_cooldowns = self._select_hard_market_type_blocks(risky_market_types, policy_mode)
        watch_market_types = [
            str(item.get("segment", ""))
            for item in risky_market_types[:3]
            if str(item.get("segment", ""))
        ]

        max_entry_price = _safe_float(risk_flags.get("suggested_max_entry_price"), 0.85)
        if policy_mode == "DEFENSIVE":
            max_entry_price = min(max_entry_price, 0.75)

        allowed_confidence = ["MEDIUM", "HIGH"]
        market_type_confidence_overrides = {}
        if policy_mode == "DEFENSIVE":
            for market_type in watch_market_types:
                if market_type not in market_type_cooldowns:
                    market_type_confidence_overrides[market_type] = "HIGH"

        base_max_open_positions = int(capital.get("max_open_positions", 5) or 5)
        if policy_mode == "DEFENSIVE":
            base_max_open_positions = min(base_max_open_positions, 3)

        pilot_whitelist = self._build_pilot_whitelist(shadow_eligibility)
        pilot_extra_slots = 1 if pilot_whitelist and policy_mode == "DEFENSIVE" else 0

        policy = {
            "generated_at": datetime.now().isoformat(),
            "mode": policy_mode,
            "max_entry_price": round(max_entry_price, 4),
            "allowed_confidence": allowed_confidence,
            "cooldown_cities": city_cooldowns,
            "blocked_price_bands": blocked_price_bands,
            "cooldown_market_types": market_type_cooldowns,
            "watch_market_types": watch_market_types,
            "market_type_confidence_overrides": market_type_confidence_overrides,
            "max_open_positions": base_max_open_positions,
            "pilot_extra_slots": pilot_extra_slots,
            "pilot_whitelist": pilot_whitelist,
            "reasons": [
                f"strategy_mode={strategy_advice.get('mode', 'observe')}",
                f"bot_health={summary.get('bot_health_status', 'UNKNOWN')}",
                f"drawdown={summary.get('drawdown_pct', 0.0):.1f}%",
            ],
        }

        self.policy_path.parent.mkdir(parents=True, exist_ok=True)
        self.policy_path.write_text(json.dumps(policy, indent=2, ensure_ascii=False), encoding="utf-8")
        return policy

    def load_active_policy(self) -> Dict[str, Any]:
        return self._load_json(self.policy_path, {})

    @staticmethod
    def _select_hard_market_type_blocks(risky_market_types: List[Dict[str, Any]], policy_mode: str) -> List[str]:
        if policy_mode != "DEFENSIVE":
            return []

        hard_blocks: List[str] = []
        for item in risky_market_types:
            market_type = str(item.get("segment", ""))
            trades = int(item.get("trades", 0) or 0)
            total_pnl = _safe_float(item.get("total_pnl_eur"))
            win_rate = _safe_float(item.get("win_rate_pct"))
            stop_loss_ratio = _safe_float(item.get("stop_loss_ratio"))
            if (
                market_type
                and trades >= 25
                and total_pnl <= -3000.0
                and win_rate <= 2.0
                and stop_loss_ratio >= 0.80
            ):
                hard_blocks.append(market_type)
        return hard_blocks

    @staticmethod
    def _build_pilot_whitelist(shadow_eligibility: Dict[str, Any]) -> List[Dict[str, str]]:
        candidates = shadow_eligibility.get("top_candidates", [])
        if not isinstance(candidates, list):
            return []

        whitelist: List[Dict[str, str]] = []
        seen = set()
        for item in candidates:
            city = str(item.get("city", ""))
            market_type = str(item.get("market_type", ""))
            price_band = str(item.get("price_band", ""))
            if not city or not market_type or not price_band:
                continue
            key = (city.lower(), market_type.lower(), price_band)
            if key in seen:
                continue
            seen.add(key)
            whitelist.append(
                {
                    "city": city,
                    "market_type": market_type,
                    "price_band": price_band,
                }
            )
            if len(whitelist) >= 3:
                break
        return whitelist

    @staticmethod
    def _load_json(path: Path, default: Dict[str, Any]) -> Dict[str, Any]:
        if not path.exists():
            return default
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except Exception as exc:
            logger.debug("Policy JSON nicht lesbar (%s): %s", path, exc)
        return default
