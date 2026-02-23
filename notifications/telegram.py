# =============================================================================
# TELEGRAM NOTIFICATIONS
# =============================================================================
import logging
import os
from datetime import datetime
from typing import Optional, Dict, Any
import requests

logger = logging.getLogger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org/bot{token}"
DEFAULT_TIMEOUT = 10


def _get_config() -> tuple[Optional[str], Optional[str]]:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    return token or None, chat_id or None


def is_configured() -> bool:
    token, chat_id = _get_config()
    return bool(token and chat_id)


def send_message(
    text: str,
    parse_mode: str = "HTML",
    disable_notification: bool = False,
    timeout: int = DEFAULT_TIMEOUT,
) -> bool:
    token, chat_id = _get_config()
    if not token or not chat_id:
        logger.debug("Telegram: nicht konfiguriert, Nachricht wird ignoriert")
        return False
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text[:4096],
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
            "disable_notification": disable_notification,
        }
        resp = requests.post(url, json=payload, timeout=timeout)
        if resp.ok:
            logger.debug("Telegram: Nachricht gesendet")
            return True
        else:
            logger.warning(f"Telegram API Fehler: {resp.status_code} {resp.text[:100]}")
            return False
    except requests.exceptions.Timeout:
        logger.warning("Telegram: Timeout beim Senden")
        return False
    except Exception as e:
        logger.warning(f"Telegram: Fehler beim Senden: {e}")
        return False

# =============================================================
# HIGH-LEVEL ALERT FUNKTIONEN
# =============================================================

def alert_stop_loss(
    market_id: str,
    market_question: str,
    entry_price: float,
    exit_price: float,
    pnl_eur: float,
    pnl_pct: float,
) -> bool:
    """Sende Stop-Loss Alert (CRITICAL - sofort mit Ton)."""
    suffix = "..." if len(market_question) > 60 else ""
    i_stop = chr(0x1F534); i_pin = chr(0x1F4CD); i_q = chr(0x2753)
    i_dn = chr(0x1F4C9); i_mny = chr(0x1F4B0); i_clk = chr(0x23F0); NL = chr(10)
    t = (
        i_stop + " <b>STOP-LOSS AUSGELOEST</b>" + NL + NL
        + i_pin + " Market: <code>" + market_id[:20] + "...</code>" + NL
        + i_q + " " + market_question[:60] + suffix + NL + NL
        + i_dn + " Entry: <b>" + format(entry_price, ".3f") + "</b>" + NL
        + i_dn + " Exit:  <b>" + format(exit_price, ".3f") + "</b>" + NL
        + i_mny + " P&L: <b>" + format(pnl_eur, "+.2f") + " EUR ("
        + format(pnl_pct, "+.1f") + "%)</b>" + NL + NL
        + i_clk + " " + datetime.now().strftime("%H:%M:%S"))
    return send_message(t, disable_notification=False)

def alert_take_profit(
    market_id: str,
    market_question: str,
    entry_price: float,
    exit_price: float,
    pnl_eur: float,
    pnl_pct: float,
) -> bool:
    """Sende Take-Profit Alert (ALERT - sofort)."""
    suffix = "..." if len(market_question) > 60 else ""
    i_ok = chr(0x2705); i_pin = chr(0x1F4CD); i_q = chr(0x2753)
    i_up = chr(0x1F4C8); i_mny = chr(0x1F4B0); i_clk = chr(0x23F0); NL = chr(10)
    t = (
        i_ok + " <b>TAKE-PROFIT ERREICHT</b>" + NL + NL
        + i_pin + " Market: <code>" + market_id[:20] + "...</code>" + NL
        + i_q + " " + market_question[:60] + suffix + NL + NL
        + i_up + " Entry: <b>" + format(entry_price, ".3f") + "</b>" + NL
        + i_up + " Exit:  <b>" + format(exit_price, ".3f") + "</b>" + NL
        + i_mny + " P&L: <b>" + format(pnl_eur, "+.2f") + " EUR ("
        + format(pnl_pct, "+.1f") + "%)</b>" + NL + NL
        + i_clk + " " + datetime.now().strftime("%H:%M:%S"))
    return send_message(t, disable_notification=True)

def alert_high_edge(
    market_id: str,
    market_question: str,
    edge: float,
    model_prob: float,
    market_prob: float,
    confidence: str,
) -> bool:
    """Sende Alert wenn Edge > 20% (sehr attraktiver Trade)."""
    suffix = "..." if len(market_question) > 60 else ""
    i_tgt = chr(0x1F3AF); i_pin = chr(0x1F4CD); i_q = chr(0x2753)
    i_cht = chr(0x1F4CA); i_rob = chr(0x1F916); i_cdn = chr(0x1F4B9)
    i_clk = chr(0x23F0); NL = chr(10)
    t = (
        i_tgt + " <b>HOHER EDGE ERKANNT</b>" + NL + NL
        + i_pin + " Market: <code>" + market_id[:20] + "...</code>" + NL
        + i_q + " " + market_question[:60] + suffix + NL + NL
        + i_cht + " Edge:     <b>" + format(edge, "+.1%") + "</b>" + NL
        + i_rob + " Modell:   <b>" + format(model_prob, ".1%") + "</b>" + NL
        + i_cdn + " Markt:    <b>" + format(market_prob, ".1%") + "</b>" + NL
        + i_tgt + " Konf.:    <b>" + confidence + "</b>" + NL + NL
        + i_clk + " " + datetime.now().strftime("%H:%M:%S"))
    return send_message(t, disable_notification=True)

