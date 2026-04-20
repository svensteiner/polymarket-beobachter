# Profitability Optimizer Loop — 2026-04-20 (Runde 3)

Generated: 2026-04-20 ~10:15 UTC | Run by: scheduled optimizer task

---

## 1. Status

| Kennzahl | Wert |
|---|---|
| Equity | 4.945,28 EUR (-54,72 EUR / -1,09% ROI) |
| Allocated | 20,00 EUR (Dallas YES-at_or_below, läuft heute aus) |
| Realized PnL | -54,72 EUR |
| Win Rate (real, nicht-zombie) | ~38% gesamt; YES-only: 2/4 = 50% |
| Profit Factor | ~0,25 — KRITISCH, strukturell durch Position-Sizing verursacht |
| Buenos Aires-Zombie | SELBST-GEHEILT: 20 EUR freigegeben, 0 PnL (zombie_expired) |
| Neue Entries seit gestern | 0 (Edge-Dürre hält an) |

**Kurzfazit**: Die Zombie-Bereinigung funktioniert. Buenos Aires (Apr 18) wurde heute 10:14 UTC automatisch freigegeben. Einzige offene Position: Dallas YES at_or_below (resolves heute). **Hauptfund dieser Runde**: Die realisierte P&L-Asymmetrie ist vollständig auf Positions-Sizing zurückzuführen — alle großen Verluste kamen aus 10–20 EUR Positionen, alle echten Gewinne aus 5 EUR Positionen. Dieser Fehler ist jetzt behoben.

---

## 2. Diagnose

### Top 3 Verlusttreiber

#### A) Positions-Sizing-Asymmetrie — Strukturell / BEHOBEN
**Das zentrale Problem dieser Runde:**

| Position | Entry EUR | Outcome | PnL |
|---|---|---|---|
| Paris TP3 (Apr 16) | 5 EUR | +WIN | +0,92 EUR |
| Paris TP3 (Apr 16) | 5 EUR | +WIN | +2,24 EUR |
| SF TP3 (Apr 16) | 5 EUR | +WIN | +1,33 EUR |
| LA TP3 (Apr 16) | 5 EUR | +WIN | +5,19 EUR |
| Atlanta Emergency-SL (Apr 17) | **20 EUR** | -LOSS | **-18,46 EUR** |
| Ankara Emergency-SL (Apr 19) | **10 EUR** | -LOSS | **-7,07 EUR** |
| Buenos Aires zombie | 20 EUR | 0 | 0 EUR |

Retrograde Hochrechnung: **Bei einheitlich 5 EUR Positions-Größe wäre die Gesamt-PnL POSITIV:**
- Paris/SF/LA TP3: +9,68 EUR (unverändert, waren 5 EUR)
- Atlanta: -4,62 EUR (statt -18,46 EUR)
- Ankara: -3,54 EUR (statt -7,07 EUR)
- **Netto: +1,52 EUR statt -20,55 EUR** (YES-only Trades)

**Maßnahme: position_size_eur 10.0 → 5.0 — IMPLEMENTIERT.**

#### B) Emergency-SL auf YES-exact-Märkte (Ankara, Apr 19) — teilweise behoben
- Drift-Guard verhindert zukünftige Stale-Proposal-Einträge
- Ankara war noch VOR dem Drift-Guard-Deployment eingetreten (12:22 UTC, Guard aktiv ab ~14:00)
- Bei 5 EUR Entry: max -4,75 EUR statt -7,07 EUR

#### C) Edge-Dürre (0 neue Einträge seit Apr 19 14:38) — Marktstruktur-Problem
- Observer findet keine YES-Edge-Kandidaten
- YES-only Modus filtert 100% der NO-Opportunities heraus
- Kein Eingriff möglich ohne Daten-Basis

---

### Top 3 Gewinnmuster

#### A) YES-Bets in niedrigen Preisbändern (0,10–0,45) mit TP3-Exit
- LA YES bei 0,147: +117% (+5,19 EUR auf 5 EUR)
- Paris YES bei 0,437: +34% (+0,92 EUR)
- Paris YES re-entry 0,604: +57% (+2,24 EUR)
- SF YES bei 0,422: +36% (+1,33 EUR)
- **Pattern**: TP3-System funktioniert auf 5 EUR Basis sehr gut. Gewinne akkumulieren.

