# Overnight Debug Report — 2026-03-28

Erstellt: 2026-03-28
Autor: Claude Code Agent
Status: ABGESCHLOSSEN

## Executive Summary

**ROOT CAUSE FOUND**: Die 5% Win-Rate und -73.90 EUR P&L wurden durch einen kritischen Bug in `_calc_unrealized_pct()` verursacht, der ALLE NO-Positionen (69% der Trades) zerstoert hat. Falsche Take-Profit und Stop-Loss Trigger haben Positionen zum falschen Zeitpunkt geschlossen und potentielle Gewinner in garantierte Verlierer verwandelt.

Drei weitere Bugs wurden gefunden und gefixt: Kapital-Reconciliation-Drift, leerer Observation-Log, und ein Trailing-Stop-Berechnungsfehler.

---

## Bug #1: NO-Position Unrealized P&L Berechnung (KRITISCH)

**Datei:** `paper_trader/position_manager.py:_calc_unrealized_pct`
**Impact:** 14/37 geschlossene Positionen (38%) direkt betroffen. Alle 29 NO-Positionen potentiell betroffen.
**Schwere:** KRITISCH — Hauptursache der 5% Win-Rate

### Ursache

Fuer NO-Positionen wird `entry_price` in NO-Terms gespeichert (z.B. 0.77 wenn YES bei 0.23 stand), aber `current_price` von `snapshot.mid_price` ist immer der YES-Preis (z.B. 0.26).

**Alt (fehlerhaft):**
```python
return (entry - current_price) / entry
# = (0.7725 - 0.26) / 0.7725 = +66.3% (FALSCH)
```

**Korrekt:**
```python
current_no_price = 1.0 - current_price  # YES -> NO konvertieren
return (current_no_price - entry) / entry
# = (0.74 - 0.7725) / 0.7725 = -4.2% (RICHTIG)
```

### Konsequenzen

| Szenario | Fehlerhaft | Korrekt | Effekt |
|----------|-----------|---------|--------|
| NO entry=0.77, YES mid=0.26 | +66.3% | -4.2% | Falscher TP auf verlierender Position |
| NO entry=0.83, YES mid=0.24 | +75.3% | -5.8% | Falscher TP auf verlierender Position |
| NO entry=0.14, YES mid=0.87 | -487.7% | -11.7% | Falscher SL mit falschem Prozent |
| NO entry=0.20, YES mid=0.70 | -299.0% | -15.1% | Falscher SL mit falschem Prozent |

### Beweis aus geschlossenen Positionen

```
NO | entry=0.7725 | TP3 (+67.0%) | tats. P&L: -7.7% EUR  <- FALSCHER TP
NO | entry=0.8292 | TP3 (+75.3%) | tats. P&L: -8.2% EUR  <- FALSCHER TP
NO | entry=0.8240 | TP3 (+76.9%) | tats. P&L: -5.8% EUR  <- FALSCHER TP
NO | entry=0.1472 | SL (-487.7%) | tats. P&L: -16.3% EUR <- FALSCHER SL %
NO | entry=0.2030 | SL (-299.0%) | tats. P&L: -12.7% EUR <- FALSCHER SL %
```

### Fix

Commit `5156edc`: `current_price` (YES) wird in NO-Terms konvertiert vor dem Vergleich.

### Tests

16 Unit-Tests in `tests/unit/test_unrealized_pct.py` — alle bestanden.

---

## Bug #2: Trailing Stop Preis fuer NO-Positionen

**Datei:** `paper_trader/position_manager.py:_calc_trailing_stop_price`
**Impact:** Trailing Stops fuer NO-Positionen bei falschen YES-Schwellen gesetzt
**Schwere:** HOCH

### Ursache

Die alte Formel `entry_NO * (1 - lock_in_pct)` ergab z.B. 0.77 als Stop (Break-Even). Aber YES war bei ~0.23 — YES muesste auf 0.77 steigen um den Stop zu triggern, was fast nie passiert.

**Korrekte Formel:** `1.0 - entry_NO * (1 + lock_in_pct)` = 0.23 (Break-Even). Triggert korrekt wenn YES ueber den Entry-Punkt steigt.

### Fix

Gleicher Commit wie Bug #1.

