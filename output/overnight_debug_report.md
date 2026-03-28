# Overnight Debug Report — 2026-03-28

## Zusammenfassung

- **5 Bugs untersucht**
- **2 Bugs gefixt** (KRITISCH — bereits committed)
- **1 Design-Gap dokumentiert** (kein Code-Bug)
- **1 Bug als falsch-positiv eingestuft** (Capital Reconciliation funktioniert korrekt)
- **1 vorhandener Fix bestätigt** (weather_signal.py to_json bereits gefixt)

---

## Bug 1: TP/SL Prozent-Berechnung fuer NO-Positionen (KRITISCH — GEFIXT)

**Prioritaet:** 3 (TP/SL-Logik)
**Status:** GEFIXT — Commit 5156edc

### Root Cause

PositionManager._calc_unrealized_pct() in paper_trader/position_manager.py hatte einen fundamentalen Fehler bei NO-Positionen:

Fehlerhafter Code:


current_price ist immer snapshot.mid_price = der YES-Marktpreis.
entry ist der NO-Entry-Preis (= 1 - YES-Preis zum Zeitpunkt des Einstiegs).

Der fehlerhafte Code vergleicht direkt den NO-Entry-Preis mit dem aktuellen YES-Preis.
Das ergibt voellig falsche Prozentwerte.

Beispiel mit echten Trades (Markt 1714786):
- NO-Entry = 0.7725 (YES war ~0.23), aktueller YES-Preis = 0.27
- Fehlerhafte Berechnung: (0.7725 - 0.27) / 0.7725 = +64.9% -> TP3 ausgeloest!
- Korrekte Berechnung: ((1-0.27) - 0.7725) / 0.7725 = -4.2% (leichter Verlust)
- Tatsaechliche P&L: -7.7% (Position verliert Geld, TP3 haette nie feuern sollen)

Bestaetigte Auswirkung (7 von 26 Trades betroffen):
- Markt 1714786: Exit TP3 (+67.0%), tatsaechliche P&L = -7.7%
- Markt 1714829: Exit TP3 (+75.3%), tatsaechliche P&L = -8.2%
- Markt 1714822: Exit TP3 (+76.9%), tatsaechliche P&L = -5.8%
- Markt 1680717: Stop-Loss -340.6%, tatsaechliche P&L = -0.3% (viel zu frueh!)
- Markt 1680717: Stop-Loss -289.3%, tatsaechliche P&L = -14.8%
- Markt 1714814: Stop-Loss -487.7%, tatsaechliche P&L = -16.3%

Fix (position_manager.py):


---

## Bug 2: Trailing-Stop-Preis-Berechnung fuer NO-Positionen (KRITISCH — GEFIXT)

**Prioritaet:** 3 (TP/SL-Logik, Teil 2)
**Status:** GEFIXT — Commit 5156edc

### Root Cause

_calc_trailing_stop_price() berechnete falsche Trailing-Stop-Preise fuer NO-Positionen.

Fehlerhafter Code:


Der Stop-Preis wird als YES-Marktpreis-Schwelle gespeichert. Der fehlerhafte Code setzte den
Stop auf ~0.77 (= NO-Entry-Preis), was bedeutete der Stop feuerte sofort wenn YES > 0.77 —
aber YES war bereits am Entry ~0.23! Der Stop war also von Anfang an sinnlos.

Fix:


Fuer entry=0.77, lock_in=0.0: Stop = 1.0 - 0.77 = 0.23 (korrekt).

16 neue Unit-Tests in tests/unit/test_unrealized_pct.py — alle bestanden.

---

## Bug 3: YES/NO Seiten-Auswahl (PRIORITAET 1 — KEIN CODE-BUG)

**Prioritaet:** 1
**Status:** KEIN CODE-BUG — Design-Gap dokumentiert

Die Seiten-Auswahl-Logik (simulator.py Zeile 433) ist korrekt:
  side = YES wenn proposal.edge > 0, sonst NO
  proposal.edge = model_probability - implied_probability

Verdaechtige hohe NO-Entry-Preise (z.B. 0.7725, 0.8292) entstehen durch stale Proposals:
- Proposal bei YES=0.73 erstellt -> edge=-0.64 -> BUY NO bei 0.27
- Bei Ausfuehrung YES=0.22 (Markt bewegt sich!) -> NO-Preis = 0.78
- Bot kauft korrekt NO @ 0.77 aber Markt hat Vorhersage bereits eingepreist
- Tatsaechlicher Edge bei Entry: (1-0.09) - 0.77 = +14% statt erwarteter +64%

