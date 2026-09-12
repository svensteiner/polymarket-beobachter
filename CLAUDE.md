# Polymarket Beobachter — Agent-Memory

Eine Datei. Anweisungen + aktueller Stand. Bei Statusfragen zuerst diesen Block lesen, dann die Live-Dateien darunter.

Antworte auf Deutsch. Konkret. Paper-only. **Ziel ist Gewinn, nicht Wetter.**

## Pfad

`C:\Users\botrunner\projects\polymarket-beobachter`

Kein Polymarket-API-Key. Alles lokal. Pipeline alle 15 Min — nicht extra starten.

## Neustart (2026-09-12) — hat Vorrang vor dem historischen Stand

Nutzerauftrag: aufraeumen, neu starten, nachweisbare Netto-Edge finden. Hauptagent plant/nimmt ab; guenstige Worker implementieren begrenzte Pakete. Keine Gewinnzusage. Paper/research-only, keine Keys, echten Orders, Kapitalerhoehungen oder Schliessung der Legacy-SD-Position.

### Aktueller Betrieb

- `research_runner.py --interval 900`, PID 40984 / Launcher 18392, seit 2026-09-12 13:53 CEST. `start_bot.bat` / `DAUERLAUF.bat` starten diesen Runner; `SESSION.bat` einmalig. Single-instance-Sperre; Rotationslog 2 MiB plus Backup. Keine unnoetigen Neustarts bei 15-Min-Pausen.
- Status: `output/research_status.json`, Heartbeat `output/research_runner.heartbeat.json`, Log `logs/research_runner.log`. `profit_proven=false`, keine Orders oder Handelsbuchmutationen. Letzter abgenommener Lauf 13:53:28: Status ok, 292 Events, 20 binaere Buchpaare, 7 gueltige Zeit-/Kostenbewertungen, 0 Kandidaten; 0 FDV-Regelpaare in diesem Universe-Ausschnitt. Das beweist keine generelle Chancenlosigkeit.
- Discovery `analytics/market_universe.py`, Version `stratified_v1`: vier GETs mit je 75 Events (alte Basis, neueste, 24h-Umsatz, bald endend). Dedup/Provenienz/Fehlerbericht, maximal 300 unique, `universe_complete=false`. Alle Scanner erhalten dieselbe Eventliste; kein dreifacher Discovery-Abruf. Abweichende Duplikatversionen werden gezaehlt, erste Kopie bleibt erhalten.
- `analytics/execution_scan.py`, `binary_snapshot_v3_stratified`: 20 Paare / maximal 40 Book-Requests, aktuell 5 je Quellgruppe. Separate Quellcursor gegen Verdrangung/Starvation. Nicht unterstuetzte Outcome-Labels (z.B. Up/Down, Teamnamen) vor Book-GET abgelehnt und gezaehlt (letzter Lauf 1594). Das ist eine explizite Abdeckungsgrenze, keine Bewertung dieser Strategien.
- `paper_trader/execution_cost.py`: Decimal-Preislevel/Fills fuer hypothetische 5 Anteile je Leg, Gamma-Gebuehren, konservativ auf 5 Stellen aufgerundet. Token/Condition/Status/Mindestmenge/Tiefe/Zeit validiert; Alter <=30s, Skew <=5s. Bewertungszeit NACH den Antworten je Paar. `MIN_NET=0.01` je Set unveraendert. `evaluate_buy_leg` erfindet keine Auszahlung. Alte LEGACY-Struct-Arb-Best-Ask/Tiefenschaetzung nicht als neue Ausfuehrungsevidenz verwenden.
- 59 gezielte Forschungs-Tests bestanden, separater Code-Review; echte Smoke- und Dauerlaufmessungen abgenommen. Keine Lockerung von Other-/Live-/Zeit-/Mindestnetto-Sperren.

### Bisherige Evidenz und Entscheidungen

