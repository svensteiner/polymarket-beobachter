# Stabilitaets-Check Report - Polymarket Weather Trading Bot

**Datum:** 2026-02-09
**Analyst:** Claude Opus 4.6 (Stabilitaets-Check Agent)
**Geprueft:** 16 Dateien im gesamten Projekt

---

## Zusammenfassung

| Kategorie | Anzahl |
|-----------|--------|
| KRITISCH (sofort fixen) | 8 |
| WICHTIG (sollte gefixt werden) | 12 |
| NICE-TO-HAVE (Verbesserungen) | 10 |

---

## KRITISCH - Sofort fixen

### K1: Bare `except:` in `collector/client.py` (Zeile 332-333)

**Datei:** `collector/client.py`
**Zeile:** 332-333
**Problem:** Zwei bare `except:` ohne spezifische Exception-Klasse in `get_market_odds_yes()`:
```python
except:
    pass
```
Diese fangen ALLE Exceptions ab, inklusive `KeyboardInterrupt`, `SystemExit`, `MemoryError`. Der Bot kann damit nicht sauber per Ctrl+C gestoppt werden, wenn er gerade in dieser Funktion haengt.

**Empfohlener Fix:**
```python
except (json.JSONDecodeError, ValueError, TypeError):
    pass
```

---

### K2: Nicht-atomare Schreib-Operationen auf `capital_config.json` (`capital_manager.py`, Zeile 136-137)

**Datei:** `paper_trader/capital_manager.py`
**Zeile:** 116-137 (`_save_config` und `_create_default_config`)
**Problem:** Sowohl `_save_config()` als auch `_create_default_config()` schreiben direkt in die Config-Datei mit `open(path, "w")`. Wenn der Prozess waehrend des Schreibens abstuerzt (Stromausfall, Kill, Exception), ist die Datei korrupt und das gesamte Kapital-Tracking ist verloren. Im Gegensatz dazu nutzt `write_bot_status()` in `cockpit.py` korrekt atomares Schreiben via `.tmp + rename`.

**Empfohlener Fix:**
```python
def _save_config(self, reason: str) -> None:
    # Atomarer Write: erst in .tmp schreiben, dann umbenennen
    tmp_path = self._config_path.with_suffix(".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    tmp_path.replace(self._config_path)
```

---

### K3: JSONL-Dateien werden ohne Schutz gegen korrupte Zeilen gelesen (`paper_trader/logger.py`, Zeile 188-216)

**Datei:** `paper_trader/logger.py`
**Zeile:** 188-216 (`read_all_trades`), 219-250 (`read_all_positions`)
**Problem:** Wenn eine JSONL-Zeile durch Crash waehrend `_append_json` nur halb geschrieben wurde, wird die Zeile per `json.loads` geparst und die `JSONDecodeError` wird abgefangen - aber das `KeyError` fuer fehlende Pflichtfelder wird still verschluckt (Zeile 212). Fehlende Felder in korrupten Eintraegen fuehren zu stillen Datenverlust. Schwerwiegender: `_append_json()` (Zeile 128) nutzt `open(path, 'a')` ohne `flush()` oder `fsync()` - bei Stromausfall kann ein unvollstaendiger JSON-String die gesamte nachfolgende Zeilenberechnung brechen.

**Empfohlener Fix:**
```python
def _append_json(self, path: Path, data: Dict[str, Any]):
    line = json.dumps(data, ensure_ascii=False) + '\n'
    with open(path, 'a', encoding='utf-8') as f:
        f.write(line)
        f.flush()
        os.fsync(f.fileno())
```

---

### K4: Division by Zero in `simulator.py` (Zeile 354)

