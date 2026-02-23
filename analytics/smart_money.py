# =============================================================================
# SMART MONEY SUBGRAPH TRACKER
# =============================================================================
#
# Verfolgt grosse Wallet-Bewegungen in Wetter-Markten via Polymarket Subgraph.
# "Smart Money" = Wallets mit historisch guter Trefferquote.
#
# GraphQL API: https://api.thegraph.com/subgraphs/name/polymarket/matic-markets
# Alternative: https://clob.polymarket.com/trades
#
# WICHTIG: Nur zur Beobachtung - kein automatisches Copy-Trading!
#
# =============================================================================

import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
import requests

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
SMART_MONEY_FILE = PROJECT_ROOT / "data" / "smart_money.json"
CLOB_API_BASE = "https://clob.polymarket.com"
SUBGRAPH_URL = "https://api.thegraph.com/subgraphs/name/polymarket/matic-markets"

# Minimum Trade-Groesse um als "Smart Money" zu gelten (USD)
MIN_SMART_MONEY_SIZE_USD: float = 500.0

# Minimum Trefferquote um als "Smart Money" zu gelten
MIN_WIN_RATE: float = 0.60

# Minimum Anzahl Trades um bewertet zu werden
MIN_TRADES_FOR_RANKING: int = 5


def _load_smart_money_db() -> Dict[str, Any]:
    """Lade persistierte Smart Money Datenbank."""
    if not SMART_MONEY_FILE.exists():
        return {"wallets": {}, "updated_at": None}
    try:
        with open(SMART_MONEY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"wallets": {}, "updated_at": None}


def _save_smart_money_db(db: Dict[str, Any]) -> None:
    """Persistiere Smart Money Datenbank."""
    db["updated_at"] = datetime.now(timezone.utc).isoformat()
    SMART_MONEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(SMART_MONEY_FILE, "w", encoding="utf-8") as f:
            json.dump(db, f, indent=2, ensure_ascii=False)
    except OSError as e:
        logger.warning(f"Smart Money DB konnte nicht gespeichert werden: {e}")


def get_recent_trades_for_market(
    token_id: str,
    limit: int = 50,
    timeout: int = 10,
) -> List[Dict[str, Any]]:
    """
    Hole aktuelle Trades fuer einen Markt via CLOB API.

    Args:
        token_id: Polymarket Token ID (clobTokenIds[0] oder [1])
        limit: Max Anzahl Trades
        timeout: HTTP Timeout

    Returns:
        Liste von Trade-Dicts
    """
    try:
        resp = requests.get(
            f"{CLOB_API_BASE}/trades",
            params={"token_id": token_id, "limit": limit},
            timeout=timeout,
            headers={"User-Agent": "PolymarketWeatherBot/1.0"},
        )
        resp.raise_for_status()
        data = resp.json()
        trades = data if isinstance(data, list) else data.get("data", [])
        return trades
    except Exception as e:
        logger.debug(f"CLOB Trades fuer {token_id}: {e}")
        return []


def get_large_trades_via_subgraph(
    market_id: str,
    min_size_usd: float = MIN_SMART_MONEY_SIZE_USD,
    hours_back: int = 48,
    timeout: int = 15,
) -> List[Dict[str, Any]]:
    """
    Hole grosse Trades via Polymarket Subgraph GraphQL.

    Args:
        market_id: Polymarket Market ID
        min_size_usd: Minimale Trade-Groesse
        hours_back: Stunden rueckblickend
        timeout: HTTP Timeout

    Returns:
        Liste von grossen Trades
    """
    cutoff = int((datetime.now(timezone.utc) - timedelta(hours=hours_back)).timestamp())

    query = """
    query LargeTrades($market: String!, $minSize: BigDecimal!, $cutoff: Int!) {
      fpmmTrades(
        where: {
          fpmm: $market
          collateralAmountUSD_gt: $minSize
          creationTimestamp_gt: $cutoff
        }
        orderBy: collateralAmountUSD
        orderDirection: desc
        first: 20
      ) {
        id
        trader { id }
        outcome
        outcomeIndex
        collateralAmount
        collateralAmountUSD
        outcomeTokensTraded
        creationTimestamp
        type
      }
    }
    """
    try:
        resp = requests.post(
            SUBGRAPH_URL,
            json={
                "query": query,
                "variables": {
                    "market": market_id.lower(),
                    "minSize": str(min_size_usd),
                    "cutoff": cutoff,
                },
            },
            timeout=timeout,
            headers={"Content-Type": "application/json"},
        )
        resp.raise_for_status()
        data = resp.json()
        trades = data.get("data", {}).get("fpmmTrades", [])
        return trades
    except Exception as e:
        logger.debug(f"Subgraph Trades fuer {market_id}: {e}")
        return []


