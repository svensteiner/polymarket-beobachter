# Edge-Routine — Digest

**Lauf:** 2026-08-05T05:00:22.922339+00:00  
**Status:** OK

## Was hat sich geändert

- 🟢 Kandidaten-Kohorte ist über Break-even (+0.58%, n=55) — bei kleinem n noch Rauschen, weiter sammeln.

## Aktueller Stand

| Kennzahl | Wert |
|---|---|
| Überlebende Hypothesen | **KEINE** |
| Hypothesen getestet / OOS n | 15 / 1366 |
| Bester Kandidat | `no_fade_10_20` · net +0.64% · t=0.985 · q=1.0 |
| Regime-Guard | ✅ aktiv |
| Forward aufgelöst (Gate 1: 150) | 244 |
| Kandidaten-Kohorte (exact+eng) | n=55 · net real +0.58% |
| Modell-Skill-Nische (B4) | KEINE (getestet 2 Zellen · Δ OOS -1.71%) |
| Arbitrage erntbar | nein (-2.98%/Set) |
| Arb-Partitionen (negRisk) | 0/52 vollständig · Preis-Coverage median 18.2% / max 36.4% |
| Half-Spread (kalibriert) | 0.00211 |

## Nächste Arbeit

1. **B2-Fortsetzung (aussichtsreichster Pfad):** Pro Event die vollständige Bucket-Marktliste aus der Gamma-API persistieren (`/events?tag_slug=weather` nutzt der Collector bereits), damit Vollständigkeit VOR dem Handel prüfbar ist statt aus dem Ausgang. Erst dann ist der Arbitrage-Test valide wiederholbar — und es wäre die einzige modell- UND regime-unabhängige Edge-Klasse.
2. **B4 erledigt (negativ):** Konditionaler Modell-Skill-Scan (`analytics/model_skill_scan.py`) findet KEINE Stadt×Typ-Nische mit Modell-Brier < Markt-Brier OOS (BH-korrigiert). Forecaster ist auch konditional nicht überlegen — nicht erneut aufrollen ohne neues Modell-/Datenmaterial.
3. **B5:** Preis-Momentum — zuerst verifizieren, ob `logs/weather_observations*.jsonl` mehrere Snapshots je Markt enthält.
4. **Neue Hypothesen** sind billig: ein Eintrag in `HYPOTHESES` in `analytics/edge_scanner.py` genügt, das Harness erledigt Walk-Forward, reale Kosten und BH-Korrektur.

---
*Läuft 3x täglich lokal (Task `WeatherObserver-EdgeRoutine`). Plan + Methoden-Guardrails: `reports/edge_search_plan_2026-07-27.md` · Historie: `data/edge_routine_history.jsonl`*
