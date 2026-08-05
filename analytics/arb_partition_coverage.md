# Cross-Market-Arbitrage — Partitions-Coverage (autoritativ via negRiskMarketID)

**Generiert:** 2026-08-05T05:00:22.890507+00:00  
**Roh-Snapshots ausgewertet:** 490 · Half-Spread 0.0021 · Lead 24.0h  

> **Fortschritt gegenüber `arb_capturability.py`:** Dort wurden Buckets per Heuristik `(Stadt, Datum, Metrik)` gruppiert — eine Schätzung, die nie beweisen kann, dass man eine *vollständige* Partition sieht. Polymarket liefert die Partition aber autoritativ: alle Buckets eines Multi-Outcome-Events teilen dieselbe `negRiskMarketID` (`negRisk`-Märkte sind per Konstruktion disjunkt & vollständig, genau ein Bucket löst YES auf). Der Collector persistiert dieses Feld bereits in jedem Roh-Snapshot. **Partitions-Zugehörigkeit ist damit ex-ante bekannt — aus der Marktstruktur, ohne jede Outcome-Konditionierung.**

## Datenlage

- negRisk-Partitionen gesamt (≥3 Buckets): **379**
- davon in unserem beobachteten+aufgelösten Universum (tägliche Stadt-Temp): **52**
- **vollständig bepreist UND aufgelöst: 0**

## Der harte Blocker: Preis-Coverage

Um die Arbitrage-Summe S = Σ YES-Preise zu bilden, brauchen wir den Preis **jedes** Buckets zum selben Zeitpunkt. Unser Beobachtungs-Log erfasst aber nur die ~3-5 Buckets, die der Observer tatsächlich bewertet — von typisch 11:

| Kennzahl | Wert |
|---|---:|
| Preis-Coverage min | 9.1% |
| Preis-Coverage **median** | **18.2%** |
| Preis-Coverage mean | 18.4% |
| Preis-Coverage max | 36.4% |
| Partitionen mit Coverage ≥80% | 0 |

## Partitionen (nach Coverage sortiert)

| negRiskID | Event | Buckets | bepreist | aufgelöst | Coverage | komplett |
|---|---|---:|---:|---:|---:|:---:|
| `0xe8ead9a016` | Highest temperature in London on July 29? | 11 | 4 | 4 | 36.4% | — |
| `0x2d224918a7` | Highest temperature in Seoul (Incheon) on July 30? | 11 | 4 | 4 | 36.4% | — |
| `0xa0e5c62f16` | Highest temperature in Tokyo on July 30? | 11 | 4 | 4 | 36.4% | — |
| `0x8ffaa08fee` | Highest temperature in London on July 30? | 11 | 4 | 4 | 36.4% | — |
| `0x8e88b514f7` | Highest temperature in Paris on July 30? | 11 | 4 | 4 | 36.4% | — |
| `0x0fc5fca76e` | Highest temperature in Seoul on July 31? | 11 | 4 | 4 | 36.4% | — |
| `0x910978b550` | Highest temperature in London on August 4? | 11 | 4 | 4 | 36.4% | — |
| `0x8bcb295b50` | Highest temperature in Paris on August 4? | 11 | 4 | 4 | 36.4% | — |
| `0x536027425d` | Lowest temperature in London on July 29? | 11 | 3 | 3 | 27.3% | — |
| `0xe0186cf3d7` | Highest temperature in Ankara on July 29? | 11 | 3 | 3 | 27.3% | — |
| `0x21b9817727` | Highest temperature in Tokyo on July 31? | 11 | 3 | 3 | 27.3% | — |
| `0xcff854830d` | Highest temperature in Chengdu on July 31? | 11 | 3 | 3 | 27.3% | — |
| `0xa7228c6c00` | Highest temperature in Helsinki on July 31? | 11 | 3 | 3 | 27.3% | — |
| `0x213a0496b1` | Highest temperature in London on August 1? | 11 | 3 | 3 | 27.3% | — |
| `0x5110d73032` | Highest temperature in Paris on August 1? | 11 | 3 | 3 | 27.3% | — |
| `0x81db8ea47e` | Highest temperature in Madrid on August 1? | 11 | 3 | 3 | 27.3% | — |
| `0xc5ce91a23b` | Highest temperature in London on August 3? | 11 | 3 | 3 | 27.3% | — |
| `0x991aec1c19` | Highest temperature in Paris on August 3? | 11 | 3 | 3 | 27.3% | — |
| `0xe43152843b` | Lowest temperature in Paris on July 29? | 11 | 2 | 2 | 18.2% | — |
| `0xa8b48426ce` | Highest temperature in Paris on July 29? | 11 | 2 | 2 | 18.2% | — |

## Verdikt

**Arbitrage weiterhin NICHT testbar — aber der Grund ist jetzt präzise benannt und ein anderer als bisher angenommen.**

- Das *Partitions-Problem* (welche Buckets gehören zusammen?) ist **gelöst**: `negRiskMarketID` liefert die vollständige, exhaustive Menge ex-ante. Die alte Heuristik und ihr Look-ahead-Risiko sind damit überflüssig.
- Der *tatsächliche* Blocker ist **Preis-Coverage**: wir bepreisen im Median nur **18.2%** der Buckets einer Partition, im Maximum **36.4%**, und **keine einzige** Partition ist vollständig bepreist. Wer eine unvollständige Bucket-Menge kauft, kennt S nicht und kann in ~⅔ der Fälle den Gewinner-Bucket gar nicht gekauft haben.

**Konkreter, korrigierter nächster Schritt (ersetzt den alten Vorschlag in `arb_capturability.py`, Markt-IDs zu persistieren — das allein reicht NICHT):** Der Observer muss für *jeden* Bucket einer negRisk-Partition einen Preis-Snapshot zum gemeinsamen Lead-Zeitpunkt schreiben, nicht nur für die Buckets, die er handelbar findet. Erst wenn Preis-Coverage → 100% geht, produziert genau dieses Modul (ohne weitere Änderung) einen validen, look-ahead-freien Arb-Test. Das ist eine **Forward-Datenerfassungs-Aufgabe**, keine Analyse — und sie berührt den 15-Min-Zyklus, daher separat und bewusst zu entscheiden.

---
*READ-ONLY · PAPER ONLY · Partition autoritativ via negRiskMarketID*
