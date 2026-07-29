# Cross-Market-Arbitrage — Partitions-Coverage (autoritativ via negRiskMarketID)

**Generiert:** 2026-07-29T11:00:31.609568+00:00  
**Roh-Snapshots ausgewertet:** 564 · Half-Spread 0.0051 · Lead 24.0h  

> **Fortschritt gegenüber `arb_capturability.py`:** Dort wurden Buckets per Heuristik `(Stadt, Datum, Metrik)` gruppiert — eine Schätzung, die nie beweisen kann, dass man eine *vollständige* Partition sieht. Polymarket liefert die Partition aber autoritativ: alle Buckets eines Multi-Outcome-Events teilen dieselbe `negRiskMarketID` (`negRisk`-Märkte sind per Konstruktion disjunkt & vollständig, genau ein Bucket löst YES auf). Der Collector persistiert dieses Feld bereits in jedem Roh-Snapshot. **Partitions-Zugehörigkeit ist damit ex-ante bekannt — aus der Marktstruktur, ohne jede Outcome-Konditionierung.**

## Datenlage

- negRisk-Partitionen gesamt (≥3 Buckets): **388**
- davon in unserem beobachteten+aufgelösten Universum (tägliche Stadt-Temp): **78**
- **vollständig bepreist UND aufgelöst: 0**

## Der harte Blocker: Preis-Coverage

Um die Arbitrage-Summe S = Σ YES-Preise zu bilden, brauchen wir den Preis **jedes** Buckets zum selben Zeitpunkt. Unser Beobachtungs-Log erfasst aber nur die ~3-5 Buckets, die der Observer tatsächlich bewertet — von typisch 11:

| Kennzahl | Wert |
|---|---:|
| Preis-Coverage min | 9.1% |
| Preis-Coverage **median** | **18.2%** |
| Preis-Coverage mean | 20.3% |
| Preis-Coverage max | 45.5% |
| Partitionen mit Coverage ≥80% | 0 |

## Partitionen (nach Coverage sortiert)

| negRiskID | Event | Buckets | bepreist | aufgelöst | Coverage | komplett |
|---|---|---:|---:|---:|---:|:---:|
| `0x6b62e0a8ba` | Highest temperature in Seoul on July 25? | 11 | 5 | 5 | 45.5% | — |
| `0xc352ad34aa` | Highest temperature in London on July 26? | 11 | 5 | 5 | 45.5% | — |
| `0x267ea5766d` | Highest temperature in Seoul on July 26? | 11 | 5 | 5 | 45.5% | — |
| `0x34d3c192a2` | Highest temperature in Helsinki on July 24? | 11 | 4 | 4 | 36.4% | — |
| `0xfd2458cbd2` | Highest temperature in Buenos Aires on July 24? | 11 | 4 | 4 | 36.4% | — |
| `0x06ee133894` | Highest temperature in Madrid on July 25? | 11 | 4 | 4 | 36.4% | — |
| `0x28db592af6` | Highest temperature in London on July 28? | 11 | 4 | 4 | 36.4% | — |
| `0xeea70af521` | Highest temperature in Seoul on July 28? | 11 | 4 | 4 | 36.4% | — |
| `0x31f0b6d2d0` | Highest temperature in London on July 22? | 11 | 3 | 3 | 27.3% | — |
| `0xcb8e8e29fd` | Highest temperature in Paris on July 22? | 11 | 3 | 3 | 27.3% | — |
| `0x28b9c50bfb` | Highest temperature in Toronto on July 22? | 11 | 3 | 3 | 27.3% | — |
| `0xb0fe1f3235` | Highest temperature in Seattle on July 22? | 11 | 3 | 3 | 27.3% | — |
| `0xf69e0c8178` | Highest temperature in Paris on July 23? | 11 | 3 | 3 | 27.3% | — |
| `0xaa020c7f1c` | Highest temperature in Seoul on July 23? | 11 | 3 | 3 | 27.3% | — |
| `0xe1e19b3ac0` | Highest temperature in Chengdu on July 23? | 11 | 3 | 3 | 27.3% | — |
| `0x2d462fb5f9` | Highest temperature in Helsinki on July 23? | 11 | 3 | 3 | 27.3% | — |
| `0xd3331055f0` | Highest temperature in Seattle on July 23? | 11 | 3 | 3 | 27.3% | — |
| `0x9ed8b03d6f` | Highest temperature in Paris on July 24? | 11 | 3 | 3 | 27.3% | — |
| `0x6e6f9ea3aa` | Highest temperature in Seoul on July 24? | 11 | 3 | 3 | 27.3% | — |
| `0x8ed745021b` | Highest temperature in Chengdu on July 24? | 11 | 3 | 3 | 27.3% | — |

## Verdikt

**Arbitrage weiterhin NICHT testbar — aber der Grund ist jetzt präzise benannt und ein anderer als bisher angenommen.**

- Das *Partitions-Problem* (welche Buckets gehören zusammen?) ist **gelöst**: `negRiskMarketID` liefert die vollständige, exhaustive Menge ex-ante. Die alte Heuristik und ihr Look-ahead-Risiko sind damit überflüssig.
- Der *tatsächliche* Blocker ist **Preis-Coverage**: wir bepreisen im Median nur **18.2%** der Buckets einer Partition, im Maximum **45.5%**, und **keine einzige** Partition ist vollständig bepreist. Wer eine unvollständige Bucket-Menge kauft, kennt S nicht und kann in ~⅔ der Fälle den Gewinner-Bucket gar nicht gekauft haben.

**Konkreter, korrigierter nächster Schritt (ersetzt den alten Vorschlag in `arb_capturability.py`, Markt-IDs zu persistieren — das allein reicht NICHT):** Der Observer muss für *jeden* Bucket einer negRisk-Partition einen Preis-Snapshot zum gemeinsamen Lead-Zeitpunkt schreiben, nicht nur für die Buckets, die er handelbar findet. Erst wenn Preis-Coverage → 100% geht, produziert genau dieses Modul (ohne weitere Änderung) einen validen, look-ahead-freien Arb-Test. Das ist eine **Forward-Datenerfassungs-Aufgabe**, keine Analyse — und sie berührt den 15-Min-Zyklus, daher separat und bewusst zu entscheiden.

---
*READ-ONLY · PAPER ONLY · Partition autoritativ via negRiskMarketID*
