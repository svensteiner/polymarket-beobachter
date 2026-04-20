# Polymarket Beobachter — Strategy Analysis & Hardening Report
**Datum:** 2026-04-16  
**Erstellt von:** Automated strategy review (scheduled task)

---

## 1. Aktueller Performance-Status

| Metrik | Wert | Bewertung |
|--------|------|-----------|
| Trades total | 12 | zu wenig für statistische Signifikanz |
| Win Rate | 41.67% | unter 50% → schlecht |
| PnL | -23.53 EUR | negativ |
| Profit Factor | 0.183 | <1 → verlustreich |
| Brier Skill Score | -0.306 | **negativ** = schlechter als naive Baseline |
| Bot Health | ELEVATED | Guardrails aktiv |
| Kalibrations-Qualität | POOR | Modell überbewertet Sicherheit |

---

## 2. Wurzelursachen-Analyse

### Kernproblem: 7 von 12 Trades = Stop-Loss-Exits
```
strategy_attribution:
  stop_loss: 7 Trades, 0% WR, -28.81 EUR  ← ALLE Verluste hier
  other:     5 Trades, 100% WR, +5.27 EUR  ← ALLE Gewinne hier
```

**Interpretation**: Die Strategie ist grundsätzlich korrekt — wenn Positionen bis zur
Auflösung gehalten werden (100% WR). Das Problem ist, dass 7 Positionen so stark gegen
uns liefen (-70%), dass der Stop-Loss ausgelöst wurde.

### Ursache 1: NO-Wetten auf nahezu unmögliche Ereignisse

Analyse der Proposals:
- London YES=7.5% → Modell sagt 2.8% → NO-Wette bei implizierter 92.5% Sicherheit
- Paris YES=20% → Modell sagt 6.1% → NO-Wette bei implizierter 80% Sicherheit

Wenn wir bei 7.5% YES-Preis NO wetten, muss der Markt von 7.5% auf ~15% steigen, um
unsere Position um 70% zu entwerten. Das passiert bei aktuellen Wetterdaten-Updates.

**Strukturelles Problem**: Bei sehr niedrigen YES-Preisen ist das Modell am unsichersten,
wir treten aber mit höchster scheinbarer Konfidenz auf.

### Ursache 2: Negative Brier Skill Score (-0.306)

Das Modell ist schlechter als eine naive Baseline (einfach immer die Basisrate vorhersagen).
Bei nur 5 kalibrierten Datenpunkten:
- 3 Predictions im Bereich 0.4-0.6: Outcome war 0 (falsch, aber nah)
- Scheinbar korrekt bei extremen Prognosen (0.076→0.0)

Das Modell neigt dazu, zu EXTREME Wahrscheinlichkeiten zu generieren (z.B. 2.8% statt 10%).

### Ursache 3: MIN_ODDS=0.024 erlaubte Micro-Probability-Märkte

Die bisherige Konfiguration erlaubte Märkte wo YES bei 2.4% steht. Bei solchen Märkten:
- Risiko/Reward ist asymmetrisch gegen uns (kleiner Gewinn, großer potenzieller Verlust)
- Modell-Unsicherheit ist am höchsten (jede kleine Temperaturänderung ist entscheidend)

---

## 3. Implementierte Korrekturen (2026-04-16)

### Fix 1: `config/weather.yaml` — Strengere Ensemble-Parameter
```yaml
# Vorher → Nachher
MIN_ODDS: 0.024 → 0.15        # Nur Märkte wo YES >= 15%
ENSEMBLE.VARIANCE_THRESHOLD: 0.15 → 0.08   # Strengere Konsistenz-Anforderung
ENSEMBLE.MIN_INDEPENDENT_SOURCES: 1 → 2    # Mindestens 2 unabh. Quellen
```

**Auswirkung**: Filtert die "Near-Impossible-Event"-Märkte heraus wo wir systemisch verlieren.

### Fix 2: `core/weather_engine.py` — Probability Calibration Shrinkage
```python
if raw_prob < 0.08 or raw_prob > 0.92:
    fair_prob = raw_prob * 0.85 + market_odds * 0.15
```
**Auswirkung**: Verhindert überconfident Edge-Signale bei extremen Wahrscheinlichkeiten.
Wenn Modell "2.8%" sagt und Markt "7.5%", wird Modell-Prob auf ~3.9% gezogen.
Das reduziert den berechneten Edge und macht den Filter strenger.

