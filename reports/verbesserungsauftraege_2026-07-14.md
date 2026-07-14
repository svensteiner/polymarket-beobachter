# Verbesserungsaufträge für den Implementierungs-Loop (Opus 4.8)

**Erstellt:** 2026-07-14 (Strategie-Review, Fable)
**Ziel:** Edge beweisen (Gate 1–3 in `analytics/edge_status.md`), dafür zuerst die Datenversorgung reparieren.
**Arbeitsregeln (gelten für jede Iteration):**

- Genau EIN Auftrag pro Iteration, klein und reversibel (siehe `agent/project/workflows/edge_stability_loop.md`).
- Nach jeder Änderung verifizieren: `python cockpit.py --run-once --no-color`.
- Ergebnis unten im Abschnitt "Loop-Journal" dokumentieren (Datum, Auftrag, Ergebnis, Commit).
- KEINE Änderungen an `config/weather.yaml`-Parametern ohne User-Freigabe. KEIN Live-Trading. Keine destruktiven Git-Operationen.
- Commits mit Prefix `fix:`/`feat:`/`perf:`.

---

## A1 (P0) — Collector-422 fixen: Gamma-API-Offset-Cap ✅ ERLEDIGT (2026-07-14, siehe Loop-Journal)

**Symptom:** Seit 2026-07-11 07:20 schlägt JEDER Pipeline-Run fehl: `collector: Client error: 422 Unprocessable Entity`, `Markets fetched: 0`. Über 300 Runs ohne Marktdaten.

**Root Cause (verifiziert am 2026-07-14 per curl):**
Die Gamma-API hat ein Offset-Limit eingeführt. `GET /events?limit=100&offset=2100&tag_slug=weather` →
`422 {"type":"validation error","error":"offset too large, use /events/keyset for deeper pagination"}`.
`collector/client.py::fetch_weather_markets()` paginiert mit `closed=None` durch ALLE historischen Weather-Events (2000+), läuft in den Cap, und die Exception aus `_request()` (Zeile 397: 4xx → sofortiger `RuntimeError`) vernichtet den gesamten Fetch — auch die bereits geladenen ~2100 Events.

**Fix (drei Teile, alle in `collector/client.py`):**

1. **`closed=false` an die API übergeben:** In `fetch_weather_markets()` beim Aufruf von `fetch_events(...)` `closed=False` statt `closed=None` setzen (der Collector will ohnehin nur offene Märkte, `include_closed=False`; das clientseitige Nachfiltern bleibt als Sicherheitsnetz). Damit schrumpft die Seitenzahl auf wenige Pages und der Cap wird nie erreicht.
2. **Fail-open bei Paginierungsfehlern:** Die `while`-Schleife pro Tag in ein `try/except` fassen: Fehler mitten in der Paginierung → `logger.warning` + `break` (bereits gesammelte Märkte zurückgeben), NICHT die Exception propagieren. Ein Teilergebnis ist besser als 0 Märkte.
3. **Harte Offset-Grenze:** Zusätzlich `offset >= 2000` → `break` (defensiv, falls der Cap wieder sinkt). Optional später: `/events/keyset` für tiefe Paginierung — für Weather-only nicht nötig.

**Akzeptanz:** `python cockpit.py --run-once --no-color` → `Markets fetched > 0`, `Weather candidates > 0`, collector-Step OK, kein 422 in `logs/observer.log` für diesen Run.

---

## A2 (P1) — Zombie-Snapshot-Retries tombstonen

**Symptom:** `logs/snapshot_errors.log`: market_ids `2887877`, `2877738` (vorher auch `2867172`, `2867104`) werden seit Tagen alle 15 Minuten neu abgefragt — "market not found in Gamma API after retry".

