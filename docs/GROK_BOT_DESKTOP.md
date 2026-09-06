# Grok Bot am Windows-Desktop

Grok Bot ist die Desktop-App fuer KI-Teamkollegen (nicht der normale Grok-Chat).
In diesem Projekt steuert sie den Weather-Paper-Trader ueber den lokalen MCP-Server.

## Voraussetzungen

- Windows 10/11, x64 oder Arm64
- Python 3.10+ im PATH oder unter `C:\Program Files\Python3xx\`
- Berechtigter Account: SuperGrok Plus/Heavy, Cursor Pro+/Ultra, oder Cursor Teams
- Cursor nicht im Legacy Privacy Mode (Grok Bot braucht Cloud-Speicher)

Download-Seite: https://x.ai/bot

## Schnellinstallation

Im Projektordner doppelklicken:

```text
install_grok_bot.bat
```

Oder in PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File setup_grok_bot.ps1
```

Das Skript:

1. Holt den aktuellen Windows-Installer von der Cursor/xAI Update-API
2. Installiert Grok Bot (ueberspringt, wenn schon vorhanden)
3. Installiert das Python-Paket `mcp`
4. Traegt den Weather-Bot MCP-Server in `%USERPROFILE%\.cursor\mcp.json` und `%USERPROFILE%\.grok\config.toml` ein
5. Legt eine Desktop-Verknuepfung an
6. Startet Grok Bot

## Nach dem Start

1. In Grok Bot **Sign in with Cursor** waehlen
2. Neuen Bot anlegen:

**Name:** Weather Observer

**Job:** Strategie-Manager fuer den Polymarket Weather Paper-Trader

**Beschreibung:** Du bist die Fuehrungskraft des lokalen Paper-Trading-Bots. Status, Kapital, Positionen und Performance ueber MCP pruefen. Kein Live-Trading. Parameter nur innerhalb Governance-Limits. Immer auf Deutsch antworten.

3. Erste Nachricht:

```text
Wie laeuft der Weather-Bot? Status, Kapital, offene Positionen und Health.
Kein Live-Trading. Nichts aendern, nur reporten.
```

## Manuelle MCP-Config (falls noetig)

Cursor Desktop / Grok Bot lesen projektseitig:

- `.cursor/mcp.json`
- `.grok/config.toml`
- `.mcp.json`

User-seitig schreibt das Setup-Skript absolute Pfade nach:

- `%USERPROFILE%\.cursor\mcp.json`
- `%USERPROFILE%\.grok\config.toml`

## Troubleshooting

| Problem | Fix |
|---|---|
| Installer-API nicht erreichbar | Manuell von https://x.ai/bot laden, danach `setup_grok_bot.ps1` erneut (konfiguriert MCP trotzdem) |
| MCP startet nicht | `python -m mcp_server` im Projektordner testen; `logs/mcp_server_error.log` lesen |
| Python nicht gefunden | Python 3.10+ installieren und PATH setzen, danach Setup erneut |
| Login schlaegt fehl | Cursor-Session aktiv, Plan berechtigt, Legacy Privacy Mode aus |
| Bot sieht keine Tools | Grok Bot neu starten; in Cursor MCP fuer `polymarket-beobachter` pruefen |
