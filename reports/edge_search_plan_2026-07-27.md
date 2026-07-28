# Edge-Such-Programm — ernsthafte Verbreiterung (Plan für den Umsetzungs-Loop)

**Erstellt:** 2026-07-27 (Strategie/Fable) · **Umsetzung:** Opus-Loop, 1 Auftrag pro Iteration
**Warum jetzt:** Der einzige Kandidat (NO-Fade auf exact-Longshots) hat sich forward NICHT bestätigt (n=199, exact −1,13%) und der Gate-3-Regime-Guard hat **auto-pausiert** (14-Tage-Gap −0,017, Verzerrung wegarbitriert). Am selben Pferd weiterreiten bringt nichts. Wir müssen die Edge-Suche **systematisch verbreitern** — aber mit derselben Ehrlichkeit, die uns bisher vor Fehlsignalen bewahrt hat.

---

## METHODEN-GUARDRAILS (gelten für JEDEN Auftrag — nicht verhandelbar)

Diese Regeln verhindern, dass wir uns eine Edge einbilden. Jede Analyse MUSS sie einhalten:

1. **Walk-Forward, kein Look-ahead.** Selektionsregeln/Parameter NUR auf Train (< eingefrorenem Cutoff) definieren, genau EINMAL auf Test (OOS) evaluieren. Vorbild: `analytics/edge_salvage.py`.
2. **Echte Kosten, nicht 0,5c.** Der synthetische 0,5c-Half-Spread hat uns Edges vorgegaukelt; real gemessen ~3,6c avg / 3c median (`analytics/forward_reconciliation.json`). Default-Kosten = realistischer 2–3c, plus Kosten-Stress-Sweep. Wo möglich echten `clob_book`-Spread nutzen.
3. **Cluster-t (city|date), Schwelle t>2.** Korrelierte Buckets zählen einmal. Vorbild: `_simulate()` in `analytics/edge_research.py`.
4. **Multiple-Comparison-Ehrlichkeit.** JEDE getestete Hypothese wird geloggt. Benjamini-Hochberg über alle Tests. Ein einzelnes t>2 unter 20 Tests ist Rauschen, kein Fund.
5. **Regime-Transparenz.** Immer pro Monat/Regime ausweisen. Keine Edge, die an einem Monat hängt (Lehre aus Mai). Gate-3-Gap mitführen.
6. **Überlebende → Forward-Shadow, nie direkt Kapital.** Was OOS bei realen Kosten BH-korrigiert t>2 schafft, wird als Paper-Kohorte forward getrackt (Vorbild: exact+tight in `forward_reconciliation.py`). Gate 1/2/3 vor jedem Cent.
7. **Go-Live bleibt eingefroren. Keine `config/weather.yaml`-Änderung, kein Live-Trading ohne explizite User-Freigabe.** Der NO-Fade-Auto-Pause bleibt aktiv (er ist korrekt).
8. **Read-only Research.** Neue Analyse-Module ändern nie Thresholds/State. Fail-open. Schwere Scans laufen als eigener Task (täglich/on-demand), NICHT im 15-Min-Zyklus (Cycle muss <2 min bleiben).

---

## PHASE 1 — FUNDAMENT (zuerst; macht alle Edge-Zahlen vertrauenswürdig)

### F1 (P0) — Realistische Kosten als Default in allen Backtests
**Problem:** `edge_research.py` und `edge_salvage.py` melden Headline-Zahlen bei 0,5c Half-Spread. Real ~3c. Damit sind ALLE bisherigen +2,87%/+2,60% optimistisch verzerrt.
**Auftrag:** Kalibriere die Kosten an die gemessene reale Spread-Verteilung (aus `data/no_fade_shadow.jsonl`, Feld `real_spread`: median ~0,03). Setze in `edge_research`/`edge_salvage` den Default-`HALF_SPREAD` auf den realistischen Wert (bzw. rechne round-trip korrekt) und weise Headline IMMER bei realistischem UND optimistischem Kostenniveau aus. Ziel: die „wahre" Netto-Edge sehen, nicht die synthetische.
**Akzeptanz:** Beide Module zeigen Netto-Edge bei ~3c; jede Edge-Aussage nennt das Kostenniveau. Dokumentiere, welche bisherigen „Überlebenden" bei realen Kosten noch überleben (Erwartung: exact_only kippt, siehe 3c-Spalte in edge_salvage).

