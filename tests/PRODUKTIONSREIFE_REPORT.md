# Produktionsreife-Report: Polymarket Weather Observer Bot

**Erstellt:** 2026-02-09
**Analysierte Version:** Weather Observer v1.0.0
**Status:** Paper Trading (Phase 1)

---

## 1. Zusammenfassung

Der Bot ist als Paper-Trading-System **solide aufgebaut**, hat aber mehrere Luecken, die vor einem produktiven Einsatz (auch als dauerhaft laufendes Paper-Trading-System) geschlossen werden muessen. Die groessten Risiken liegen bei **unkontrolliertem Daten-Wachstum** (1.8 GB Collector-Daten!), **fehlender Alerting-Integration** und **fehlender Config-Validation**.

**Gesamtbewertung: 65/100 - Guter Prototyp, aber noch nicht produktionsreif.**

---

## 2. Checkliste Deployment

| # | Punkt | Status | Details |
|---|-------|--------|---------|
| 1.1 | start_bot.bat: Auto-Restart | OK | Max 50 Restarts, dann 10 Min Pause + Counter-Reset. Sauberer Exit bei Code 0. Restart-Delay 30s. |
| 1.2 | start_bot.bat: Python-Erkennung | OK | Sucht .venv, python, py -3 in korrekter Reihenfolge. |
| 1.3 | start_bot.bat: Log-Umleitung | OK | stdout/stderr in cockpit_console.log. Restart-Events in restart.log. |
| 1.4 | start_bot.bat: UTF-8 Handling | OK | PYTHONUTF8=1, PYTHONIOENCODING=utf-8, PYTHONUNBUFFERED=1 gesetzt. |
| 1.5 | Watchdog: Heartbeat-Check | OK | Prueft alle 5 Min via Task Scheduler. MaxAge 20 Min korrekt (> 15 Min Intervall). |
| 1.6 | Watchdog: Prozess-Kill | OK | Findet Python-Prozesse mit cockpit.py im CommandLine und killt sie. Raeumt Lockfile auf. |
| 1.7 | Watchdog: Bot-Neustart | OK | Startet via start_bot.bat als Hidden Window. |
| 1.8 | Setup-Script: Task Scheduler | OK | setup_watchdog.ps1 erstellt beide Tasks, Admin-Check, alte Tasks werden entfernt. |
| 1.9 | Setup-Script: Vollstaendige Installation | FEHLT | Kein Install-Script das Python, venv, pip install, .env-Template und Verzeichnisse einrichtet. |
| 1.10 | Lockfile: Race-Condition-Schutz | OK | PID-basiert, prueft ob Prozess noch lebt (Windows ctypes + Fallback). |
| 1.11 | Lockfile: Stale-Lockfile-Cleanup | OK | Alter Lockfile wird ueberschrieben wenn PID nicht mehr lebt. |
| 1.12 | start_bot.bat: stderr-Erfassung | WARNUNG | stderr geht nur in cockpit_console.log (2>&1). Kein separates Error-Log. |

### Kritische Luecken Deployment:

**FEHLT: Install-/Bootstrap-Script**
Es gibt kein automatisiertes Setup-Script, das alles einrichtet:
- Python venv anlegen
- pip install -r requirements.txt
- .env aus .env.example kopieren
- Verzeichnisse anlegen
- Erster Testlauf

**Empfehlung (Prioritaet MITTEL):** Ein `bootstrap.bat` erstellen:
```batch
@echo off
echo [1/4] Erstelle Virtual Environment...
python -m venv .venv
echo [2/4] Installiere Abhaengigkeiten...
.venv\Scripts\pip install -r requirements.txt
echo [3/4] Erstelle .env aus Template...
if not exist ".env" copy .env.example .env
echo [4/4] Erstelle Verzeichnisse...
mkdir logs 2>nul
mkdir data 2>nul
mkdir output 2>nul
echo.
echo Setup abgeschlossen. Bitte .env Datei ausfuellen!
echo Dann starten mit: start_bot.bat
```

---

## 3. Checkliste Konfiguration

