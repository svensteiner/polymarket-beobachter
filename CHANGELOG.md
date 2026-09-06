# Changelog

All notable changes to polymarket-beobachter are documented here.

## [Unreleased]

### 2026-09-06

#### Added
- **Grok Bot Desktop-Installation** — `install_grok_bot.bat` / `setup_grok_bot.ps1`
  laden den aktuellen Windows-Installer, binden den lokalen MCP-Server an
  Cursor/Grok Bot und legen eine Desktop-Verknuepfung an. Projekt-Configs:
  `.cursor/mcp.json`, `.grok/config.toml`, `.mcp.json`. Anleitung:
  `docs/GROK_BOT_DESKTOP.md`.

### 2026-04-08

#### Fixed
- **Edge drought broken** — `config/weather.yaml` had drifted at runtime to
  `MIN_ODDS=0.40, MAX_ODDS=0.45` (a 5-cent eligibility window) which caused
  the bot to find 0 edge for 8 consecutive cycles. Restored to working
  longshot range `MIN_ODDS=0.02, MAX_ODDS=0.40`. Verified with 3 consecutive
  paper-mode pipeline runs (4 edge observations each). After deploy the
  background daemon found 5 edge observations and entered 1 paper position.
  Commit `0c0f26e`.

#### Refactor
- Removed dead code across 68 files: unused imports, dead local assignments,
  and superfluous f-strings. No behavior changes. All 471 tests still pass.
  Commit `9a83638`.

### Known issues / follow-ups (not fixed yet)
- `analytics/strategy_advisor.py` is the source of the runtime config drift
  that progressively tightens filter parameters when no edge is found,
  creating a self-defeating loop. Needs a floor on adaptive tightening, or
  a regression guard that triggers when `edge_observations == 0` for >5 cycles.
- `tests/unit/test_weather_engine.py` leaks synthetic observations
  (`market_id=m1/m2/m3`, `forecast_source=test_source`) into production
  `logs/weather_observations.jsonl` because tests with `has_edge=True` bypass
  the `LOG_ALL_OBSERVATIONS=False` gate in `core/weather_engine.py:287`.
  Fix: tests should override `OBSERVATION_LOG_PATH` in `create_test_config()`
  to a temp dir, or `_log_observation` should respect `LOG_ALL_OBSERVATIONS`
  unconditionally.
- Bot health remains `ELEVATED` due to historical drawdown of 18.5% — this
  is a separate recovery path managed by `paper_trader/bot_health_monitor.py`
  and is not affected by the filter fix.