### Fix 3: `paper_trader/simulator.py` — Low-Probability NO-Bet Gate
```python
# Wenn YES-Preis < 15% und wir NO wetten: 20% Edge-Mindestanforderung (statt 8%)
if is_no_bet and implied_prob < 0.15:
    require edge >= 0.20
```
**Auswirkung**: Schützt vor der gefährlichsten Trade-Kategorie.

### Fix 4: `proposals/signal_adapter.py` — Ensemble-Qualität in Proposals
Ensemble-Varianz und Quellen-Anzahl werden jetzt in `warnings` weitergegeben:
- `HIGH_VARIANCE:0.12` → simulierter Entry wird geblockt
- `LOW_SOURCE_COUNT:1` → simulierter Entry wird geblockt

---

## 4. Live-Trading Readiness Checklist

**Technisch:**
- [x] Paper-Trader läuft stabil (15-min Pipeline)
- [x] Position-Manager mit Staged TP + Trailing Stop
- [x] Stop-Loss (-70%) aktiv
- [x] Bot-Health-Monitor mit Guardrails
- [x] Telegram-Notifikationen konfiguriert
- [x] Ensemble-Multi-Source-Forecasting
- [x] Fee-Aware Edge-Berechnung

**Strategie-Qualität (NEU bewertet):**
- [ ] Win Rate > 55% über 30+ Trades → Aktuell 41.67%/12 Trades ← BLOCKIERT
- [ ] Profit Factor > 1.0 → Aktuell 0.183 ← BLOCKIERT
- [ ] Brier Skill Score > 0 → Aktuell -0.306 ← BLOCKIERT
- [x] Drawdown < 5% → Aktuell 0.56%

**Live-Trading: NOCH NICHT BEREIT**

Mindestanforderungen bevor `enabled: true` gesetzt werden darf:
1. 50+ Paper-Trades mit den neuen Parametern
2. Win Rate >= 55% in den letzten 30 Trades
3. Profit Factor >= 1.2
4. Brier Skill Score >= 0.05

---

## 5. Erwartete Auswirkung der Korrekturen

Nach den Änderungen werden weniger Trades eingenommen (höhere Filterung), aber:
- Verbleibende Trades haben höheres Konfidenz-Niveau
- Near-Impossible-Events sind ausgeschlossen (größte Verlustquelle)
- Ensemble-Konsistenz ist Pflicht (2 unabhängige Quellen)

**Erwartete neue Parameter:**
- Trades/Woche: ~3-5 (statt ~5-8)
- Erwartete Win Rate: 55-65% (war 41.67%)
- Erwarteter Profit Factor: 1.1-1.5 (war 0.183)

---

## 6. Weitere Empfehlungen (nicht implementiert, TODO)

### A. Forecast-Stabilität-Check
Bevor eine Position eröffnet wird: Prüfen ob sich der Forecast in den letzten 3h
signifikant verändert hat. Instabile Forecasts → kein Entry.

### B. Markt-Momentum-Filter
Wenn der YES-Preis in den letzten 2h gestiegen ist (Markt kauft YES), keine NO-Wette eingehen.
Dies würde signalisieren, dass "Smart Money" andere Informationen hat.

### C. Resolution-Time-Optimierung
Hard-Limit auf 48h bis Auflösung einführen. Unsere 100% WR-Trades waren wahrscheinlich
Same-Day oder Next-Day Märkte wo Forecast-Präzision am höchsten ist.

### D. Seasonal/Regional Kalibrierung
Separate Brier-Score-Tracking pro Stadt und Jahreszeit. Städte mit < 40% WR über 20
Trades automatisch für 7 Tage sperren.

---

## 7. Konfiguration für Live-Trading (wenn bereit)

```yaml
# config/live_trading.yaml empfohlene Parameter:
capital:
  initial_eur: 1000
  max_position_eur: 25     # Start sehr klein (2.5%)
  max_open_positions: 3    # Fokus statt Diversifikation
  max_daily_trades: 2      # Qualität über Quantität
  max_daily_loss_eur: 50   # 5% Daily Stop

entry:
  min_edge: 0.25           # 25% minimum (statt 8%)
  min_confidence: "HIGH"   # NUR HIGH confidence
  max_odds: 0.65           # NO bets: nur wenn YES 35-65%
```

---

*Bericht generiert: 2026-04-16T20:15:00Z*