| # | Punkt | Status | Details |
|---|-------|--------|---------|
| 3.1 | Strategie-Parameter konfigurierbar | OK | weather.yaml enthaelt MIN_EDGE, MAX_ODDS, SIGMA_F etc. Keine Hardcodes im Engine-Code. |
| 3.2 | Kelly-Parameter konfigurierbar | WARNUNG | MIN_POSITION_EUR, MAX_POSITION_EUR, KELLY_FRACTION sind als Python-Konstanten in kelly.py hardcoded, nicht in Config-Datei. |
| 3.3 | Take-Profit/Stop-Loss konfigurierbar | WARNUNG | TAKE_PROFIT_PCT=0.15 und STOP_LOSS_PCT=-0.25 sind als Klassen-Konstanten in position_manager.py hardcoded. |
| 3.4 | Diversifikation konfigurierbar | WARNUNG | MAX_POSITIONS_PER_CITY_DATE=1 und MAX_POSITIONS_PER_CITY=3 sind als Python-Konstanten in simulator.py hardcoded. |
| 3.5 | .env Handling | TEILWEISE | dotenv wird in multi_forecast.py geladen, aber nur mit try/except und python-dotenv fehlt in requirements.txt! |
| 3.6 | Config-Validation beim Start | FEHLT | Kein Code der prueft ob weather.yaml vollstaendig/gueltig ist. Fehlende Keys fuehren zu Runtime-Errors. |
| 3.7 | Environment-Variable fuer Intervall | OK | --interval Parameter am CLI. |
| 3.8 | Kapital-Config | OK | data/capital_config.json mit sauberer Struktur und Governance-Notice. |
| 3.9 | Module Config | OK | config/modules.yaml mit enable-Flags und Prioritaeten. |

### Kritische Luecken Konfiguration:

**FEHLT: python-dotenv in requirements.txt**
`core/multi_forecast.py` importiert `dotenv`, aber es fehlt in requirements.txt. Auf einem frischen System wuerde der Import still fehlschlagen (try/except) und alle API-Keys waeren leer.

**Empfehlung (Prioritaet HOCH):** In requirements.txt hinzufuegen:
```
python-dotenv>=1.0.0
```

**FEHLT: Config-Validation**
Wenn weather.yaml korrupt ist oder Keys fehlen, gibt es keinen sauberen Fehler beim Start.

**Empfehlung (Prioritaet MITTEL):** Config-Validation beim Start:
```python
# In orchestrator.py oder cockpit.py beim Start
REQUIRED_KEYS = ["MIN_EDGE", "MAX_ODDS", "MIN_LIQUIDITY", "ALLOWED_CITIES", "SIGMA_F"]

def validate_weather_config(config: dict) -> list[str]:
    """Pruefe ob alle erforderlichen Keys vorhanden sind."""
    errors = []
    for key in REQUIRED_KEYS:
        if key not in config:
            errors.append(f"Fehlender Key: {key}")
    if config.get("MIN_EDGE", 0) < 0 or config.get("MIN_EDGE", 0) > 1:
        errors.append(f"MIN_EDGE ausserhalb 0-1: {config.get('MIN_EDGE')}")
    if config.get("MAX_ODDS", 0) < config.get("MIN_ODDS", 0):
        errors.append("MAX_ODDS < MIN_ODDS")
    return errors
```

**WARNUNG: Hardcodierte Trading-Parameter**
Kelly-Sizing, TP/SL und Diversifikations-Limits sind direkt im Python-Code als Konstanten. Aenderungen erfordern Code-Edits statt Config-Anpassungen.

**Empfehlung (Prioritaet NIEDRIG):** Alle Trading-Parameter in eine zentrale Config-Datei (z.B. `config/trading.yaml`) auslagern.

---

## 4. Checkliste Monitoring & Alerting

| # | Punkt | Status | Details |
|---|-------|--------|---------|
| 4.1 | Bot Status JSON | OK | bot_status.json mit schema_version, pid, uptime, run_count, consecutive_errors, last_run Details. Atomic Write via .tmp + rename. |
| 4.2 | Heartbeat File | OK | heartbeat.txt mit ISO-Timestamp. Wird nach jedem Pipeline-Run geschrieben. |
| 4.3 | Crash Log | OK | crash.log mit Traceback, Timestamp, PID. Append-only. |
| 4.4 | Audit Trail | OK | audit/observer_YYYY-MM-DD.jsonl pro Tag. Alle Pipeline-Runs mit Steps und Ergebnissen. |
| 4.5 | Status Summary | OK | output/status_summary.txt mit Append pro Run. |
| 4.6 | Restart Log | OK | restart.log in start_bot.bat. |
| 4.7 | Watchdog Log | OK | watchdog.log mit allen Checks. |
| 4.8 | Telegram Alerting | FEHLT | .env.example hat TELEGRAM_BOT_TOKEN/CHAT_ID Felder, aber es gibt KEINEN Code der Telegram-Nachrichten sendet! proposals/__init__.py sagt explizit "No notifications (Telegram, etc.)". |
| 4.9 | Email Alerting | FEHLT | Keine Email-Benachrichtigung implementiert. |
| 4.10 | Dashboard / Status Page | FEHLT | flet ist in requirements.txt, aber kein Dashboard-Code vorhanden. |
| 4.11 | Metriken: Duration pro Run | WARNUNG | duration_seconds ist im bot_status.json immer 0 - wird offenbar nicht korrekt gemessen. |
| 4.12 | Metriken: Memory/CPU | FEHLT | Kein Monitoring von Ressourcen-Verbrauch. |

