# Edge-Routine — Digest

**Lauf:** 2026-08-21T17:00:20.711990+00:00  
**Status:** OK

## Was hat sich geändert

- Keine entscheidungsrelevante Änderung seit dem letzten Lauf.

## Aktueller Stand

| Kennzahl | Wert |
|---|---|
| Überlebende Hypothesen | **KEINE** |
| Hypothesen getestet / OOS n | 15 / 1618 |
| Bester Kandidat | `no_fade_10_20` · net +0.31% · t=0.553 · q=1.0 |
| Regime-Guard | 🛑 PAUSIERT |
| Forward aufgelöst (Gate 1: 150) | 397 |
| Kandidaten-Kohorte (exact+eng) | n=82 · net real +1.22% |
| Modell-Skill-Nische (B4) | KEINE (getestet 2 Zellen · Δ OOS -1.69%) |
| Arbitrage erntbar | nein (-4.36%/Set) |
| Arb-Partitionen (negRisk) | 0/47 vollständig · Preis-Coverage median 9.1% / max 54.5% |
| Half-Spread (kalibriert) | 0.00517 |

## Nächste Arbeit

1. **B2-Fortsetzung (aussichtsreichster Pfad):** Pro Event die vollständige Bucket-Marktliste aus der Gamma-API persistieren (`/events?tag_slug=weather` nutzt der Collector bereits), damit Vollständigkeit VOR dem Handel prüfbar ist statt aus dem Ausgang. Erst dann ist der Arbitrage-Test valide wiederholbar — und es wäre die einzige modell- UND regime-unabhängige Edge-Klasse.
2. **B4 erledigt (negativ):** Konditionaler Modell-Skill-Scan (`analytics/model_skill_scan.py`) findet KEINE Stadt×Typ-Nische mit Modell-Brier < Markt-Brier OOS (BH-korrigiert). Forecaster ist auch konditional nicht überlegen — nicht erneut aufrollen ohne neues Modell-/Datenmaterial.
3. **B5:** Preis-Momentum — zuerst verifizieren, ob `logs/weather_observations*.jsonl` mehrere Snapshots je Markt enthält.
4. **Neue Hypothesen** sind billig: ein Eintrag in `HYPOTHESES` in `analytics/edge_scanner.py` genügt, das Harness erledigt Walk-Forward, reale Kosten und BH-Korrektur.
5. NO-Fade bleibt regime-pausiert — nicht daran weiterarbeiten, solange der Gap negativ ist.

---
*Läuft 3x täglich lokal (Task `WeatherObserver-EdgeRoutine`). Plan + Methoden-Guardrails: `reports/edge_search_plan_2026-07-27.md` · Historie: `data/edge_routine_history.jsonl`*
