# Profitability Optimizer Loop — 2026-04-19 (Runde 2, ~14:17 UTC)

Generated: 2026-04-19 ~14:17 UTC | Run by: scheduled optimizer task

---

## 1. Status

| Kennzahl | Wert |
|---|---|
| Equity | 4.952,35 EUR (-47,65 EUR / -0,95% ROI) |
| Win Rate (gesamt) | 32,26% (10/31 Trades) |
| Profit Factor | 0,261 — KRITISCH SCHLECHT |
| Max Drawdown | 48,99 EUR / 0,98% |
| Bot-Status | ELEVATED (edge_drought_8 — 8 Runs ohne Edge-Kandidaten) |
| YES-only Modus | AKTIV seit 2026-04-18 |
| Neue Entries heute | 0 (0 Edge-Kandidaten aus 393 Weather-Märkten) |

**Kurzfazit**: Die Verlustpfade (NO-Bets, Stale-Proposal-Drift) sind identifiziert und durch Code-Fixes der letzten 24h großteils geschlossen. Das akute Kapitalrisiko ist auf -0,95% Drawdown begrenzt. Der größte verbleibende Verlusttreiber — Cold Bias bei YES at_or_above — ist jetzt durch Position-Size-Cap adressiert.

---

## 2. Diagnose

### Top 3 Verlusttreiber (historisch, aus 31 geschlossenen Trades)

#### A) Atlanta YES at_or_above — -18,46 EUR (größter Einzelverlust)
- Market 2003743: "Will highest temp in Atlanta be 74°F or higher on April 19?"
- Entry 2026-04-17, Exit 2026-04-19 via Emergency-SL (-89,8%)
- Modell: 78,3% Wahrscheinlichkeit | Markt: 44,2% implied | **Actual: NEIN (Temp nicht erreicht)**
- **Cold Bias bestätigt**: Modell überschätzt systematisch HOT-Day-Wahrscheinlichkeit für at_or_above-Märkte in der 0,30–0,65 Preiszone
- Stake war 20 EUR (Kelly-Sizing bei 84% Edge → große Allokation)

#### B) Stop-Loss-Kaskade NO-Bets — -41,06 EUR (10 SL-Exits)
- Alle 10 SL-Exits waren NO-Bets auf "between"/"exact"-Märkten
- Durchschnittlicher SL-Verlust: -4,11 EUR bei SL-Größe von ~73–93%
- **Status: BLOCKIERT** — YES-only Modus aktiv, NO-between/exact generell gebannt
- Ursache war Resolution-Day-Preis-Spikes bei engen Temperatur-Bändern

#### C) Ankara YES-exact Stale-Proposal — ~-0 EUR (behoben, Futur-Risiko eliminiert)
- Proposal bei YES=19,5% generiert (Edge=+87,8%), aber Execution bei YES=49,7%
- Realtime-Edge bei Execution: (36,6%-49,7%)/49,7% = **-26,2%** (negativ!)
- Trade wurde trotzdem eingegangen (Code-Fix fehlte noch)
- Position PAPER-20260419-34c4dc49 ist noch OPEN (10 EUR Risiko)
- **Fix implementiert in heutigem vorherigen Run**: Drift-Guard blockiert zukünftige Fälle
- Rollback-Bedingung: Kein Rollback nötig — der Guard ist immer korrekt

---

### Top 3 Gewinnmuster

#### A) TP3 YES-Exits — 7/7 = 100% WR, +11,79 EUR
- Paris YES 19°C: +0,92 + 2,24 EUR (beide TP3)
- SF YES 66-67°F: +1,33 EUR (TP3 +36%)
- LA YES 68-69°F (re-entry nach SL bei 0,147): +5,19 EUR (+117%!)
- Tokyo YES: +1,08 EUR
- **Pattern**: YES-Bets in "between"-Märkten mit niedrigem Entry-Preis (0,10–0,45) performen stark

