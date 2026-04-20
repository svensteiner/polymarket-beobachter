# Profitability Optimizer Loop — 2026-04-19

**Run time:** 2026-04-19T17:22 UTC  
**Bot status:** ALIVE | ELEVATED | DEFENSIVE  
**Capital:** 4,945.28 EUR (start: 5,000 EUR) | ROI: -1.09%  
**Open positions:** 0  
**Decision this cycle: HOLD — no config change**

---

## 1. AKTUELLER STATUS

| Metrik | Wert |
|--------|------|
| Total Kapital | 4,945.28 EUR |
| Realisiertes P&L | -54.72 EUR |
| ROI | -1.09% |
| Max Drawdown | 56.07 EUR (1.12%) |
| Bot Health | ELEVATED |
| Agent Policy | DEFENSIVE |
| Edge Drought | 8 Zyklen ohne Signal |
| Offene Positionen | 0 |
| Geschlossene Positionen | 32 (+ 28 Zombies à 0 EUR) |

---

## 2. WICHTIGSTE VERLUSTQUELLEN

### 2a. Stop-Loss: Primärer Blutungskanal (-41.06 EUR)
- 10 SL-Exits, alle mit -70% bis -93% Positionsverlust
- Durchschnittlich -4.11 EUR pro SL-Treffer
- Wenn ein NO-Trade von SL getroffen wird, hat die Position fast ihren vollen Wert verloren
- Ursache: Markt bewegt sich stark gegen Modell → YES-Preis steigt stark → NO-Wert kollabiert

### 2b. Emergency-SL auf LOW-Liquiditätsmärkten (-25.53 EUR)
- 2 Treffer: Atlanta YES/at_or_above (-18.46) + Ankara YES/exact (-7.07)
- Positionen konnten nicht normal gemanagt werden → Emergency-SL bei -89.8% / -67.8%
- **BEREITS BEHOBEN**: LOW-liq Block ist aktiv und verhindert neue Eintritte

### 2c. NO/exact Segment: Komplettes Versagen (19 Trades, 0% WR, -14.19 EUR)
- Jeder einzelne NO-Bet auf "wird es genau X°C sein" verliert
- Der Bot exitiert einige früh via Guardrail (-2.57 EUR aus 3 Exits), aber spart damit nur Folgeschäden
- 16 verbleibende NO/exact Trades gehen in SL oder Resolution Loss
- **Hypothese**: Modell unterschätzt systematisch die Wahrscheinlichkeit, dass Temperaturen genau in engen Bändern liegen

### 2d. YES/at_or_above Segment (-17.38 EUR, avg -4.34 EUR/Trade)
- 4 Trades, 25% WR, katastrophaler Durchschnittsverlust
- Bereits durch LOW-liq Block und DEFENSIVE Policy stark eingeschränkt

---

## 3. WICHTIGSTE GEWINNQUELLEN

### 3a. Take-Profit (TP3): Einziger zuverlässiger Winner
| Typ | Trades | WR | P&L |
|-----|--------|-----|-----|
| TP3 Exits | 6 | 100% | +11.52 EUR |
| Guardrail-Exit (NO-between blocked) | 3 | 100% | +5.04 EUR |
| Trailing-Stop | 1 | 100% | +0.26 EUR |

Take-Profits FUNKTIONIEREN. Wenn ein Trade ins Plus geht, werden gewinne sicher genommen.

### 3b. Profitable Städte (kleine Stichprobe)
- Houston: 2 Trades, 50% WR, +1.95 EUR
- Tokyo: 5 Positionen, 20% WR, +1.08 EUR

---

## 4. SEGMENT-ANALYSE

### Nach Side/Type
| Segment | n | WR | P&L | Avg |
|---------|---|----|-----|-----|
| NO/between | 25 | 20% | -20.94 | -0.84 |
| YES/at_or_above | 4 | 25% | -17.38 | -4.34 |
| **NO/exact** | **19** | **0%** | **-14.19** | **-0.75** |
| YES/exact | 4 | 50% | -3.91 | -0.98 |
| NO/at_or_above | 2 | 0% | 0.00 | 0.00 |
| NO/at_or_below | 5 | 20% | +0.36 | +0.07 |
| YES/between | 1 | 100% | +1.33 | +1.33 |

**Stärkstes Signal: NO/exact — 19 Trades, exakt 0% Win Rate**

### Nach Edge Bucket (Paradoxon!)
| Bucket | n | WR | P&L |
|--------|---|----|-----|
| premium (höchste Edge) | 43 | 21% | -38.85 |
| medium | 11 | 9% | -12.16 |
| high | 6 | 0% | -3.71 |

**Das "Premium"-Signal-Bucket verliert am meisten.** Höhere modellierte Edge = Model am stärksten falsch.  
→ Direkte Evidenz für kaputte Modell-Kalibrierung.

### Nach Stadt (Top 5 Verlierer)
| Stadt | n | WR | P&L |
|-------|---|----|-----|
| Atlanta | 3 | 33% | -16.88 |
| New York | 7 | **0%** | -8.79 |
| Ankara | 4 | **0%** | -7.07 |
| San Francisco | 7 | 29% | -7.06 |
| London | 3 | **0%** | -4.27 |

