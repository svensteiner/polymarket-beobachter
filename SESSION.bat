@echo off
title Polymarket Observer - Session
pushd "%~dp0"

set "PYTHON_EXE="
if exist "%~dp0.venv\Scripts\python.exe" set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
if not defined PYTHON_EXE (
    where python >nul 2>nul && set "PYTHON_EXE=python"
)

set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set PYTHONUNBUFFERED=1

echo [%DATE% %TIME%] Session gestartet...
"%PYTHON_EXE%" -u cockpit.py --no-color
echo [%DATE% %TIME%] Session beendet (exit=%ERRORLEVEL%)
pause
popd
endlocal