def analyze_wallet_performance(
    wallet_address: str,
    trades: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Analysiere Performance einer Wallet basierend auf bekannten Trades.

    Args:
        wallet_address: Wallet-Adresse
        trades: Liste von abgeschlossenen Trades dieser Wallet

    Returns:
        Performance-Dict mit Win-Rate, Profit etc.
    """
    if not trades:
        return {
            "wallet": wallet_address,
            "trades": 0,
            "win_rate": 0.0,
            "is_smart_money": False,
        }

    wins = [t for t in trades if t.get("won", False)]
    total = len(trades)
    win_rate = len(wins) / total if total > 0 else 0.0

    total_profit = sum(t.get("pnl_usd", 0) for t in trades)
    total_volume = sum(t.get("size_usd", 0) for t in trades)

    is_smart = (
        total >= MIN_TRADES_FOR_RANKING
        and win_rate >= MIN_WIN_RATE
    )

    return {
        "wallet": wallet_address,
        "trades": total,
        "wins": len(wins),
        "win_rate": round(win_rate, 3),
        "total_profit_usd": round(total_profit, 2),
        "total_volume_usd": round(total_volume, 2),
        "is_smart_money": is_smart,
        "last_seen": datetime.now(timezone.utc).isoformat(),
    }


def scan_market_for_smart_money(
    market_id: str,
    token_id: str,
    market_question: str = "",
) -> List[Dict[str, Any]]:
    """
    Scanne einen Markt nach Smart Money Aktivitaet.

    Args:
        market_id: Polymarket Market ID
        token_id: CLOB Token ID
        market_question: Markt-Frage (fuer Logging)

    Returns:
        Liste von Smart Money Trades
    """
    db = _load_smart_money_db()

    trades = get_recent_trades_for_market(token_id, limit=50)

    if not trades:
        trades = get_large_trades_via_subgraph(market_id, min_size_usd=MIN_SMART_MONEY_SIZE_USD)

    smart_trades = []
    for trade in trades:
        size_usd = 0.0
        for size_field in ("collateralAmountUSD", "size", "amount"):
            try:
                size_usd = float(trade.get(size_field, 0))
                if size_usd > 0:
                    break
            except (TypeError, ValueError):
                pass

        if size_usd < MIN_SMART_MONEY_SIZE_USD:
            continue

        wallet = (
            trade.get("trader", {}).get("id")
            or trade.get("maker")
            or trade.get("address", "")
        )
        if not wallet:
            continue

        wallet_info = db["wallets"].get(wallet.lower(), {})
        is_known_smart = wallet_info.get("is_smart_money", False)

        trade_info = {
            "wallet": wallet,
            "size_usd": size_usd,
            "market_id": market_id,
            "market_question": market_question[:60],
            "timestamp": trade.get("creationTimestamp", datetime.now(timezone.utc).isoformat()),
            "outcome": trade.get("outcome", trade.get("outcomeIndex", "?")),
            "is_known_smart_money": is_known_smart,
            "win_rate_historical": wallet_info.get("win_rate", 0.0),
        }
        smart_trades.append(trade_info)

        if is_known_smart:
            logger.info(
                f"SMART MONEY: {wallet[:10]}... | "
                f"{size_usd:.0f} USD | WR={wallet_info.get('win_rate', 0):.0%} | "
                f"{market_question[:40]}"
            )

    return smart_trades


def get_smart_money_summary() -> Dict[str, Any]:
    """
    Hole Summary der Smart Money Datenbank.

    Returns:
        Summary-Dict
    """
    db = _load_smart_money_db()
    wallets = db.get("wallets", {})

    smart_wallets = {
        addr: info
        for addr, info in wallets.items()
        if info.get("is_smart_money", False)
    }

    return {
        "total_wallets_tracked": len(wallets),
        "smart_money_wallets": len(smart_wallets),
        "updated_at": db.get("updated_at"),
        "top_performers": sorted(
            smart_wallets.values(),
            key=lambda x: x.get("win_rate", 0),
            reverse=True,
        )[:5],
    }