**Auftrag:** Tombstone-Cache einführen (z. B. `data/market_tombstones.json`): Nach 3 aufeinanderfolgenden not-found-Antworten wird die market_id persistent als "gone" markiert und bei Snapshots übersprungen (einmalige Log-Zeile statt Dauer-Retry). Entspricht der Stabilitätsregel "Wiederholte Snapshot-Fehler sollen gecacht oder gedrosselt werden" (`agent/project/AGENTS.md`). Fundstelle des Retry-Codes über `grep -rn "market not found in Gamma API" --include=*.py` suchen.

**Akzeptanz:** Nach 3 Runs tauchen die beiden IDs nicht mehr in `logs/snapshot_errors.log` auf; Tombstone-Datei existiert und wird geladen.

---

## A3 (P1) — Forward-Lane-Zufluss wiederherstellen und messen

**Kontext:** Gate 1 braucht ~150+ aufgelöste NO-Fade-Positionen über ≥2 Kalendermonate (aktuell 93 aufgelöst, nur 5 offen — der Zufluss ist wegen A1 versiegt).

**Auftrag (NACH A1):** Verifizieren, dass `analytics/no_fade_forward` nach dem Collector-Fix wieder neue Entries generiert (P(YES) 10–20 %, exact+between, Lead >6h). Zusätzlich in `analytics/no_fade_forward.md` eine Kennzahl "Entries letzte 7 Tage" ausgeben, damit ein erneutes Versiegen sofort sichtbar wird.

**Akzeptanz:** Innerhalb von 24h nach A1-Fix mindestens 1 neuer Forward-Entry ODER dokumentierte Begründung (z. B. kein Markt im Preisfenster); neue Kennzahl erscheint im Report.

---

## A4 (P2) — `market_type_blocked` Guardrail auditieren

**Symptom:** 100 % der Guardrail-Checks werden mit `market_type_blocked` geblockt (Top Block Reason in praktisch jedem Run seit Tagen).

**Auftrag:** Klären, welcher Markt-Typ da wiederholt anklopft und ob der Block korrekt ist (die NO-Guardrails gegen Narrow-Band-Märkte sind gewollt). Wichtig: Prüfen, dass der Block NICHT die Forward-Lane-Entries (exact/between für NO-Fade) betrifft. Ergebnis als kurze Notiz in `analytics/edge_status.md`-Quelle oder als Kommentar im Guardrail-Code dokumentieren. Nur fixen, falls ein legitimer Typ fälschlich geblockt wird — sonst nur dokumentieren.

**Akzeptanz:** Schriftliche Antwort im Loop-Journal: welcher Typ, welche Regel, korrekt ja/nein.

---

## A5 (P2) — Forward vs. Backtest Reconciliation (der eigentliche Edge-Beweis)

**Kontext:** Backtest sagt +2.87 %/Share netto (n=1142, Cluster-t=3.19). Forward-Lane liegt bei **-5.04 % modelliert / -5.42 % real** (n=93) trotz 81.7 % NO-Win-Rate. Diese Diskrepanz ist DIE offene Frage — wenn sie bei n≥150 bestehen bleibt, ist die Edge ehrlich tot (Gate 1 verfehlt).

**Auftrag:** Analyse-Skript (read-only, z. B. `analytics/forward_reconciliation.py`) das Forward-Positionen und Backtest-Universe vergleicht:
- Pro Monat/Bucket/Stadt: Entry-Preis-Verteilung, realisierte YES-Rate, PnL/Share.
- Sind die Forward-Entries teurer eingekauft (Spread/Timing) als der Backtest annimmt?
- Selektionseffekt: erwischt die Lane systematisch andere Märkte als das Backtest-Universe?
Output als `analytics/forward_reconciliation.md`, fail-open in den Zyklus eingehängt wie die anderen Edge-Module.

**Akzeptanz:** Report beantwortet quantitativ, woher die ~8 Prozentpunkte Differenz kommen (Kosten vs. Regime vs. Selektion vs. Rauschen bei n=93).

---