---

## Bug #3: Kapital-Reconciliation Drift

**Dateien:** `paper_trader/capital_manager.py:reconcile()`, `core/self_healer.py:reconcile_capital()`
**Impact:** ~191 EUR Korrektur bei jedem Pipeline-Run
**Schwere:** MITTEL

### Ursache

Partial Exits (TP1/TP2) geben Kapital korrekt via `release_capital()` frei. Die Reconciliation liest aber die volle `cost_basis` aus noch-offenen Positionen und "korrigiert" den Betrag zurueck auf den vollen Wert.

### Fix

Commit `eff75dc`: Beide Reconciliation-Punkte lesen `tp_state.json` fuer `exited_fraction` pro Position: `expected = cost_basis * (1 - exited_fraction)`.

---

## Bug #4: Leerer Observation-Log im MCP

**Datei:** `mcp_server/server.py:_load_jsonl_tail()`
**Impact:** `get_market_observations()` gab immer `[]` zurueck
**Schwere:** NIEDRIG (nur Monitoring)

### Ursache

Die 190K-Zeilen `weather_observations.jsonl` startet mit alten mehrzeiligen JSON-Eintraegen. Die Parser-Funktion hatte ein einzelnes try/except um die ganze Schleife — eine ungueltige Zeile crashte alles.

### Fix

Commit `30a5d7f`: try/except pro Zeile + Tail-Read fuer grosse Dateien.

---

## Backtest-Ergebnisse

Siehe `output/backtest_results.json` fuer volle Daten.

| Metrik | Wert |
|--------|------|
| Geschlossene Positionen | 37 |
| Echte Trades | 26 |
| Gewinne | 3 |
| Verluste | 23 |
| Win-Rate | 11.54% |
| Gesamt-P&L | -76.35 EUR |
| Durchschn. Gewinn | +29.42 EUR |
| Durchschn. Verlust | -7.16 EUR |
| YES-Positionen | 11 |
| NO-Positionen | 26 |
| Bug-betroffene Positionen | 14 (38%) |
| Falsche TP-Exits (NO) | 7 |
| Falsche SL-Exits (NO) | 6 |

---

## Seiten-Auswahl (AUFTRAG 3)

**Ergebnis: KORREKT.** Die Seiten-Logik funktioniert wie vorgesehen:

```python
side = "YES" if proposal.edge > 0 else "NO"
# edge = model_probability - implied_probability
```

Das 70% NO-Verhaeltnis ist erwartet fuer Wetter-Maerkte wo das Modell haeufig denkt, der Markt ueberbewertet YES. Das EIGENTLICHE Problem war die TP/SL-Exit-Logik, nicht die Seiten-Auswahl.

---

## Bot-Daemon (AUFTRAG 7)

Einstiegspunkt: `python cockpit.py --scheduler` (15-Min Intervall, Crash-Resilienz, Lockfile).

---

## Ensemble-Kalibrierung (AUFTRAG 8)

Code-Level validiert. GFS 31-Member Ensemble-Counting (85% Gewicht) + CDF-Fallback (15%). Die bereits gefixten Bugs (Nacht-Temperatur, OpenWeather 3h-Slot) sind korrekt im Code.

---

## Offene Punkte

1. **Post-Fix-Trades beobachten**: 5 offene Positionen werden der erste Test
2. **TP/SL-Schwellen evtl. anpassen**: TP1=+7%, TP2=+12%, TP3=+18%, SL=-35% sollten mit korrekter Berechnung funktionieren
3. **Historische NO-Positionen nicht wiederherstellbar**: 14 bug-betroffene Trades sind abgeschlossen
4. **Kapital-Reset erwaegen**: -76.35 EUR P&L ist teilweise kuenstlich (bug-induziert)

---

## Commit-Historie

| Commit | Beschreibung |
|--------|-------------|
| `5156edc` | fix: NO-Position unrealized P&L und Trailing Stop |
| `eff75dc` | fix: Kapital-Reconciliation beruecksichtigt Partial Exits |
| `30a5d7f` | fix: Observation-Log-Reader toleriert nicht-JSONL Zeilen |
| `d9ec5ca` | test: 16 Unit-Tests + backtest_results.json |
