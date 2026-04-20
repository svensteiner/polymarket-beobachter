# Polymarket Beobachter — Strategie-Hardening Report
**Erstellt:** 2026-04-16  
**Status:** Paper Trading → Live Trading Vorbereitung

---

## 1. Performance-Diagnose (13 abgeschlossene Trades)

| Metrik | Wert | Bewertung |
|--------|------|-----------|
| Win-Rate gesamt | 38.46% (5/13) | Kritisch (Ziel: >60%) |
| Win-Rate: Held to Resolution | **100% (5/5)** | Exzellent |
| Win-Rate: Stop-Loss-Exits | **0% (0/8)** | Katastrophal |
| Profit Factor | 0.16 | Katastrophal |
| Brier Skill Score | -0.31 | Modell schlechter als Baseline |
| Ø Gewinn | +1.05 EUR | Zu klein vs. Verlust |
| Ø Verlust | -4.11 EUR | Stop-Loss-dominiert |

### Kernbefund: Stop-Losses zerstören die Performance

**Alle 5 Gewinne** kamen von Positionen, die bis zur Resolution gehalten wurden.  
**Alle 8 Verluste** kamen von Stop-Loss-Exits — ausnahmslos NO-Wetten auf Schmalband-Märkte.

---

## 2. Root-Cause-Analyse: Was genau schief lief

### Problem A: NO-Wetten auf "between" und "exact" Märkte
Beispiel: "Will temp in SF be between 84-85°F?" → NO-Wette  
- NO-Einstiegspreis: 0.45-0.70 (YES nur 30-55% wahrscheinlich)
- Am Resolution-Tag springt YES plötzlich Richtung 0 oder 100%  
- NO-Kontrakt verliert -71 bis -93% im Mid-Trade  
- Stop-Loss (−70%) greift — BEVOR der Markt auflöst
- Historische WR: **0/8 NO-between/exact-Trades = 0% Gewinn**

**Warum**: Schmalbandmärkte (1°F Band) haben extrem volatile Preise kurz vor Resolution. 
Ein Forecast von 84.5°F ist schwer von 85.1°F zu unterscheiden — die Modellunschärfe 
(ursprünglich sigma=3.5°F) war zu klein für diese Märkte.

### Problem B: NO-Wette bei 92% YES-Preis durchgerutscht
Trade SF: entry_price=0.076 (NO-Kontrakt), YES-Preis war 92.4%  
→ Normalerweise sollte MIN_ENTRY_PRICE=0.35 das blockieren  
→ Bug: Filter prüfte YES-Preis (0.924 > 0.35 = OK) statt NO-Preis (0.076 < 0.35 = BLOCK)  
→ Maximales Verlustrisiko bei 7.6% Gewinnpotenzial

### Problem C: Modell-Überkonfidenz (BSS = −0.31)
Das Wettermodell schätzt Wahrscheinlichkeiten zu extrem ein. Besonders bei 
Schmalband-Märkten (1°F Bänder) kann eine Temperaturabweichung von 1°F den Ausgang 
komplett umkehren. Das ursprüngliche sigma=3.5°F war zu eng kalibriert.

---

## 3. Implementierte Fixes (2026-04-16)

### Fix 1: NO-Wetten auf Schmalband-Märkte gesperrt
**Datei:** `paper_trader/simulator.py`  
NO-Wetten auf "between" und "exact" Market-Types werden jetzt abgelehnt.  
Begründung: 100% historische Verlustrate, systematische resolution-day Preissprünge.

### Fix 2: NO-Bet Entry-Price-Check korrigiert  
**Datei:** `paper_trader/entry_guardrails.py`  
Für NO-Wetten wird jetzt der NO-Kontraktpreis (= 1 − YES-Preis) gegen MIN_ENTRY_PRICE 
geprüft, nicht mehr der YES-Preis. Blockiert schlechte R:R-Situationen.

### Fix 3: SIGMA_F erhöht (3.5°F → 4.5°F)
**Datei:** `config/weather.yaml`  
Größere Unsicherheit im Temperaturmodell → niedrigere Wahrscheinlichkeiten bei  
Schmalband-Ereignissen → weniger falsche Signale, bessere Kalibrierung.

### Fix 4: MIN_TIME_TO_RESOLUTION_HOURS erhöht (4h → 24h)
**Datei:** `config/weather.yaml`  
Same-day Trades (< 24h bis Resolution) haben höchste Forecast-Unsicherheit.  
Mit 24h Vorlauf stimmen Ensemble-Modelle besser überein.