**Datei:** `paper_trader/simulator.py`
**Zeile:** 354
**Problem:** `size_contracts = position_eur / entry_price` - wenn `entry_price` exakt 0.0 ist (z.B. durch fehlerhafte API-Daten oder Edge Case in der Slippage-Berechnung), kommt es zu einer `ZeroDivisionError`. Der `entry_price` wird zwar in `slippage.py` auf `[0.01, 0.99]` geclamped, aber das gilt nur fuer den normalen Pfad. Der simulated Snapshot setzt `best_bid = max(0.01, implied_prob - 0.02)`, was bei `implied_prob = 0.01` zu `best_bid = 0.01` fuehrt, aber nach Slippage koennte der Wert durch Rundungsfehler problematisch werden.

**Empfohlener Fix:**
```python
if entry_price <= 0.0:
    # Safety guard gegen Division by Zero
    record = PaperTradeRecord(...)
    record.reason = "Entry price <= 0 - cannot calculate contracts"
    log_trade(record)
    return (None, record)
size_contracts = position_eur / entry_price
```

---

### K5: Division by Zero in `position_manager.py` (Zeile 164-174)

**Datei:** `paper_trader/position_manager.py`
**Zeile:** 164-174
**Problem:** In `check_mid_trade_exits()` wird `entry_price <= 0` zwar geprueft (Zeile 165), aber die Berechnung `unrealized_pct = (current_price - entry_price) / entry_price` ist auch bei sehr kleinen `entry_price`-Werten (z.B. 0.001) instabil und kann zu extremen Werten fuehren. Ausserdem wird `position.cost_basis_eur` in `simulate_exit_market()` (Zeile 455) als Divisor verwendet: `pnl_pct = (realized_pnl / position.cost_basis_eur) * 100` ohne Pruefung ob `cost_basis_eur > 0`.

**Empfohlener Fix:**
```python
if entry_price <= 0.01:  # Minimum sinnvoller Preis
    continue
# In simulate_exit_market:
pnl_pct = (realized_pnl / position.cost_basis_eur) * 100 if position.cost_basis_eur > 0 else 0.0
```

---

### K6: `get_open_positions()` liest GESAMTE JSONL-Datei bei JEDEM Aufruf (`logger.py`, Zeile 252-267)

**Datei:** `paper_trader/logger.py`
**Zeile:** 252-267
**Problem:** `get_open_positions()` wird pro Pipeline-Run MINDESTENS 5x aufgerufen (von `simulator.py`, `position_manager.py` 2x, `averaging_down.py`, `edge_reversal.py`). Jeder Aufruf liest die GESAMTE `paper_positions.jsonl` und parst JEDEN Eintrag. Bei 1000+ Eintraegen wird das zunehmend langsam und CPU-intensiv. Die Datei waechst monoton (append-only) und wird NIE bereinigt.

**Empfohlener Fix:**
- In-Memory-Cache der offenen Positionen mit Invalidierung bei Schreibzugriff
- Oder: Separate Datei `open_positions.json` die nur offene Positionen haelt
- Langfristig: SQLite statt JSONL

---

### K7: Race Condition beim Lockfile (`cockpit.py`, Zeile 62-75)

**Datei:** `cockpit.py`
**Zeile:** 62-75
**Problem:** Zwischen `LOCKFILE.exists()` (Zeile 64) und `LOCKFILE.write_text()` (Zeile 74) gibt es ein TOCTOU (Time-of-check-to-time-of-use) Fenster. Wenn zwei Bot-Instanzen fast gleichzeitig starten, koennen beide das Lockfile als nicht-existent lesen und beide ihre PID hineinschreiben. Auf Windows ist dies besonders relevant, da `write_text()` nicht atomar ist.

**Empfohlener Fix:**
```python
import msvcrt  # Windows file locking
def acquire_lock():
    try:
        fd = os.open(str(LOCKFILE), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
    except FileExistsError:
        # Lockfile existiert bereits - PID pruefen
        ...
```
Oder: `fcntl.flock()` auf Unix, `msvcrt.locking()` auf Windows.

---

### K8: Kein Timeout/Schutz bei Wetter-API-Ketten (`multi_forecast.py`, Zeile 326-372)