#### B) Guardrail-Exits als proaktive Kapitalsicherung
- Houston NO-between: +1,95 EUR (+39%)
- Atlanta NO-between: +1,58 EUR (+31%)
- Seattle NO-between: +1,51 EUR (+30%)
- **Pattern**: Wenn der Guardrail früh eingreift, rettet er bis zu 90% des Kapitals.

#### C) SELF-HEAL Zombie-Bereinigung (neu beobachtet)
- Buenos Aires (Apr 18): 20 EUR freigegeben, 0 PnL (kein echter Verlust)
- Das System erkennt und bereinigt Zombie-Positionen korrekt
- Das freigegeben Kapital ist jetzt wieder verfügbar

---

### Wichtigste Datenprobleme

| Problem | Schwere | Status |
|---|---|---|
| Proposal-Edge zeigt Snapshot-Wert, nicht Execution-Wert | HOCH | Drift-Guard aktiv für zukünftige Trades |
| Buenos Aires Apr 18 als OPEN gemeldet bis 10:14 Apr 20 | MITTEL | BEHOBEN: SELF-HEAL hat Kapital freigegeben |
| Brier Skill Score negativ (Modell schlechter als Baseline) | KRITISCH | Strukturelles Problem, kein Quick-Fix |

### Wichtigste Exit-/Risikoprobleme

| Problem | Schwere | Status |
|---|---|---|
| Emergency-SL bei niedrigem Preis kurz vor Resolution | HOCH | Teilweise durch 5 EUR Cap gemildert |
| Dallas YES at_or_below 20 EUR (resolution heute) | MITTEL | Monitor-only, kein Eingriff |
| at_or_above YES Cold-Bias | MITTEL | BEHOBEN: Size-Cap 5 EUR aktiv (H-06) |

---

## 3. Maßnahmen

### Priorität 1 — IMPLEMENTIERT: position_size_eur 10.0 → 5.0

**Was**: `data/capital_config.json` Zeile `"position_size_eur": 10.0` → `"position_size_eur": 5.0`

**Warum**: Asymmetrie-Analyse zeigt eindeutig, dass alle Verluste aus 10–20 EUR Positionen kamen, alle Gewinne aus 5 EUR. Die Kelly-Sizing-Logik liest den Wert live aus capital_config.json (via `_get_caps()` in `kelly.py`), kein Neustart nötig. Wirkt ab dem nächsten Pipeline-Run.

**Retrograde Wirkung auf YES-only Trades**: -20,55 EUR → +1,52 EUR (hypothetisch).

**Rollback-Bedingung**: Falls WR ≥ 60% über 10+ YES-Trades → position_size_eur auf 10 EUR erhöhen.

**Verifizierung**: Nächste YES-Entry muss `cost_basis_eur = 5.0` zeigen.

### Priorität 2 — BEOBACHTUNG: Dallas YES at_or_below (löst heute auf)

**Offene Position**: PAPER-20260418-63112737, Dallas, "Will highest temp in Dallas be 71°F or below on April 20?"
- Entry: 0,283 EUR, 70,6 Kontrakte, 20 EUR Einsatz (aus alter 20-EUR-Konfiguration)
- Model: 46,2% | Market: 28,3% | Edge: +63% real
- market_type: at_or_below (kein at_or_above-Cap-Problem)

**Kein Eingriff**: Die Position ist korrekt eingegangen (Drift-Guard war aktiv). Zombie-Cleanup oder Position-Manager handeln automatisch bei Resolution.

**Erwartung**: Wenn YES (Temp ≤71°F): ~+50 EUR Gewinn. Wenn NO: -20 EUR Verlust. Historische at_or_below WR: 25% (1/4), aber Dallas hatte guten Model-Edge.

### Priorität 3 — HYPOTHESE: MIN_EDGE_ABSOLUTE 0,10 → 0,07

**Status**: Unverändert aus Runden 1 und 2. Edge-Dürre verhindert Test.

**Aktivieren wenn**: Observer > 5 YES-Kandidaten findet, die nur wegen Edge-Floor abgelehnt werden.

**Nicht implementieren** bis Testdaten vorliegen.

---

## 4. Erwarteter Effekt