- Alter Wetter-YES-Pfad -86.96 EUR, eingefroren. NO-Fade OOS/ausfuehrbare Kosten unzureichend. Nicht reaktivieren. Historische Reports/alte Kandidaten sind keine aktuelle Erfolgsevidenz.
- Marktauswahlfehler belegt: jeweils 75 neue/bald endende Events fehlten vollstaendig im alten Default-300-Ausschnitt; 65/75 umsatzstarke ebenfalls. Neue Discovery behebt diese Verzerrung. Beleg `output/discovery_strata_probe.json`, Abnahme `output/stratified_acceptance_snapshot.json`.
- Fullset-Gegenprobe: 1000 Events, 481 NegRisk, davon 435 augmented. Sechs guenstige standard/nicht-augmented Sets mit 57 echten Books untersucht: Netto je Set Fed-Cuts -0.006212, OpenAI-IPO -0.020932, Starship -0.016046, Eurozone-Inflation -0.026860, China-GDP -0.012462, Brasilien-Inflation -0.024062. Nur statische Depth-Diagnose, nicht alle Legs zeitlich zulaessig; Fed-Cuts ausserdem 13 Legs ueber Legacy-MAX_LEGS=12. Kein Entry. Verkaufsscreen Republican-House-Sitze: Brutto-Bids 1.018, nach Gebuehren -0.017026 je Set. Belege `output/fullset_screen_latest.json` / `output/fullset_sell_screen_latest.json`, Discovery-Rohdaten `output/fullset_screen_input.json`. Kein Onchain-Vollstaendigkeits-/Mint-/Fillnachweis behauptet.
- FDV-Implikation `analytics/implication_scan.py`: nur vollstaendige auditierte Metamask-/Hyperbeat-Regeltexte (Whitespace-Normalisierung; keine Zahlenersetzung), gleiche Entity/Event/EndDate/ResolutionSource, verschiedene Conditions/Tokens. Lower-YES + Higher-NO nur BEDINGTE Modellauszahlung wegen separater Oracle-Aufloesung/50-50/Klarstellungen. Maximal20 Paare/40Requests, `fdv_implication_v1`. Bewiesene Regelgleichheit allein garantiert keinen Ertrag.
- Metamask >500M bzw. >700M YES + >1B NO: beste beobachtete Differenz nach Referenzgebuehren nur 0.00145 USDC fuer 5 Sets / 0.00029 je Set. 22 Paare x14 Empfangszustaende =308 wiederholte, NICHT unabhaengige Samples;0 ueber MIN_NET. Rueckverkauf bei hypothetisch gescheitertem zweiten Leg: -0.13942 (lowerYES zuerst) bzw. -0.10443 (higherNO zuerst). Bei250/1000ms keine intervenierende Nachricht, Kosten fortgeschrieben gleich. Wirtschaftlich abgelehnt. `output/book_stream_economics.json` mit Fill-Traces/Annahmen/Hashes.
- Frische-Diagnose: wiederholte REST/Batch/WS-Antworten mit identischen aelteren Book-Zeitstempeln/-Hashes trotz kurzer Antwortzeit. Empfangszeit und Buchzeit trennen; KEINE bestehende Frischesperre geloest. Offizielle Quellen: https://docs.polymarket.com/api-reference/wss/market , https://docs.polymarket.com/concepts/negative-risk , https://docs.polymarket.com/trading/fees .
- Separate begrenzte Rohaufzeichnung `analytics/book_stream_probe.py`, nicht im Dauerloop:1..300s, <=30Token, standard2000Frames/5MiB, originale Nachrichten/Empfangszeit/monotone Zeit, PING/Timeouts, atomareJSONL. Echte30.031s-Probe:11Anfangsbuecher,11price_change-Nachrichten/22Updates,2PONG,35009Bytes;Anfangsalter1.371..170.420s. Capture `output/book_stream_probe_latest.jsonl` + `.summary.json` + `output/book_stream_probe_contracts.json`; SHA256429efc8715babf297689bb44e7c11f7e21a23fbadb2e03fe6016b62f2ef1059f. Referenzgebuehrenmetadaten aelter als Capture, kein Echtfillbeleg.
- `analytics/book_stream_replay.py`: absolute Mengen, Null=Loeschung, Quellenreihenfolge/letzter BBO pro Frame, Fehler/Missing/Manifest sperren Simulation. 30/30 BBO-Vergleiche passen;7 nicht abonnierte Companion-Deltas ignoriert. `output/book_stream_replay_latest.json`. Interne Konsistenz ja, lueckenloser Feed/Execution/Gewinn nein. 13Replay- und9Probe-Tests enthalten in59Gesamttests.
- Neueste Scanner-Rohdaten in Statusdatei; `data/research_execution_history.jsonl` und `data/research_implication_history.jsonl` je maximal200 kompakte Zyklen. Keine komplette Langzeithistorie aller Orderbuecher, kein bestandener Forward-Test. Fruehe unversionierte binaere Smoke-Messung verwendete globale statt paarweiser Zeit und gilt nicht als Nachweis.

### BTC-TWAP Gegenprobe (2026-09-12, 14:00 CEST)