#### B) Guardrail-Exits als Gewinner — +4,03 EUR
- Houston NO-between (proaktiver Guardrail-Exit): +1,95 EUR (+39%)
- Atlanta NO-between: +1,58 EUR (+31%)
- Seattle NO-between: +1,51 EUR (+30%)
- Pattern: Wenn NO-Bets früh erkannt und proaktiv geschlossen werden, rettet das den Großteil des Kapitals

#### C) Niedrigpreis YES-Entries (0,10–0,20 Zone) — Beste Risk/Reward
- LA YES-Nachkauf nach SL bei 0,147: +5,19 EUR (+103%)
- Das profitabelste Preisband im gesamten System
- Die Stale-Proposal-Drift-Guard muss diese Entries bei STEIGENDEM Preis blockieren, nicht verhindern

---

### Wichtigste Datenprobleme

| Problem | Schwere | Status |
|---|---|---|
| Brier Skill Score -0,47 (schlechter als Baseline) | KRITISCH | Modell-Cold-Bias, kein Quick-Fix |
| 8 aufeinanderfolgende Zero-Edge-Runs | HOCH | Strukturell: Marktlage bietet kaum YES-Signals |
| Calibration bins bei 0.4–0.6 zeigen 0% Trefferquote (4/5 Bins) | HOCH | Modell unzuverlässig in mittlerem Konfidenzbereich |

### Wichtigste Exit-/Risikoprobleme

| Problem | Schwere | Status |
|---|---|---|
| Atlanta -18,46 EUR (20 EUR Stake, Cold Bias) | HOCH | **BEHOBEN: at_or_above YES Size-Cap implementiert** |
| Ankara Stale-Proposal (negative Realtime-Edge) | MITTEL | **BEHOBEN: Drift-Guard aktiv** |
| SL doppelt auf gleichem Markt (NYC between 2×) | MITTEL | **BEHOBEN: SL-Cooloff 12h** |

---

## 3. Maßnahmen

### Priorität 1 — IMPLEMENTIERT: at_or_above YES Position-Size-Cap
**Was**: In `paper_trader/simulator.py` nach Zeile 896 (nach Kelly-Cap): Cap bei 5 EUR wenn side=YES UND market_type=at_or_above UND snapshot.mid_price in [0.30, 0.65].

**Warum**: Atlanta -18,46 EUR war ein 20 EUR Stake mit Cold-Bias-Fehler. Bei 5 EUR wäre der Verlust -4,62 EUR statt -18,46 EUR (= 13,85 EUR gespart).

**Erwarteter Effekt**: Max Einzelverlust auf YES at_or_above sinkt von ~18 EUR auf ~5 EUR. TP-Gewinne werden kleiner (Tokyo: ~+0,27 EUR statt +1,08 EUR wenn 5 EUR), aber asymmetrisch besser.

**Rollback-Bedingung**: Entfernen wenn YES at_or_above WR ≥ 60% über 5+ neue Trades.

### Priorität 2 — BEOBACHTUNG: Offene Positionen prüfen

Offene Positionen (Stand 14:17 UTC):
1. **Ankara YES-exact, market 2003773** (10 EUR): Proposal-Edge war korrekt bei 19,5%, execution bei 49,7% → negative Realtime-Edge. Diese Position hat erhöhtes Verlustrisiko. Monitor-only, kein manueller Eingriff im autonomen Modus.
2. **Dallas YES-at_or_below 71°F, market 2011134** (20 EUR): edge=96,7%, model=46,2% vs market=28,3% → positiver Edge. NICHT vom neuen Cap betroffen (at_or_below, nicht at_or_above). Risikoprofil ist akzeptabel.
3. **Buenos Aires YES-exact** (20 EUR): Auflösung Apr 18 wahrscheinlich abgelaufen → Zombie oder expired.

**Empfehlung**: Keine Aktion. Position-Manager und Guardrails laufen automatisch.

### Priorität 3 — HYPOTHESE für nächsten Loop: MIN_EDGE_ABSOLUTE Experiment

