# Logging-Analyse Report - Polymarket Weather Observer

**Erstellt:** 2026-02-09
**Analysiert von:** Logging-Perfektionierungs-Agent
**Projekt:** Polymarket Weather Observer (Paper Trading)

---

## 1. Aktuelle Logging-Architektur

```
+-------------------------------------------------------------------+
|                        cockpit.py (Entry Point)                    |
|   - setup_logging() -> shared/logging_config.py                   |
|   - setup_crash_logger() -> logs/crash.log                        |
|   - write_heartbeat() -> logs/heartbeat.txt                       |
|   - write_bot_status() -> logs/bot_status.json                    |
+-------------------------------------------------------------------+
         |
         v
+-------------------------------------------------------------------+
|              shared/logging_config.py                              |
|   - RotatingFileHandler -> logs/observer.log (5MB x 3)            |
|   - StreamHandler -> Console                                      |
|   - Format: "%(asctime)s | %(levelname)-8s | %(name)s | %(msg)s"  |
+-------------------------------------------------------------------+
         |
         v (Python logging.getLogger(__name__))
+-------------------------------------------------------------------+
|                    Module-Logger                                   |
|                                                                    |
|  app/orchestrator.py ------> logging.getLogger(__name__)          |
|  core/weather_engine.py ---> logging.getLogger(__name__)          |
|  collector/collector.py ---> logging.getLogger(__name__)          |
|  core/outcome_tracker.py --> logging.getLogger(__name__)          |
|  paper_trader/simulator.py -> logging.getLogger(__name__)         |
|  paper_trader/position_manager.py -> logging.getLogger(__name__)  |
|  paper_trader/capital_manager.py --> logging.getLogger(__name__)  |
|  paper_trader/edge_reversal.py ----> logging.getLogger(__name__)  |
|  paper_trader/logger.py -----------> logging.getLogger(__name__)  |
+-------------------------------------------------------------------+
         |
         v (Parallel dazu: Eigene JSONL-Log-Dateien)
+-------------------------------------------------------------------+
|                     JSONL-Logging (Append-Only)                   |
|                                                                    |
|  paper_trader/logger.py:                                          |
|    -> paper_trader/logs/paper_trades.jsonl                        |
|    -> paper_trader/logs/paper_positions.jsonl                     |
|                                                                    |
|  core/weather_engine.py:                                          |
|    -> logs/weather_observations.jsonl                             |
|                                                                    |
|  core/outcome_tracker.py:                                         |
|    -> data/outcomes/predictions.jsonl                             |
|    -> data/outcomes/resolutions.jsonl                             |
|    -> data/outcomes/corrections.jsonl                             |
|                                                                    |
|  app/orchestrator.py:                                             |
|    -> logs/audit/observer_YYYY-MM-DD.jsonl                        |
|    -> output/status_summary.txt (Append)                          |
+-------------------------------------------------------------------+
         |
         v
+-------------------------------------------------------------------+
|                    Status-Dateien (JSON)                           |
|                                                                    |
|  logs/bot_status.json ---- Atomic Write (.tmp + rename)           |
|  logs/heartbeat.txt ------ ISO Timestamp                          |
|  logs/crash.log ---------- Textformat, Append                     |
|  data/capital_config.json  Kapital-State (ueberschrieben)         |
+-------------------------------------------------------------------+
```

### Log-Datei-Uebersicht (aktueller Stand)