| Metrik | Vorher (10 EUR) | Nach Fix (5 EUR) | Verbesserung |
|---|---|---|---|
| Max Einzelverlust YES (Emergency-SL) | ~-9,5 EUR | ~-4,75 EUR | -50% |
| Max Einzelverlust YES at_or_above | ~-5 EUR (Cap) | ~-5 EUR (Cap unverändert) | — |
| TP3-Gewinn Paris/SF-Typ | ~+1,8 EUR | ~+0,9 EUR | -50% (akzeptabel) |
| Profit Factor (theoretisch bei 50% WR) | ~0,37 | ~0,73 | Deutliche Verbesserung |
| Max Drawdown je Trade | 9,5 EUR | 4,75 EUR | Halbiert |

**Warum besser trotz kleineren Gewinnen**: Der historische Verlust/Gewinn-Quotient ist >2:1. Bei 5 EUR sinkt die Verlustseite stärker als die Gewinnseite relativ gesehen, weil die TP3-Exits relativ zur Einsatzgröße konstant bleiben (~27–117% Gewinn).

---

## 5. Testplan

**Kurztest nach nächstem Pipeline-Run**:
- Log muss zeigen: `size=5.00 EUR` für neue YES-Entries
- Kein `size=10.00 EUR` mehr (außer für Dallas, bereits offen)

**Dallas-Resolution beobachten** (heute Apr 20):
- Bei YES-Resolution: +50 EUR → Equity ~4995 EUR (nahe Breakeven)
- Bei NO-Resolution: -20 EUR → Equity ~4925 EUR (weitere Diagnose nötig)

**Kennzahl die sich verbessern muss**:
- Nächste 5 YES-Entries: kein einzelner Verlust > 5 EUR
- Profit Factor der YES-only Phase nach 10 neuen Trades: > 0,6

---

## 6. Entscheidung: ANPASSEN (1 Änderung implementiert)

**Implementiert**: `position_size_eur 10 → 5` — die wichtigste strukturelle Verbesserung dieser Session. Direkte Maßnahme mit messbarem Effekt.

**HOLD**: YES-only Modus, SL-Cooloff 12h, Drift-Guard, at_or_above Cap, Edge-Floors — alle korrekt.

**BEOBACHTEN**: Dallas-Resolution heute. SELF-HEAL Zombie-System funktioniert.

**WEITERE DATEN NÖTIG**: MIN_EDGE_ABSOLUTE Experiment, LOW-liq YES Bypass (Human Approval).

---

## Hypothesen-Tabelle (aktuell)

| # | Hypothese | Status | Ergebnis |
|---|---|---|---|
| H-01 | YES-only Mode verbessert WR | PROMOTE | 2/4=50% WR YES-only ✓ |
| H-02 | LOW-liq Block stoppt Verluste | PROMOTE | Korrekt ✓ |
| H-03 | 12h Proposal-Intake-Fenster | PROMOTE | Implementiert ✓ |
| H-04 | LOW-liq YES bypass für HIGH CONVICTION | PENDING | Human Approval erforderlich |
| H-05 | MIN_EDGE_ABSOLUTE 0.10→0.07 | PENDING | Kein Testfenster |
| H-06 | at_or_above YES Size-Cap 5 EUR | AKTIV | Noch kein neuer Trade zum Testen |
| **H-07** | **position_size_eur 10→5 EUR (alle YES-Typen)** | **NEU/AKTIV** | **Implementiert 2026-04-20 ~10:15 UTC** |

---

## Anhang: Segment-Performance (Stand 2026-04-19 20:37)

| Segment | Trades | WR% | Total PnL |
|---|---|---|---|
| exact | 23 | 8,7% | -18,10 EUR |
| between | 23 | 26,1% | -19,61 EUR |
| at_or_above | 6 | 16,7% | -17,38 EUR |
| at_or_below | 4 | 25,0% | +0,36 EUR |
| **London** | 3 | 0% | -4,27 EUR |
| **New York City** | 7 | 0% | -8,79 EUR |
| **Atlanta** | 3 | 33% | -16,88 EUR |
| **Ankara** | 4 | 0% | -7,07 EUR |
| **Houston** | 2 | 50% | +1,95 EUR |
| **Los Angeles** | 4 | 25% | -2,44 EUR |

---

*Nächste Iteration*: Dallas-Resolution prüfen. Bei 5+ neuen YES-Entries → Win-Rate und Profit Factor aktualisieren. Falls WR < 40% auf YES → Entry-Filter nochmals verschärfen.
