# Profitability Optimizer Loop — 2026-04-19 (auto)

Generated: 2026-04-19 ~11:15 UTC | Run by: scheduled optimizer task

---

## 1. Aktueller Status

| Kennzahl | Wert |
|---|---|
| Bot-Status | HEALTHY (0 Fehler, 6 Runs heute) |
| Equity | 4.952,35 EUR (-47,65 EUR / -0,95% ROI) |
| Allociertes Kapital | 40 EUR (~10 offene Positionen × 4 EUR) |
| Neue Entries heute | **0** |
| YES-only Modus | Aktiv seit 2026-04-18 |
| Observer-Ergebnis (letzte Pipeline) | 0 edge-Kandidaten aus 500 Märkten |

Bot läuft korrekt. Keine kritischen Fehler. Alle Safety-Filter greifen wie vorgesehen.

---

## 2. Wichtigste Verlustquellen

### A) NO-Bets (historisch, nun blockiert) — -34,77 EUR
- 6/21 Wins (29% WR)
- **Alle 10 Stop-Loss-Exits waren NO-Bets**
- YES-only Modus korrekt aktiv, dieser Verlustpfad ist eliminiert

### B) "at_or_above"-Markttyp — -17,38 EUR
- 1/6 Wins (17% WR)
- Hier lag der große YES-Einzelverlust (~-18 EUR)
- Dieses Market-Type-Muster muss beobachtet bleiben

### C) Preisband 0.50–0.70 (Entry-Preis) — -23,35 EUR
- 4/33 Wins (12% WR) — katastrophal
- Bot bettet häufig wenn Markt schon bei 50–70% ist → keine echte Edge mehr
- Problem: der Großteil der historischen NO-Bets fiel in dieses Band

### D) LOW-liq NO-Bets Atlanta — -18,46 EUR (kumuliert)
- 0% WR auf allen LOW-liq-Entries
- LOW-liq-Block korrekt aktiv

---

## 3. Wichtigste Gewinnquellen

### A) YES-Bets nach YES-only Modus (ab 2026-04-18) — +5,57 EUR
- **4/4 Wins = 100% WR** (sehr kleiner Sample)
- Alle über TP3 (+27% bis +117%) oder Trailing-Stop ausgestiegen
- Beste Subgruppe im System

### B) Preisband 0.10–0.20 (Entry-Preis) — +0,84 EUR
- 1/3 Wins (33% WR) mit kleinem Sample
- **Das profitabelste Preisband absolut**
- Hier findet das Modell echte YES-Edge: Markt preist 10–20%, Modell sieht 30–40%

### C) Tokyo und Houston — je +1,08 und +1,95 EUR
- Zwei der wenigen Städte mit positivem PnL
- Beide haben niedrige Stop-Loss-Ratios — Modell trifft besser

---

## 4. Kritische Beobachtung: Verpasste Opportunity heute

### NYC YES 56–57°F — PROP-20260419-6cb26f8b

```
Markt:       NYC highest temp 56-57°F on April 19
Richtung:    YES (Markt unterpreist YES)
Edge:        +109,5% (HIGH CONVICTION, vom System so geloggt)
Konfidenz:   HIGH (4-Quellen-Ensemble, variance=0.0079)
Marktpreis:  17% implied probability
Modell:      35,6% probability → Bet YES
Blockiert:   LOW-liq filter ("entry blocked to prevent unmanageable position")
```

**Dieses Signal ist eine echte Chance.** Warum:
1. Preisband 0.10–0.20 → das historisch profitabelste Band
2. "between"-Markttyp → besser als "exact" oder "at_or_above"
3. YES-Richtung → korrekte Mode
4. 4 unabhängige Forecast-Quellen → hohe Datenqualität

**Die LOW-liq-Sperre wurde kalibriert auf**: Atlanta at_or_above NO-Bets (0% WR, -18,46 EUR)
**Sie blockiert aber jetzt auch**: NYC between YES-Bets mit 109,5% Edge

Das sind strukturell verschiedene Trades. Die Pauschalisierung ist zu konservativ.

### Ankara YES 11°C — edge +87,8%
- Ebenfalls YES, market_price=19,5%, edge=+87,8%
- Blockiert durch "Max 10 positions reached" in früherer Pipeline-Phase

---

## 5. Root-Cause-Analyse: Warum 0 neue Trades?