**Datei:** `core/multi_forecast.py`
**Zeile:** 326-372
**Problem:** `fetch_forecast_multi()` ruft bis zu 4 APIs sequentiell auf (Tomorrow.io, OpenWeather, WeatherAPI, NOAA). Jeder hat `REQUEST_TIMEOUT = 15` Sekunden. Im Worst Case (alle 4 APIs timeout) dauert ein einzelner Forecast-Abruf **60 Sekunden**. Bei 50 Maerkten waeren das **50 Minuten** - weit ueber dem 15-Minuten-Scheduler-Intervall. Es gibt kein globales Timeout fuer die gesamte Engine-Run.

**Empfohlener Fix:**
- Globales Timeout fuer den gesamten Engine-Run (z.B. 10 Minuten)
- Oder: Parallel-Fetching mit `concurrent.futures.ThreadPoolExecutor`
- Oder: Kuerzere Timeouts pro API (z.B. 8 Sekunden) und globales Budget

---

## WICHTIG - Sollte gefixt werden

### W1: `status_summary.txt` waechst unbegrenzt (`orchestrator.py`, Zeile 565)

**Datei:** `app/orchestrator.py`
**Zeile:** 565
**Problem:** `open(summary_file, 'a')` - die Datei wird nur appended, nie gekuerzt. Bei 96 Runs pro Tag (alle 15 Min) waechst sie um ca. 50KB/Tag, also ~18MB/Jahr. Kein Mechanismus zur Rotation oder Bereinigung.

**Empfohlener Fix:** Rotation implementieren - z.B. letzte 500 Eintraege behalten oder taeglich rotieren.

---

### W2: `audit_file` JSONL waechst unbegrenzt (`orchestrator.py`, Zeile 588-607)

**Datei:** `app/orchestrator.py`
**Zeile:** 588-607
**Problem:** `_log_to_audit()` schreibt in taegliche JSONL-Dateien (`observer_YYYY-MM-DD.jsonl`), aber es gibt keinen Mechanismus zum Loeschen alter Audit-Dateien. Nach Monaten sammeln sich hunderte Dateien an.

**Empfohlener Fix:** Altes Audit nach 30 Tagen loeschen oder komprimieren.

---

### W3: `weather.yaml` wird ohne Validierung geladen (`weather_engine.py`, Zeile 482-485)

**Datei:** `core/weather_engine.py`
**Zeile:** 464-485 (`load_config`)
**Problem:** `yaml.safe_load(f)` gibt `None` zurueck wenn die Datei leer ist. Es gibt keine Validierung der Pflichtfelder (MIN_EDGE, MAX_ODDS, etc.). Ein leeres oder fehlerhaftes YAML fuehrt zu `None`-Werten die erst spaeter als AttributeError aufschlagen.

**Empfohlener Fix:**
```python
config = yaml.safe_load(f) or {}
required_keys = ["MIN_EDGE", "MIN_EDGE_ABSOLUTE", "MAX_ODDS"]
for key in required_keys:
    if key not in config:
        raise ValueError(f"Missing required config key: {key}")
```

---

### W4: Globale Singletons sind nicht thread-safe (mehrere Dateien)

**Dateien:**
- `paper_trader/simulator.py` Zeile 607-615 (`_simulator`)
- `paper_trader/position_manager.py` Zeile 252-260 (`_manager`)
- `paper_trader/logger.py` Zeile 331-339 (`_paper_logger`)
- `paper_trader/snapshot_client.py` Zeile 366-374 (`_snapshot_client`)
- `paper_trader/slippage.py` Zeile 215-223 (`_slippage_model`)
- `app/orchestrator.py` Zeile 641-649 (`_orchestrator`)

**Problem:** Alle `get_*()` Singleton-Funktionen nutzen das Pattern `if _instance is None: _instance = X()`. Dieses Pattern ist NICHT thread-safe. Wenn zwei Threads gleichzeitig `get_simulator()` aufrufen, koennen zwei Instanzen erstellt werden. Obwohl der Bot aktuell single-threaded laeuft, ist dies eine Zeitbombe bei spaeterer Parallelisierung.

