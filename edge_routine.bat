@echo off
:: =============================================================================
:: EDGE ROUTINE - laeuft 3x taeglich (Windows Task Scheduler)
:: =============================================================================
::
:: Zwei Schritte:
::   1. ANALYSE (immer, kostenlos): re-runs alle schweren Edge-Scans, schreibt
::      analytics/edge_routine_digest.md mit Zustandsaenderungen + Arbeitsliste.
::   2. ARBEIT (optional, kostet API-Budget): Claude-Agent nimmt den obersten
::      Punkt der Arbeitsliste und macht konkreten Fortschritt.
::
:: Agent-Schritt abschalten:  set EDGE_AGENT=0  (oder Zeile unten auskommentieren)
:: Manuell testen:            edge_routine.bat
:: =============================================================================
setlocal enableextensions enabledelayedexpansion

pushd "%~dp0"

set "PYTHON_EXE="
if exist "%~dp0.venv\Scripts\python.exe" set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
if not defined PYTHON_EXE (
    where python >nul 2>nul && set "PYTHON_EXE=python"
)
if not defined PYTHON_EXE (
    echo [%DATE% %TIME%] FEHLER: kein Python gefunden >> "logs\edge_routine.log"
    popd & endlocal & exit /b 1
)

set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set PYTHONUNBUFFERED=1

if not exist "logs" mkdir "logs"
set "LOG_FILE=logs\edge_routine.log"

:: Log-Rotation: auf 2 MB begrenzen
for %%F in ("%LOG_FILE%") do set "LOG_SIZE=%%~zF"
if defined LOG_SIZE if !LOG_SIZE! GTR 2097152 (
    del /q "%LOG_FILE%.old" 2>nul
    ren "%LOG_FILE%" "edge_routine.log.old" 2>nul
)

echo. >> "%LOG_FILE%"
echo ========================================================= >> "%LOG_FILE%"
echo [%DATE% %TIME%] EDGE ROUTINE START >> "%LOG_FILE%"

:: --- Schritt 1: Analyse (immer) ------------------------------------------
"%PYTHON_EXE%" -u -m analytics.edge_routine >> "%LOG_FILE%" 2>&1
set "ANALYSE_EXIT=!ERRORLEVEL!"
echo [%DATE% %TIME%] Analyse beendet (exit=!ANALYSE_EXIT!) >> "%LOG_FILE%"

:: --- Schritt 2: Agent-Arbeit (optional) ----------------------------------
if not defined EDGE_AGENT set "EDGE_AGENT=1"
:: Leerzeichen tolerieren (falls EDGE_AGENT unquoted gesetzt wurde)
for /f "tokens=* delims= " %%A in ("!EDGE_AGENT!") do set "EDGE_AGENT=%%A"
set "EDGE_AGENT=!EDGE_AGENT: =!"
if "!EDGE_AGENT!"=="0" (
    echo [%DATE% %TIME%] Agent-Schritt uebersprungen ^(EDGE_AGENT=0^) >> "%LOG_FILE%"
    goto done
)

where claude >nul 2>nul
if errorlevel 1 (
    echo [%DATE% %TIME%] claude CLI nicht gefunden - Agent-Schritt uebersprungen >> "%LOG_FILE%"
    goto done
)

echo [%DATE% %TIME%] Agent-Schritt startet... >> "%LOG_FILE%"

call claude -p "Du arbeitest am Polymarket-Wetter-Bot in %CD%. Ziel: eine handelbare Edge finden - ehrlich, nicht eingebildet. LIES ZUERST: analytics/edge_routine_digest.md (frischer Stand + Arbeitsliste) und reports/edge_search_plan_2026-07-27.md (Methoden-Guardrails). Nimm den OBERSTEN offenen Punkt der Arbeitsliste und mache konkreten, abgeschlossenen Fortschritt daran - lieber ein Punkt fertig als drei angefangen. PFLICHT-GUARDRAILS: Walk-Forward ohne Look-ahead; realistische Kosten via analytics/cost_model.py; Cluster-t; neue Hypothesen als Eintrag in HYPOTHESES in analytics/edge_scanner.py (das Harness macht BH-Korrektur automatisch); jede Analyse read-only und fail-open. VERBOTEN: config/weather.yaml aendern, Live-Trading aktivieren, destruktive Git-Operationen, Guardrails im Simulator lockern. Wenn ein Ergebnis negativ ist, berichte es als negativ - ein ehrliches Nein ist wertvoller als eine erfundene Edge. Trage dein Ergebnis am Ende ins Loop-Journal in reports/edge_search_plan_2026-07-27.md ein und committe mit Prefix feat:/fix:/docs:. Antworte auf Deutsch." --allowedTools "Read,Write,Edit,Bash,Grep,Glob" >> "%LOG_FILE%" 2>&1

echo [%DATE% %TIME%] Agent-Schritt beendet (exit=!ERRORLEVEL!) >> "%LOG_FILE%"

:done
echo [%DATE% %TIME%] EDGE ROUTINE ENDE >> "%LOG_FILE%"
popd
endlocal
exit /b 0
