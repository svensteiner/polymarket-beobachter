# Profitability Optimizer Loop — 2026-04-19 (Evening Update, ~19:10 UTC)

**Run time:** 2026-04-19T19:10 UTC  
**Bot status:** ALIVE | ELEVATED | DEFENSIVE  
**Capital:** 4,945.28 EUR (start: 5,000 EUR) | ROI: -1.09%  
**Open positions:** 2 (Buenos Aires YES/exact + Dallas YES/at_or_below)  
**Decision this cycle: HOLD — Champion-Konfiguration bleibt unverändert**

---

## 1. AKTUELLER STATUS

| Metrik | Wert | vs. letzter Loop (17:22) |
|--------|------|--------------------------|
| Total Kapital | 4,945.28 EUR | = |
| Realisiertes P&L | -54.72 EUR | = |
| ROI | -1.09% | = |
| Max Drawdown | 56.07 EUR (1.12%) | = |
| Bot Health | ELEVATED | = |
| Agent Policy | DEFENSIVE | = |
| Edge Drought | 8+ Zyklen ohne Signal | +1 Zyklus |
| Offene Positionen | 2 (Buenos Aires + Dallas) | -1 (Ankara geschlossen) |
| Geschlossene Positionen | 32 | = |

### Was sich seit dem letzten Loop ereignet hat:
- **Ankara YES/exact (PAPER-20260419-34c4dc49)** geschlossen um 14:38 UTC via Emergency-SL: -67.8%, -7.07 EUR  
  → Diese Position hatte 24h Restlaufzeit und war LOW-liq — korrekt getriggert  
  → Bereits in der aktuellen P&L-Bilanz enthalten (Performance-Report aktuell)
- **Buenos Aires YES/exact (market 1996328)**: API gibt "market not found in Gamma API after retry" zurück  
  → **ZOMBIE-RISIKO**: Position wurde am 2026-04-17 eröffnet, Auflösung war am 2026-04-18  
  → Der Bot loggt Snapshot-Fehler seit mindestens 18:58 UTC

---

## 2. KRITISCHER ALARM: Buenos Aires Zombie-Position

**Position:** PAPER-20260417-e8e76536  
**Frage:** Will the highest temperature in Buenos Aires be 26°C on April 18?  
**Seite:** YES, Einstieg 0.3657, Cost Basis 20 EUR  
**Resolution war:** 2026-04-18 (gestern!)  
**Status laut Log:** OPEN (aber Markt nicht mehr in Gamma API)

**Problem:** Der Markt 1996328 existiert nicht mehr in der Gamma API. Das bedeutet:
- Die Frage wurde bereits gestern aufgelöst
- Der Bot kann den aktuellen Preis nicht abrufen
- Die Position ist ein Zombie — sie verschwindet irgendwann via SELF-HEAL, aber der P&L ist unbekannt

**Erwartetes P&L:** Wenn Buenos Aires am 18.4. nicht exakt 26°C erreichte (sehr wahrscheinlich bei exact-Wetten), ist diese Position verloren → ca. -20 EUR nicht-realisiert

**Handlungsempfehlung für Entwickler:** `position_manager.py` — Zombie-Resolution forcieren wenn Markt seit >12h nicht abrufbar und Auflösung in der Vergangenheit liegt

---

## 3. SEGMENT-ANALYSE (vollständig, 56 betrachtete Positionen)

### 3a. Nach Side (aus trade_autopsy.json)
| Seite | Trades | WR | P&L | Status |
|-------|--------|----|-----|--------|
| YES | 10 | 40% | -12.88 EUR | Akzeptabel — im YES-only Mode behalten |
| NO | 26 | ~23% | -34.77 EUR | **BLOCKIERT** via YES-only mode ✓ |

**YES-only mode seit 2026-04-18 korrekt aktiv. Keine Änderung.**

### 3b. Nach Market Type (Closed Positions, 32 Trades)
| Typ | n | WR | P&L | Avg/Trade |
|-----|---|----|-----|-----------|
| **at_or_above** | 6 | 16.7% | **-17.38 EUR** | **-4.34 EUR** |
| exact | 12 | 25% | -18.10 EUR | -1.51 EUR |
| between | 11 | 36.4% | -19.61 EUR | -1.78 EUR |
| **at_or_below** | 3 | 33.3% | **+0.36 EUR** | **+0.12 EUR** |