**Empfohlener Fix:**
```python
from threading import Lock
_lock = Lock()
def get_simulator() -> ExecutionSimulator:
    global _simulator
    if _simulator is None:
        with _lock:
            if _simulator is None:
                _simulator = ExecutionSimulator()
    return _simulator
```

---

### W5: `crash.log` waechst unbegrenzt (`cockpit.py`, Zeile 103)

**Datei:** `cockpit.py`
**Zeile:** 103
**Problem:** `open(CRASH_LOG, "a")` appended endlos. Im Crash-Loop-Szenario (z.B. bei kaputtem API-Key) wird die crash.log innerhalb von Stunden riesig. Kein Rotationsmechanismus.

**Empfohlener Fix:** RotatingFileHandler oder manuelles Truncate nach z.B. 10MB.

---

### W6: `_parse_last_crash()` liest gesamte crash.log in Speicher (`cockpit.py`, Zeile 120)

**Datei:** `cockpit.py`
**Zeile:** 120
**Problem:** `CRASH_LOG.read_text()` liest die gesamte Datei in den Speicher. Bei einer grossen crash.log (siehe W5) kann dies zu hohem Speicherverbrauch fuehren. Die Funktion wird bei JEDEM `write_bot_status()`-Aufruf aufgerufen.

**Empfohlener Fix:** Nur die letzten N Bytes der Datei lesen (z.B. `f.seek(-10000, os.SEEK_END)`).

---

### W7: Fehlende Fehlerbehandlung bei `yaml.safe_load` (`averaging_down.py`, Zeile 176-177 und `edge_reversal.py`, Zeile 69-70)

**Datei:** `paper_trader/averaging_down.py` Zeile 176-177
**Datei:** `paper_trader/edge_reversal.py` Zeile 69-70
**Problem:** `yaml.safe_load(f)` kann bei korruptem YAML eine `yaml.YAMLError` werfen. Der aeussere `try/except` faengt das zwar ab, aber die Fehlermeldung ist dann generisch ("Cannot load weather model for averaging down"). Ausserdem wird `yaml` erst innerhalb der Funktion importiert, was bei Import-Fehler eine wenig aussagekraeftige Meldung ergibt.

**Empfohlener Fix:** Spezifisches YAML-Error-Handling mit aussagekraeftiger Meldung.

---

### W8: API-Keys im Klartext in Environment (`multi_forecast.py`, Zeile 103, 179, 250)

**Datei:** `core/multi_forecast.py`
**Zeile:** 103 (`TOMORROW_IO_API_KEY`), 179 (`OPENWEATHER_API_KEY`), 250 (`WEATHERAPI_KEY`)
**Problem:** API-Keys werden per `os.environ.get()` geladen. Wenn `.env` versehentlich committed wird, sind alle Keys kompromittiert. Es gibt keine Warnung wenn der Key ein ungueltiges Format hat (z.B. zu kurz).

**Empfohlener Fix:**
- `.env` in `.gitignore` sicherstellen
- Key-Format-Validierung (z.B. Mindestlaenge)
- Warnung loggen wenn kein Key vorhanden ist (aktuell wird still `None` zurueckgegeben)

---

### W9: `_fetch_gamma_markets_batch` laedt ALLE 500 Markets (`snapshot_client.py`, Zeile 149-150)

**Datei:** `paper_trader/snapshot_client.py`
**Zeile:** 149-150
**Problem:** `_fetch_gamma_markets_batch()` ruft `fetch_all_markets(max_markets=500)` auf, um darin nach den gewuenschten Market-IDs zu suchen. Das ist extrem ineffizient und unnoetig, da `get_snapshots_batch()` (Zeile 207-240) diese Funktion gar nicht mehr nutzt und stattdessen individuelle Lookups macht. Aber `get_snapshot()` nutzt als Fallback `fetch_markets(limit=100)` (Zeile 182), was ein aehnliches Problem ist.