- Neue BTC-5m-Regeln und resolutionSource nennen Chainlink TWAP60s, nicht Spot. Korrektur: twapEnabled/Lookback-Flags fehlen in der gespeicherten Probe; fruehere Worker-Angabe dazu war nicht durch Rohdaten belegt. Quellen: https://docs.polymarket.com/market-data/chainlink-twap und https://docs.chain.link/data-streams/how-report-timestamps-work . Rollendes Lookback ist keine 5-Min-Kerze; genaue Settlement-Auswahl an Grenzen in geprueften Quellen nicht belegt. Kein Richtungssignal aus vermuteter Semantik.
- Public RTDS funktioniert ohne Credentials. Leerer TEXT-Frame ist beobachtete ACK, kein Close. Entgegen Dokumentation folgte bei Probe ein subscribe-Backfill mit59 Samples; diese waren erst ab Empfang bekannt, kein historischer Tradability-Beleg. Rohdaten output/twap_reference_probe.jsonl, Regeln output/twap_rule_probe.json.
- Separate begrenzte Boundary-Aufzeichnung output/twap_boundary_1200.jsonl: Beobachtung12:00:00UTC mit exaktem E18-Wert77338.862239471026307072 erst12:00:01.322UTC empfangen. Nicht als bestaetigter Settlement-Startpreis verwenden, solange Regelzuordnung fehlt.
- Zwei reale BTC-Buchpaare vor Boundary: 5Anteile proLeg, Tiefe vorhanden, Books55..74ms alt. Hypothetisches Vollset-Netto nach Rate0.07: -0.022034 und -0.044994 USDC/Set. Kein Buy-both-Edge. Belege output/twap_boundary_books.json und output/twap_boundary_costs.json. Keine Orders/LLM-Aufrufe/Produktionsaenderung. Naechster sinnvoller Test: vorab registrierter Richtungsvergleich mit bestaetigter Anchor-/Settlement-Zuordnung und parallel aufgezeichneten ausfuehrbaren Buechern; Feedlatenz allein reicht nicht.

- Follow-up12:02UTC: Drei abgeschlossene BTC5m-Maerkte (11:40,11:45,11:50) liefern eventMetadata.priceToBeat/finalPrice, jeweils naechster Start exakt vorheriges Ende auf Anzeige-Praezision; Preise1/0 und UMA resolved. Beleg output/twap_prior_resolutions.json. Markt11:55 liefert bislang nur Start77340.04751252416, noch closed=false/kein finalPrice. Vor Bekanntgabe des Ergebnisses in output/twap_semantics_preregister.json festgehalten: erwartetes Down und finalPrice~77338.862239471026307072 aus live empfangenem12:00-TWAP. Start erst nach Ende abgerufen: ausdruecklich NUR Referenz-/Semantiktest, kein handelbarer Backtest. Spaeter mit tatsaechlicher Aufloesung vergleichen; fehlende Samples/Rundungsgrenzen bleiben ungeklaert. Letzte API-Evidenz output/twap_1155_resolution_followup.json.

- Semantiktest jetzt bestanden fuer EINEN Markt: 11:55-Markt closed=true, UMA resolved, Down[0,1], veroeffentlichtes finalPrice77338.86223947103 entspricht live12:00-TWAP bis Anzeige-Praezision (Differenz3.692928e-12). output/twap_semantics_result.json / output/twap_two_resolution_latest.json. Kein allgemeiner Rundungs-/Gapnachweis und kein Trade.
- Neuer prospektiv festgelegter BTC12:00..12:05-Diagnosetest: output/twap_1205_preregister.json vor beiden Offsets(-30s,-10s) angelegt, Signal letzte rechtzeitig empfangene TWAP vs beobachtetem12:00-Anchor, 250ms Latenzszenario/5Shares. RTDS155s/153Frames abgeschlossen. Erstes CLOB-Capture erreichte10000Frames nach30s (nicht ausreichend); zweite Aufnahme75s/5319Frames/4.95MB complete=true umfasst beide Termine. output/twap_1205_books_decisions.jsonl und output/twap_1205_reference.jsonl.
- Beide Richtungssignale Down, aber Szenarien INVALID: Replay12 BBO-Abweichungen und keine Down-Asks. Rohfeed an Terminen selbst best_bid0.99/best_ask1, Seq2744/4313; kein positiver Fill erfunden. output/twap_1205_diagnostic.json: P&L/Break-even explizit null. Guenstiger Worker prueft Ursprung der BBO-Abweichungen; vor50-Markt-Forward-Test Feedkonsistenz und verfuegbaren Anchor bestaetigen. Noch kein neuer Produktionscode.

