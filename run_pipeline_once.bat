@echo off
REM =============================================================================
REM POLYMARKET BEOBACHTER - SINGLE PIPELINE RUN
REM =============================================================================
REM Fuehrt die Pipeline einmal aus. Fuer Task Scheduler.
REM =============================================================================

cd /d "%~dp0"
python cockpit.py --run-once

REM Log schreiben
echo %date% %time% - Pipeline executed >> logs\scheduler_runs.log