**Empfohlener Fix:** Die ungenutzten Batch-Methoden entfernen und nur direkte Lookups nutzen.

---

### W10: Keine Rate-Limiting-Abhaengigkeit zwischen API-Calls (`multi_forecast.py` + `collector/client.py`)

**Datei:** `core/multi_forecast.py` und `collector/client.py`
**Problem:** Die Pipeline macht API-Calls an Polymarket (Collector + Snapshot), Tomorrow.io, OpenWeather, WeatherAPI und NOAA. Es gibt keinen globalen Rate-Limiter. Bei vielen offenen Positionen (z.B. 30) werden 30 individuelle Snapshot-Requests plus 30 Forecast-Requests gemacht - das kann API-Limits sprengen.

**Empfohlener Fix:** Globaler Rate-Limiter (z.B. Token-Bucket) oder mindestens `time.sleep()` zwischen Requests.

---

### W11: `cost_basis_eur` kann negativ werden bei `release_capital` (`capital_manager.py`, Zeile 247)

**Datei:** `paper_trader/capital_manager.py`
**Zeile:** 247
**Problem:** `return_amount = cost_basis_eur + pnl_eur`. Wenn `pnl_eur` stark negativ ist (z.B. -200 bei cost_basis von 100), wird `return_amount = -100`, was die `available_capital` REDUZIERT statt zu erhoehen. Das `allocated_capital` wird trotzdem um `cost_basis` reduziert (Zeile 253). Das kann zu `available_capital < 0` fuehren, was eine Buchungs-Inkonsistenz ist.

**Empfohlener Fix:**
```python
return_amount = max(0.0, cost_basis_eur + pnl_eur)
```

---

### W12: Sleep-Loop im Scheduler kann bei Systemzeit-Aenderung fehlschlagen (`cockpit.py`, Zeile 404-410)

**Datei:** `cockpit.py`
**Zeile:** 404-410
**Problem:** Der Countdown-Loop `for remaining in range(interval_seconds, 0, -1): time.sleep(1)` ist empfindlich gegenueber Systemzeit-Aenderungen (z.B. NTP-Sync, Sommerzeit). Der innere `except Exception` (Zeile 408) faengt Fehler ab und ruft dann `time.sleep(interval_seconds)` auf - aber wenn das erste Sleep fehlgeschlagen ist, kann das zweite ebenfalls fehlschlagen, was zu einer Endlosschleife fuehrt (die aeussere While-Schleife startet erneut).

**Empfohlener Fix:** `threading.Event().wait()` oder Berechnung mit `time.monotonic()` statt `time.sleep()`.

---

## NICE-TO-HAVE - Verbesserungen

### N1: Veraltete `datetime.utcnow()` Nutzung (mehrere Dateien)

**Dateien:**
- `core/weather_engine.py` Zeile 198, 245, 445
- `core/multi_forecast.py` Zeile 161, 211, 261
- `paper_trader/averaging_down.py` Zeile 242
- `paper_trader/edge_reversal.py` Zeile 108
- `app/orchestrator.py` Zeile 469

**Problem:** `datetime.utcnow()` ist seit Python 3.12 deprecated und gibt ein naives datetime-Objekt zurueck (ohne Timezone-Info). Das kann bei Vergleichen mit timezone-aware datetimes zu Fehlern fuehren.

**Empfohlener Fix:** `datetime.now(timezone.utc)` statt `datetime.utcnow()`

---

### N2: `sys.path.insert(0, ...)` in mehreren Modulen

**Dateien:**
- `paper_trader/simulator.py` Zeile 31
- `paper_trader/position_manager.py` Zeile 25
- `paper_trader/averaging_down.py` Zeile 30
- `paper_trader/edge_reversal.py` Zeile 27
- `paper_trader/snapshot_client.py` Zeile 32