| Datei | Groesse | Rotation | Format |
|-------|---------|----------|--------|
| `logs/observer.log` | **0 (fehlt!)** | Ja (5MB x 3) | Text |
| `logs/weather_observations.jsonl` | **3.3 MB** | **KEINE** | JSONL |
| `logs/weather_signals.jsonl` | 936 KB | **KEINE** | JSONL |
| `logs/scheduler_runs.log` | 9 KB | **KEINE** | Text |
| `logs/cockpit_console.log` | 36 KB | **KEINE** | Text |
| `logs/crash.log` | 0 (leer/fehlt) | **KEINE** | Text |
| `logs/bot_status.json` | 424 B | Ueberschrieben | JSON |
| `logs/heartbeat.txt` | 28 B | Ueberschrieben | Text |
| `logs/audit/observer_*.jsonl` | ~44 KB total | **Taeglich rotiert** | JSONL |
| `paper_trader/logs/paper_trades.jsonl` | **191 KB** | **KEINE** | JSONL |
| `paper_trader/logs/paper_positions.jsonl` | 6 KB | **KEINE** | JSONL |
| `data/outcomes/predictions.jsonl` | variabel | **KEINE** | JSONL |
| `output/status_summary.txt` | wachsend | **KEINE** | Text |

---

## 2. Findings nach Prioritaet

### KRITISCH (P0)

#### F01: `observer.log` wird nie erzeugt
**Problem:** Die `shared/logging_config.py` konfiguriert einen `RotatingFileHandler` fuer `logs/observer.log`, aber die Datei existiert nicht. Moegliche Ursache: `setup_logging()` wird erst in `cockpit.py main()` aufgerufen. Wenn Module vorher importiert werden oder wenn `--run-once` mit `--no-color` laeuft, wird `console_output=False` gesetzt - aber die Datei sollte trotzdem existieren.

**Auswirkung:** Die zentrale, rotierte Log-Datei ist leer/fehlend. Alle Python-Logger-Ausgaben verschwinden moeglicherweise ins Nichts.

**Empfehlung:** Pruefen, ob der Root-Logger tatsaechlich Nachrichten empfaengt. Sicherstellen, dass `setup_logging()` frueh genug aufgerufen wird.

#### F02: `weather_observations.jsonl` waechst unbegrenzt (3.3 MB)
**Problem:** Die Datei `logs/weather_observations.jsonl` hat bereits 3.3 MB und hat **KEINE Rotation**. Sie wird von `WeatherEngine._log_observation()` direkt per `open(..., 'a')` beschrieben - ohne jegliche Groessenbegrenzung.

**Auswirkung:** Bei 15-Minuten-Intervallen und ~100 Observations pro Run waechst diese Datei um ca. 15 MB/Tag. In einem Monat: ~450 MB. In einem Jahr: ~5.5 GB.

**Empfehlung:** JSONL-Rotation einfuehren (taeglich oder groessenbasiert).

#### F03: Stille `except ... pass` Bloecke in cockpit.py
**Problem:** `cockpit.py` hat mindestens 6 `except Exception: pass`-Bloecke (Zeilen 73, 85, 94, 108, 197, 229, 386, 408, 427). Diese Stellen verschlucken Fehler komplett:
- `write_heartbeat()` (Zeile 94-95): Fehler wird verschluckt
- `write_bot_status()` (Zeile 197-198): Fehler wird verschluckt
- `release_lock()` (Zeile 85-86): Fehler wird verschluckt
- Crash-Log Writes (Zeile 386-387, 427-428): Meta-Fehler beim Fehler-Logging werden verschluckt

**Auswirkung:** Wenn das Logging selbst fehlschlaegt, erfaehrt man es nie. Debugging wird extrem schwierig.

**Empfehlung:** Mindestens `logger.debug()` in diesen Bloecken verwenden, nicht komplett schweigen.

---

### HOCH (P1)

#### F04: Keine Pipeline-Run-Korrelations-ID
**Problem:** Es gibt eine `run_id` nur im `OutcomeTracker` (Zeile 461 in orchestrator.py), aber diese ID wird NICHT an die anderen Pipeline-Steps weitergegeben. Der Collector, Weather Observer, Proposal Generator und Paper Trader loggen ohne Korrelations-ID.

