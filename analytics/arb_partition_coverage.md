# Cross-Market-Arbitrage — Partitions-Coverage (autoritativ via negRiskMarketID)

**Generiert:** 2026-08-13T11:00:34.046867+00:00  
**Roh-Snapshots ausgewertet:** 552 · Half-Spread 0.0051 · Lead 24.0h  

> **Fortschritt gegenüber `arb_capturability.py`:** Dort wurden Buckets per Heuristik `(Stadt, Datum, Metrik)` gruppiert — eine Schätzung, die nie beweisen kann, dass man eine *vollständige* Partition sieht. Polymarket liefert die Partition aber autoritativ: alle Buckets eines Multi-Outcome-Events teilen dieselbe `negRiskMarketID` (`negRisk`-Märkte sind per Konstruktion disjunkt & vollständig, genau ein Bucket löst YES auf). Der Collector persistiert dieses Feld bereits in jedem Roh-Snapshot. **Partitions-Zugehörigkeit ist damit ex-ante bekannt — aus der Marktstruktur, ohne jede Outcome-Konditionierung.**

## Datenlage

- negRisk-Partitionen gesamt (≥3 Buckets): **390**
- davon in unserem beobachteten+aufgelösten Universum (tägliche Stadt-Temp): **55**
- **vollständig bepreist UND aufgelöst: 0**

## Der harte Blocker: Preis-Coverage

Um die Arbitrage-Summe S = Σ YES-Preise zu bilden, brauchen wir den Preis **jedes** Buckets zum selben Zeitpunkt. Unser Beobachtungs-Log erfasst aber nur die ~3-5 Buckets, die der Observer tatsächlich bewertet — von typisch 11:

| Kennzahl | Wert |
|---|---:|
| Preis-Coverage min | 9.1% |
| Preis-Coverage **median** | **9.1%** |
| Preis-Coverage mean | 15.4% |
| Preis-Coverage max | 36.4% |
| Partitionen mit Coverage ≥80% | 0 |

## Partitionen (nach Coverage sortiert)

| negRiskID | Event | Buckets | bepreist | aufgelöst | Coverage | komplett |
|---|---|---:|---:|---:|---:|:---:|
| `0xbc3394545d` | Highest temperature in Paris on August 7? | 11 | 4 | 4 | 36.4% | — |
| `0x52795afd4d` | Highest temperature in Paris on August 9? | 11 | 4 | 4 | 36.4% | — |
| `0xe4cd6f59dc` | Highest temperature in Seoul (Incheon) on August 11? | 11 | 4 | 4 | 36.4% | — |
| `0xe6b7a7e3fc` | Highest temperature in Chengdu on August 8? | 11 | 3 | 3 | 27.3% | — |
| `0x08bc059d7a` | Highest temperature in London on August 9? | 11 | 3 | 3 | 27.3% | — |
| `0xbb519e2afb` | Highest temperature in Ankara on August 9? | 11 | 3 | 3 | 27.3% | — |
| `0x76255f9304` | Highest temperature in Chengdu on August 10? | 11 | 3 | 3 | 27.3% | — |
| `0x9c141d22db` | Lowest temperature in London on August 10? | 11 | 3 | 3 | 27.3% | — |
| `0x897cacd720` | Highest temperature in London on August 11? | 11 | 3 | 3 | 27.3% | — |
| `0xfc9f304965` | Highest temperature in Paris on August 11? | 11 | 3 | 3 | 27.3% | — |
| `0x18a9602bfc` | Highest temperature in London on August 12? | 11 | 3 | 3 | 27.3% | — |
| `0x3237d2f1d6` | Lowest temperature in London on August 6? | 11 | 2 | 2 | 18.2% | — |
| `0x33133a8329` | Highest temperature in Paris on August 6? | 11 | 2 | 2 | 18.2% | — |
| `0x26d42bfd38` | Highest temperature in Atlanta on August 6? | 11 | 2 | 2 | 18.2% | — |
| `0xf10b2296e9` | Highest temperature in London on August 7? | 11 | 2 | 2 | 18.2% | — |
| `0x1a7f87e67d` | Highest temperature in Seoul (Incheon) on August 7? | 11 | 2 | 2 | 18.2% | — |
| `0x4bcb144bb0` | Highest temperature in Ankara on August 7? | 11 | 2 | 2 | 18.2% | — |
| `0xdfe2984dc5` | Highest temperature in Madrid on August 7? | 11 | 2 | 2 | 18.2% | — |
| `0xaef057257d` | Highest temperature in Seoul (Incheon) on August 8? | 11 | 2 | 2 | 18.2% | — |
| `0x5ab913a65b` | Highest temperature in Seoul (Incheon) on August 9? | 11 | 2 | 2 | 18.2% | — |

## Verdikt

**Arbitrage weiterhin NICHT testbar — aber der Grund ist jetzt präzise benannt und ein anderer als bisher angenommen.**

- Das *Partitions-Problem* (welche Buckets gehören zusammen?) ist **gelöst**: `negRiskMarketID` liefert die vollständige, exhaustive Menge ex-ante. Die alte Heuristik und ihr Look-ahead-Risiko sind damit überflüssig.
- Der *tatsächliche* Blocker ist **Preis-Coverage**: wir bepreisen im Median nur **9.1%** der Buckets einer Partition, im Maximum **36.4%**, und **keine einzige** Partition ist vollständig bepreist. Wer eine unvollständige Bucket-Menge kauft, kennt S nicht und kann in ~⅔ der Fälle den Gewinner-Bucket gar nicht gekauft haben.

**Konkreter, korrigierter nächster Schritt (ersetzt den alten Vorschlag in `arb_capturability.py`, Markt-IDs zu persistieren — das allein reicht NICHT):** Der Observer muss für *jeden* Bucket einer negRisk-Partition einen Preis-Snapshot zum gemeinsamen Lead-Zeitpunkt schreiben, nicht nur für die Buckets, die er handelbar findet. Erst wenn Preis-Coverage → 100% geht, produziert genau dieses Modul (ohne weitere Änderung) einen validen, look-ahead-freien Arb-Test. Das ist eine **Forward-Datenerfassungs-Aufgabe**, keine Analyse — und sie berührt den 15-Min-Zyklus, daher separat und bewusst zu entscheiden.

---
*READ-ONLY · PAPER ONLY · Partition autoritativ via negRiskMarketID*