**New York: 7 Positionen, keine einzige gewonnen.**

---

## 5. KALIBRIERUNG DES MODELLS

- **Brier Skill Score: -0.4737** (Negativer Wert = schlechter als Baseline-Vorhersage!)
- Calibration bins 0.4-0.6: Modell sagt 45-53% YES-Wahrscheinlichkeit, tatsächlich 0% YES
- Modell **überschätzt systematisch YES-Wahrscheinlichkeiten** im mittleren Bereich
- **Konsequenz**: "Premium Edge" entsteht oft durch Modell-Fehler, nicht echte Mispricings

---

## 6. ZOMBIE-POSITIONEN

- 28 SELF-HEAL Zombie-Schließungen à 0.00 EUR P&L
- Positionen konnten nicht normal aufgelöst werden (Markt verschwunden, API-Probleme)
- Kein Kapitalverlust, aber operativer Overhead
- Gesamt: 60 Positionen mit P&L im Log, davon 28 Nullen

---

## 7. HYPOTHESEN-PROTOKOLL

| # | Hypothese | Betroffenes Segment | Erwarteter Effekt | Priorität |
|---|-----------|---------------------|-------------------|-----------|
| H1 | **NO/exact beim Eintritt sperren** | NO/exact, 19 Trades, 0% WR | -14.19 EUR Verluste verhindert | **HOCH** |
| H2 | YES/at_or_above sperren | 4 Trades, avg -4.34 | -17.38 EUR Verluste verhindert | HOCH |
| H3 | SIGMA_F erhöhen (5.5→7.0) | Alle Segmente | Weniger Signale, höhere Qualität | MITTEL |
| H4 | MIN_EDGE erhöhen (0.4→0.5) | Marginale Trades (Paris, Buenos Aires) | Kleiner Effekt (-2.73 EUR) | NIEDRIG |
| H5 | New York City sperren | NYC, 0% WR, 7 Trades | -8.79 EUR verhindert | MITTEL |

### Champion/Challenger Status
- **Champion**: Aktuelle Konfiguration (MIN_EDGE=0.4, SIGMA_F=5.5)
- **Challenger (nicht gestartet)**: H1 — Entry-Block für NO/exact
- **Blocker**: H1 braucht Code-Änderung, kein Config-Parameter verfügbar

---

## 8. ENTSCHEIDUNG DIESER ITERATION: HOLD

**Keine Parameteränderung in diesem Zyklus.**

Begründung:
1. **Edge Drought**: 8 Zyklen ohne Signal → keine aktiven Trades zum Testen
2. **Kleine Stichprobe**: 32 Trades, zu wenig für sichere Parameterentscheidungen
3. **H1 (NO/exact Block) braucht Code-Änderung**: Kein verfügbarer Config-Parameter
4. **Aktuelle Guardrails funktionieren**: LOW-liq Block + DEFENSIVE Policy begrenzen Schaden
5. **Hektische Änderungen sind kontraindiziert**: Optimierungsprinzip 1 — Stabilität ohne Edge

---

## 9. BUGS / TECHNISCHE PROBLEME

### Bug: analyze_city_performance wirft TypeError
```
Error: unsupported operand type(s) for +=: 'int' and 'NoneType'
```
Wahrscheinliche Ursache: `realized_pnl_eur=None` in offenen/Zombie-Positionen wird nicht als 0 behandelt.  
Fix: `pnl += p.get('realized_pnl_eur') or 0` statt `pnl += p.get('realized_pnl_eur', 0)`

---

## 10. NÄCHSTE SCHRITTE

### Sofort (Code-Änderung durch Entwickler)
1. **NO/exact Entry-Block implementieren**: Vor Positionseintritt prüfen: `if side == 'NO' and market_type == 'exact': SKIP`
2. **analyze_city_performance Bug fixen**: None-safe Addition
3. **YES/at_or_above prüfen**: Wenn LOW-liq Block nicht ausreicht, explizit sperren

### Nächster Optimizer-Zyklus (wenn aktive Trades fließen)
1. SIGMA_F=7.0 Experiment starten (Hypothese H3)
2. Mindestens 20 neue Trades sammeln
3. NO/exact WR re-evaluieren nach Entry-Block

### Rollback-Bedingung (falls Änderungen gemacht werden)
- Profit Factor unter Champion-Level (aktuell 0.2352, schlimmer ist schlechter)
- Win Rate fällt unter 25% im 30-Trade-Fenster
- Drawdown überschreitet 2.0%

---

## 11. AUSGABE-ZUSAMMENFASSUNG

| | |
|--|--|
| **Iteration** | 2026-04-19 |
| **Status** | HOLD |
| **Primäre Verlustquelle** | Stop-Losses (-41 EUR) + Emergency-SL (-25 EUR) |
| **Stärkstes negatives Segment** | NO/exact (0% WR, 19 Trades) |
| **Stärkstes positives Signal** | Take-Profit Exits (100% WR) |
| **Modell-Kalibrierung** | POOR (BSS: -0.47) |
| **Nächste Aktion** | Code-Block für NO/exact Entry |
| **Champion-Config** | Unverändert |