### F2 (P0) — Wiederverwendbares Edge-Scanner-Harness `analytics/edge_scanner.py`
**Problem:** Wir testen Hypothesen ad hoc; kein Schutz gegen Multiple-Comparison-Selbsttäuschung.
**Auftrag:** Generalisiere die Walk-Forward-Maschinerie aus `edge_salvage.py` zu einem read-only Harness, das eine Liste benannter Hypothesen (Selector-Funktionen + Side) entgegennimmt und für jede liefert: Train-Stats, OOS-Stats, Kosten-Stress, Cluster-t. Danach **Benjamini-Hochberg** über alle p-Werte (aus t via Näherung), Ausgabe eines Leaderboards `analytics/edge_scanner.md|json` mit Spalte „übersteht BH-Korrektur @ realen Kosten". JEDE je getestete Hypothese wird in einem persistenten Log `data/edge_hypotheses_log.jsonl` festgehalten (damit „wir haben 30 getestet" sichtbar bleibt). Reuse: `build_records`, `_simulate` aus `edge_research`.
**Akzeptanz:** `python -m analytics.edge_scanner` erzeugt Leaderboard; mind. die 5 Hypothesen aus Phase 2 laufen durch; BH-Korrektur sichtbar; Hypothesen-Log wächst.

---

## PHASE 2 — BREITE (neue Edge-Hypothesen, ALLE durch das F2-Harness)

### B1 (P1) — Beide Enden der Favorite-Longshot-Kurve
**Idee:** Longshot-Bias hat oft eine symmetrische Seite: Favoriten (P>0,80) werden UNTERbepreist. Die Kalibrierkurve in `edge_research.json` deutete positive no_fade_ev in 0,50–0,65 und 0,80–1,00 an (aber winziges n).
**Auftrag:** Model-free über die ganze Kurve: für jedes Preisband die echte YES-Rate vs Preis, und teste systematisch YES-Kauf auf starke Favoriten (P>0,80) bzw. NO auf das Komplement. Walk-Forward + reale Kosten via F2.
**Akzeptanz:** Leaderboard-Eintrag pro Band; klare Aussage, ob ein Band OOS bei realen Kosten t>2 schafft.

### B2 (P1) — Cross-Market-Arbitrage: ist sie nach Kosten erntbar?
**Idee:** `analytics/arbitrage_detector.py` findet Monotonie-Verletzungen (P(>30°C) > P(>25°C)). Bisher nur Detektion, keine Erntbarkeits-Quantifizierung.
**Auftrag:** Für erkannte inkonsistente Sets: simuliere den Arb-Trade (long die unterbepreiste, short die überbepreiste Seite) bis Resolution mit REALEN Kosten beider Beine. Wie oft, wie groß, netto nach Kosten? Das ist die einzige *modellunabhängige, regime-unabhängige* Edge-Klasse — höchste Priorität wenn sie trägt.
**Akzeptanz:** Report `analytics/arb_capturability.md`: n Gelegenheiten, Ø Magnitude, Netto-PnL nach realen Kosten, Cluster-t. Ehrliche Aussage erntbar ja/nein.

### B3 (P1) — Regime-getakteter NO-Fade (Auferstehung als Timing-Strategie?)
**Idee:** Der NO-Fade ist nicht tot, sondern regime-abhängig. Gate-3-Gap ist gerade negativ → pausiert. Aber als GETAKTETE Strategie (nur handeln wenn 14-Tage-Gap > Schwelle) könnte er netto positiv sein.
**Auftrag:** Backteste Regime-Switching: NO-Fade exact nur in Perioden mit rollendem Gap > τ (sweep τ auf Train, fix auf Test). Vergleiche gegen Always-On OOS. Reale Kosten.
**Akzeptanz:** Klare Aussage, ob Timing die Kosten schlägt und ob es Always-On OOS übertrifft.

### B4 (P2) — Konditionaler Modell-Skill-Scan (gibt es EINE Nische?)
**Idee:** Modell-Brier ≫ Markt-Brier global. Aber vielleicht schlägt das Modell den Markt in EINER Zelle (Stadt × Typ × Lead-Bucket × Saison).
**Auftrag:** Rastere (Stadt, Typ, Lead-Bucket, Monat) und finde Zellen mit Modell-Brier < Markt-Brier OOS bei n≥30. BH-korrigiert. Falls eine Nische existiert → erste echte Forecasting-Edge.
**Akzeptanz:** Liste der Zellen (falls vorhanden) mit OOS-Skill; ehrlich „keine" wenn keine BH-übersteht.