**Auswirkung:** Wenn man einen bestimmten Pipeline-Run debuggen will, kann man die Log-Eintraege verschiedener Module nicht zusammenfuehren. Man muss ueber Timestamps korrelieren (ungenau).

**Empfehlung:** Eine `run_id` (UUID) in `run_pipeline()` erzeugen und per `logging.LoggerAdapter` oder `contextvars` an alle Sub-Logger durchreichen.

#### F05: Inkonsistentes Duration-Logging
**Problem:**
- `WeatherEngine.run()` loggt `run_duration_seconds` korrekt
- `Collector.run()` loggt `duration` korrekt
- `Orchestrator.run_pipeline()` loggt **KEINE Gesamt-Dauer**
- `bot_status.json` zeigt `"duration_seconds": 0` - der Wert wird aus dem `result.summary` gelesen, der dieses Feld nie setzt!

**Auswirkung:** Die Gesamt-Pipeline-Dauer ist nirgends zuverlaessig geloggt. Bot-Status zeigt immer `0`.

**Empfehlung:** `duration_seconds` in `_build_summary()` berechnen und korrekt setzen.

#### F06: `output/status_summary.txt` waechst unbegrenzt
**Problem:** `_write_status_summary()` schreibt per Append (`'a'`) in `status_summary.txt`. Jeder Run fuegt ~12 Zeilen hinzu. Bei 96 Runs/Tag: ~1.150 Zeilen/Tag.

**Auswirkung:** Datei waechst stetig. Kein Mechanismus zum Kuerzen oder Rotieren.

**Empfehlung:** Nur die letzten N Runs behalten oder taeglich rotieren.

#### F07: `paper_trades.jsonl` waechst unbegrenzt (191 KB)
**Problem:** Paper Trades werden nur angehaengt. Die Append-Only-Policy ist bewusst gewaehlt (Audit-Trail), aber es gibt keine Archivierungs-Strategie.

**Auswirkung:** Bei langer Laufzeit koennte diese Datei gross werden. Zudem wird `read_all_trades()` bei jeder Iteration aufgerufen, was bei grossen Dateien langsam wird.

**Empfehlung:** Monatliche Archivierung (Move zu `paper_trades_YYYY-MM.jsonl.gz`). Read-Performance durch Index-Cache verbessern.

---

### MITTEL (P2)

#### F08: Kein strukturiertes Logging fuer maschinelle Auswertung
**Problem:** Die Python-Logger schreiben unstrukturierten Text:
```
2026-02-09 21:44:18 | INFO     | collector | Fetched 323 weather-tagged markets
```
Waehrend die JSONL-Dateien strukturiert sind, fehlt eine einheitliche Bruecke. Der Hauptlog (`observer.log`) ist nicht maschinell parsebar.

**Auswirkung:** Automatisierte Log-Analyse (z.B. Fehler-Rate pro Modul, Durchschnittsdauer) erfordert Regex-Parsing des Textlogs.

**Empfehlung:** JSON-Formatter als Alternative fuer File-Logging. Behalte Text fuer Console.

#### F09: `get_layer_logger()` ist ein toter Code-Pfad
**Problem:** `shared/logging_config.py` hat eine Funktion `get_layer_logger(layer=None)` die immer denselben Logger `"weather_observer"` zurueckgibt. Der `layer`-Parameter wird ignoriert. Kein Modul nutzt diese Funktion - alle verwenden `logging.getLogger(__name__)`.

**Auswirkung:** Verwirrender, toter Code. Kein funktionaler Schaden.

**Empfehlung:** Entfernen oder durch sinnvolle Hierarchie ersetzen.

#### F10: Doppelte Log-Systeme fuer Paper Trading
**Problem:** Der Paper Trader loggt zweifach:
1. Via Python `logging` (in `observer.log` / Console): `logger.info(f"PAPER_ENTER: ...")`
2. Via JSONL (`paper_trades.jsonl`, `paper_positions.jsonl`)

