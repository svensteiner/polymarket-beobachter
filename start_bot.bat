@echo off
setlocal enableextensions enabledelayedexpansion

rem =============================================================================
rem Weather Observer - Start Script with Auto-Restart
rem =============================================================================
rem
rem  Restart-Loop: Falls Python abstuerzt, wird der Bot automatisch neu gestartet.
rem  Max 50 Restarts, danach 10 Minuten Pause und Counter-Reset.
rem
rem  Usage:
rem    start_bot.bat          (default 900s interval)
rem    start_bot.bat 600      (custom interval in seconds)
rem =============================================================================

pushd "%~dp0"

rem --- Python finden ---
set "PYTHON_EXE="
if exist "%~dp0.venv\Scripts\python.exe" (
    set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
) else (
    call python -V >nul 2>nul && set "PYTHON_EXE=python"
    if not defined PYTHON_EXE (
        call py -3 -V >nul 2>nul && set "PYTHON_EXE=py -3"
    )
)

if not defined PYTHON_EXE (
    echo Python not found. Install Python 3.x or create a .venv in this folder.
    popd
    exit /b 1
)

if not exist "logs" mkdir "logs"

set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"

set "LOG_FILE=logs\cockpit_console.log"
set "RESTART_LOG=logs\restart.log"
set "INTERVAL=900"
if not "%~1"=="" set "INTERVAL=%~1"

set "RESTART_COUNT=0"
set "MAX_RESTARTS=50"

echo [%DATE% %TIME%] ========================================== >> "%RESTART_LOG%"
echo [%DATE% %TIME%] Bot-Starter gestartet (interval=%INTERVAL%s) >> "%RESTART_LOG%"

:loop
set /a RESTART_COUNT+=1
echo [%DATE% %TIME%] Start #!RESTART_COUNT! >> "%RESTART_LOG%"
echo [%DATE% %TIME%] --- Start #!RESTART_COUNT! --- >> "%LOG_FILE%"

"%PYTHON_EXE%" -u cockpit.py --scheduler --interval %INTERVAL% --no-color >> "%LOG_FILE%" 2>&1
set "EXIT_CODE=!ERRORLEVEL!"

echo [%DATE% %TIME%] Bot gestorben (exit code !EXIT_CODE!, Restart #!RESTART_COUNT!) >> "%RESTART_LOG%"

rem --- Sauberer Exit bei Code 0 (Ctrl+C / geplanter Stopp) ---
if "!EXIT_CODE!"=="0" (
    echo [%DATE% %TIME%] Sauberer Exit, kein Neustart. >> "%RESTART_LOG%"
    goto end
)

rem --- Max Restarts pruefen ---
if !RESTART_COUNT! GEQ %MAX_RESTARTS% (
    echo [%DATE% %TIME%] Max Restarts erreicht ^(!MAX_RESTARTS!^), Pause 10 Minuten... >> "%RESTART_LOG%"
    timeout /t 600 /nobreak >nul
    set "RESTART_COUNT=0"
    echo [%DATE% %TIME%] Counter zurueckgesetzt, weiter geht's. >> "%RESTART_LOG%"
)

echo [%DATE% %TIME%] Neustart in 30 Sekunden... >> "%RESTART_LOG%"
timeout /t 30 /nobreak >nul
goto loop

:end
echo [%DATE% %TIME%] Bot-Starter beendet. >> "%RESTART_LOG%"
popd
endlocal