### B5 (P2) — Preis-Pfad-Momentum/Reversal (model-free)
**Idee:** Sagt die EIGENE Preisbewegung eines Marktes über die letzten N Stunden die Resolution über den aktuellen Preis hinaus voraus?
**Vorab-Check:** Verifiziere, dass `logs/weather_observations*.jsonl` mehrere Timestamps pro market_id enthält (nötig für Pfad). Falls nur ein Snapshot/Markt → Auftrag zurückstellen + Order-Book-Snapshotting nachrüsten.
**Auftrag:** Feature = Preisdrift letzte N h; teste ob Drift-Vorzeichen/Größe Resolution über Basispreis hinaus erklärt. Walk-Forward + reale Kosten.
**Akzeptanz:** Aussage ob Momentum/Reversal-Signal OOS trägt, oder klare Zurückstellung mit Grund.

---

## PHASE 3 — KONSOLIDIEREN

### C1 — Überlebende in Forward-Shadow überführen
Jede Hypothese, die OOS bei realen Kosten BH-korrigiert t>2 schafft, wird als eigene Paper-Kohorte in `forward_reconciliation.py` getrackt (wie exact+tight). Gate 1 (n≥150, ≥2 Monate), Gate 2 (reale Fills), Gate 3 (Regime) müssen frei sein, bevor Kapital überhaupt zur Debatte steht.

### C2 — `edge_status.md` als Kommandozentrale
Erweitere die „wo stehen wir"-Seite um das Scanner-Leaderboard (Top-Kandidaten, OOS-t bei realen Kosten, BH-Status, Forward-n). Eine Seite, die ehrlich sagt: haben wir Edge, ja/nein, und was ist der beste laufende Kandidat.

---

## Reihenfolge & Reuse
F1 → F2 zuerst (Fundament). Dann B1–B3 (höchste EV: model-/regime-robust), dann B4–B5. C1/C2 laufend.
**Wiederverwenden statt duplizieren:** `build_records`, `_simulate`, `_wilson`, `_taker_fee` (edge_research); `fetch_no_book_cost` (paper_trader/clob_book); `arbitrage_detector`; Kohorten-Muster (forward_reconciliation). Vor jedem neuen Modul kurz prüfen, was schon existiert (analytics/ ist voll).

## Erfolgsdefinition
„Edge haben" = mindestens EINE Hypothese, die (a) OOS bei realen ~3c-Kosten Cluster-t>2 schafft, (b) BH-korrigiert überlebt, (c) über ≥2 Kalendermonate/Regime hält, (d) danach forward als Paper-Kohorte bei realen Fills netto>0 bestätigt. Erst dann Gespräch über einen winzigen Live-Test. Bis dahin: weiter suchen, ehrlich bleiben, nichts riskieren.

---

