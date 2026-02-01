@echo off
REM =============================================================================
REM POLYMARKET BEOBACHTER - START ALL
REM =============================================================================
REM
REM Startet alle aktivierten Module gleichzeitig.
REM Liest Konfiguration aus config/modules.yaml
REM
REM Usage:
REM   start_all.bat              - Normal starten
REM   start_all.bat --dashboard  - Nur Dashboard
REM   start_all.bat --scheduler  - Nur Scheduler
REM   start_all.bat --control    - Control Center GUI
REM
REM =============================================================================

title Polymarket Beobachter - Startup

cd /d "%~dp0"

echo.
echo  ====================================================
echo   POLYMARKET BEOBACHTER
echo   Startup Script
echo  ====================================================
echo.

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python nicht gefunden!
    echo Bitte Python installieren: https://python.org
    pause
    exit /b 1
)

REM Parse arguments
if "%1"=="--dashboard" goto :dashboard_only
if "%1"=="--scheduler" goto :scheduler_only
if "%1"=="--control" goto :control_center
if "%1"=="--help" goto :help

REM Default: Start Control Center
goto :control_center

:control_center
echo [INFO] Starte Control Center...
echo.
python control_center.py
goto :end

:dashboard_only
echo [INFO] Starte nur Dashboard...
echo.
start "Dashboard" python flet_dashboard.py --dark --refresh 30
echo Dashboard gestartet in neuem Fenster.
goto :end

:scheduler_only
echo [INFO] Starte nur Scheduler (Pipeline alle 15 Min)...
echo.
python cockpit.py --scheduler --interval 900
goto :end

:help
echo.
echo Verwendung:
echo   start_all.bat              - Control Center GUI (empfohlen)
echo   start_all.bat --dashboard  - Nur Dashboard starten
echo   start_all.bat --scheduler  - Nur Pipeline Scheduler
echo   start_all.bat --control    - Control Center GUI
echo   start_all.bat --help       - Diese Hilfe
echo.
goto :end

:end
echo.
echo  ====================================================
echo   Beendet
echo  ====================================================