def alert_pipeline_error(error_msg: str, step: str = "unknown") -> bool:
    """Sende Alert bei Pipeline-Fehler (CRITICAL)."""
    i_wrn = chr(0x26A0) + chr(0xFE0F); i_pin = chr(0x1F4CD)
    i_x = chr(0x274C); i_clk = chr(0x23F0); NL = chr(10)
    t = (
        i_wrn + " <b>PIPELINE FEHLER</b>" + NL + NL
        + i_pin + " Step: <code>" + step + "</code>" + NL
        + i_x + " Fehler: " + error_msg[:200] + NL + NL
        + i_clk + " " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    return send_message(t, disable_notification=False)

def send_daily_digest(report: Dict[str, Any]) -> bool:
    """
    Sende taeglichen Performance-Digest.

    Args:
        report: Performance-Report Dict aus outcome_analyser.run_analysis()

    Returns:
        True wenn gesendet
    """
    m = report.get("metrics", {})
    d = report.get("drawdown", {})
    health = report.get("health", "NO_DATA")
    brier = report.get("calibration", {})
    n = report.get("positions_analysed", 0)
    NL = chr(10)
    health_emoji = {
        "EXCELLENT": chr(0x1F31F), "GOOD": chr(0x2705),
        "WEAK": chr(0x26A0) + chr(0xFE0F), "POOR": chr(0x1F534),
        "NO_DATA": chr(0x2753),
    }.get(health, chr(0x2753))
    brier_line = ""
    if brier.get("brier_score") is not None:
        brier_line = (
            chr(0x1F4D0) + " Brier Score: <b>" + format(brier["brier_score"], ".4f") + "</b>"
            + " [" + brier.get("interpretation", "?") + "]" + NL
        )
    i_cht = chr(0x1F4CA); i_trph = chr(0x1F3C6); i_mny = chr(0x1F4B0)
    i_up = chr(0x1F4C8); i_dn = chr(0x1F4C9); i_clk = chr(0x23F0)
    t = (
        health_emoji + " <b>TAEGLICHER DIGEST</b> - " + datetime.now().strftime("%d.%m.%Y") + NL + NL
        + i_cht + " <b>Performance (" + str(n) + " Trades)</b>" + NL
        + i_trph + " Win-Rate: <b>" + format(m.get("win_rate_pct", 0), ".1f") + "%</b> "
        + "(" + str(m.get("win_count", 0)) + "W / " + str(m.get("loss_count", 0)) + "L)" + NL
        + i_mny + " Total P&L: <b>" + format(m.get("total_pnl_eur", 0), "+.2f") + " EUR</b>" + NL
        + i_up + " Profit Factor: <b>" + format(m.get("profit_factor", 0), ".2f") + "</b>" + NL
        + i_dn + " Max Drawdown: <b>" + format(d.get("max_drawdown_pct", 0), ".1f") + "%</b>" + NL
        + brier_line + NL + i_clk + " " + datetime.now().strftime("%H:%M:%S"))
    return send_message(t, disable_notification=True)

def send_pipeline_summary(pipeline_result: Dict[str, Any]) -> bool:
    """
    Sende Pipeline-Run Summary (nur bei interessanten Events).

    Wird nur gesendet wenn:
    - Neue Positions geoeffnet
    - Positions geschlossen (P&L)
    - Fehler aufgetreten

    Args:
        pipeline_result: PipelineResult.summary Dict

    Returns:
        True wenn gesendet
    """
    entered = pipeline_result.get("paper_positions_entered", 0)
    closed = pipeline_result.get("paper_positions_closed", 0)
    pnl = pipeline_result.get("paper_pnl_eur", 0.0)
    edge_obs = pipeline_result.get("edge_observations", 0)
    state = pipeline_result.get("state", "OK")
    condition = pipeline_result.get("market_condition", "WATCH")
    if entered == 0 and closed == 0 and state == "OK":
        return False
    NL = chr(10)
    i_sig = chr(0x1F4E1); i_grn = chr(0x1F7E2); i_red = chr(0x1F534)
    i_tgt = chr(0x1F3AF); i_wrn = chr(0x26A0) + chr(0xFE0F)
    i_cht = chr(0x1F4CA); i_clk = chr(0x23F0)
    parts = [i_sig + " <b>PIPELINE RUN</b> - " + state + NL]
    if entered > 0:
        parts.append(i_grn + " Neue Positionen: <b>" + str(entered) + "</b>" + NL)
    if closed > 0:
        pnl_e = chr(0x1F4B0) if pnl >= 0 else chr(0x1F4B8)
        parts.append(i_red + " Geschlossen: <b>" + str(closed) + "</b> | "
            + pnl_e + " P&L: <b>" + format(pnl, "+.2f") + " EUR</b>" + NL)
    if edge_obs > 0:
        parts.append(i_tgt + " Edge Signale: <b>" + str(edge_obs) + "</b>" + NL)
    if state != "OK":
        parts.append(i_wrn + " Status: <b>" + state + "</b>" + NL)
    parts.append(i_cht + " Markt-Lage: <b>" + condition + "</b>" + NL)
    parts.append(i_clk + " " + datetime.now().strftime("%H:%M:%S"))
    return send_message("".join(parts), disable_notification=True)