## Loop-Journal
| Datum | Auftrag | Ergebnis | Commit |
|---|---|---|---|
| 2026-07-27 | F1 | ERLEDIGT — `analytics/cost_model.py` kalibriert sich aus 263 echten CLOB-Fills. **Plan-Annahme war FALSCH:** realistischer Half-Spread = **0,0051**, praktisch identisch mit dem alten 0,5c-Platzhalter (die 3,6c sind die volle Bid-Ask-Spanne; vom Mid zahlt man die Hälfte). Bisherige Backtests waren am Median NICHT geschönt. Aber Tail ist fett: p90-Premium 5,5c → Stress-Level 0,045. Ask-Tiefe Median 228 Shares (für Paper-Größen reichlich). | (siehe unten) |
| 2026-07-27 | F2 | ERLEDIGT — `analytics/edge_scanner.py`: Walk-Forward-Harness, exakte t-Verteilung (incomplete beta), Benjamini-Hochberg, 3 Kostenniveaus, persistentes Hypothesen-Log. **15 Hypothesen getestet, TEST n=1138: SURVIVORS = KEINE.** Höchstes t=0,86, alle q=1,0. Auch `no_fade_exact` ist tot (−0,04%, t=0,78) — der Juli-Regimewechsel hat den Kandidaten vom 14.07. kassiert. | |
| 2026-07-27 | B1 | ERLEDIGT (negativ, Datenmangel) — Favoriten-Seite praktisch untestbar: `yes_favorite_80_plus` hat **n=1**, `no_fade_05_10` n=0. Unser Universum enthält fast keine Märkte über P=0,80. Kein Signal, aber auch keine Widerlegung — die Hypothese braucht anderes Marktmaterial. | |
| 2026-07-27 | B3 | ERLEDIGT (negativ) — Regime-Timing rettet den NO-Fade nicht: `no_fade_regime_gap_02` +0,01% (t=0,64), `no_fade_exact_regime` +0,40% (t=0,74). Trailing-Gap ohne Look-ahead berechnet (nur bereits aufgelöste Märkte). | |
| 2026-07-27 | B2 | ERLEDIGT (negativ) + **BEINAHE-FEHLER GEFANGEN** — `analytics/arb_capturability.py`. Erste Version meldete +7,97%/Set: **Artefakt durch Look-ahead.** Filter „genau 1 Gewinner" konditioniert auf den Ausgang. Beweis: S skaliert mit beobachteten Gewinnern (0 YES → S=0,63 · 1 YES → S=0,92), **17,8% der Gruppen enthalten den Gewinner gar nicht** — wir sehen nur Teilmengen der Buckets, keine Partitionen. Ehrliche Rechnung (Auszahlung = tatsächlich gewinnende beobachtete Buckets, keine Outcome-Filterung): **−3,79%/Set, NICHT erntbar**; verzerrt wären es +8,18% gewesen. Metrik-basierte Gruppierung (high/low/precip) eliminierte überlappende Events (multi_winner 40→0). | |
| 2026-07-27 | F1-Folge | `edge_research.py` Kosten-Warnung korrigiert (sagte „synthetischer Platzhalter", ist jetzt gegen echte Fills validiert inkl. Tail-Hinweis). | |
| 2026-07-28 | B4 | ERLEDIGT (negativ) — `analytics/model_skill_scan.py`: konditionaler Modell-Skill-Scan über 58 Stadt×Typ-Zellen, gepaarte Brier-Differenz `d=(Markt_p−y)²−(Modell_p−y)²`, Walk-Forward (Kandidat nur wenn TRAIN>0, n≥30; einmal auf TEST), Cluster-t (city\|date), BH über getestete Zellen. **Global: Markt-Brier 0,152 vs Modell-Brier 0,167, Δ=−1,48%, Cluster-t=−6,03** (Markt entscheidend schärfer); OOS identisch (Δ=−1,63%, t=−4,03). **Nur 2 von 58 Zellen auf TRAIN positiv** (Seattle×between, Seoul×exact) — beide kippen auf TEST negativ. Selbst ohne Walk-Forward-Disziplin erreicht die beste TEST-Zelle (London×exact +0,77%) nur t=0,93. **SURVIVORS = KEINE.** Lead bewusst KEINE Zell-Dimension (Daten eng um 24h: p25=17h/p75=25h). Scan in `edge_routine` verdrahtet (Step + Digest-Zeile + Transition für künftige Nische). Forecaster ist auch konditional nicht überlegen. | (lokal) |

### Offen / nächste Aufträge
- **B2-Fortsetzung (aussichtsreichster Pfad):** Vollständigkeit lässt sich *vorab* prüfen, statt aus dem Ausgang — die Gamma-API liefert Events MIT vollständiger Marktliste (`/events?tag_slug=weather`, der Collector nutzt das bereits). Wenn wir pro Event alle Bucket-Markt-IDs persistieren, wird der Arbitrage-Test valide wiederholbar. **Das ist der einzige Kandidat, der modell- UND regime-unabhängig wäre.**
- ~~**B4** (konditionaler Modell-Skill-Scan)~~ **ERLEDIGT 2026-07-28, negativ** — keine Stadt×Typ-Nische mit Modell-Brier < Markt-Brier OOS. Nicht erneut aufrollen ohne neues Modell-/Datenmaterial (z.B. andere Ensemble-Features, längere Leads mit mehr Streuung).
- **B5** (Preis-Momentum) offen — vorher verifizieren, ob `logs/weather_observations*.jsonl` mehrere Snapshots je market_id enthält (nötig für Preis-Pfad).
- **Betrieb:** Die neuen Scans laufen bewusst NICHT im 15-Min-Zyklus (Guardrail 8). On-demand via `python -m analytics.edge_scanner` / `.arb_capturability` / `.cost_model`; ein täglicher Task wäre sinnvoll.