**Problem:** Jedes Modul manipuliert `sys.path` individuell. Das ist fragil und kann zu Import-Reihenfolge-Problemen fuehren. Ausserdem wird der Pfad bei jedem Import eingefuegt, was die Path-Liste verlaengert.

**Empfohlener Fix:** Entweder ein `pyproject.toml` mit korrektem Package-Setup oder ein zentraler `__init__.py` der den Pfad setzt.

---

### N3: Keine Input-Validierung fuer `--interval` Argument (`cockpit.py`, Zeile 535-536)

**Datei:** `cockpit.py`
**Zeile:** 535-536
**Problem:** `--interval` akzeptiert jeden Integer, auch negative Werte oder 0. `time.sleep(0)` oder `time.sleep(-1)` wuerden zu unerwarteten Verhalten fuehren.

**Empfohlener Fix:**
```python
if args.interval < 60:
    parser.error("Interval must be at least 60 seconds")
```

---

### N4: Hartcodierte Magic Numbers

**Dateien und Zeilen:**
- `paper_trader/simulator.py` Zeile 244: `spread_pct=4.0` (woher kommt 4%?)
- `paper_trader/snapshot_client.py` Zeile 276-277: `yes_price - 0.01` / `+ 0.01` (1 Cent Spread)
- `paper_trader/averaging_down.py` Zeile 242: `timedelta(days=2)` (warum 2 Tage?)
- `paper_trader/edge_reversal.py` Zeile 108: `timedelta(days=2)` (gleicher Magic Number)
- `collector/client.py` Zeile 135: `time.sleep(0.5)` (warum 500ms?)
- `collector/client.py` Zeile 256: `time.sleep(0.3)` (warum 300ms?)

**Problem:** Diese Werte sollten als benannte Konstanten mit Kommentar definiert sein.

**Empfohlener Fix:** Konstanten mit erklaerenden Namen an den Anfang der jeweiligen Datei verschieben.

---

### N5: Windows-spezifischer Code in `cockpit.py` ohne Fallback

**Datei:** `cockpit.py`
**Zeile:** 42-59 (`_pid_alive`)
**Problem:** Der Hauptpfad nutzt `ctypes.windll` was nur unter Windows existiert. Der Fallback `os.kill(pid, 0)` funktioniert unter Windows nicht zuverlaessig. Wenn der Code auf Linux/Mac ausgefuehrt wuerde, koennte die PID-Pruefung fehlerhaft sein.

**Empfohlener Fix:** Explizite Plattform-Pruefung und separater Unix-Pfad.

---

### N6: Keine Deduplizierung bei Pipeline-Steps (`orchestrator.py`)

**Datei:** `app/orchestrator.py`
**Zeile:** 105-133
**Problem:** Wenn ein Step fehlschlaegt (z.B. Collector), laufen die folgenden Steps trotzdem. Der Weather Observer versucht dann alte Kandidaten-Dateien zu nutzen (Fallback, Zeile 190-197), was sinnvoll ist. Aber der Paper Trader verarbeitet auch Proposals die auf veralteten Daten basieren. Es gibt keine Markierung welche Daten "frisch" und welche "stale" sind.

**Empfohlener Fix:** Daten-Freshness-Timestamp mitgeben und bei zu alten Daten warnen.

---

### N7: Logging auf INFO-Level fuer Kelly-Sizing (`kelly.py`, Zeile 97-101)

**Datei:** `paper_trader/kelly.py`
**Zeile:** 97-101
**Problem:** `logger.info()` wird bei JEDER Kelly-Berechnung aufgerufen. Bei 50 Kandidaten pro Run sind das 50 INFO-Zeilen die die Logs unuebersichtlich machen.

**Empfohlener Fix:** Auf `logger.debug()` aendern.

---

### N8: `_extract_city_date` Regex ist fragil (`simulator.py`, Zeile 78-94)

