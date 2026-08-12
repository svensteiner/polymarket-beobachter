# Edge-Routine — Digest

**Lauf:** 2026-08-12T17:00:36.309578+00:00  
**Status:** OK

## Was hat sich geändert

- Keine entscheidungsrelevante Änderung seit dem letzten Lauf.

## Aktueller Stand

| Kennzahl | Wert |
|---|---|
| Überlebende Hypothesen | **KEINE** |
| Hypothesen getestet / OOS n | 15 / 1485 |
| Bester Kandidat | `no_fade_10_20` · net +0.74% · t=0.905 · q=1.0 |
| Regime-Guard | ✅ aktiv |
| Forward aufgelöst (Gate 1: 150) | 317 |
| Kandidaten-Kohorte (exact+eng) | n=70 · net real +3.57% |
| Modell-Skill-Nische (B4) | KEINE (getestet 2 Zellen · Δ OOS -1.70%) |
| Arbitrage erntbar | nein (-3.27%/Set) |
| Arb-Partitionen (negRisk) | 0/60 vollständig · Preis-Coverage median 9.1% / max 45.5% |
| Half-Spread (kalibriert) | 0.0021 |

## Nächste Arbeit

1. **B2-Fortsetzung (aussichtsreichster Pfad):** Pro Event die vollständige Bucket-Marktliste aus der Gamma-API persistieren (`/events?tag_slug=weather` nutzt der Collector bereits), damit Vollständigkeit VOR dem Handel prüfbar ist statt aus dem Ausgang. Erst dann ist der Arbitrage-Test valide wiederholbar — und es wäre die einzige modell- UND regime-unabhängige Edge-Klasse.
2. **B4 erledigt (negativ):** Konditionaler Modell-Skill-Scan (`analytics/model_skill_scan.py`) findet KEINE Stadt×Typ-Nische mit Modell-Brier < Markt-Brier OOS (BH-korrigiert). Forecaster ist auch konditional nicht überlegen — nicht erneut aufrollen ohne neues Modell-/Datenmaterial.
3. **B5:** Preis-Momentum — zuerst verifizieren, ob `logs/weather_observations*.jsonl` mehrere Snapshots je Markt enthält.
4. **Neue Hypothesen** sind billig: ein Eintrag in `HYPOTHESES` in `analytics/edge_scanner.py` genügt, das Harness erledigt Walk-Forward, reale Kosten und BH-Korrektur.

---
*Läuft 3x täglich lokal (Task `WeatherObserver-EdgeRoutine`). Plan + Methoden-Guardrails: `reports/edge_search_plan_2026-07-27.md` · Historie: `data/edge_routine_history.jsonl`*