### Kritische Luecken Monitoring:

**FEHLT: Alerting bei Problemen**
Der Watchdog startet den Bot neu, aber NIEMAND wird benachrichtigt. Wenn der Bot 5x hintereinander crashed, merkt es keiner.

**Empfehlung (Prioritaet HOCH):** Minimal-Alerting im Watchdog per PowerShell:
```powershell
# In watchdog.ps1, nach Start-Bot:
function Send-Alert {
    param([string]$Message)
    $token = $env:TELEGRAM_BOT_TOKEN
    $chatId = $env:TELEGRAM_CHAT_ID
    if ($token -and $chatId) {
        $url = "https://api.telegram.org/bot$token/sendMessage"
        $body = @{ chat_id = $chatId; text = "[WeatherBot] $Message" }
        try {
            Invoke-RestMethod -Uri $url -Method Post -Body ($body | ConvertTo-Json) -ContentType "application/json" | Out-Null
        } catch {}
    }
}

# Nach Neustart-Logik:
Send-Alert "Bot war tot (Heartbeat $ageMinutes min alt). Neustart durchgefuehrt."
```

**WARNUNG: duration_seconds immer 0**
In `cockpit.py` wird `write_bot_status()` nach dem Pipeline-Run aufgerufen, aber die Duration wird aus `result.summary` gelesen, wo sie nicht berechnet wird.

**Empfehlung (Prioritaet MITTEL):** Duration in `_build_summary` berechnen:
```python
# In orchestrator.py _build_summary:
import time
# Am Anfang von run_pipeline:
self._run_start = time.monotonic()
# In _build_summary:
"duration_seconds": round(time.monotonic() - self._run_start, 1),
```

---

## 5. Checkliste Data Management

| # | Punkt | Status | Details |
|---|-------|--------|---------|
| 5.1 | Log Rotation: observer.log | OK | RotatingFileHandler mit 5 MB max, 3 Backups = max 20 MB. |
| 5.2 | Log Rotation: weather_observations.jsonl | KRITISCH | 89.965 Zeilen, waechst unbegrenzt! Kein Rotation. |
| 5.3 | Log Rotation: weather_signals.jsonl | KRITISCH | 25.346 Zeilen, waechst unbegrenzt! Kein Rotation. |
| 5.4 | Log Rotation: status_summary.txt | WARNUNG | 400 KB, Append-only, waechst unbegrenzt. |
| 5.5 | Log Rotation: crash.log | WARNUNG | Append-only, kein Limit. |
| 5.6 | Log Rotation: cockpit_console.log | WARNUNG | Von BAT-Script nur appended, kein Rotation. |
| 5.7 | Log Rotation: Paper Trader Logs | WARNUNG | paper_positions.jsonl und paper_trades.jsonl sind Append-only by Design, aber unbegrenzt. |
| 5.8 | Log Rotation: Audit Logs | OK | Taeglich neue Datei (observer_YYYY-MM-DD.jsonl), aber kein Cleanup alter Dateien. |
| 5.9 | Collector Data | KRITISCH | 1.8 GB in data/collector! Waechst taeglich weiter. Kein Cleanup. |
| 5.10 | Backup-Strategie | FEHLT | Kein Backup fuer capital_config.json, Positions-Logs, etc. |
| 5.11 | Disk Space Monitoring | FEHLT | Keine Pruefung ob genuegend Platz vorhanden. |

### Kritische Luecken Data Management:

**KRITISCH: 1.8 GB Collector-Daten ohne Cleanup**
`data/collector/candidates/` enthaelt taeglich neue Dateien mit allen Markt-Daten. Nach wenigen Monaten sind es leicht 50+ GB.

**Empfehlung (Prioritaet HOCH):** Cleanup-Job der alte Collector-Daten loescht:
```python
# cleanup.py - Aufrufen nach jedem Pipeline-Run
from pathlib import Path
from datetime import date, timedelta

def cleanup_old_collector_data(days_to_keep: int = 7):
    """Loesche Collector-Daten aelter als N Tage."""
    candidates_root = Path(__file__).parent / "data" / "collector" / "candidates"
    if not candidates_root.exists():
        return

    cutoff = (date.today() - timedelta(days=days_to_keep)).isoformat()
    deleted = 0
    for day_dir in sorted(candidates_root.iterdir()):
        if day_dir.is_dir() and day_dir.name < cutoff:
            import shutil
            shutil.rmtree(day_dir)
            deleted += 1

    if deleted:
        logging.info(f"Cleanup: {deleted} alte Collector-Verzeichnisse geloescht")
```

**KRITISCH: weather_observations.jsonl waechst unbegrenzt**
Bei 90.000 Zeilen in wenigen Tagen wird diese Datei schnell mehrere hundert MB gross.

**Empfehlung (Prioritaet HOCH):** Entweder:
- RotatingFileHandler analog zu observer.log verwenden, ODER
- Taeglich neue Datei anlegen: `weather_observations_YYYY-MM-DD.jsonl`

**FEHLT: Backup von kritischen State-Dateien**
`data/capital_config.json` ist die einzige Quelle fuer den Kapital-Stand. Wenn diese Datei korrupt wird, sind alle Daten verloren.

**Empfehlung (Prioritaet MITTEL):** Vor jedem Write ein Backup anlegen:
```python
# In capital_manager.py _save_config:
import shutil
backup_path = self._config_path.with_suffix('.json.bak')
if self._config_path.exists():
    shutil.copy2(self._config_path, backup_path)
```

---

## 6. Checkliste Security

| # | Punkt | Status | Details |
|---|-------|--------|---------|
| 6.1 | API Keys in .env | OK | .env.example als Template, .env existiert lokal. |
| 6.2 | .env in .gitignore | UNKLAR | Keine .gitignore gefunden! .env koennte versehentlich committed werden. |
| 6.3 | Keine Secrets im Code | OK | Keine PRIVATE_KEY, PASSWORD, SECRET oder TOKEN als Strings im Python-Code. |
| 6.4 | Keine Secrets in Logs | OK | API-Keys werden nie geloggt. Nur Market-IDs und Preise in Logs. |
| 6.5 | Private Key Schutz | OK | POLYMARKET_PRIVATE_KEY nur in .env.example als Platzhalter. |
| 6.6 | Live-Trading Gate | OK | LIVE_TRADING_ENABLED=false in .env. Paper-Trading ist Default. |
| 6.7 | File Permissions | WARNUNG | Keine expliziten Permissions auf .env oder capital_config.json. Windows-Standard. |
| 6.8 | Lockfile Security | OK | PID-basiert, nur eigener Prozess kann Lockfile entfernen. |

### Kritische Luecken Security:

**KRITISCH: Keine .gitignore**
Es wurde keine `.gitignore`-Datei im Projektverzeichnis gefunden. Die `.env`-Datei mit API-Keys und potentiell dem Private Key koennte versehentlich in Git committed werden.

**Empfehlung (Prioritaet HOCH):** `.gitignore` erstellen:
```gitignore
# Secrets
.env

# Python
__pycache__/
*.pyc
.venv/

# Logs (optional - je nach Policy)
logs/
*.log

# Data (grosse Dateien)
data/collector/

# IDE
.vscode/
.idea/

# OS
Thumbs.db
.DS_Store
```

---

## 7. Checkliste Recovery