**Datei:** `paper_trader/simulator.py`
**Zeile:** 78-94
**Problem:** Die Regex-Patterns zur Stadt/Datum-Extraktion sind hart auf englische Polymarket-Fragen kodiert. Wenn Polymarket das Frageformat aendert (z.B. "Will the high temperature..." statt "...temperature in City be..."), greifen die Patterns nicht mehr. Es gibt separate, inkompatible Implementierungen in `averaging_down.py` (Zeile 60-129).

**Empfohlener Fix:** Zentralisierte Stadt/Datum-Extraktion in einem gemeinsamen Modul (z.B. `shared/market_parser.py`).

---

### N9: SSL-Context wird mehrfach erstellt

**Dateien:**
- `core/multi_forecast.py` Zeile 85: `ssl.create_default_context()` bei jedem API-Call
- `paper_trader/snapshot_client.py` Zeile 107: Einmal im Constructor
- `collector/client.py` Zeile 64: Einmal im Constructor

**Problem:** In `_api_get()` in `multi_forecast.py` wird bei JEDEM HTTP-Call ein neuer SSL-Context erstellt. Das ist nicht kritisch, aber ueberfluessig.

**Empfohlener Fix:** SSL-Context einmal global erstellen und wiederverwenden.

---

### N10: Fehlende Type-Hints bei Rueckgabewerten

**Dateien:**
- `cockpit.py` Zeile 306: `run_pipeline_with_progress()` hat kein Return-Type-Hint
- `paper_trader/averaging_down.py` Zeile 99-105: `extract_city()` und `extract_threshold_f()` haben Hints, aber die Patterns koennen `None` bei verschiedenen Edge Cases zurueckgeben ohne Warnung

**Problem:** Fehlende Type-Hints erschweren die statische Analyse und IDE-Unterstuetzung.

**Empfohlener Fix:** Durchgehende Type-Hints einfuegen, idealerweise mit `mypy` in der CI-Pipeline.

---

## Generelle Architektur-Beobachtungen

### Staerken des aktuellen Codes:
1. **Gute Exception-Hierarchie** in `collector/client.py` - differenziert zwischen 4xx und 429/5xx
2. **Exponentielles Backoff** korrekt implementiert in der Retry-Logik
3. **Atomarer Write** fuer `bot_status.json` (via .tmp + rename) ist best practice
4. **RotatingFileHandler** fuer Logs verhindert unbegrenztes Wachstum
5. **Threading-Lock** im `CapitalManager` fuer Kapital-Allokation
6. **Conservative Slippage Model** mit Floor und Cap ist robust

### Systematische Schwaechen:
1. **Kein globales Timeout** fuer die gesamte Pipeline - ein Haengen in einer API kann die ganze Pipeline blockieren
2. **Append-only JSONL** ohne Rotation/Bereinigung - waechst monoton
3. **Kein Health-Check der Abhaengigkeiten** (API-Erreichbarkeit, Disk-Space, etc.)
4. **Kein Graceful Shutdown Signal-Handler** - bei SIGTERM (z.B. Windows Task Manager) wird kein Cleanup gemacht

---

## Prioritaets-Reihenfolge fuer Fixes

1. **K2** (Atomarer Write fuer capital_config.json) - Datenverlust-Risiko
2. **K1** (Bare except entfernen) - Bot-Stabilit bei Ctrl+C
3. **K8** (Globales Timeout fuer API-Chain) - Pipeline kann haengen
4. **K4/K5** (Division by Zero Guards) - Crash-Risiko
5. **K6** (JSONL Performance) - Wird mit der Zeit schlimmer
6. **K3** (JSONL Atomarer Write) - Datenintegritaet
7. **K7** (Lockfile Race Condition) - Seltener Edge Case
8. **W11** (Negative Capital) - Buchungs-Inkonsistenz
9. **W3** (Config Validierung) - Silent Failures
10. Rest nach Verfuegbarkeit

---

*Dieser Report wurde automatisch generiert am 2026-02-09 vom Stabilitaets-Check Agent.*
*Keine Code-Aenderungen wurden vorgenommen - nur Analyse.*
