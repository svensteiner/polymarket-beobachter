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
| **Primaer** | `paper_trader/struct_arb.py` — complete-set + binary-lock, nur nach echten CLOB-Asks + Fee, MIN_NET 1%. Active-leg Filter + Ask-Coverage >= 0.92. Inactive-Skip nur wenn `skipped_inactive_ok` (Person/Option A-J); Residual-Other / Catch-all blockt Entry (`residual_other`). MAX_BOOK_FETCHES 45, fail-open. Cash wenn nichts da ist. |
| Struct-Arb Scan | Residual-Other-Gate aktiv. Paper-Run 15:07 PT: scanned 102, **entered=0**, residual_other=90, candidates=8, rejected_cost=7, book_fetches=45/45. **Kein cleanes MIN_NET ohne Other.** Offen bleibt **South Dakota Senate** (Legacy, skipped_inactive=11 inkl. Other, nicht auto-close). Neue Entries brauchen `skipped_inactive_ok` + `residual_risk` none/placeholders_only. MIN_NET bleibt 1%. PAPER ONLY. |
| Health | ELEVATED (Edge-Drought auf dem alten YES-Pfad). consecutive_errors 0. Fail-open im Zyklus. |
| Go-Live | Gesperrt bis Forward-Edge bewiesen. Positives Paper-P&L ist kein Beweis. |

Naechster Schritt: Kein MIN_NET-Locker, kein Other-Skip. SD-Legacy nicht schliessen. Naechste Kante: Binaries mit vollen Books / Maker-Resting (Near-Miss ~ -0.14c nach Fee) oder mehr Events — nur wenn klein und klar. Groesse nur erhoehen wenn `analytics/struct_arb.md` ueber Tage `entered>0` **und** positives P&L nach echten Fills zeigt.

2026-08-24 Querdenker (kein Code, kein Entry): Post-close Wetter vs NOAA/METAR. Seoul Aug-24 bereits auto-resolved. Offene Aug-24 Daily-Temps (endDate 12:00Z, closed=false) sind nach METAR schon eingepreist: London 22C ask 0.998, Paris 27C 0.996, Chengdu 37C 1.00, Madrid 29C ask 0.85 bei METAR-Max 29C. US-Maxima (NYC/ORD/MIA) noch intra-day, kein Post-Close. Nested FDV/by-date Leitern: Ask-Inversionen ja, tradeable Bid-Ask-Arb (bid_hi > ask_lo) = 0. Kein post_close_sniper bis Winner-Ask klar unter 0.90 nach offizieller Obs.

2026-08-24 Cleanup: Tote Module geloescht (LLM-Parser, Charts-CLI, unused loggers). Wetter-Preis-Fetch nur noch city-temp; Forecast-APIs fuer blockierte Typen aus; Evolution/LLM-Analyst/General-Scan aus dem 15-Min-Zyklus.

## Status lesen (Live, jeden Zyklus)

- `analytics/struct_arb.md` — Primaer-Lane
- `analytics/edge_status.md` — NO-Fade + Health
- `output/status_summary.txt` — letzte Pipeline-Runs
- `logs/bot_status.json` / `logs/bot_health.json`
- `data/capital_config.json`
- `data/struct_arb.jsonl` / `data/no_fade_harvest.jsonl`

## Strategie

1. **Struct Arb (aktiv, Paper):** Gamma-Events ohne Wetter-Filter. Nur live Legs (active/liquidity/yes_price/bestBid); Inactive **nur** Person/Option A-J droppen (`skipped_inactive_ok`). Residual Other/Catch-all ist kein complete set (kann YES resolven und D+R wipen) — Skip `residual_other`, kein CLOB. Ask-Coverage >= 0.92. Netto >= 1% nach Ask+Fee. Tiefe muss Shares decken. Incomplete (z.B. Nobel 20/71) nie. CLOB-Probes: 2-leg first, dann absteigend Gamma-`est_net` (BUY_YES_SET); Binary analog. Ledger: `residual_risk` none|placeholders_only. Offenes SD hat Residual-Other (Legacy). `collector/sanitizer.py` nicht anfassen.
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