## A6 (P3) — Health-Erholung nach Collector-Fix verifizieren

**Auftrag (NACH A1):** Bot Health steht auf CRITICAL, Live-Readiness-Blocker "0 Trades in 7 Tagen", M6-Stabilitätsuhr auf 0.0 Tage. Nach dem Fix prüfen, dass Health wieder OK/WARN erreicht, der Blocker verschwindet, und die M6-Uhr wieder zählt. Falls Health an veralteten Zählern hängt, minimal korrigieren.

**Akzeptanz:** `logs/bot_health.json` ≠ CRITICAL nach 3 fehlerfreien Runs.

---

## A7 (P3) — Housekeeping (nur wenn A1–A6 erledigt)

- `output/status_summary.txt` wächst unbegrenzt (3600+ Zeilen) → Rotation auf die letzten ~200 Runs.
- `config/weather_backup_*.yaml` sammelt sich an (5 Stück von heute) → Backups auf die letzten 10 begrenzen.

---

## Loop-Journal

| Datum | Auftrag | Ergebnis | Commit |
|---|---|---|---|
| 2026-07-14 | A1 | ERLEDIGT (Fable): `collector/client.py` — `closed=False` bei `include_closed=False`, Fail-open bei Paginierungsfehler (Teilergebnis statt RuntimeError), `MAX_EVENT_OFFSET=2000`. Verifiziert: Run OK, 500 Märkte, 399 Kandidaten, kein 422. | via auto-save |
| 2026-07-14 | A2 | ERLEDIGT (Fable): neues `paper_trader/market_tombstones.py` (persistent, `data/market_tombstones.json`, 3-Miss-Schwelle) + eingehängt in `snapshot_client.py` (Skip vor Fetch, record_miss/record_hit). Verifiziert: Tombstone-Datei angelegt, IDs 2877738/2887877 bei miss_count=1 — nach 3 Runs stummgeschaltet. | via auto-save |
| 2026-07-14 | A3 | ERLEDIGT (Fable): `no_fade_lane.summary()` liefert `entries_last_7d`, Report zeigt "Entries letzte 7 Tage" mit Warnhinweis bei 0. Verifiziert: zeigt 5. | via auto-save |
| 2026-07-14 | A4 | ERLEDIGT (Fable, nur Doku): `market_type_blocked` (`entry_guardrails.py:207`) blockt exact/at_or_above im **Produktions-Simulator** (config `BLOCKED_MARKET_TYPES: [exact, at_or_above]`) — korrekt, kein Forward-Edge. Die NO-Fade-Forward-Lane läuft **komplett an entry_guardrails vorbei** (liest direkt weather_observations.jsonl), ist also NICHT betroffen. Kein Fix nötig. | — |
| 2026-07-14 | A5 | ERLEDIGT (Fable): neues `analytics/forward_reconciliation.py` (read-only, in Zyklus eingehängt) → `analytics/forward_reconciliation.md|json`. **BEFUND:** Lücke −7.9pp ist zu −8.4pp Win-Rate (90.1%→81.7%), Kosten vernachlässigbar (+0.5pp Einstieg, −0.4pp Slippage). Forward-Lane sah **Mai nie** (stärkster Backtest-Monat, +4.44%) → Edge regime-abhängig. `between` bricht besonders ein (−13.25%). | via auto-save |
| 2026-07-14 | A6 | ERLEDIGT (Fable): 2 Pipeline-Runs OK statt DEGRADED (Collector liefert wieder), keine 422/Tracebacks im Log. Bot-Health/M6-Uhr erholen sich über die nächsten regulären Runs automatisch. | — |
| 2026-07-14 | A7 | KEIN CODE NÖTIG (Fable): `status_summary.txt` bereits per `_trim_status_summary` auf 120 Runs begrenzt (aktiv), `weather_backup_*.yaml` bereits per `_backup_config()` auf 5 begrenzt. Beides funktioniert. | — |
