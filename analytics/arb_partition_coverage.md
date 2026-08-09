# Cross-Market-Arbitrage — Partitions-Coverage (autoritativ via negRiskMarketID)

**Generiert:** 2026-08-09T17:00:39.890696+00:00  
**Roh-Snapshots ausgewertet:** 571 · Half-Spread 0.0017 · Lead 24.0h  

> **Fortschritt gegenüber `arb_capturability.py`:** Dort wurden Buckets per Heuristik `(Stadt, Datum, Metrik)` gruppiert — eine Schätzung, die nie beweisen kann, dass man eine *vollständige* Partition sieht. Polymarket liefert die Partition aber autoritativ: alle Buckets eines Multi-Outcome-Events teilen dieselbe `negRiskMarketID` (`negRisk`-Märkte sind per Konstruktion disjunkt & vollständig, genau ein Bucket löst YES auf). Der Collector persistiert dieses Feld bereits in jedem Roh-Snapshot. **Partitions-Zugehörigkeit ist damit ex-ante bekannt — aus der Marktstruktur, ohne jede Outcome-Konditionierung.**

## Datenlage

- negRisk-Partitionen gesamt (≥3 Buckets): **403**
- davon in unserem beobachteten+aufgelösten Universum (tägliche Stadt-Temp): **59**
- **vollständig bepreist UND aufgelöst: 0**

## Der harte Blocker: Preis-Coverage

Um die Arbitrage-Summe S = Σ YES-Preise zu bilden, brauchen wir den Preis **jedes** Buckets zum selben Zeitpunkt. Unser Beobachtungs-Log erfasst aber nur die ~3-5 Buckets, die der Observer tatsächlich bewertet — von typisch 11:

| Kennzahl | Wert |
|---|---:|
| Preis-Coverage min | 9.1% |
| Preis-Coverage **median** | **9.1%** |
| Preis-Coverage mean | 15.9% |
| Preis-Coverage max | 45.5% |
| Partitionen mit Coverage ≥80% | 0 |

## Partitionen (nach Coverage sortiert)

| negRiskID | Event | Buckets | bepreist | aufgelöst | Coverage | komplett |
|---|---|---:|---:|---:|---:|:---:|
| `0x8cee6108d2` | Highest temperature in Tokyo on August 6? | 11 | 5 | 5 | 45.5% | — |
| `0x910978b550` | Highest temperature in London on August 4? | 11 | 4 | 4 | 36.4% | — |
| `0x8bcb295b50` | Highest temperature in Paris on August 4? | 11 | 4 | 4 | 36.4% | — |
| `0x8025bc5c1d` | Highest temperature in Paris on August 5? | 11 | 4 | 4 | 36.4% | — |
| `0xbc3394545d` | Highest temperature in Paris on August 7? | 11 | 4 | 4 | 36.4% | — |
| `0xc5ce91a23b` | Highest temperature in London on August 3? | 11 | 3 | 3 | 27.3% | — |
| `0x991aec1c19` | Highest temperature in Paris on August 3? | 11 | 3 | 3 | 27.3% | — |
| `0x23fb22b671` | Highest temperature in London on August 5? | 11 | 3 | 3 | 27.3% | — |
| `0x2f9149f774` | Highest temperature in Ankara on August 5? | 11 | 3 | 3 | 27.3% | — |
| `0x2f77979e7f` | Highest temperature in Seoul (Incheon) on August 6? | 11 | 3 | 3 | 27.3% | — |
| `0xe6b7a7e3fc` | Highest temperature in Chengdu on August 8? | 11 | 3 | 3 | 27.3% | — |
| `0x1978efbd2a` | Highest temperature in Madrid on August 3? | 11 | 2 | 2 | 18.2% | — |
| `0x590f42a54f` | Highest temperature in Seoul (Incheon) on August 4? | 11 | 2 | 2 | 18.2% | — |
| `0x8af56fac62` | Highest temperature in Ankara on August 4? | 11 | 2 | 2 | 18.2% | — |
| `0xf71333c091` | Highest temperature in Helsinki on August 4? | 11 | 2 | 2 | 18.2% | — |
| `0x842a3e4a69` | Highest temperature in Seoul (Incheon) on August 5? | 11 | 2 | 2 | 18.2% | — |
| `0xd473c07c7b` | Highest temperature in Madrid on August 5? | 11 | 2 | 2 | 18.2% | — |
| `0xa173316513` | Highest temperature in San Francisco on August 5? | 11 | 2 | 2 | 18.2% | — |
| `0x3237d2f1d6` | Lowest temperature in London on August 6? | 11 | 2 | 2 | 18.2% | — |
| `0x33133a8329` | Highest temperature in Paris on August 6? | 11 | 2 | 2 | 18.2% | — |

## Verdikt

**Arbitrage weiterhin NICHT testbar — aber der Grund ist jetzt präzise benannt und ein anderer als bisher angenommen.**

- Das *Partitions-Problem* (welche Buckets gehören zusammen?) ist **gelöst**: `negRiskMarketID` liefert die vollständige, exhaustive Menge ex-ante. Die alte Heuristik und ihr Look-ahead-Risiko sind damit überflüssig.
- Der *tatsächliche* Blocker ist **Preis-Coverage**: wir bepreisen im Median nur **9.1%** der Buckets einer Partition, im Maximum **45.5%**, und **keine einzige** Partition ist vollständig bepreist. Wer eine unvollständige Bucket-Menge kauft, kennt S nicht und kann in ~⅔ der Fälle den Gewinner-Bucket gar nicht gekauft haben.

**Konkreter, korrigierter nächster Schritt (ersetzt den alten Vorschlag in `arb_capturability.py`, Markt-IDs zu persistieren — das allein reicht NICHT):** Der Observer muss für *jeden* Bucket einer negRisk-Partition einen Preis-Snapshot zum gemeinsamen Lead-Zeitpunkt schreiben, nicht nur für die Buckets, die er handelbar findet. Erst wenn Preis-Coverage → 100% geht, produziert genau dieses Modul (ohne weitere Änderung) einen validen, look-ahead-freien Arb-Test. Das ist eine **Forward-Datenerfassungs-Aufgabe**, keine Analyse — und sie berührt den 15-Min-Zyklus, daher separat und bewusst zu entscheiden.

---
*READ-ONLY · PAPER ONLY · Partition autoritativ via negRiskMarketID*