Das ist bewusst so designt (Text fuer Mensch, JSONL fuer Maschine), aber die Informationen sind nicht identisch. Das JSONL hat mehr Details (Slippage, Contracts), das Text-Log hat weniger.

**Auswirkung:** Bei Diskrepanzen ist unklar, welche Quelle korrekt ist.

**Empfehlung:** Sicherstellen, dass die Text-Logs mindestens die Position-ID enthalten fuer Cross-Referenz.

#### F11: Kein Logging von API-Response-Zeiten
**Problem:** Die Weather-APIs (Tomorrow.io, OpenWeather, WeatherAPI, NOAA) werden in `core/multi_forecast.py` aufgerufen, aber die Response-Zeiten werden NICHT geloggt.

**Auswirkung:** Man kann nicht erkennen, welche API langsam ist oder Timeouts verursacht.

**Empfehlung:** `time.perf_counter()` um jeden API-Call und die Dauer loggen.

#### F12: Keine Memory/CPU-Metriken
**Problem:** Es werden keine System-Ressourcen-Metriken geloggt. Bei einem 15-Minuten-Scheduler kann ein Memory-Leak ueber Stunden/Tage unbemerkt bleiben.

**Auswirkung:** Potenzielle Stabilitaetsprobleme bleiben unsichtbar.

**Empfehlung:** Nach jedem Pipeline-Run `psutil.Process().memory_info().rss` loggen (optional, nur wenn `psutil` installiert).

---

### NIEDRIG (P3)

#### F13: `weather_signals.jsonl` ist Altlast (936 KB)
**Problem:** Die Datei `logs/weather_signals.jsonl` (936 KB) wird scheinbar nicht mehr aktiv beschrieben. Sie stammt aus einer frueheren Version.

**Auswirkung:** Verschwendet Speicherplatz und koennte verwirren.

**Empfehlung:** Archivieren oder loeschen, wenn nicht mehr benoetigt.

#### F14: `cockpit_console.log` und `cockpit_console.err.log` ohne Handler
**Problem:** Diese Dateien existieren (36 KB / 0 KB), aber kein Code in `cockpit.py` schreibt explizit dorthin. Sie stammen moeglicherweise von einem externen Wrapper (BAT-Datei Redirect).

**Auswirkung:** Unklar, ob diese Dateien noch befuellt werden.

**Empfehlung:** Klaeren und dokumentieren, woher diese Dateien kommen.

#### F15: Audit-Logs sind gut, aber ohne Retention-Policy
**Problem:** `logs/audit/observer_YYYY-MM-DD.jsonl` ist eine solide taeglich-rotierende Loesung. Aber es gibt keinen Mechanismus, alte Dateien zu loeschen.

**Auswirkung:** Bei langem Betrieb: ~29 KB/Tag x 365 = ~10 MB/Jahr. Unkritisch, aber unaufgeraeumt.

**Empfehlung:** Automatisches Loeschen nach 90 Tagen.

---

## 3. Sensitive Daten - Analyse

### Ergebnis: KEINE sensitiven Daten in Logs gefunden

| Pruefpunkt | Status | Details |
|------------|--------|---------|
| API-Keys in Logs | SICHER | Keine Treffer fuer `api_key`, `API_KEY`, `secret`, `token`, `password` |
| Polymarket API Key | SICHER | Projekt benoetigt keinen API Key (nur oeffentliche Endpoints) |
| PII (Personendaten) | SICHER | Keine persoenlichen Daten - nur Markt- und Wetterdaten |
| Finanzdaten | OK | Nur Paper-Trading-Daten (simuliert, keine echten Betraege) |
| Weather-API-Keys | PRUEFEN | Keys liegen in `config/weather.yaml` - nicht in Logs, aber Datei pruefen |

---

## 4. Empfohlene Ziel-Architektur

