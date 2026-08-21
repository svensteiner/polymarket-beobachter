# Conditional Model-Skill Scan — findet der Forecaster EINE Nische?

**Generiert:** 2026-08-21T11:00:05.465493+00:00  
**Lead:** ~24.0h · **OOS-Cutoff:** 2026-06-01 · TRAIN n=2172 · TEST n=1615  
**Raster:** Stadt × Typ · min n/Zelle = 30 · FDR-Korrektur: Benjamini-Hochberg @ α=0.05

> **Metrik:** gepaarte Brier-Differenz je Markt `d = (Markt_p − y)² − (Modell_p − y)²`. **d > 0 ⇒ Modell schärfer als Markt.** Walk-forward: Zelle ist Kandidat nur, wenn sie auf TRAIN positiv ist; genau **einmal** auf TEST ausgewertet. Cluster-t nach (Stadt, Datum). Nur was die BH-Korrektur übersteht, zählt.

## Globale Grundlinie (recomputed auf lead-anchored Universum)

| Fenster | n | Markt-Brier | Modell-Brier | Δ (Markt−Modell) | Cluster-t |
|---|---:|---:|---:|---:|---:|
| Gesamt | 3787 | 0.15359 | 0.16892 | -0.015335 | -6.802 |
| Train | 2172 | 0.14272 | 0.15677 | -0.014045 | -4.487 |
| TEST (OOS) | 1615 | 0.1682 | 0.18526 | -0.017069 | -5.11 |

*Δ < 0 heißt: der Markt ist im Schnitt schärfer als das Modell (Modell-Brier höher). Das ist der bekannte globale Befund — die Frage ist, ob es eine Ausnahme-Zelle gibt.*

## Kandidaten-Zellen (auf TRAIN positiv, auf TEST ausgewertet)

| Stadt | Typ | n(tr) | Δ(tr) | n(te) | Δ(te) | Cluster-t(te) | p | q (BH) | Verdikt |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| Seattle | between | 93 | +0.0003 | 69 | -0.0066 | 0.037 | 0.97073 | 1.0 | ❌ negativ auf TEST |
| Seoul | exact | 86 | +0.0057 | 181 | -0.0205 | -2.734 | 1.0 | 1.0 | ❌ negativ auf TEST |

## Verdikt

**Keine der 2 getesteten Kandidaten-Zellen** (von 58 Stadt×Typ-Zellen) zeigt OOS signifikanten Modell-Skill nach BH-Korrektur. Das bestätigt: der Forecaster hat **keine handelbare Prognose-Nische** — global anti-kalibriert, und auch konditional keine Ausnahme. Ehrliches Nein.

---
*READ-ONLY · Walk-forward, kein Look-ahead · gepaarte Brier-Differenz · Lead fix ~24h (Daten zu eng geclustert für Lead-Raster) · Monat = Regime-Schnitt, keine Zell-Dimension.*
