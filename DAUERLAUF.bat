@echo off
:: Auto-hide: bei normalem Start unsichtbar neu starten
if "%~1" NEQ "hidden" (
    powershell -WindowStyle Hidden -Command "Start-Process -FilePath 'cmd.exe' -ArgumentList '/c \"%~f0\" hidden' -WindowStyle Hidden -WorkingDirectory '%~dp0'"
    exit /b
)
setlocal enableextensions enabledelayedexpansion
title Polymarket Observer - Dauerlauf

pushd "%~dp0"

set "PYTHON_EXE="
if exist "%~dp0.venv\Scripts\python.exe" set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
if not defined PYTHON_EXE (
    where python >nul 2>nul && set "PYTHON_EXE=python"
)

if not exist "logs" mkdir "logs"

set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set PYTHONUNBUFFERED=1
set INTERVAL=900

set "LOG_FILE=logs\dauerlauf_restart.log"
set "RESTART_LOG=logs\restart.log"
set "RESTART_COUNT=0"
set "MAX_RESTARTS=50"

:: Log-Rotation: dauerlauf_restart.log auf 2 MB begrenzen (verhindert GB-Wachstum)
for %%F in ("%LOG_FILE%") do set "LOG_SIZE=%%~zF"
if defined LOG_SIZE if !LOG_SIZE! GTR 2097152 (
    del /q "%LOG_FILE%.old" 2>nul
    ren "%LOG_FILE%" "dauerlauf_restart.log.old" 2>nul
    echo [%DATE% %TIME%] Log rotiert (war !LOG_SIZE! Bytes) >> "%LOG_FILE%"
)

echo [%DATE% %TIME%] ===== DAUERLAUF gestartet ===== >> "%RESTART_LOG%"

:loop
set /a RESTART_COUNT+=1
echo [%DATE% %TIME%] --- Start #!RESTART_COUNT! --- >> "%RESTART_LOG%"

"%PYTHON_EXE%" -u cockpit.py --scheduler --interval %INTERVAL% --no-color >> "%LOG_FILE%" 2>&1
set "EXIT_CODE=!ERRORLEVEL!"

echo [%DATE% %TIME%] Beendet (exit=!EXIT_CODE!, #!RESTART_COUNT!) >> "%RESTART_LOG%"

if "!EXIT_CODE!"=="0" goto end

if !RESTART_COUNT! GEQ %MAX_RESTARTS% (
    echo [%DATE% %TIME%] Max Restarts - Pause 10 Min >> "%RESTART_LOG%"
    timeout /t 600 /nobreak >nul
    set "RESTART_COUNT=0"
)

echo [%DATE% %TIME%] Neustart in 30s... >> "%RESTART_LOG%"
timeout /t 30 /nobreak >nul
goto loop

:end
echo [%DATE% %TIME%] Sauberer Exit. >> "%RESTART_LOG%"
popd
endlocal
