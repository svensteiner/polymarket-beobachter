# Polymarket Beobachter — Agent-Memory

Eine Datei. Anweisungen + aktueller Stand. Bei Statusfragen zuerst diesen Block lesen, dann die Live-Dateien darunter.

Antworte auf Deutsch. Konkret. Paper-only. **Ziel ist Gewinn, nicht Wetter.**

## Pfad

`C:\Users\botrunner\projects\polymarket-beobachter`

Kein Polymarket-API-Key. Alles lokal. Pipeline alle 15 Min — nicht extra starten.

## Neustart (2026-09-12) — hat Vorrang vor dem historischen Stand

Nutzerauftrag: aufraeumen, neu starten, nachweisbare Netto-Edge finden. Hauptagent plant und nimmt ab; guenstige Worker implementieren klar begrenzte Pakete. Keine Gewinnzusage.

- Neuer Einstieg: `research_runner.py`, Forschungsbetrieb ohne Orders und ohne Aenderungen an Handelsbuechern. `start_bot.bat` / `DAUERLAUF.bat` verwenden diesen Einstieg; `SESSION.bat` einen einzelnen Abruf. Aktueller Prozess 21148 (Launcher 23520) am 2026-09-12 um 13:31 CEST gestartet, Intervall 900 Sekunden. Neben Marktinventar jetzt binaere Orderbuch-Kostenmessung und bedingte FDV-Implikationspruefung.
- Neue Module: `paper_trader/execution_cost.py` (Decimal, mengenabhaengige Ask-Fills, marktbezogene Gebuehren, Token-/Status-/Zeit-/Mindestmengenpruefungen) und `analytics/execution_scan.py` (20 rotierende binaere Maerkte, maximal 40 Book-Requests, 5 Anteile je Leg als hypothetische Probe in USDC). MIN_NET unveraendert 0.01 je Anteil. Kein tatsaechlicher Fill und kein Gewinn verbucht.
- Abnahme: 17 gezielte Tests und Code-Review bestanden. Echter Abruf: 300 Events, 485 binaere Maerkte. Korrigierte Version `binary_snapshot_v2` nimmt Bewertungszeit je Paar NACH den Antworten. Erster korrigierter Lauf: 20 bewertet, 9 gueltig, 11 Zeitstempel-Ablehnungen, 0 Kandidaten; alle 20 Ergebnisse exakt aus gespeicherten Snapshots reproduziert. Erster Dauerlauf danach: weitere 20 bewertet, 7 gueltig, 13 Zeitstempel-Ablehnungen, 0 Kandidaten, Cursor jetzt 60. Der fruehere unversionierte Testlauf verwendete faelschlich eine globale Bewertungszeit und ist kein Forward-Nachweis.
- SHA256 von Struct-Arb-Ledger, NO-Fade-Ledger und Kapitaldatei vor/nach neuen Messungen identisch. Doppelstart-Sperre bleibt aktiv. Logrotation 2 MiB plus ein Backup. Neueste Rohbuecher/Metadaten in `output/research_status.json`; letzte 200 Zyklusauswertungen mit Fill-Traces in `data/research_execution_history.jsonl`. Diese rollende Messhistorie allein ist kein langfristiger Forward-Test.
- Neue Statusquelle: `output/research_status.json`. `profit_proven=false`, bis ein separater Ausfuehrungs- und Forward-Test bestanden ist. Alte Wetter-/NO-Fade-Reports sind historische Evidenz, kein aktueller Erfolgsnachweis.
- Alter Bot: Pause in `bot_control.json` UND `logs/bot_control.json` gesetzt und durch `logs/heartbeat.json` am 2026-09-12 um 13:17:55 bestaetigt. Windows verweigert Stop des alten PID 14280 und Aenderung der geplanten Aufgaben. Die alte Edge-Routine und der alte Watchdog sind als erfolgreiche No-ops stillgelegt.
- Bereinigt: 727 advisory-only Zielwarnungen, 15 alte Prompt-/Reportdateien, 23 Dateien des unreferenzierten `agent/`-Stacks, 291 Cachedateien. Keine Markt-/Trade-Daten, keine `.env`, keine Git-Historie geloescht.
- `logs/dauerlauf_restart.log` (~3.5 GB) ist vom alten Prozess gesperrt; Loeschversuch erfolglos. Nach dessen regulaerem Ende entfernen. Keine weitere unbeschraenkte Warteausgabe im neuen Runner.
- Automatische Freigabepruefung blockierte Sammelbefehle zum Entfernen von Verzeichnissen (auch leerer Cache-/Agent-Verzeichnisse); Begruendung nur `blocked by policy`. Gepruefte einzelne Altdateien konnten entfernt werden. Leere Verzeichnisse bleiben deshalb teilweise bestehen.
- Forschungsbefund: letzter alter Struct-Arb-Scan 107 Maerkte, 11 Kandidaten, alle nach Kosten abgelehnt, 0 neue Entries. Alter Wetterpfad: -86.96 EUR. NO-Fade nicht robust OOS/ausfuehrbar.
- Technische Schulden: LEGACY-Struct-Arb verwendet weiterhin Best-Ask plus aggregierte Tiefe. Neue Kostenengine umgeht diese Schaetzung und beruecksichtigt Preisstufen/Gebuehren/Zeiten. Vor Paper-Entries fehlen noch zeitlicher Fill-Replay, Teilfuellungs-/Leg-Risiko, Kapitalbindung und ein langfristiges Forward-Protokoll. Positive Snapshot-Schaetzwerte sind kein Gewinnbeweis.
- Zusaetzliche Hypothesenprobe: 15 Gamma-Preisinversionen in FDV-/Bewertungsschwellen entdeckt. Sechs an echten Asks geprueft. Metamask YES >500M bzw. >700M + NO >1B zeigte brutto 1 Cent je Set, nach marktbezogener Gebuehr nur 0.00145 USDC fuer 5 Sets (vor Latenz/Leg-Risiko); Vollstaendige Beschreibungen tatsaechlich identisch; Schwellen stehen nur im Titel. Inzwischen enge Regelabnahme fuer Metamask/Hyperbeat, siehe unten. Kein Handelsauftrag, weit unter bestehender Schwelle. Andere gepruefte Paare groesstenteils schon am Ask negativ. Naechste Forschung: regelgleiche Implikationspaare systematisch gegen Books pruefen, nicht nur Gamma-Inversionen zaehlen.
- FDV-Erweiterung abgenommen (2026-09-12 13:31 CEST): `analytics/implication_scan.py`, `evaluate_buy_leg` und Runner-Integration. 29 gezielte Tests bestanden, separater Code-Review. Ausschliesslich vollstaendige auditierte Metamask-/Hyperbeat-Regeltexte nach Whitespace-Normalisierung, gleiche Entity/Event/EndDate/ResolutionSource, unterschiedliche Conditions/Tokens; keinerlei Zahlenersetzung in Beschreibungen. Lower-YES + Higher-NO ergibt nur eine BEDINGTE Modell-Auszahlung, keine garantierte Arbitrage (separate Oracle-Aufloesung/50-50/Klarstellungen und Leg-Ausfuehrung).
- FDV-Messung: 49 Regelpaare, 20 rotierende Paare / maximal 40 Book-Requests pro Zyklus. Vorab-Smoke 1 gueltige Bewertung, 0 Kandidaten. Erster gespeicherter Dauerlauf 0 gueltig, 18 Skew- und 2 Altersablehnungen: `insufficient_data`, Gesamtstatus `scan_partial`. Alle 20 gespeicherten Bewertungen/Ablehnungen aus Rohdaten nachvollzogen. Binaere Lane im selben Lauf 4 gueltig, 0 Kandidaten, Cursor 80. Keinerlei Gewinn-/Edge-Nachweis; Datenqualitaet begrenzt Aussagekraft. Schwellen bleiben unveraendert.
- FDV-Rohdaten/Regeln/Hashes in neuester `output/research_status.json`; `data/research_implication_history.jsonl` enthaelt maximal 200 kompakte Zyklen mit Bewertungsspuren, NICHT komplette historische Orderbuecher. Methodenversion `fdv_implication_v1`. Handelsbuecher und Kapital-SHA256 weiterhin unveraendert. Guenstige Worker implementierten; Hauptagent lehnte unzureichende Regel-/Fehlerbehandlung ab und korrigierte vor finaler Abnahme.
- Frische-Diagnose 2026-09-12: Prozess 21148 weiterhin aktiv, kein unnoetiger Neustart. Wiederholte REST-GETs, ein Batch-POST auf /books (nur Lesedaten) und WebSocket-Anfangssnapshots lieferten dieselben Book-Hashes/-Zeitstempel trotz aktueller kurzer Antworten. Ein alter Buchzeitstempel ist daher nicht mit hoher Transportlatenz gleichzusetzen; Empfangszeit allein beweist aber ebenfalls keine handelbare Frische. Bestehende Zeit-/Skew-Sperren unveraendert. Offizielle API: https://docs.polymarket.com/api-reference/wss/market und https://docs.polymarket.com/api-reference/market-data/get-order-book.
- Neuer separater, begrenzter Rohdaten-Probe `analytics/book_stream_probe.py` (nicht im 15-Min-Runner): maximal 30 Token, Dauer 1..300s, standardmaessig 2000 Frames/5 MiB; Socket-Timeouts/PING, atomare JSONL-Datei, Empfangszeit und monotone Laufzeit, originale Server-Zeitstempel. `websocket-client>=1.9.0` deklariert. 9 Probe-Tests und insgesamt 38 gezielte Tests bestanden, Code-Review ohne verbleibenden wesentlichen Befund. Kein Orderpfad. `complete` bedeutet abgeschlossene begrenzte Aufzeichnung mit allen Anfangssnapshots, NICHT lueckenlose Marktwahrheit oder Fill-/Profitnachweis.
- Echte Probe: 30.031 Sekunden, 11 Metamask-Token, 14 Frames = 11 Anfangsbuecher (ein Sammelframe), 11 price_change-Nachrichten mit 22 Preisstufenupdates fuer 6 Token, 2 PONG. 35009 Bytes, alle Sequenzen/Dateilaenge/Tokenabdeckung geprueft. Anfangs-Buchalter 1371..170420ms. Dateien `output/book_stream_probe_latest.jsonl`, `.jsonl.summary.json` und `output/book_stream_probe_contracts.json` (zugehoerige Gamma-/REST-Referenzmetadaten, Zeitpunkt der urspruenglichen Statusquelle vermerkt). SHA256 Rohcapture 429efc8715babf297689bb44e7c11f7e21a23fbadb2e03fe6016b62f2ef1059f. Keine Gewinnbewertung aus unsynchronisierten alten Buchzeiten abgeleitet.
- Naechste konkrete Abnahme: Preisstufen-Replay der aufgezeichneten book/price_change-Nachrichten, Abgleich mit gemeldeten Best-Bid/Ask, dann vorab definierte 250ms/1000ms Verzoegerung zwischen hypothetischen Legs und Kosten eines fehlgeschlagenen zweiten Legs. Erst danach ueber Frischemodell entscheiden. Handelsbuch-/Kapital-Hashes weiterhin identisch. Kein weiterer breiter Umbau allein fuer gruene Tests.
- Reihenfolge: schlanker Forschungsstart -> korrekte Ausfuehrungssimulation -> vorab festgelegter Forward-Test -> erst dann wirtschaftliche Entscheidung. Bestehende MIN_NET-/Other-/Live-Sperren bleiben erhalten; Legacy-SD-Position nicht automatisch schliessen.
- Neue OpenAI Agents API ist als Forschungs-/Entwicklungssteuerung vorgesehen, noch nicht integriert. Kein LLM im zeitkritischen Preis-/Risikopfad; API-Kosten gehoeren in die Wirtschaftlichkeitsrechnung.

## Historischer Stand (2026-08-24)

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