```
+-------------------------------------------------------------------+
|                     cockpit.py (Entry Point)                       |
|   run_id = uuid4().hex[:12] pro Pipeline-Run                      |
+-------------------------------------------------------------------+
         |
         v
+-------------------------------------------------------------------+
|              shared/logging_config.py (ERWEITERT)                  |
|                                                                    |
|  Console Handler:                                                  |
|    - Text-Format (fuer Menschen)                                   |
|    - Level: INFO                                                   |
|                                                                    |
|  File Handler (observer.log):                                      |
|    - JSON-Format (strukturiert, maschinenlesbar)                   |
|    - RotatingFileHandler 5MB x 3 (BEHALTEN)                       |
|    - Level: DEBUG                                                  |
|    - Felder: timestamp, level, module, run_id, message, extra      |
|                                                                    |
|  Korrelation:                                                      |
|    - run_id per contextvars.ContextVar                             |
|    - Automatisch in jedem Log-Eintrag                              |
+-------------------------------------------------------------------+
         |
         v
+-------------------------------------------------------------------+
|               JSONL-Logs (Append-Only, MIT ROTATION)               |
|                                                                    |
|  weather_observations.jsonl:                                       |
|    -> Taeglich rotiert: weather_obs_YYYY-MM-DD.jsonl               |
|    -> Alte Dateien: nach 30 Tagen loeschen                         |
|                                                                    |
|  paper_trades.jsonl:                                               |
|    -> Monatlich archiviert: paper_trades_YYYY-MM.jsonl.gz          |
|    -> Aktuelle Datei bleibt fuer schnellen Zugriff                 |
|                                                                    |
|  audit/observer_YYYY-MM-DD.jsonl:                                  |
|    -> Retention: 90 Tage (BEHALTEN)                                |
+-------------------------------------------------------------------+
         |
         v
+-------------------------------------------------------------------+
|              Performance-Metriken (NEU)                            |
|                                                                    |
|  Pro Pipeline-Run:                                                 |
|    - Gesamt-Dauer (duration_seconds)                               |
|    - Dauer pro Step (collector, observer, trader)                  |
|    - API Response-Zeiten (forecast APIs)                           |
|    - Anzahl API-Calls + Fehler                                     |
|    - Memory-Nutzung (optional)                                     |
+-------------------------------------------------------------------+
```

---

## 5. Konkrete Verbesserungen pro Datei

### `shared/logging_config.py`

| Aenderung | Prioritaet | Aufwand |
|-----------|------------|---------|
| JSON-Formatter hinzufuegen fuer File-Handler | P2 | Mittel |
| `run_id` per `contextvars` hinzufuegen | P1 | Mittel |
| `get_layer_logger()` entfernen (toter Code) | P3 | Klein |
| Log-Format um `run_id` erweitern | P1 | Klein |

**Konkret: JSON-Formatter**
```python
import json

class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_entry = {
            "ts": self.formatTime(record),
            "level": record.levelname,
            "module": record.name,
            "msg": record.getMessage(),
            "run_id": getattr(record, 'run_id', None),
        }
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry)
```

### `cockpit.py`

| Aenderung | Prioritaet | Aufwand |
|-----------|------------|---------|
| `except Exception: pass` durch mindestens `logger.debug()` ersetzen | P0 | Klein |
| `duration_seconds` korrekt in `write_bot_status()` setzen | P1 | Klein |
| Crash-Log Rotation (max. 1 MB) hinzufuegen | P2 | Klein |

**Konkret: Stille Fehler beheben**
```python
# VORHER (schlecht):
def write_heartbeat():
    try:
        ...
    except Exception:
        pass  # <-- Fehler verschwindet

# NACHHER (besser):
def write_heartbeat():
    try:
        ...
    except Exception as e:
        # Non-critical aber nicht komplett verschlucken
        import sys
        print(f"Heartbeat write failed: {e}", file=sys.stderr)
```

### `app/orchestrator.py`