| # | Punkt | Status | Details |
|---|-------|--------|---------|
| 7.1 | Crash Recovery: Lockfile | OK | Stale Lockfile wird erkannt und ueberschrieben (PID-Check). |
| 7.2 | Crash Recovery: Auto-Restart | OK | start_bot.bat + Watchdog bieten doppelte Sicherung. |
| 7.3 | Crash Recovery: Positionen | OK | Offene Positionen sind in paper_positions.jsonl als Append-Only Log gespeichert. Werden beim naechsten Run korrekt geladen. |
| 7.4 | Crash Recovery: Kapital-State | WARNUNG | capital_config.json wird direkt ueberschrieben (kein atomic write). Bei Crash waehrend Write -> korrupte Datei -> Bot startet nicht. |
| 7.5 | Crash Recovery: Pipeline-Idempotenz | OK | Proposals werden per ID dedupliziert (get_executed_proposal_ids). Kein doppelter Entry moeglich. |
| 7.6 | Crash Recovery: Error Backoff | OK | Ab 5 consecutive errors: exponentieller Backoff bis max 10 Min. |
| 7.7 | Inkonsistenter State | WARNUNG | Wenn capital_manager Kapital allokiert aber Position-Log vor dem Write crashed: Kapital ist weg, Position nicht erfasst. Kein Transaction-Mechanismus. |
| 7.8 | Crash Recovery: Audit Continuity | OK | Audit-Log ist Append-Only, ueberlebt Crashes. |

### Kritische Luecken Recovery:

**WARNUNG: Kein Atomic Write fuer capital_config.json**
`_save_config()` in capital_manager.py schreibt direkt in die Datei. Bot-Status (bot_status.json) verwendet korrekt `.tmp + rename`, aber capital_config.json nicht.

**Empfehlung (Prioritaet HOCH):** Atomic Write analog zu bot_status.json:
```python
# In capital_manager.py _save_config:
import json
tmp_path = self._config_path.with_suffix('.tmp')
with open(tmp_path, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
tmp_path.replace(self._config_path)
```

**WARNUNG: Kapital-Position Race Condition**
Wenn der Bot zwischen `allocate_capital()` und `log_position()` crashed, ist Kapital allokiert aber keine Position erfasst. Beim Neustart stimmt der verfuegbare Kapitalstand nicht.

**Empfehlung (Prioritaet MITTEL):** Einen Reconciliation-Check beim Start einbauen:
```python
def reconcile_capital_on_startup():
    """Gleiche Kapital-State mit offenen Positionen ab."""
    open_positions = get_paper_logger().get_open_positions()
    expected_allocated = sum(p.cost_basis_eur for p in open_positions)

    state = get_capital_manager().get_state()
    diff = abs(state.allocated_capital_eur - expected_allocated)

    if diff > 1.0:  # Mehr als 1 EUR Abweichung
        logger.warning(
            f"Kapital-Reconciliation: allocated={state.allocated_capital_eur:.2f}, "
            f"expected={expected_allocated:.2f}, diff={diff:.2f}"
        )
        # Auto-Fix
        state.allocated_capital_eur = expected_allocated
        state.available_capital_eur = state.initial_capital_eur + state.realized_pnl_eur - expected_allocated
```

---

## 8. Checkliste Code-Qualitaet & Tests

| # | Punkt | Status | Details |
|---|-------|--------|---------|
| 8.1 | Unit Tests | TEILWEISE | 7 Test-Dateien vorhanden: weather_filter, weather_probability, weather_signal, weather_engine, collector, module_loader, outcome_tracker. |
| 8.2 | Integration Tests | TEILWEISE | 2 Integration-Tests: outcome_tracker, weather_validation. |
| 8.3 | Paper Trader Tests | FEHLT | Keine Tests fuer simulator.py, position_manager.py, capital_manager.py, kelly.py. |
| 8.4 | E2E Tests | FEHLT | tests/e2e Verzeichnis existiert, aber leer. |
| 8.5 | Error Handling | OK | Jeder Pipeline-Step hat try/except mit sauberem Fallback. |
| 8.6 | Logging | OK | Konsistentes Python logging Modul mit strukturierten Nachrichten. |
| 8.7 | Type Hints | OK | Durchgehend Type Hints in allen analysierten Dateien. |
| 8.8 | Docstrings | OK | Ausfuehrliche Docstrings mit Governance-Notices. |
| 8.9 | Dependency Pinning | WARNUNG | requirements.txt nutzt >= statt ==. Builds sind nicht reproduzierbar. |

---

## 9. Prioritaetenliste der Empfehlungen

### Prioritaet HOCH (Muss gefixt werden)