```
Market Scan:  500 Märkte → 391 Weather-Kandidaten
Pre-Filter:   374 ausgesiebt (resolution < 60h)
Observer:     57 verbleibend → 0 bestanden
              Filter-Breakdown: TYPE:48, ODDS:38, CITY:8, LIQUIDITY:4, RESOLUTION:1

Paper-Trader: 18 Proposals aus letzten 12h evaluiert
              → 8 eligible → 7× LOW-liq SKIP + 1× YES-only SKIP = 0 Entries
```

**Strukturelles Problem**: Das Modell hat einen **systematischen Cold Bias**.
- Modell prognostiziert Temperaturen konsistent zu niedrig (vs. tatsächliche Maxima)
- Dadurch: Modell sieht immer NO-Edge (Markt überschätzt YES → Modell sagt bette NO)
- Aber NO-Bets verlieren weil die Temperaturen tatsächlich die Schwellwerte erreichen
- Brier Skill Score = -0,28 → das Modell ist für NO-Bets schlechter als naives Baseline

**Resultat**: Die aktuelle Marktkonstellation bietet nur NO-Signale. YES-only Mode blockiert diese korrekt. Die wenigen YES-Signale (NYC, Ankara) liegen in LOW-liq-Märkten.

---

## 6. Empfohlene Maßnahmen (prioritisiert)

### Maßnahme 1 (SOFORT, kein Risiko): Post-Resolution-Check NYC

**Hypothese**: Die NYC YES 56–57°F Bet würde gewonnen haben.

**Action**: Wenn der NYC Markt heute (Auflösung ~23:59 UTC Apr 19) resolviert, prüfen:
- War der tatsächliche NYC Höchstwert am 19. April zwischen 56–57°F?
- Ensemble-Prognose war 50,2°F → Modell hätte einen Fehler gehabt (Forecast zu niedrig)
- **Wenn NYC tatsächlich 56–57°F hatte**: Validierung der YES-Edge-Kalibrierung
- **Wenn NYC nicht 56–57°F hatte**: Bestätigung des Cold Bias (Forecast 50°F zu niedrig vs. Markt 17%, Modell 35,6% → beide falsch)

### Maßnahme 2 (MITTELFRISTIG, Human Approval erforderlich): LOW-liq Bypass für HIGH CONVICTION YES

**Hypothese**: YES-Bets mit HIGH CONVICTION (edge > 80%) in "between"-Märkten bei 0.15–0.22 Entry-Preis haben ein anderes Risikoprofil als die LOW-liq NO-Bets die den Block ausgelöst haben.

**Vorgeschlagene Änderung** (Codeanpassung, nicht weather.yaml):
```python
# In paper_trader/simulator.py
# Bypass LOW-liq block wenn alle Bedingungen erfüllt:
if (
    is_yes_bet
    and edge_pct >= 0.80
    and market_type == "between"
    and 0.13 <= entry_price <= 0.25
):
    position_size = min(position_size, 2.0)  # Halbierte Größe
    allow_entry = True  # LOW-liq-Block übersteuern
```

**Erwarteter Effekt**: +1–2 zusätzliche YES-Bets/Tag in aktueller Marktlage
**Rollback-Bedingung**: WR dieser Subgruppe < 30% nach 5 Trades → Block wieder aktivieren
**Risiko**: Keine SL/TP-Durchsetzung bei LOW-liq → Zombie-Position möglich
**Minderung**: Halbierte Positionsgröße (2 EUR) + Position landet in Manual-Review-Queue

**Erfordert**: Menschliche Freigabe + Code-Änderung im paper_trader

### Maßnahme 3 (EXPERIMENT, sicher ausführbar): MIN_EDGE_ABSOLUTE 0.10 → 0.07

**Hypothese** (aus trade_autopsy.json, Priorität 1): Edge-Filter zu streng für at_or_above/below-Märkte. Könnte 20–30% mehr YES-Proposals/Tag generieren.

**Status**: Aktuell NICHT der Bottleneck (Bottleneck ist LOW-liq-Block, nicht Edge-Discovery).
**Empfehlung**: Im nächsten Loop ausführen wenn Observer-Kandidaten verfügbar sind (>0 markets passing filter). Heute wäre dieser Experiment-Run nutzlos.

---

## 7. Hypothesenprotokoll (Champion/Challenger)