| Aenderung | Prioritaet | Aufwand |
|-----------|------------|---------|
| `run_id` erzeugen und an Summary anhaengen | P1 | Klein |
| `duration_seconds` in `_build_summary()` berechnen | P1 | Klein |
| Step-Dauer pro Pipeline-Step loggen | P2 | Mittel |
| Status-Summary-Datei groessenbegrenzen | P1 | Klein |

**Konkret: duration_seconds**
```python
def run_pipeline(self) -> PipelineResult:
    import time
    pipeline_start = time.perf_counter()
    # ... pipeline steps ...
    pipeline_duration = time.perf_counter() - pipeline_start
    result.summary["duration_seconds"] = round(pipeline_duration, 2)
```

### `core/weather_engine.py`

| Aenderung | Prioritaet | Aufwand |
|-----------|------------|---------|
| JSONL-Observation-Log taeglich rotieren | P0 | Mittel |
| `run_id` in Observations aufnehmen | P1 | Klein |
| Forecast-API-Dauer loggen (in `_process_market`) | P2 | Klein |

**Konkret: Taeglich rotierte Observations**
```python
from datetime import date

def _log_observation(self, observation):
    log_dir = Path(self.observation_log_path).parent
    log_dir.mkdir(parents=True, exist_ok=True)
    daily_file = log_dir / f"weather_obs_{date.today().isoformat()}.jsonl"
    with open(daily_file, 'a') as f:
        f.write(observation.to_json() + "\n")
```

### `paper_trader/logger.py`

| Aenderung | Prioritaet | Aufwand |
|-----------|------------|---------|
| Monatliche Archivierung fuer `paper_trades.jsonl` | P1 | Mittel |
| Statistik-Cache statt volles Re-Read | P2 | Mittel |
| `_append_json` mit Flush fuer Datensicherheit | P3 | Klein |

### `paper_trader/simulator.py`

| Aenderung | Prioritaet | Aufwand |
|-----------|------------|---------|
| Position-ID in Text-Logs hinzufuegen | P2 | Klein |
| Kelly-Sizing-Entscheidung loggen | P2 | Klein |

### `paper_trader/position_manager.py`

| Aenderung | Prioritaet | Aufwand |
|-----------|------------|---------|
| Anzahl gecheckte Positionen + Dauer loggen | P2 | Klein |

### `paper_trader/capital_manager.py`

| Aenderung | Prioritaet | Aufwand |
|-----------|------------|---------|
| Capital-State-Aenderungen in separatem Audit-Log | P3 | Mittel |

### `collector/collector.py`

| Aenderung | Prioritaet | Aufwand |
|-----------|------------|---------|
| API-Response-Time loggen | P2 | Klein |
| Anzahl geloeschter/neuer Candidates vs. vorheriger Run | P3 | Mittel |

### `core/outcome_tracker.py`

| Aenderung | Prioritaet | Aufwand |
|-----------|------------|---------|
| Resolution-Check-Dauer pro Market loggen | P2 | Klein |
| Gesamt-Statistik am Ende von `update_resolutions` | P3 | Klein |

### `core/multi_forecast.py` (nicht direkt analysiert, aber relevant)

| Aenderung | Prioritaet | Aufwand |
|-----------|------------|---------|
| Response-Time pro API-Provider loggen | P1 | Klein |
| Rate-Limit-Warnungen loggen | P2 | Klein |
| Fallback-Kette explizit loggen (welcher Provider wurde genutzt) | P2 | Klein |

---

## 6. Log-Rotation Empfehlung

### Sofort umsetzen (P0)

| Datei | Aktuell | Empfehlung |
|-------|---------|------------|
| `logs/observer.log` | 5MB x 3 (konfiguriert) | **Bug fixen** - Datei wird nicht erzeugt |
| `logs/weather_observations.jsonl` | **3.3 MB, kein Limit** | Taeglich rotieren: `weather_obs_YYYY-MM-DD.jsonl`, 30 Tage Retention |

