# Cross-Market-Arbitrage — Partitions-Coverage (autoritativ via negRiskMarketID)

**Generiert:** 2026-08-30T05:00:28.532234+00:00  
**Roh-Snapshots ausgewertet:** 579 · Half-Spread 0.0052 · Lead 24.0h  

> **Fortschritt gegenüber `arb_capturability.py`:** Dort wurden Buckets per Heuristik `(Stadt, Datum, Metrik)` gruppiert — eine Schätzung, die nie beweisen kann, dass man eine *vollständige* Partition sieht. Polymarket liefert die Partition aber autoritativ: alle Buckets eines Multi-Outcome-Events teilen dieselbe `negRiskMarketID` (`negRisk`-Märkte sind per Konstruktion disjunkt & vollständig, genau ein Bucket löst YES auf). Der Collector persistiert dieses Feld bereits in jedem Roh-Snapshot. **Partitions-Zugehörigkeit ist damit ex-ante bekannt — aus der Marktstruktur, ohne jede Outcome-Konditionierung.**

## Datenlage

- negRisk-Partitionen gesamt (≥3 Buckets): **335**
- davon in unserem beobachteten+aufgelösten Universum (tägliche Stadt-Temp): **7**
- **vollständig bepreist UND aufgelöst: 0**

## Der harte Blocker: Preis-Coverage

Um die Arbitrage-Summe S = Σ YES-Preise zu bilden, brauchen wir den Preis **jedes** Buckets zum selben Zeitpunkt. Unser Beobachtungs-Log erfasst aber nur die ~3-5 Buckets, die der Observer tatsächlich bewertet — von typisch 11:

| Kennzahl | Wert |
|---|---:|
| Preis-Coverage min | 9.1% |
| Preis-Coverage **median** | **9.1%** |
| Preis-Coverage mean | 10.4% |
| Preis-Coverage max | 18.2% |
| Partitionen mit Coverage ≥80% | 0 |

## Partitionen (nach Coverage sortiert)

| negRiskID | Event | Buckets | bepreist | aufgelöst | Coverage | komplett |
|---|---|---:|---:|---:|---:|:---:|
| `0x23c23f6f8d` | Lowest temperature in London on August 25? | 11 | 2 | 2 | 18.2% | — |
| `0x7f17ecbbf7` | Lowest temperature in London on August 23? | 11 | 1 | 1 | 9.1% | — |
| `0xd121dc3fb8` | Lowest temperature in Paris on August 23? | 11 | 1 | 1 | 9.1% | — |
| `0x7298a5587e` | Highest temperature in Chicago on August 23? | 11 | 1 | 1 | 9.1% | — |
| `0xa6a14fc137` | Highest temperature in Toronto on August 24? | 11 | 1 | 1 | 9.1% | — |
| `0xed544845ef` | Highest temperature in Chicago on August 24? | 11 | 1 | 1 | 9.1% | — |
| `0xc33828c31e` | Highest temperature in Denver on August 24? | 11 | 1 | 1 | 9.1% | — |

## Verdikt

**Arbitrage weiterhin NICHT testbar — aber der Grund ist jetzt präzise benannt und ein anderer als bisher angenommen.**

- Das *Partitions-Problem* (welche Buckets gehören zusammen?) ist **gelöst**: `negRiskMarketID` liefert die vollständige, exhaustive Menge ex-ante. Die alte Heuristik und ihr Look-ahead-Risiko sind damit überflüssig.
- Der *tatsächliche* Blocker ist **Preis-Coverage**: wir bepreisen im Median nur **9.1%** der Buckets einer Partition, im Maximum **18.2%**, und **keine einzige** Partition ist vollständig bepreist. Wer eine unvollständige Bucket-Menge kauft, kennt S nicht und kann in ~⅔ der Fälle den Gewinner-Bucket gar nicht gekauft haben.

**Konkreter, korrigierter nächster Schritt (ersetzt den alten Vorschlag in `arb_capturability.py`, Markt-IDs zu persistieren — das allein reicht NICHT):** Der Observer muss für *jeden* Bucket einer negRisk-Partition einen Preis-Snapshot zum gemeinsamen Lead-Zeitpunkt schreiben, nicht nur für die Buckets, die er handelbar findet. Erst wenn Preis-Coverage → 100% geht, produziert genau dieses Modul (ohne weitere Änderung) einen validen, look-ahead-freien Arb-Test. Das ist eine **Forward-Datenerfassungs-Aufgabe**, keine Analyse — und sie berührt den 15-Min-Zyklus, daher separat und bewusst zu entscheiden.

---
*READ-ONLY · PAPER ONLY · Partition autoritativ via negRiskMarketID*
