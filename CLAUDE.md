# Polymarket Beobachter — Agent-Memory

Eine Datei. Anweisungen + aktueller Stand. Bei Statusfragen zuerst diesen Block lesen, dann die Live-Dateien darunter.

Antworte auf Deutsch. Konkret. Paper-only. **Ziel ist Gewinn, nicht Wetter.**

## Pfad

`C:\Users\botrunner\projects\polymarket-beobachter`

Kein Polymarket-API-Key. Alles lokal. Pipeline alle 15 Min — nicht extra starten.

## Stand (2026-08-24)

| | |
|---|---|
| Identitaet | Gewinn-Bot. Wetter ist optional, nicht die Strategie. |
| Live-Trading | Gesperrt. Kein Order ohne explizite Freigabe. |
| Paper-Kapital | 5000 EUR Start, verfuegbar ~4913 EUR, YES-Paper-P&L **-86.96 EUR** |
| Wetter-YES | Tot. Modell-Brier 0.169 vs Markt 0.154. `BLOCKED_MARKET_TYPES`: exact, at_or_above, between. Observations oft 0. Nicht wieder oeffnen. |
| NO-Fade Harvest | exact + Spread <2c. 8 resolved, P&L **-0.43 EUR**. Broad NO-Fade OOS t=0.46, nach Kosten oft tot. |
| **Primaer** | `paper_trader/struct_arb.py` — complete-set + binary-lock, nur nach echten CLOB-Asks + Fee, MIN_NET 1%. Active-leg Filter + Ask-Coverage >= 0.92. Bei knapper Book-Budget: CLOB-Probe-Reihenfolge 2-leg zuerst, dann hoechstes Gamma-`est_net` (`completeset_yes_net` auf bestAsk/yes). Cash wenn nichts da ist. |
| Struct-Arb Scan | Active-leg + Coverage 0.92 + Gamma-est_net Probe-Ranking. **1 Paper-Entry: South Dakota Senate** (D+R, n=2, 11 Placeholders gedroppt, asks 0.018+0.965, net +1.29%, coverage 0.983). Budget-Skips zuvor 19 — Ranking zielt auf mehr MIN_NET-Locks. PAPER ONLY. |
| Health | ELEVATED (Edge-Drought auf dem alten YES-Pfad). consecutive_errors 0. Fail-open im Zyklus. |
| Go-Live | Gesperrt bis Forward-Edge bewiesen. Positives Paper-P&L ist kein Beweis. |

Naechster Schritt: Struct-Arb laufen lassen. Groesse nur erhoehen wenn `analytics/struct_arb.md` ueber Tage `entered>0` **und** positives P&L nach echten Fills zeigt.

2026-08-24 Cleanup: Tote Module geloescht (LLM-Parser, Charts-CLI, unused loggers). Wetter-Preis-Fetch nur noch city-temp; Forecast-APIs fuer blockierte Typen aus; Evolution/LLM-Analyst/General-Scan aus dem 15-Min-Zyklus.

## Status lesen (Live, jeden Zyklus)

- `analytics/struct_arb.md` — Primaer-Lane
- `analytics/edge_status.md` — NO-Fade + Health
- `output/status_summary.txt` — letzte Pipeline-Runs
- `logs/bot_status.json` / `logs/bot_health.json`
- `data/capital_config.json`
- `data/struct_arb.jsonl` / `data/no_fade_harvest.jsonl`

## Strategie

1. **Struct Arb (aktiv, Paper):** Gamma-Events ohne Wetter-Filter. Nur live Legs (active/liquidity/yes_price/bestBid); Inactive-Placeholders droppen. Ask-Coverage >= 0.92. Netto >= 1% nach Ask+Fee. Tiefe muss Shares decken. Incomplete (z.B. Nobel 20/71) nie. CLOB-Probes: 2-leg first, dann absteigend Gamma-`est_net` (BUY_YES_SET); Binary analog. `collector/sanitizer.py` nicht anfassen.
2. **Wetter-YES (eingefroren):** Forecast schlaegt den Markt nicht, auch nicht konditional. Guardrails bleiben.
3. **NO-Fade (Schatten/Harvest):** Research + kleines Harvest-Ledger. Nicht die Identitaet. Regime-abhaengig.
4. **Umsetzung:** Plaene hier entscheiden, Code an guenstigere Modelle geben. Tests vor Merge. Kein Live.

Kernmodule: `app/orchestrator.py`, `paper_trader/struct_arb.py`, `paper_trader/struct_arb_math.py`, `paper_trader/clob_book.py`, `config/weather.yaml`.

## Regeln

- Deutsch. Vor Aenderungen kurz sagen was passiert. Danach testen (`pytest` fuer die Lane, nicht immer vollen Cockpit-Run).
- Kein Live-Trading, keine Keys, keine Kapitalerhoehung ohne Freigabe.
- Stabilitaet vor Aktivitaet: lieber Cash als erzwungene Trades.
- Diesen Stand in **dieser Datei** aktualisieren wenn sich die Strategie oder der Ledger-Zustand aendert — keine zweite Memory-Datei.

## Legacy (nicht neu bauen)

Paper-YES-Stack existiert noch und bleibt fuer den alten Simulator: TP +15% / SL -25%, Averaging-Down, Diversifikation, Fee-Model, Kelly-Decay, Ensemble, Telegram, Gamma-Discovery, Wetter-Engine. Nicht reaktivieren solange Struct-Arb die Primaer-Lane ist.
