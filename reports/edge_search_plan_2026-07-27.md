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
| | | | |