- BBO-Audit abgeschlossen:12Abweichungen aus6Paaren konsekutiver Frames (Seq20/21,97/98,344/345,610/611,1434/1435,1901/1902), Empfangsabstand0..1ms, gleicher jeToken-Hash und nachfolgende Loeschung erklaeren temporaeren Zwischenzustand. Bestehender Replay prueft korrekt pro Frame nach allen darin enthaltenen Aenderungen. KEINE dokumentierte Atomaritaet ueberFrames behaupten, spaetere Daten nicht rueckdatieren; bestehendes Gate unveraendert. Beleg output/twap_bbo_transition_audit.json.
- Frueherer Einstieg nur explorative Hypothese: erste Aufnahme~98s vorEnde DownAsk0.79, zweite~48s vorEnde0.98, anvorregistrierten30/10s keineAsks. output/twap_earlier_entry_feasibility.json trennt rechtzeitig empfangene Referenz von spaeterer Auswahl. Keine zeitliche Optimierung auf diesem einen Fenster als Edge werten. Naechste Pruefung muss vorher festen frueheren Zeitpunkt und unabhaengige Fenster definieren; kein50-Markt-Lauf gestartet.

### Begrenzter Forward-Pilot (abgenommen und gestartet)

- Separater read-only Recorder analytics/twap_forward.py: Worker-Entwurf hatte kritische Timing-/Schemafehler; Hauptagent korrigierte Runtime, Worker erweiterte Gegenproben, unabhaengiger Abschlussreview ohne kritische Befunde. 18 neue Tests +59 bisherige=77passed. Echter gespeicherter RTDS-Feed offline korrekt geparst. Ein bis maximal3 ZUKUENFTIGE aufeinanderfolgende BTC5m-Fenster, keine Veraenderung am Dauerloop/Orderpfad.
- Metadaten20s vor Entscheidung, danach kurze RTDS-Aufnahme bis Entscheidung (max40s), keine gesamte Fensterhistorie. Vor Start feste90s-vorEnde-Entscheidung, q5, 250ms Mindestverzoegerung vor parallelem REST-Abruf beider Books; tatsaechliche Request-/Empfangszeiten zaehlen, keine behauptete250ms-Filllatenz. REST vermeidet unbelegte atomare WS-Framezusammenfassung.
- Preisanker MUSS aus vor Entscheidung empfangenem eventMetadata.priceToBeat stammen. Fehlender Anchor/verspaetete Metadaten/Tie/fehlender oder >5s alter LIVE-TWAP/ungueltige Books fuehren zu protokolliertemSkip; Backfill niemals rueckdatieren. Bookalter<=30s/Skew<=5s unveraendert, echtesOrderminimum/Tiefe/Gebuehren. Keine P&L vor bestaetigterAufloesung, keine Fills behaupten.
- Pilot prueft Datenverfuegbarkeit und Kostenrechnung; erst danach vorregistrierte unabhaengige groessere Stichprobe. Wiederholte Zeitpunkte desselben Markts zaehlen nicht als unabhaengige Erfolge. Keine Schwellenoptimierung auf bisherigen Einzelbeispielen.
- Dauerloop12:08:33UTC bestaetigt:293Events,20Paare,4gueltigeBewertungen,0Kandidaten,keineRequestfehler. Kein Profitnachweis.

- ERSTER PILOT BEENDET (exit0): PID12672, exec session56108, gestartet mit --start-epoch1789215600 --windows1 --output output/twap_forward_pilot_1220. Registrierung1789215469329ms liegt vor Fenster12:20..12:25UTC; Entscheidung12:23:30UTC, Metadaten12:23:10UTC. Prozess perWin32_Process livebestaetigt. Nichtduplizieren/restartenwegenWarten. Ergebnis erwartet output/twap_forward_pilot_1220/window_1.json nachEntscheidung+REST. NormalerDauerloopunveraendert.
- Noch keinForwardgewinn/Settlement-Auswertung/Pilot-Ergebnis. NACHProzessende Ergebnis/Skip undtatsaechlicheZeitenpruefen, spaetereAufloesung separatabgleichen. EinPilot istkeinEdgebeweis.

- Zweiter Referenzvergleich12:05 jetzt resolvedDown[0,1]: finalPrice77333.78911327518 stimmt zum gespeicherten TWAP-Endwert77333.789113275182481408 (Differenz-2.481408e-12). Beide geprueften Endpunkte passen auf Anzeigepraezision; weiterhin kein universellerMissing-Sample-/Rundungsnachweis. output/twap_1205_resolution_latest.json. Vorregistrierte30/10s-Szenarien bleiben wegen fehlenderDown-Asks ohneTrade/P&L, trotz richtigerRichtung.
- Pilot12672/session56108 um12:18:30UTC erneutlivebestaetigt, wartet planmaessig bis Metadaten12:23:10UTC. KeinNeustart.