**Worst Segment aktiv: YES/at_or_above — 16.7% WR, -17.38 EUR**  
Dieser Typ ist noch erlaubt unter YES-only mode und ist der verbleibende Hauptverlustkanal.

### 3c. Nach Exit-Typ (Strategy Attribution)
| Exit | n | WR | P&L | Bewertung |
|------|---|----|-----|-----------|
| Take Profit | 7 | **100%** | +11.79 EUR | ✅ FUNKTIONIERT |
| Stop Loss | 10 | 0% | -41.06 EUR | ❌ PRIMÄRE BLUTUNG |
| Guardrail Exit | 13 | 23.1% | +0.08 EUR | ≈ NEUTRAL |
| Resolution Loss | 2 | 0% | -25.54 EUR | ❌ EMERGENCY SL |

**Take-Profit-Mechanismus ist der einzige zuverlässige Winner. SL ist der Hauptverlustkanal.**  
Folgerung: Das Problem ist nicht der Exit, sondern der Entry.

### 3d. Nach Stadt (Top-Verlierer)
| Stadt | n | WR | P&L | Risk-Flag |
|-------|---|----|-----|-----------|
| **Atlanta** | 3 | 33% | **-16.88 EUR** | HIGH (Emergency-SL) |
| **New York City** | 7 | **0%** | **-8.79 EUR** | HIGH (0% WR über 7 Trades) |
| **Ankara** | 4 | 0% | -7.07 EUR | MITTEL (LOW-liq Block greift) |
| **San Francisco** | 4 | 50% | -7.06 EUR | MITTEL (WR OK, Verluste groß) |
| **London** | 3 | 0% | -4.27 EUR | MITTEL |

| Stadt | n | WR | P&L | Risk-Flag |
|-------|---|----|-----|-----------|
| **Houston** | 2 | 50% | **+1.95 EUR** | POSITIV |
| **Tokyo** | 4 | 25% | **+1.08 EUR** | POSITIV |

**New York: 7 Trades, 0% WR — klarer Kandidat für Cooldown/Block**

### 3e. Nach Preisband
| Band | n | WR | P&L | Bewertung |
|------|---|----|-----|-----------|
| 0.10-0.20 | 3 | 33% | **+0.84 EUR** | ✅ Einziges profitables Band |
| 0.00-0.10 | 4 | 0% | -4.22 EUR | ❌ |
| 0.35-0.50 | 10 | 50% | -25.60 EUR | ❌ Hohe WR, große Verluste |
| 0.50-0.70 | 33 | 12% | -23.35 EUR | ❌ Schlechteste Kombination |
| 0.70-0.85 | 4 | 0% | -2.38 EUR | ❌ |

**Das 0.35-0.50 Band hat 50% WR aber massive Verluste → Verluste pro Trade zu groß**  
**Das 0.50-0.70 Band hat das meiste Volumen und die schlechteste Performance**

### 3f. Edge Bucket Paradoxon (bestätigt)
| Bucket | n | WR | Avg P&L/Trade |
|--------|---|----|---------------|
| Premium (höchste Edge) | 43 | 21% | -0.90 EUR |
| Medium | 11 | 9% | -1.11 EUR |
| High | 6 | 0% | -0.62 EUR |

**Höhere modellierte Edge = schlechtere Performance. Brier Skill Score = -0.4737.**  
Das Modell ist systematisch falsch kalibriert. "Premium Edge" = Modell am stärksten falsch.

---

## 4. VERLUSTQUELLEN (PRIORISIERT)

1. **Stop-Loss auf YES/at_or_above und NO/between (-41.06 EUR)**  
   - 10 SL-Exits, alle zwischen -70% und -93%  
   - NO-Bets durch YES-only mode eliminiert ✓  
   - YES/at_or_above noch aktiv → nächster Block-Kandidat

2. **Emergency-SL auf LOW-Liq-Märkten (-25.54 EUR)**  
   - Atlanta (-18.46) + Ankara (-7.07): Emergency-SL bei -90% / -68%  
   - LOW-liq Block aktiv ✓ — verhindert neue Eintritte  
   - Buenos Aires (20 EUR) möglicherweise Zombie → unrealisierter Verlust