| # | Hypothese | Status | Ergebnis |
|---|---|---|---|
| H-01 | YES-only Mode verbessert WR | **PROMOTE** | 4/4=100% WR, +5.57 EUR ✓ |
| H-02 | LOW-liq Block stoppt Atlanta-Verluste | **PROMOTE** | 0 neue LOW-liq Verluste ✓ |
| H-03 | 12h Proposal-Intake-Fenster (von 6h) | **PROMOTE** | Korrekt implementiert, 18 Proposals evaluiert ✓ |
| H-04 | LOW-liq YES bypass für HIGH CONVICTION | **NEU** | Noch nicht getestet. Erfordert Human Approval. |
| H-05 | MIN_EDGE_ABSOLUTE 0.10→0.07 | **PENDING** | Kein geeignetes Testfenster heute. |

---

## 8. Rollback-Regeln (aktive Konfiguration)

| Filter | Rollback-Bedingung |
|---|---|
| YES-only Mode | NO WR ≥ 40% über 10+ neue NO-Trades → wieder aktivieren |
| LOW-liq Block | Kein Rollback nötig — funktioniert korrekt |
| Aktuelle Konfiguration (MIN_EDGE=0.4) | Beibehalten — keine Verschlechterung |

---

## 9. Entscheidung: HOLD

**Die Konfiguration bleibt unverändert.**

Begründung:
- Bot arbeitet korrekt mit allen Safety-Filtern
- Kapital ist zu 99% erhalten (-0,95% Verlust)
- Keine Änderung möglich die den aktuellen Bottleneck (LOW-liq-Block) adressiert ohne Code-Änderung
- Kein Parameter-Experiment würde heute etwas bringen (0 Observer-Kandidaten)
- Die einzige wertvolle Änderung (LOW-liq YES bypass) erfordert Human Approval

**Das Schweigen des Bots ist heute die richtige Entscheidung.** Kapitalschutz > Aktivität.

---

## 10. Nächste Iteration

| Zeitpunkt | Aktion |
|---|---|
| ~23:59 UTC heute | NYC Market Auflösung prüfen → war 56–57°F das tatsächliche Maximum? |
| Nächster Loop | Observer-Kandidaten prüfen — gibt es neue 60–96h YES-Opportunities? |
| Nächster Loop | MIN_EDGE_ABSOLUTE 0.07 Experiment laufen lassen wenn Observer > 0 Kandidaten hat |
| Human Review erforderlich | LOW-liq YES bypass: Code-PR erstellen, Human Approval holen |

---

## Anhang: Segment-Performance (alle abgeschlossenen Trades)

### Nach Stadt (Top/Bottom)

| Stadt | Trades | WR% | Netto-PnL |
|---|---|---|---|
| Houston | 2 | 50% | +1,95 EUR ✓ |
| Tokyo | 4 | 25% | +1,08 EUR ✓ |
| Paris | 7 | 29% | -1,86 EUR |
| Toronto | 7 | 14% | -3,27 EUR |
| Seattle | 3 | 33% | -3,26 EUR |
| London | 3 | 0% | -4,27 EUR |
| San Francisco | 4 | 50% | -7,06 EUR |
| New York City | 7 | 0% | -8,79 EUR ✗ |
| Atlanta | 3 | 33% | -16,88 EUR ✗ |

### Nach Markttyp

| Typ | Trades | WR% | Netto-PnL |
|---|---|---|---|
| at_or_below | 4 | 25% | +0,36 EUR |
| between | 23 | 26% | -19,61 EUR |
| exact | 22 | 9% | -11,02 EUR |
| at_or_above | 6 | 17% | -17,38 EUR ✗ |

### Nach Entry-Preisband

| Band | Trades | WR% | Netto-PnL |
|---|---|---|---|
| 0.10–0.20 | 3 | 33% | +0,84 EUR ✓ |
| 0.35–0.50 | 9 | 56% | -18,53 EUR |
| 0.50–0.70 | 33 | 12% | -23,35 EUR ✗ |
| 0.70–0.85 | 4 | 0% | -2,38 EUR |

**Fazit**: Das System muss im 0.10–0.22 Entry-Preisband bleiben (beste historische Performance). NYC und Ankara sind genau dort. Der LOW-liq Block verhindert den Zugang zu diesen Trades.