- Pilot12:20..12:25 beendet: skip_missing_anchor, eventMetadata.priceToBeat im vor Entscheidung empfangenenEvent FEHLT. Capture20Frames/18LiveUpdates ohneFehler; beide REST-Anfragen252/253ms nachEntscheidung, Antworten378/383ms danach. output/twap_forward_pilot_1220/window_1.json +acceptance.json. KeinTrade/PNL; kein groessererForward-Lauf bevor Startpreisquelle rechtzeitig belegt. NaechsterkonkreterSchritt: veroeffentlichte Startpreisquelle/Cacheverhalten ermitteln, ohne spaetere Daten rueckzudatieren oder Testgate zu lockern.

### Public-Anchor-Fallback und zweiter Pilot

- Nach erstem missing_anchor-Pilot oeffentlicheEventseite geprueft: SSR QueryKey exakt [crypto-prices,price,BTC,startISO,fiveminute,endISO,true,60] enthaelt data.openPrice. Reale Probe12:26:23UTC lieferte77300.33740458488 fuer12:25..12:30, vorEntscheidung12:28:30; Gamma gleichzeitigeventMetadata=null. Belege output/twap_public_anchor_refresh.html/.json, output/twap_public_anchor_verified.json. Gamma-Gegenprobe12:33UTC bestaetigt denselben Startpreis77300.33740458488 exakt; Ereignisclosed=true. Beleg output/twap_public_anchor_gamma_comparison.json. Damit ein rechtzeitig erfasster PublicAnchor spaeter durchGamma bestaetigt, noch kein allgemeinerEdgebeweis.
- Cache-Control public,s-maxage60,stale-while-revalidate3600; erstevorMarktstarterzeugteSeite hatteKEINpassendesQuery. KeineWertannahme beiCachemiss. Parser analytics/twap_anchor.py: exacttypisierteQuery/singlematch,positiveDecimal,updated>=start<=receipt,receipt<=decision; HTML3MiB/global200000Nodes/Recursionfailclosed. ReactFlightChunksjoin, bytegenaueT-Length-Records ueberspringen, nurstrukturierteJSONRows; nieplainTextalsQuery/eval.
- Workerentwurf understeAbnahme enthieltenFramingluecke; Hauptagent korrigierte anhand echterHTML. FrischerRealSmoke mitAKTUELLEMCode +separaterReview bestanden. Gesamt88Tests. twap_forward.py v2_public_anchor nutztFallbackNURwennGammaAnchorfehlt; speichertHTML/Cacheheader/Request-/Receiptdaten/ausgewaehlteQuelle. KeineOrders/P&Lbehauptung.
- ZWEITER PILOT BEENDET exit0: PythonPID50968, execsession64312. Start1789216500=12:35UTC,1Fensterbis12:40UTC,Entscheidung12:38:30UTC,Metadaten12:38:10UTC. output/twap_forward_pilot_1235/preregister.json registriert1789216235382 vorStart, Versionbtc5m_twap_forward_v2_public_anchor. LiveProzessbestaetigt. Aufwindow_1.json warten, nichtduplizieren/restarten. ErstesPilotsession56108 istbeendet.

- ZweiterPilot1235 erfolgreich: Up-Signal, PublicAnchor77315.95365271563, TWAP77319.749438263353409536 beobachtet12:38:28/empfangen12:38:29.737UTC. UpAsk0.85, q5, Fee0.04463, Gesamt4.29463 (unabhaengignachgerechnet); Breakeven0.858926, kein Wahrscheinlichkeitsschaetzer. Books67/60ms alt, Requests+252ms, Antworten+376/396ms. ConditionalP&LUp+0.70537/Down-4.29463, ErgebnisNOCHOFFEN, KEINEechtenFills. output/twap_forward_pilot_1235/window_1.json +acceptance.json, SHA85af4acf0ac93bb77d2bb67e7ec745de4110e38a17f592a7af2f83250bacc283.
- DREIFENSTER-PILOT AKTIV: PID41012, execsession81026. Registrierung1789216748255 vorStart1789216800(12:40UTC),--windows3, unveraendertesv2-Protokoll90svorEnde/q5. output/twap_forward_pilot_1240_three. Entscheidungen12:43:30,12:48:30,12:53:30UTC, Fensterenden12:45/50/55. Prozesslivebestaetigt. KeinNeustart/Duplikat. Vor Kenntnis1235Aufloesung registriert, keineOptimierungnachEinzelergebnis.

### OpenAI-Agenten-API: gepruefter Integrationspunkt