3. **YES/at_or_above Segment (-17.38 EUR, 16.7% WR, 4.34 EUR avg loss)**  
   - Einziges remaining YES-Segment mit klar negativem Edge  
   - Derzeit noch aktiv und nicht blockiert  
   - Dallas (OPEN, YES/at_or_below) — anderer Typ, akzeptabel

---

## 5. GEWINNQUELLEN

1. **Take-Profit Exits: 100% WR, +11.79 EUR** — TP-Mechanismus korrekt
2. **Houston: 50% WR, +1.95 EUR** — kleines Sample, positiv
3. **Tokyo: 25% WR, +1.08 EUR** — kleines Sample, positiv  
4. **Preisband 0.10-0.20: +0.84 EUR** — einziges profitables Band

---

## 6. HYPOTHESEN-PROTOKOLL (aktualisiert)

| # | Hypothese | Segment | Erwarteter Effekt | Status |
|---|-----------|---------|-------------------|--------|
| **H1** | YES/at_or_above Entry-Block | 4-6 Trades, 16.7% WR, -17.38 EUR | Verlust verhindern | **OFFEN** (Code-Änderung) |
| H2 | New York City Cooldown | 7 Trades, 0% WR, -8.79 EUR | -8.79 EUR verhindert | OFFEN (Config) |
| H3 | SIGMA_F 5.5→7.0 | Alle Segmente | Weniger, qualitativ bessere Signale | WARTEN (kein Edge) |
| H4 | Zombie-Force-Resolution | Buenos Aires (1996328) | Position korrekt schließen | SOFORT (Code) |
| ~~H-NO~~ | ~~NO/exact Block~~ | ~~19 Trades, 0% WR~~ | ~~Bereits gelöst durch YES-only~~ | ✅ ERLEDIGT |

### Champion/Challenger Status
- **Champion**: Aktuelle Konfiguration (MIN_EDGE=0.4, SIGMA_F=5.5, YES-only, LOW-liq Block)
- **Challenger**: H1 — YES/at_or_above Entry-Block (warte auf Code-Implementierung)
- **Blocker**: Kein Config-Parameter verfügbar, braucht Code-Änderung im simulator.py

---

## 7. AKTUELLER EDGE-DROUGHT: ANALYSE

**Warum findet der Bot keine Edge?**

Alle Observationen heute zeigen negative Edges (edge=-1, NO_SIGNAL). Die wenigen Signale mit OBSERVE-Action haben alle negativen model_probability-Wert (bot denkt YES-Wahrscheinlichkeit ist viel niedriger als Marktpreis).

Konkrete Signale heute:
- Atlanta: model=12.7%, market=23.5% → Edge -46% (zu niedrig für YES)
- New York: model=12.4%, market=31.5% → Edge -59% (zu niedrig für YES)  
- Paris: model=21.0%, market=37.5% → Edge -44% (zu niedrig für YES)

**Interpretation**: Das Modell sieht gerade überall Markt-Überbewertungen auf der YES-Seite.  
Das würde NO-Bets nahelegen — aber NO ist korrekt gesperrt.

**Konklusion**: Der Edge-Drought ist strukturell. Der Markt preist diese Wetter-Events höher ein als das Modell. Das ist entweder:
1. Markt hat Recht → Modell unterschätzt YES-Wahrscheinlichkeiten systematisch
2. Modell hat Recht → Markt übertreibt → Edge liegt auf der NO-Seite (gesperrt)

Bei Brier Skill Score -0.47 ist Option 1 wahrscheinlicher. Das Modell hat einen systematischen Bias.

**Implikation für SIGMA_F**: SIGMA_F = 5.5°F ist möglicherweise zu eng, wodurch YES-Probs zu hoch berechnet werden für moderate Temperaturanforderungen. H3 (SIGMA_F erhöhen) bleibt relevant sobald wieder Trades fließen.

---

## 8. ENTSCHEIDUNG DIESER ITERATION: HOLD

**Keine Parameteränderung.**

Begründung:
1. **Edge Drought**: 8+ Zyklen ohne Signal → kein Test möglich
2. **Kleine Stichprobe**: 32 Trades zu wenig für Parameterentscheidungen
3. **H1 braucht Code-Änderung**: Kein Config-Hebel verfügbar
4. **Aktuelle Guardrails wirken korrekt**: LOW-liq Block + YES-only + DEFENSIVE
5. **Buenos Aires Zombie**: Warte auf Selbstauflösung (0-20 EUR Risiko, bereits Open)

---