Fehlende Sicherheitspruefung: Kein Re-Check des Edges gegen den aktuellen Snapshot-Preis.
Empfehlung: Entry-Edge-Revalidierung implementieren (siehe Abschnitt Empfehlungen).

---

## Bug 4: Capital Reconciliation (KEIN BUG)

**Prioritaet:** 4
**Status:** KEIN BUG — funktioniert korrekt

SELF-HEAL Capital Reconciliation Meldungen sind normales Verhalten.
Capital allocated = 287.91 EUR = exakt die Summe der 5 echten offenen Positionen.
Die 25 rohen OPEN-Eintraege in paper_positions.jsonl sind mehrfache Status-Updates derselben Positionen (nach get_open_positions() Dedup korrekt 5 Positionen).

---

## Bug 5: Weather Observations Log Format (BEREITS GEFIXT)

**Prioritaet:** 5
**Status:** BEREITS GEFIXT (vor dieser Debug-Session)

weather_signal.py to_json() war indent=2 (multi-line JSON), _load_jsonl_tail() liest zeilenweise.
Fix bereits vorhanden: return json.dumps(self.to_dict(), separators=(',', ':'))

Alte Logs (7.2 MB, 8264 Eintraege) enthalten noch multi-line JSON aus der Zeit vor dem Fix.
Neue Observationen werden korrekt im JSONL-Format geschrieben.
Empfehlung: logs/weather_observations.jsonl bei Gelegenheit leeren.

---

## Backtest-Ergebnisse

Datei: output/backtest_results.json

| Kennzahl | Wert |
|----------|------|
| Gesamt geschlossene Positionen | 43 |
| Davon wirklich aufgeloest | 2 |
| Modell korrekt (bei aufgeloesten) | 0 / 2 (0%) |
| Trades mit positivem Edge bei Entry | 17 / 17 (alle SELF-HEAL exits) |
| TP/SL-Bug-Faelle | 7 |
| SL-Prozent-Inkonsistenz | 6 |
| Gesamt realisierter P&L | -76.36 EUR |
| Win / Loss / Zero-PnL | 3 / 23 / 17 |

Hinweis: Nur 2 aufgeloeste Positionen — zu wenig fuer statistisch signifikante Modell-Aussagen.

---

## Bot-Daemon Start-Befehle

Windows: DAUERLAUF.bat oder start_bot.bat
Linux:   ./run_daemon.sh
Debug:   python cockpit.py --run-once --no-color

Laeuft automatisch alle 15 Min (INTERVAL=900).

---

## Ensemble-Kalibrierung

OpenWeather 3h->daily Fix ist korrekt implementiert (openweather_client.py Zeilen 93-109).

---

## Empfehlungen

### Hoch (naechste Sprint)

1. Entry-Edge-Revalidierung implementieren:
   Nach snapshot-Fetch in simulator.py:
   actual_edge = model_prob - snapshot.mid_price  (fuer YES)
   actual_edge = (1-model_prob) - (1-snapshot.mid_price)  (fuer NO)
   Bei actual_edge < MIN_EDGE -> SKIP (Markt bewegt sich zu stark)

2. Observation Log bereinigen (optional):
   echo  > logs/weather_observations.jsonl

### Mittel

3. Win-Rate Tracking verbessern: Marktaufloesungs-Monitoring optimieren
4. TP-Parameter pruefen: STOP_LOSS_PCT = -0.35 eventuell auf -0.20 reduzieren

---

## Test-Ergebnisse nach Fixes

16 neue Tests (test_unrealized_pct.py): 16/16 PASSED
Gesamt-Test-Suite: 401/407 PASSED (6 pre-existierende Fehler, unveraendert)
Pipeline-Test: cockpit.py --run-once laeuft durch

Pre-existierende Testfehler (nicht durch diesen Debug verursacht):
- TestPositionManagement::test_stop_loss_bei_kursverlust: Test-Erwartung falsch
  (SL-Threshold = -35%, Test triggert bei -30%)
- 5x TestTimeDecay.*: Abweichungen in kelly.py time_decay_factor Werten

---

Erstellt: 2026-03-28 | Agent: Overnight Debug Session