- Offizielle aktuelle API-Doku bestaetigt client.beta.agents.create / POST /agents, wiederverwendbare projektbezogene Agents sowie multi_agent.enabled/max_concurrent_subagents und expliziteTools: https://developers.openai.com/api/reference/typescript/resources/beta/subresources/agents/methods/create . Das ist tatsaechlich eine AgentsAPI, nicht nur das aeltere AgentsSDK.
- Architekturentscheidung fuer spaetere Integration: Forschungsauftraege/Quellenbelege/Versuchsauswertung koordinieren, begrenzte read-only Funktionen fuer Messstatus/Experimente. Deterministische Kosten-/Zeit-/Risikogates entscheiden weiterhin. Keine Order-/Key-/Kapitaltools an Agenten. Hauptagent gibt Experiment vor und nimmt Evidenz ab; guenstige Worker liefern begrenzte Arbeitspakete.
- SDK/Accountzugang/Modellpreise noch nicht verifiziert, keine API-Keys gelesen, keine bezahlten Aufrufe/Registrierungen gestartet. Integration weiterhin offen; kein Gewinnvorteil allein durch API-Wechsel behauptet.

### Schutz, Aufraeumrest und naechste Abnahme

- Handelsbuch-/Kapital-SHA256 seit Neustart unveraendert: struct_arb.jsonl 56843b7c732dd33cf3e41434216227b6d1393a537f9026aff7076af30cfde6dd; no_fade_harvest.jsonl d09fffeeb957c68560a8b7a6804a5211417dfb36ac944b9cf2c05a9dc595f48f; capital_config.json e6dee7666219736005d37ff2e811f9e71dbb741fd2a72f6fbb7b56bc2576076f.
- Alter Bot PID14280 pausiert via bot_control.json UND logs/bot_control.json; letzte Pause bestaetigt13:17:55. Windows verweigerte Stop/Taskaenderung. Alter edge_routine.bat/watchdog.ps1 erfolgreiche No-ops. Gesperrtes altes logs/dauerlauf_restart.log (~3.5GB) nach regulaerem Prozessende entfernen.
- Entfernt:727 advisory-only Zielwarnungen,15 alte Prompt/Reports,23 ungenutzte agent-Stack-Dateien,291Caches. Keine Markt-/Trade-Daten, .env oder Git-Historie geloescht. Automatische Freigabepruefung blockierte Sammel-Verzeichnisloeschungen mit lediglich 'blocked by policy'; einige leere Verzeichnisse bleiben.
- Naechste Forschung: neue groessere Netto-Ueberschuesse im breiteren Universe; keine weitere Optimierung der abgelehnten Metamask-Minidifferenz. Vor Paper-Entries fehlen belastbare Fill-/Teilfill-/Leg-Ausfuehrung, Kapitalbindung und vorab definierter langfristiger Forward-Test. Neue OpenAI Agents API als Forschungssteuerung weiterhin NICHT integriert; keine bezahlten Runtime-LLM-Aufrufe, kein LLM im Preis-/Risikopfad. Entwicklung an guenstige Worker, Abnahme durch Hauptagent.

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

2026-09-12 12:44:42UTC: Pilot1235 jetzt offiziell closed=true/UMA resolved Up[1,0], Condition exakt gegen vorab gespeicherte Metadaten abgeglichen. Hypothetischer Nettoertrag bei angezeigter Tiefe +0.70537 USDC (5 Auszahlung minus4.29463 Kosten), keine realen Fills und kein Edgebeweis. Beleg output/twap_forward_pilot_1235/settlement.json. DreierpilotPID41012 weiterhin live; erstes Fenster1240 erfasst Up, Kosten3.57350 fuer5Shares, Ergebnis noch offen. Weitere Entscheidungen12:48:30/12:53:30UTC unveraendert.

2026-09-12 12:49UTC: Dreierpilot Fenster1240 offiziell resolvedDown[0,1]; vorregistriertesUp verliert hypothetisch3.57350USDC, Condition/Tokens gegen vorabMetadaten identisch. settlement_1.json gespeichert. Zusammen mit1235(+0.70537) bisher -2.86813USDC fuer2aufgeloeste Richtungsdiagnosen, keine echtenFills. Fenster1245 UpAsk0.99/Kosten4.95347, maxGewinn0.04653, noch offen. DrittesFenster unveraendert bisEntscheidung12:53:30; PID41012 live. Keine Schwellenoptimierung anhandVerlust.