## 9. TECHNISCHE PROBLEME UND BUGS

### Bug 1: Buenos Aires Zombie-Position (KRITISCH)
- **Market 1996328** nicht mehr in Gamma API
- **Resolution war 2026-04-18** — Position läuft damit 1+ Tag über Deadline
- **Fix**: `position_manager.py` — Bei Snapshot-Fehler + Auflösung in Vergangenheit: Position als Resolution-Loss schließen
- **Erwartete Auswirkung**: -20 EUR zusätzlicher realisierter Verlust

### Bug 2: analyze_city_performance MCP-Fehler (NIEDRIG)
- Fehler: `unsupported operand type(s) for +=: 'int' and 'NoneType'`
- Diagnose: Transient oder race condition beim file read; server.py enthält kein `+=`
- `outcome_analyser.py` L311/L337: `pnl = pos["realized_pnl_eur"]` ohne None-Guard, aber `_load_closed_positions()` filtert None bereits aus
- **Fix**: Defensive `or 0.0` in `_compute_city_performance` und `_compute_monthly_performance` als Präventivmaßnahme

---

## 10. OPEN-POSITION MONITORING

| Position | Market | Typ | Entry | Cost | Restlaufzeit | Risk |
|----------|--------|-----|-------|------|-------------|------|
| Buenos Aires YES | 1996328 | exact | 0.366 | 20 EUR | **ABGELAUFEN** | ZOMBIE |
| Dallas YES/≤ | 2011134 | at_or_below | 0.283 | 20 EUR | ~24h | LOW-liq warning |

**Dallas**: Model=0.462 > Market=0.283 → bot sieht YES-Edge. LOW-liq Warning aber kein Block (at_or_below). Beobachten.

---

## 11. ROLLBACK-BEDINGUNGEN

Rollback-Trigger für Champion-Konfiguration:
- Profit Factor fällt unter 0.20 (aktuell: 0.2352)
- Win-Rate fällt unter 25% im nächsten 10-Trade-Fenster
- Drawdown überschreitet 2.0% (aktuell: 1.12%)
- Buenos Aires Zombie realisiert Verlust → P&L über -75 EUR gesamt → erwägen: Handels-Pause

---

## 12. NÄCHSTE SCHRITTE (Priorität)

### Sofort — Code-Fixes (Entwickler)
1. **Buenos Aires Zombie lösen**: `position_manager.py` — force resolution wenn market_not_found + >12h nach expected resolution
2. **YES/at_or_above Block implementieren**: `simulator.py` — Entry-Block wenn `side == 'YES' and market_type == 'at_or_above'`
3. **New York City Cooldown**: `weather.yaml` — `BLOCKED_EDGE_BUCKETS` oder City-Cooldown für NYC

### Nächster Optimizer-Zyklus (wenn 5+ neue Trades fließen)
1. YES/at_or_above Block evaluieren (H1)
2. Minimum 20 neue Trades für SIGMA_F Experiment (H3)
3. NYC Cooldown auf Wirkung prüfen (H2)

### Wann ist HOLD zu brechen?
- Wenn YES/at_or_above Edge-Signal erscheint → SKIP (bis Block implementiert)
- Wenn at_or_below YES Signal erscheint → normale Evalulation
- Wenn between YES Signal mit entry_price 0.10-0.20 erscheint → attraktiv

---

## 13. ZUSAMMENFASSUNG

| | |
|--|--|
| **Iteration** | 2026-04-19 v2 (Evening) |
| **Status** | HOLD |
| **Neu seit letztem Loop** | Ankara Emergency-SL -7.07 EUR; Buenos Aires Zombie-Alarm |
| **Primäre Verlustquellen** | Stop-Losses (-41 EUR) + Emergency-SL (-25 EUR) |
| **Stärkstes negatives Segment** | YES/at_or_above (16.7% WR, -17.38 EUR) |
| **Stärkstes positives Signal** | Take-Profit Exits (100% WR, +11.79 EUR) |
| **Edge-Drought** | 8+ Zyklen — strukturell, nicht temporal |
| **Modell-Kalibrierung** | POOR (BSS: -0.47) — systematischer Bias |
| **Nächste Aktion** | Code-Block YES/at_or_above + Zombie-Fix |
| **Champion-Config** | Unverändert |
| **Rollback-Trigger** | PF < 0.20, WR < 25%, DD > 2.0% |