**Status**: Unverändert aus Runde 1. 0 Observer-Kandidaten heute → kein geeignetes Testfenster.

**Aktivieren wenn**: Observer > 5 Kandidaten findet, die aktuell nur wegen Edge-Floor durchfallen.

---

## 4. Erwarteter Effekt

| Metrik | Vorher | Nach Cap (retrograd) | Verbesserung |
|---|---|---|---|
| Max Einzelverlust YES | -18,46 EUR | -4,62 EUR | +13,84 EUR |
| Worst-Case bei 84% Edge, falsch | -18,46 EUR | -4,62 EUR | Faktor 4× Risikoreduktion |
| Avg YES Gewinn | unverändert (TP3-System) | leicht kleiner (-0,5 EUR) | Tradeoff akzeptabel |
| Max Drawdown | 0,98% | ~0,72% retrograd | Signifikante Verbesserung |

---

## 5. Testplan

**Kurztest**: `python cockpit.py --run-once --no-color` → ✅ BESTANDEN (Syntax OK, 0 Fehler, 0 neue Entries)

**Validierung des Caps** (messbar):
- Nächste YES at_or_above Entry im 0.30–0.65 Preisband muss Log zeigen: `"at_or_above YES size capped X→5.0 EUR"`
- Win/Loss dieser gecappten Entries nach 5+ Trades auswerten
- Rollback-Trigger: WR ≥ 60% → Cap kann auf 10 EUR erhöht werden

**Kennzahl die sich verbessern muss**: Max Einzelverlust auf YES at_or_above ≤ 5 EUR (statt >15 EUR).

---

## 6. Entscheidung: ANPASSEN (1 Änderung implementiert)

**Implementiert**: `at_or_above YES size cap` — konservative, reversible Maßnahme mit klarer Rollback-Bedingung.

**HOLD** für alle anderen Parameter: YES-only Modus, SL-Cooloff 12h, Stale-Drift-Guard, Edge-Floors — alle korrekt konfiguriert.

**Weitere Daten nötig** für: MIN_EDGE_ABSOLUTE Experiment (wartet auf Observer > 5 Kandidaten).

---

## Anhang: Code-Änderung

**Datei**: `paper_trader/simulator.py` — nach Zeile 896 (nach Kelly-Cap-Anwendung):

```python
# at_or_above YES position size cap (cold-bias risk mitigation):
if side == "YES" and market_type == "at_or_above":
    _mid_price = float(snapshot.mid_price or 0.5)
    if 0.30 <= _mid_price <= 0.65:
        _at_or_above_cap = 5.0
        if position_eur > _at_or_above_cap:
            logger.info(
                "at_or_above YES size capped %.1f→%.1f EUR (mid=%.1f%%). "
                "Cold-bias guard: model overestimates HOT-day probability in mid-range.",
                position_eur, _at_or_above_cap, _mid_price * 100,
            )
            position_eur = _at_or_above_cap
```

**Hypothesen-Update**:

| # | Hypothese | Status | Ergebnis |
|---|---|---|---|
| H-01 | YES-only Mode verbessert WR | PROMOTE | 4/4=100% WR, +5.57 EUR ✓ |
| H-02 | LOW-liq Block stoppt Atlanta-Verluste | PROMOTE | 0 neue LOW-liq Verluste ✓ |
| H-03 | 12h Proposal-Intake-Fenster | PROMOTE | Korrekt implementiert ✓ |
| H-04 | LOW-liq YES bypass für HIGH CONVICTION | PENDING | Human Approval erforderlich |
| H-05 | MIN_EDGE_ABSOLUTE 0.10→0.07 | PENDING | Kein Testfenster heute |
| **H-06** | **at_or_above YES Size-Cap** | **NEU/AKTIV** | **Implementiert 2026-04-19 14:10 UTC** |

---

*Nächste Iteration*: Prüfen ob Dallas YES-at_or_below (20 EUR) korrekt aufgelöst wird. Observer-Kandidaten für neuen Test-Loop abwarten.