| # | Problem | Aufwand | Datei |
|---|---------|---------|-------|
| H1 | .gitignore fehlt - .env mit Secrets koennte committed werden | 5 Min | `.gitignore` (neu) |
| H2 | python-dotenv fehlt in requirements.txt | 1 Min | `requirements.txt` |
| H3 | Collector-Daten wachsen unbegrenzt (1.8 GB!) | 30 Min | Neuer Cleanup-Job |
| H4 | weather_observations.jsonl waechst unbegrenzt (90k Zeilen) | 20 Min | Log-Rotation einbauen |
| H5 | weather_signals.jsonl waechst unbegrenzt (25k Zeilen) | 20 Min | Log-Rotation einbauen |
| H6 | capital_config.json kein atomic write | 10 Min | `paper_trader/capital_manager.py` |
| H7 | Kein Alerting - niemand merkt wenn Bot tot ist | 45 Min | `watchdog.ps1` + Telegram |

### Prioritaet MITTEL (Sollte gefixt werden)

| # | Problem | Aufwand | Datei |
|---|---------|---------|-------|
| M1 | Config-Validation beim Start fehlt | 30 Min | `cockpit.py` oder `app/orchestrator.py` |
| M2 | Kapital-Reconciliation beim Start fehlt | 30 Min | `paper_trader/capital_manager.py` |
| M3 | duration_seconds immer 0 im bot_status | 10 Min | `app/orchestrator.py` |
| M4 | Bootstrap/Install-Script fehlt | 20 Min | `bootstrap.bat` (neu) |
| M5 | Backup fuer capital_config.json | 10 Min | `paper_trader/capital_manager.py` |
| M6 | status_summary.txt waechst unbegrenzt (400 KB) | 15 Min | `app/orchestrator.py` |
| M7 | cockpit_console.log / restart.log ohne Rotation | 20 Min | `start_bot.bat` |
| M8 | Audit-Logs ohne Auto-Cleanup alter Dateien | 15 Min | `app/orchestrator.py` |

### Prioritaet NIEDRIG (Nice to have)

| # | Problem | Aufwand | Datei |
|---|---------|---------|-------|
| N1 | Trading-Parameter (TP/SL/Kelly) in Config-Datei auslagern | 1 Std | Neue `config/trading.yaml` |
| N2 | Paper Trader Tests fehlen | 2 Std | Neue Test-Dateien |
| N3 | Dependency Pinning (== statt >=) | 10 Min | `requirements.txt` |
| N4 | Disk Space Monitoring | 30 Min | `watchdog.ps1` oder `cockpit.py` |
| N5 | Memory/CPU Monitoring | 1 Std | Neues Modul |
| N6 | Dashboard (flet ist bereits als Dependency da) | 4+ Std | Neues Dashboard-Modul |

---

## 10. Fazit und naechste Schritte

### Was gut funktioniert:
- **Lockfile-Mechanismus**: Robust, PID-basiert, stale-detection
- **Dreifache Absicherung**: cockpit.py Error-Handling + start_bot.bat Restart + Watchdog
- **Audit Trail**: Append-only Logs, JSONL-Format, taeglich rotiert
- **Paper Trading Isolation**: Klare Governance-Notices, kein Zugriff auf Trading-APIs
- **Idempotenz**: Doppel-Entries werden per Proposal-ID verhindert
- **Crash Logger**: Global Exception Hook + dedizierter Crash-Log
- **Bot Status**: Atomic write, maschinenlesbar, nützliche Metriken

### Was dringend fehlt:
1. **Alerting** - Der Bot kann sterben und niemand merkt es
2. **Daten-Hygiene** - 1.8 GB Collector-Daten ohne Cleanup ist ein Zeitbomben-Problem
3. **Log-Rotation** - Mehrere JSONL-Dateien wachsen unbegrenzt
4. **.gitignore** - Sicherheitsrisiko durch potentielles Committen von .env
5. **Atomic Writes** - capital_config.json kann bei Crash korrupt werden

### Empfohlene Reihenfolge:
1. `.gitignore` erstellen (5 Minuten, hoechstes Risiko)
2. `python-dotenv` in requirements.txt (1 Minute)
3. Atomic write fuer capital_config.json (10 Minuten)
4. Collector-Cleanup implementieren (30 Minuten)
5. Telegram-Alerting im Watchdog (45 Minuten)
6. Log-Rotation fuer JSONL-Dateien (40 Minuten)
7. Config-Validation (30 Minuten)
8. Kapital-Reconciliation (30 Minuten)

**Geschaetzter Gesamtaufwand fuer HOCH-Prioritaet: ~2-3 Stunden**
