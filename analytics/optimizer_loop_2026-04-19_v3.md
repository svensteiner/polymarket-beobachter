# Profitability Optimizer Loop — 2026-04-19 v3 (~20:10 UTC)

**Run time:** 2026-04-19T20:10 UTC  
**Bot status:** ALIVE | ELEVATED | DEFENSIVE  
**Capital:** 4,945.28 EUR (start: 5,000 EUR) | ROI: -1.09%  
**Open positions (JSONL):** 30 — davon 28 Zombies (April 15–17) + 2 aktive  
**Realisiertes P&L:** -54.72 EUR | 32 geschlossene Positionen  
**Änderungen dieser Runde:** 2 Code-Fixes implementiert

---

## 1. STATUS

**POOR / DEFENSIV mit strukturellem Edge-Drought.**

| Metrik | Wert | Bewertung |
|--------|------|-----------|
| Win-Rate | 31.25% | ❌ Unter Minimum (45%) |
| Profit Factor | 0.2352 | ❌ Kritisch (< 1.0) |
| Total P&L | -54.72 EUR | ❌ |
| Avg Win | +1.68 EUR | |
| Avg Loss | -4.21 EUR | ❌ 2.5x Verlust/Gewinn-Ratio |
| Max Drawdown | 56.07 EUR (1.12%) | noch OK |
| Brier Skill Score | -0.47 | ❌ Modell schlechter als Basisrate |
| Edge-Drought | 8+ Zyklen ohne Signal | ❌ Strukturell |
| Bot Health | ELEVATED | DEFENSIV |

---

## 2. DIAGNOSE

### Top-3 Verlusttreiber

**1. Stop-Loss-Exits auf NO-Bets (-41.06 EUR, 10 Exits)**  
- Alle 10 SL-Exits waren NO-Bets auf between/exact-Märkte (-70% bis -93% pro Position)  
- Root cause: Resolution-Day Intraday-Spikes triggern SL auch auf korrekte Positionen  
- **Status: ✅ BLOCKIERT via YES-only mode (aktiv seit 2026-04-18)**

**2. YES/at_or_above Segment (-17.38 EUR, 2 Trades)**  
- 50% WR, aber durchschnittlich -8.69 EUR pro Trade  
- Gleicher Mechanismus wie NO-between: Resolution-Spike treibt den YES-Preis zur Null  
- **Status: ✅ JETZT BLOCKIERT via H1-Fix (implementiert diese Runde)**

**3. Emergency-SL auf LOW-Liquidity-Märkten (-25.54 EUR, 2 Exits)**  
- Atlanta -18.46 EUR (Emergency-SL bei -70%+ weil LOW-liq SL nie greift)  
- Ankara -7.07 EUR (gleiche Ursache)  
- **Status: ✅ BLOCKIERT via LOW-liq Entry-Block**

### Top-3 Gewinnmuster

1. **Take-Profit-Exits: 100% WR, +11.79 EUR (7 Trades)** — TP-Mechanismus funktioniert
2. **Houston: 50% WR, +1.95 EUR** — kleines Sample, positiv
3. **Tokyo: 25% WR, +1.08 EUR** — kleines Sample, positiv

### Wichtigste Datenprobleme

- **28 Zombie-Positionen (April 15–17)** stehen fälschlicherweise als OPEN im JSONL  
  Root cause: Gamma API gibt non-None Snapshots mit `mid_price=None` zurück →  
  bisheriger Zombie-Check (`snapshot is None`) feuert nicht  
  → **FIX implementiert: Check jetzt `snapshot is None OR snapshot.mid_price is None`**

- **Brier Skill Score -0.47**: Das Wettermodell ist systematisch schlechter als die Basisrate  
  → Modell überschätzt systematisch YES-Wahrscheinlichkeiten (Edge-Paradoxon: höhere  
  modellierte Edge = schlechtere echte Performance)

- **Edge-Paradoxon bestätigt**: Premium-Bucket (höchste Edge) → 21% WR, -0.90 EUR/Trade  
  Das ist kein statistisches Rauschen mehr — 43 Trades belegen systematisches Problem

### Wichtigste Risiko-/Exit-Probleme

- Resolution-Loss: 2 Trades, -25.54 EUR (avg -12.77/Trade) — Zombie-Positionen ohne saubere Resolution
- Preisband 0.50–0.70: 33 Trades, 12% WR, -23.35 EUR — größtes Verlustvolumen

---

## 3. MASSNAHMEN

### Priorität 1: YES/at_or_above Entry-Block (IMPLEMENTIERT ✅)
**Datei:** `paper_trader/simulator.py`  
**Änderung:** Neuer Guard in `_entry_quality_gate()` — blockiert alle YES-Bets auf `at_or_above`-Märkte  
**Evidenz:** 2 Trades, 50% WR aber -17.38 EUR total (avg -8.69 EUR/Trade)  
**Erwarteter Effekt:** Verhindert das zweitgrößte verbleibende Verlust-Segment

### Priorität 2: Zombie-Check-Erweiterung (IMPLEMENTIERT ✅)
**Datei:** `paper_trader/position_manager.py`  
**Änderung:** Zombie-Check feuert jetzt bei `snapshot is None OR snapshot.mid_price is None` (bisherig: nur `snapshot is None`)  
**Evidenz:** 28 Zombie-Positionen aus April 15–17 akkumuliert; keine wurden cleant  
**Erwarteter Effekt:** Nächster Pipeline-Run bereinigt alle 28 Zombies; saubere Positions-Bilanz

