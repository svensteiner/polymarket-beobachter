# MCP Server - Grok Bot / Claude als Bot-Führungskraft

Dieser MCP (Model Context Protocol) Server ermöglicht es Grok Bot (Desktop)
und Claude, als "Führungskraft" des Polymarket Weather Betting Bots zu agieren.

Windows-Desktop: `install_grok_bot.bat` ausfuehren. Details: `docs/GROK_BOT_DESKTOP.md`.

## Features

### Status-Abfragen
- **get_bot_status** - Vollständiger Bot-Status inkl. Health-Check
- **get_capital_status** - Kapitalstand und Verfügbarkeit
- **get_open_positions** - Aktuelle offene Positionen
- **get_recent_trades** - Letzte ausgeführte Trades
- **get_performance_summary** - Performance-Metriken und Statistiken

### Konfiguration
- **get_strategy_config** - Aktuelle Strategie-Parameter
- **update_strategy_param** - Parameter ändern (mit Governance-Limits)
- **update_capital_config** - Kapital-Konfiguration anpassen

### Bot-Steuerung
- **pause_bot** - Bot pausieren (mit Grund)
- **resume_bot** - Bot fortsetzen
- **get_bot_control_status** - Aktueller Kontrollstatus

### Proposals
- **get_pending_proposals** - Offene Proposals zur Review
- **get_proposal_history** - Historische Proposals

### Analyse
- **get_market_observations** - Aktuelle Marktbeobachtungen
- **analyze_city_performance** - Performance nach Stadt analysieren

### Diagnose
- **get_logs** - Log-Einträge abrufen
- **health_check** - Vollständiger System-Health-Check

## Installation

### 1. Abhängigkeiten installieren

```bash
pip install mcp
```

### 2. Server starten

```bash
# Direkt mit Python
python -m mcp_server

# Oder mit uvicorn für HTTP-Transport
uvicorn mcp_server.server:mcp.app --host 0.0.0.0 --port 8000
```

## Grok Bot / Cursor Desktop

Projekt-Configs liegen bereits im Repo:

- `.cursor/mcp.json` (Cursor Desktop + Grok Bot)
- `.grok/config.toml` (Grok CLI / Grok Bot)
- `.mcp.json` (zusaetzliche Grok-Kompatibilitaet)

Windows-Installer schreibt zusaetzlich User-Configs nach `%USERPROFILE%\.cursor\mcp.json`
und `%USERPROFILE%\.grok\config.toml`.

## Claude Desktop Integration

Füge folgendes zu deiner Claude Desktop Konfiguration hinzu:

### Windows
Bearbeite: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "polymarket-beobachter": {
      "command": "python",
      "args": ["-m", "mcp_server"],
      "cwd": "C:\\Pfad\\zu\\polymarket-beobachter"
    }
  }
}
```

### Linux/Mac
Bearbeite: `~/.config/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "polymarket-beobachter": {
      "command": "python",
      "args": ["-m", "mcp_server"],
      "cwd": "/pfad/zu/polymarket-beobachter"
    }
  }
}
```

## Governance-Regeln

Der MCP Server respektiert die Governance-Regeln des Bots:

### Parameter-Limits
- MIN_EDGE: 5% - 50%
- MIN_EDGE_ABSOLUTE: 3% - 30%
- MAX_ODDS: 20% - 60%
- KELLY_FRACTION: 0.1 - 0.5

### Kapital-Limits
- max_position_size: 50 - 500 EUR
- max_positions: 1 - 20
- initial_capital: 100 - 50000 EUR

### Audit-Logging
Alle Änderungen werden in `logs/mcp_audit.jsonl` protokolliert.

## Beispiel-Nutzung

Nach der Integration kann Claude z.B. folgende Aufgaben übernehmen:

1. **Morgen-Briefing**: "Wie ist der aktuelle Bot-Status?"
2. **Risk-Check**: "Zeige offene Positionen und deren Edge"
3. **Performance-Review**: "Wie war die Performance letzte Woche?"
4. **Intervention**: "Pausiere den Bot wegen hoher Volatilität"
5. **Strategy-Tuning**: "Erhöhe MIN_EDGE auf 15%"

## Dateipfade

Der Server greift auf folgende Dateien zu:

| Datei | Zweck |
|-------|-------|
| `data/capital_config.json` | Kapital-Konfiguration |
| `config/weather.yaml` | Strategie-Parameter |
| `paper_trader/logs/paper_positions.jsonl` | Positionsdaten |
| `paper_trader/logs/trade_log.jsonl` | Trade-Historie |
| `logs/bot_status.json` | Bot-Status |
| `logs/bot_control.json` | Pause/Resume Status |
| `logs/mcp_audit.jsonl` | MCP-Änderungsprotokoll |
| `proposals/` | Proposal-Dateien |

## Sicherheit

- Der MCP Server läuft lokal und hat keinen Internet-Zugang
- Alle Änderungen erfordern explizite Tool-Aufrufe
- Kritische Änderungen werden geloggt
- Parameter-Limits verhindern gefährliche Konfigurationen