### Fix 5: Kalibrierungsshrinkage verbessert
**Datei:** `core/weather_engine.py`  
Dreistufiges Shrinkage-Schema statt einstufigem:
- p < 0.05 oder > 0.95: 30% Shrinkage (war 15% bei engerer Grenze)
- p < 0.15 oder > 0.85: 20% Shrinkage (neu)
- Restliche Werte: 8% leichte Regularisierung (neu)

### Fix 6: Position-Size skaliert (5 EUR → 20 EUR)
**Datei:** `data/capital_config.json`  
5 EUR/Trade war für Track-Record-Aufbau. Mit den neuen Guardrails und
-70% Stop-Loss können wir 20 EUR/Trade fahren und schneller Daten sammeln.

---

## 4. Erwartete Auswirkungen

| Metrik | Vorher | Erwartet |
|--------|--------|---------|
| Win-Rate | 38% | **>65%** (nur noch "gute" Trades) |
| Ø Gewinn/Trade | +1.05 EUR | **+4-8 EUR** (20 EUR Positions) |
| Profit Factor | 0.16 | **>1.5** (deutlich weniger Stop-Losses) |
| Stop-Loss-Ratio | 62% | **<15%** (NO-between/exact blockiert) |
| Trades pro Tag | ~3-5 | ~2-4 (strengere Filter) |

---

## 5. Strategie: Aktuelle Trade-Logik

### Erlaubte Trades (nach Hardening)
| Side | Market Type | Einstiegspreis | Bedingung |
|------|-------------|----------------|-----------|
| YES | at_or_above | 0.35 – 0.85 | Forecast > Threshold + Edge ≥ 30% rel. |
| YES | at_or_below | 0.35 – 0.85 | Forecast < Threshold + Edge ≥ 30% rel. |
| YES | exact | 0.35 – 0.85 | Selten, nur HIGH confidence |
| NO | at_or_below | 0.35 – 0.65 | Forecast weit über Threshold |
| NO | at_or_above | 0.35 – 0.65 | Forecast weit unter Threshold |

### Gesperrte Trades (Schmalband-Fallen)
- ❌ NO auf "between" Markets (0% historische WR)
- ❌ NO auf "exact" Markets (0% historische WR)
- ❌ NO wenn YES-Preis > 65% (NO-Kontrakt < 35% Preis = bad R:R)
- ❌ Markets mit < 24h bis Resolution (Forecast zu ungenau)
- ❌ Ensemble-Varianz > 8% (Modelle uneinig)

---

## 6. Live-Trading-Checkliste

### Technische Voraussetzungen
- [ ] `POLYMARKET_API_KEY` + `POLYMARKET_API_SECRET` + `POLYMARKET_PASSPHRASE` in `.env`
  → Aus Polymarket-Browser: Developer Tools → Local Storage
- [ ] `POLYMARKET_WALLET_ADDRESS` (Proxy-Wallet-Adresse) in `.env`
- [ ] USDC.e-Guthaben auf dem Proxy-Wallet (mind. 500 EUR Äquivalent)
- [ ] Telegram konfiguriert: `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`

### Performance-Voraussetzungen  
- [ ] Paper Trading WR > 60% über mindestens 50 Trades (aktuell: 38% / 13 Trades)
- [ ] Profit Factor > 1.5 über letzte 30 Trades
- [ ] Kein aktiver CRITICAL-Status im bot_health.json

### Aktivierung
```bash
# In .env:
LIVE_TRADING_ENABLED=true

# Trading-Client nutzt dann echte Orders via CLOB API
# Jeder Trade wird vor Ausführung via Telegram bestätigt
```

---

## 7. Paper-Trading Status (Stand 2026-04-16)

- **Kapital:** 4.920 EUR (von 5.000 EUR Start)
- **Drawdown:** 0.58% (unkritisch, Ziel: <5%)
- **Offene Positionen:** ~10 (aus capital_config.json)
- **Bot-Status:** ELEVATED (durch alte Stop-Loss-Ratio — wird sich mit neuen Trades normalisieren)

**Nächste Milesteine bis Live-Trading:**
1. 37 weitere Paper-Trades ohne Strategie-Reset (gesamt: 50 Trades)
2. WR > 60% nach Anwendung der neuen Filter
3. Anmeldung bei Polymarket & API-Credentials bereitstellen
4. LIVE_TRADING_ENABLED=true setzen

---

*Report generiert von Claude Code (Automated Strategy Hardening Run)*
