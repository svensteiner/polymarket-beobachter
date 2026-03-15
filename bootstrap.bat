@echo off
REM =============================================================================
REM POLYMARKET BEOBACHTER - BOOTSTRAP SCRIPT
REM =============================================================================
REM
REM This script sets up the development environment for the first time.
REM Run this once after cloning the repository.
REM
REM =============================================================================

setlocal EnableDelayedExpansion

echo.
echo ===================================================
echo   Polymarket Beobachter - Setup
echo ===================================================
echo.

REM Check if Python is available
python --version >nul 2>&1
if errorlevel 1 (
    py -3 --version >nul 2>&1
    if errorlevel 1 (
        echo [ERROR] Python nicht gefunden!
        echo         Bitte Python 3.10+ installieren: https://www.python.org/downloads/
        exit /b 1
    )
    set PYTHON_CMD=py -3
) else (
    set PYTHON_CMD=python
)

echo [1/5] Python gefunden:
%PYTHON_CMD% --version

REM Create virtual environment if it doesn't exist
if not exist ".venv" (
    echo.
    echo [2/5] Erstelle Virtual Environment...
    %PYTHON_CMD% -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Virtual Environment konnte nicht erstellt werden!
        exit /b 1
    )
    echo       Virtual Environment erstellt.
) else (
    echo.
    echo [2/5] Virtual Environment existiert bereits.
)

REM Activate venv and install dependencies
echo.
echo [3/5] Installiere Abhaengigkeiten...
call .venv\Scripts\activate.bat

pip install --upgrade pip >nul 2>&1
pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Installation fehlgeschlagen!
    exit /b 1
)
echo       Abhaengigkeiten installiert.

REM Copy .env.example to .env if not exists
echo.
echo [4/5] Konfiguration...
if not exist ".env" (
    copy .env.example .env >nul
    echo       .env aus .env.example erstellt.
    echo       WICHTIG: Bitte .env Datei ausfuellen!
) else (
    echo       .env existiert bereits.
)

REM Create necessary directories
echo.
echo [5/5] Erstelle Verzeichnisse...
if not exist "logs" mkdir logs
if not exist "data" mkdir data
if not exist "output" mkdir output
if not exist "paper_trader\logs" mkdir paper_trader\logs
if not exist "paper_trader\reports" mkdir paper_trader\reports
echo       Verzeichnisse erstellt.

REM Run quick test
echo.
echo ===================================================
echo   Teste Installation...
echo ===================================================
%PYTHON_CMD% -c "import requests; import httpx; import schedule; print('OK: Alle Module geladen')"
if errorlevel 1 (
    echo [WARNING] Einige Module fehlen!
) else (
    echo [OK] Installation erfolgreich!
)

echo.
echo ===================================================
echo   Setup abgeschlossen!
echo ===================================================
echo.
echo Naechste Schritte:
echo   1. .env Datei mit API-Keys ausfuellen
echo   2. Bot starten mit: python cockpit.py --run-once
echo   3. Fuer Dauerbetrieb: setup_watchdog.ps1 ausfuehren
echo.

endlocal