### Kurzfristig (P1)

| Datei | Aktuell | Empfehlung |
|-------|---------|------------|
| `output/status_summary.txt` | Unbegrenzt wachsend | Letzten 1000 Zeilen behalten oder taeglich rotieren |
| `paper_trader/logs/paper_trades.jsonl` | 191 KB, kein Limit | Monatliche Archivierung |
| `logs/crash.log` | Unbegrenzt | Max 1 MB, aelteste Eintraege loeschen |

### Mittelfristig (P2)

| Datei | Aktuell | Empfehlung |
|-------|---------|------------|
| `logs/audit/observer_*.jsonl` | Taeglich, kein Loeschen | Retention-Policy: 90 Tage |
| `logs/scheduler_runs.log` | Kein Limit | Max 5 MB oder taeglich rotieren |
| `logs/weather_signals.jsonl` | 936 KB (Altlast?) | Archivieren oder loeschen |

### Automatisiertes Cleanup-Script

Empfehlung: Ein einfaches Python-Script das am Anfang jedes Pipeline-Runs laeuft:

```python
def cleanup_old_logs(logs_dir: Path, max_age_days: int = 30):
    """Loesche Log-Dateien aelter als max_age_days."""
    from datetime import datetime, timedelta
    cutoff = datetime.now() - timedelta(days=max_age_days)

    for pattern in ["weather_obs_*.jsonl", "audit/observer_*.jsonl"]:
        for f in logs_dir.glob(pattern):
            if datetime.fromtimestamp(f.stat().st_mtime) < cutoff:
                f.unlink()
                logger.info(f"Deleted old log: {f.name}")
```

---

## 7. Zusammenfassung

### Was gut funktioniert
- **Append-Only JSONL** fuer Paper Trading (Audit-Trail, Integritaet)
- **Taeglich rotierende Audit-Logs** (`logs/audit/observer_YYYY-MM-DD.jsonl`)
- **Bot-Status JSON** mit Atomic Write (`.tmp` + `rename`)
- **Crash-Logger** als Safety-Net fuer unerwartete Abstuerze
- **Heartbeat-File** fuer externe Monitoring-Tools
- **Keine sensitiven Daten** in Logs (API-Keys, Passwoerter etc.)
- **Konsistentes Logger-Pattern** (`logging.getLogger(__name__)`) in allen Modulen

### Was fehlt / verbessert werden muss
1. **observer.log wird nicht erzeugt** (P0 Bug)
2. **JSONL-Dateien wachsen unbegrenzt** (P0, insb. weather_observations)
3. **Stille Fehler** durch `except: pass` in cockpit.py (P0)
4. **Keine Korrelations-ID** (run_id) ueber alle Module (P1)
5. **Pipeline-Dauer wird nicht korrekt geloggt** (P1)
6. **Kein strukturiertes (JSON) Logging** im Haupt-Log (P2)
7. **Keine API-Response-Time-Metriken** (P2)
8. **Keine Resource-Metriken** (Memory, CPU) (P2)
9. **Keine Retention-Policy** fuer aeltere Log-Dateien (P2)

### Aufwandsschaetzung Gesamtverbesserung

| Phase | Aufwand | Inhalt |
|-------|---------|--------|
| Phase 1 (Quick Wins) | 2-3h | F01 Bug fix, F02 JSONL Rotation, F03 stille Fehler, F05 Duration |
| Phase 2 (Korrelation) | 3-4h | F04 run_id, F08 JSON-Formatter, F11 API-Timing |
| Phase 3 (Cleanup) | 2-3h | F06 Status Rotation, F07 Archivierung, F15 Retention |
| Phase 4 (Optional) | 2h | F12 Resource-Metriken, F09 toter Code, F13/F14 Aufraeum |

**Gesamt: ca. 9-12 Stunden fuer vollstaendige Logging-Perfektionierung.**
