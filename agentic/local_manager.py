"""
Local Bot Manager - OHNE Claude API Tokens

Laeuft komplett lokal:
- Prueft Bot-Status
- Schickt Telegram bei Problemen
- Einfache Regel-basierte Entscheidungen

KEINE Claude API Kosten!
"""

import json
import time
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [MANAGER] %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(PROJECT_ROOT / "logs" / "manager.log")
    ]
)
logger = logging.getLogger(__name__)

def load_env():
    env_file = PROJECT_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                key, val = line.split("=", 1)
                os.environ.setdefault(key.strip(), val.strip())

def send_telegram(msg):
    import requests
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": msg},
            timeout=10
        )
    except:
        pass

def check_health():
    """Prueft ob Bot laeuft."""
    heartbeat = PROJECT_ROOT / "heartbeat.txt"
    if not heartbeat.exists():
        return False, "Kein Heartbeat"
    
    try:
        ts = heartbeat.read_text().strip().replace("Z", "+00:00")
        last = datetime.fromisoformat(ts)
        age = (datetime.now(timezone.utc) - last).total_seconds()
        if age > 1800:  # 30 min
            return False, f"Heartbeat alt ({age/60:.0f} min)"
        return True, "OK"
    except:
        return False, "Heartbeat Fehler"

def get_capital():
    """Liest Kapital-Status."""
    cfg = PROJECT_ROOT / "data" / "capital_config.json"
    if cfg.exists():
        return json.loads(cfg.read_text())
    return {}

def run_check():
    """Ein Check-Zyklus."""
    healthy, reason = check_health()
    capital = get_capital()
    
    pnl = capital.get("realized_pnl_eur", 0)
    available = capital.get("available_capital_eur", 0)
    
    logger.info(f"Health: {reason} | P&L: {pnl:+.2f} EUR | Available: {available:.0f} EUR")
    
    # Alert bei Problemen
    if not healthy:
        send_telegram(f"⚠️ Bot Problem: {reason}")
    
    # Alert bei grossem Verlust
    if pnl < -100:
        send_telegram(f"🔴 Grosser Verlust: {pnl:.2f} EUR")
    
    return healthy

def daily_summary():
    """Taegliche Zusammenfassung."""
    capital = get_capital()
    msg = f"""📊 Tages-Summary

Available: {capital.get('available_capital_eur', 0):.0f} EUR
Allokiert: {capital.get('allocated_capital_eur', 0):.0f} EUR
P&L: {capital.get('realized_pnl_eur', 0):+.2f} EUR
"""
    send_telegram(msg)
    logger.info("Daily summary sent")

def main():
    load_env()
    logger.info("Local Manager gestartet")
    send_telegram("🤖 Bot Manager gestartet (lokal, keine API Kosten)")
    
    last_daily = None
    
    while True:
        try:
            run_check()
            
            # Daily um 8 Uhr
            now = datetime.now()
            if now.hour == 8 and last_daily != now.date():
                daily_summary()
                last_daily = now.date()
                
        except Exception as e:
            logger.error(f"Error: {e}")
        
        time.sleep(30 * 60)  # 30 min

if __name__ == "__main__":
    main()