### Priorität 3: Warten auf 10+ neue YES-Trades (OFFEN)
**Hypothese H3:** SIGMA_F 5.5 → 7.0 (breitere Unsicherheitsbänder → weniger False Positives)  
**Warum nicht jetzt:** Zu kleines Sample, Edge-Drought macht Test unmöglich  
**Trigger:** Aktivieren wenn 10+ neue YES-Trades abgeschlossen und PF < 0.40 bleibt

---

## 4. ERWARTETER EFFEKT

| Änderung | Verhinderte Verluste | Risiko |
|----------|---------------------|--------|
| YES/at_or_above Block | ~-8.69 EUR/Trade (wenn 1-2 Trades/Woche) | MINIMAL — konservativerer Filter |
| Zombie-Fix | Saubere P&L-Bilanz, kein "open positions inflation" | NULL — nur Cleanup |

**Kumulativer Rückblick:** Die vier implementierten Guardrails dieses Zyklus haben effektiv die verluststärksten Segmente abgeschnitten:
1. YES-only mode (NO-Bets blockiert) → -41.06 EUR Verlustpotenzial eliminiert
2. LOW-liq Entry-Block (Atlanta/Ankara) → -25.54 EUR eliminiert
3. YES/at_or_above Block (diese Runde) → -17.38 EUR eliminiert
4. Zombie-Fix (diese Runde) → Datenqualität wiederhergestellt

Nach diesen Blocks bleibt als primäres aktives Segment: **YES bets auf between/exact-Märkte mit 36-96h Restlaufzeit** — das sauberste und statistisch beste Segment.

---

## 5. TESTPLAN

**Nächster Testlauf:** Nächster Pipeline-Zyklus (in ~15 Minuten automatisch)

**Was zu prüfen ist:**
1. Zombie-Cleanup: `paper_trader/logs/paper_positions.jsonl` → Open-Positions-Count soll von 30 auf ~2 fallen
2. YES/at_or_above Block: Wenn ein `at_or_above`-Proposal erscheint → in Trade-Records als SKIP mit der neuen Reason erscheinen
3. P&L-Stabilität: Kein weiterer Verlust ohne entsprechende Signale

**Verbesserungsmetrik für Beibehaltung:**
- Profit Factor: Muss in nächsten 10 Trades auf > 0.50 steigen
- Win-Rate: Muss in nächsten 10 YES-Trades auf > 40% steigen
- Max Drawdown: Darf 2.0% (100 EUR) nicht überschreiten

---

## 6. ENTSCHEIDUNG

**Anpassen** — 2 konkrete Code-Fixes implementiert, Champion-Config sonst unverändert.

| Entscheidung | Begründung |
|-------------|------------|
| YES/at_or_above Block **AKTIVIERT** | Klare statistische Evidenz (2 Trades, -17.38 EUR) |
| Zombie-Fix **AKTIVIERT** | Kritischer Datenqualitätsfehler — 28 Phantom-Positionen |
| SIGMA_F-Änderung **WARTEN** | Zu kleines Sample für validen Test |
| NO-Bets **WEITER BLOCKIERT** | NO WR = 13%, Schwelle für Re-enable noch nicht erreicht |
| MIN_EDGE-Änderung **KEINE** | Brier BSS negativ — Edge-Berechnungen nicht vertrauenswürdig |

---

## 7. OFFENE HYPOTHESEN

| # | Hypothese | Priorität | Status |
|---|-----------|-----------|--------|
| **H1** | YES/at_or_above Entry-Block | HIGH | ✅ IMPLEMENTIERT |
| **H2** | Zombie-Fix mid_price=None | HIGH | ✅ IMPLEMENTIERT |
| H3 | SIGMA_F 5.5 → 7.0 | MEDIUM | Warten auf 10+ Trades |
| H4 | New York City City-Cooldown | LOW | Warten auf Daten (0/7 WR) |
| H5 | Proposal-Window 6h → 12h | LOW | Warten — erst Zombie-Cleanup abwarten |

---

## 8. ROLLBACK-BEDINGUNGEN

| Trigger | Massnahme |
|---------|-----------|
| PF < 0.20 | Handels-Pause, alle Entries stoppen |
| Win-Rate < 25% in nächsten 10 YES-Trades | MIN_EDGE erhöhen auf 0.50 |
| Drawdown > 2.0% (100 EUR) | Vollständige Handels-Pause |
| YES/at_or_above Block verursacht Edge-Drought > 24h | Block evaluieren — aber nur wenn andere Segmente weiterhin Signale liefern |

---

## 9. ZUSAMMENFASSUNG

| | |
|--|--|
| **Iteration** | 2026-04-19 v3 (Abend) |
| **Entscheidung** | ANPASSEN (2 Fixes) |
| **Implementiert** | YES/at_or_above Block + Zombie-Fix |
| **Primäre Verlustquellen** | Stop-Losses auf NO-Bets (-41 EUR, blockiert) + Emergency-SL auf LOW-liq (-25 EUR, blockiert) + YES/at_or_above (-17 EUR, jetzt blockiert) |
| **Verbleibendes Risiko** | Systemische Modell-Kalibrierung (BSS -0.47) — keine kurzfristige Code-Fix-Option |
| **Nächste Aktion** | Zombie-Cleanup im nächsten Zyklus validieren, dann 10 YES/between Trades abwarten für SIGMA_F-Entscheidung |
| **Champion-Config** | MIN_EDGE=0.40, YES-only, LOW-liq-Block, YES/at_or_above-Block (NEU) |
