# Edge-Routine — Digest

**Lauf:** 2026-07-30T17:00:23.654090+00:00  
**Status:** OK

## Was hat sich geändert

- 🟢 **Regime-Guard hat DEPAUSIERT** — die Longshot-Verzerrung ist zurück. NO-Fade-Lane nimmt wieder Entries auf; Kandidaten-Kohorte beobachten.

## Aktueller Stand

| Kennzahl | Wert |
|---|---|
| Überlebende Hypothesen | **KEINE** |
| Hypothesen getestet / OOS n | 15 / 1287 |
| Bester Kandidat | `no_fade_10_20` · net +0.37% · t=0.767 · q=1.0 |
| Regime-Guard | ✅ aktiv |
| Forward aufgelöst (Gate 1: 150) | 201 |
| Kandidaten-Kohorte (exact+eng) | n=44 · net real +2.15% |
| Modell-Skill-Nische (B4) | KEINE (getestet 2 Zellen · Δ OOS -1.78%) |
| Arbitrage erntbar | nein (-4.08%/Set) |
| Arb-Partitionen (negRisk) | 0/82 vollständig · Preis-Coverage median 18.2% / max 45.5% |
| Half-Spread (kalibriert) | 0.00508 |

## Nächste Arbeit

1. **B2-Fortsetzung (aussichtsreichster Pfad):** Pro Event die vollständige Bucket-Marktliste aus der Gamma-API persistieren (`/events?tag_slug=weather` nutzt der Collector bereits), damit Vollständigkeit VOR dem Handel prüfbar ist statt aus dem Ausgang. Erst dann ist der Arbitrage-Test valide wiederholbar — und es wäre die einzige modell- UND regime-unabhängige Edge-Klasse.
2. **B4 erledigt (negativ):** Konditionaler Modell-Skill-Scan (`analytics/model_skill_scan.py`) findet KEINE Stadt×Typ-Nische mit Modell-Brier < Markt-Brier OOS (BH-korrigiert). Forecaster ist auch konditional nicht überlegen — nicht erneut aufrollen ohne neues Modell-/Datenmaterial.
3. **B5:** Preis-Momentum — zuerst verifizieren, ob `logs/weather_observations*.jsonl` mehrere Snapshots je Markt enthält.
4. **Neue Hypothesen** sind billig: ein Eintrag in `HYPOTHESES` in `analytics/edge_scanner.py` genügt, das Harness erledigt Walk-Forward, reale Kosten und BH-Korrektur.

---
*Läuft 3x täglich lokal (Task `WeatherObserver-EdgeRoutine`). Plan + Methoden-Guardrails: `reports/edge_search_plan_2026-07-27.md` · Historie: `data/edge_routine_history.jsonl`*