2026-09-12 12:53:30UTC: DreierpilotPID41012/session81026 beendet exit0, alle3windowJSON vorhanden/result.ok=true. DrittesFenster1250 DownAsk0.999/Kosten4.99535 fuer5Shares, maximal+0.00465USDC, Settlement offen. Zusammen mit zweitemFenster maximal+0.05118; bisheraufgeloest-2.86813 bedeutet Gesamt4Diagnosen selbst bei beidenSiegen hoechstens-2.81695USDC. KeineEdge/keineechtenFills. Nichtmehrsession81026 pollen, terminal. NaechsterSchritt: fehlendeAufloesungen1245/1250 abgleichen und Pilot abschliessend technisch/wirtschaftlich abnehmen.

Forschungsstand nachTWAPPilot: settlement_2.json bestaetigt1245Up+0.04653; bisher3aufgeloesteDiagnosen-2.82160, letztes1250nochAufloesungoffen. Dreieracceptance.json speichertSHA/Zeitdaten/unabhaengigeKosten aller3, alleok. NaiverTWAP-Pfad wirtschaftlich nichtfreigegeben. Neues read-only LP-Reward-Screening: output/liquidity_rewards_initial_probe.json (/multi,100Rows9Configs), liquidity_rewards_three_books.json (Xi/Newsom/AOC,6Books), liquidity_rewards_current_probe.json (/current,500Rows,nextNTAw). NochkeinevollstaendigePagination/Ertragsschaetzung. AktuelleAsset0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB vsMulti0x2791... ungeklaert; WorkerprueftoffizielleDenomination. Pool istNICHTeigenerErtrag, komplementaereBooks nichtdoppeltzaehlen, Mindestgroesse200in3Beispielen. MakerRebates getrennt; QuoteQ istkeinTagesumsatzlimit. KeinneuerCode/Orders/APIKeys/paidLLM.

LP-Followup: offizielle https://docs.polymarket.com/resources/contracts ordnetC011... pUSDCollateralProxyzu. Samecondition raw/current in liquidity_rewards_same_condition.json gleicheRate7/Start/min20/max5.5, aberraw2791/id1490227 gegenCurrentC011/id0. Ursacheungeklaert, aktuelleRatenexplizitpUSD. BegrenztePagination8Seiten4000Records endetnochNICHT,nextNDAwMA==; output/liquidity_rewards_current_pages.json, keinvollstaendigerUniverse. Selectedcurrent.json bestaetigtNewsom47pUSD/day,min200,max5.5;Xi/AOCinAusschnittnichtgefunden=keineAussageueberAbwesenheit. KeinePoolanteils-/Netto-/Fillprognose.

TWAP FINAL: directGamma1250 jetztclosedtrue/UMAresolvedDown[0,1], Condition/Tokens identisch. settlement_3.json +0.00465hypothetisch. Alle4 gueltigenDiagnosenaufgeloest: +0.70537 -3.57350 +0.04653 +0.00465 = -2.81695Collateral-Einheiten nachmodelliertenGebuehren. KeineechtenFills. FruehereUSDC-Bezeichnung nichtalsgepruefteAuszahlungswaehrungwerten(pUSDMigration); Zahlenrechnunggleich, auszahlbaresUSDCnichtbelegt. NaiverRichtungsansatznichtausbauen. LPBooks enthaltenproLevelnurprice/size, keineOrderIDs/Owner; Orderqualifikation undWalletScore ausAggregaten unidentifiziert.

LP-Mathreview: offizielleVollformel in output/liquidity_rewards_official.md vorhanden (programs/liquidity-rewards.md); fruehereWorker-AussagefehlendeFormelfalsch. Mid[.1,.9],c3: f(a,b)=max(min(a,b),a/3,b/3), (a+b)/4<=f<=(a+b)/2. BeiBEKANNTENeligibleKonkurrenzscoresTc daher eigenerSampleanteil f/(f+Tc/2)..f/(f+Tc/4), keinTagesertrag. ActualTc/Einzelorderqualifikation/adjustedMidunbekannt; keinbelastbarerPunktertrag. own_quote_illustration.json nurbedingteRechnungmitANGENOMMENEMrawMid. NewsomNoTopbid99.01<200; eigene200QuoteveraendertTiefe, Midnichtungeprueftfixieren. KeineOrders.

Agenten-Kostenentscheidung: cost-aware-llm-pipelineSkillgelesen; dessenBeispielmodelle/PreiseNICHTalsaktuelleOpenAIReferenzuebernehmen. Dauerforschung96Zyklen/Tag=2880/30Tage. EinLLMCallproZyklusmit2000Input+300Outputkostetmonatlich5.76*InputpreisProM+0.864*OutputpreisProM, zuzueglichTools/Retry/Cacheabweichung; reineSensitivitaetkeinePreisbehauptung. Forschungssteuerung nurereignisgetrieben beiNEUEMgueltigemKandidaten/Fehler/Experimentabschluss; keinLLMproPolling, keinLLMPreis/Risikoentscheid. VorjedemAufrufWorstCaseKosteninklmaxOutput/Tools/Versuchenreservieren, nichtnurNachherSaldo. GesamtAPIbudgetbisexplizitgesetzt0; LaufzeitweiterohnepaidCalls. SkillbudgetcheckvorCallohneReservewaereueberschreitbar, nichtblinduebernehmen. WirtschaftlicherRahmenKapital/Verlustgrenze/Monatsnetto asynchronangefragt, keineAntwortbisher.

AutonomerZiel-Lauf wartetaufNutzereingabe: wirtschaftlicherRahmen seitmehrerenZielrundenoffen (Handelskapital,maxGesamtverlust,Monatsnettoziel; APIbudgetseparat). AllebeauftragtenPilotenbeendet/abgerechnet; keinabgenommenerEdge, LP-Ertragsanteilnichtidentifiziert. KeineweiterenVersucheoderEchtgeldschritteohnefestgelegtenRahmen. Vorhandenerread-onlyRunner40984bleibtaktiv undunveraendert. ZielNICHTerreicht; notwendigeFortsetzungnachAntwortStrategieauswahlmitexplizitenKosten/Risikokriterien, keineGewinnzusage.

AgenticAPISetup: isoliert.venv-agentic installiertopenai3.13.0; beta.agents.create/sessions.create lokalvorhanden, global2.21.0 unveraendert. .gitignoreergaenzt. KeineCredentials/APIRequests. SDK-SessionschemaohnehartesmaxOutput/SessionBudget; lokaleReservealleinGARANTIERTKEINEKostengrenze. WorkerbehauptunglokalesGategenuegezurhartenBegrenzungzurueckgewiesen. IntegrationnochNICHTaktiv/implementiert. NutzerwillmehrAgenticDelegation+Tokeneffizienz, noPollingLLM. NaechsterSchrittminimalofflineprepare/read-onlyadapter, paidSessionerstbeiBudgetentscheidungmittransparentnichtgarantiertemSessionmaximum.

HostedAgentAdapter implementiert analytics/research_coordinator.py plus11Tests(test_research_coordinator.py), Hauptagent11passed+echterStatusOfflineCLI. --modelerforderlich; offline-schema-checkwarNURPlatzhalterkeineModellverfuegbarkeitsbehauptung. StrikteCounterAllowlist,max2MiBboundedread; StandardCLInurRequestplan. dispatch(client_factory,..) GatesexaktTrue+positiveintadmission_budget,nurZulassungKEINHardCostCap; max_retries0, agents.create dannsessions.create(agent_id), inputstring/environmentnone/toolsempty/multiagentfalse SDK3.13durchReviewbestaetigt. KeinRunnerHook/AutoResearch/SessionresultPersistence/RealSmoke; keineCredentials/paidCalls. VoraktivierungguenstigesAccountModell+Preis+Budget/AkzeptanzfehlenderhartSessiongrenzeoffen. NutzerTokeneffizienz: Workerimplementieren, MainAbnahme, keineMinutenPollingLLMs.

Nutzerfreigabe:5EUR fuererstenAPItest. EinHostedAgent+eineSessionmitgpt-5.6-luna,keineTools/Subagents/Retry; gleicherSessionretrieve finalidle/errornull. output/agentic_smoke.json enthaeltIDs/usage6074input+5output=6079. Preisrechnung0.0012208USD bei0.20/1.20proM; keinebestaetigteRechnung/EURConversion. KeinautomatischerDauerbetriebfreigegeben. SessionretrieveliefertkeinenAntworttext; funktionaleResearchabnahmebrauchtnochOutputviaEvents. BudgetrestnichtausSchaetzungalsgarantiertdeklarieren.

Produktionshaertung: setup_research.ps1 erstellt.venv-research(stdlibScanner), erfolgreichvonfremdemcwdgeprueft; requirements-agentic.txt pinopenai3.13.0 separat. research_supervisor.py begrenztchild--once300s, OSsingleton, wallclockFrische/monotonicTimeout, terminate/killnurEigenchild, backoff/durableStatus. 41Tests(Supervisor10+Runner6+CoordinatorStore25)passed. AlterScanner40984+Wrapper18392identitaetsgeprueftbeendet. Supervisorjetzt51172venvlauncher/53672actualPython, ersterrealScanhealthy lastsuccess1789227381.1567476 nextdue1789228281.1567476; output/research_supervisor.json. NochkeinevollstaendigeProduktionsfreigabe: Coordinatorreview verlangtTurnIDMatching/einTurntotal, Workerfixlaeuft; keinpaidneuerRun.
