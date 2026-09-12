@echo off
title Polymarket Observer - Research Session
setlocal
pushd "%~dp0"
set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=python"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set PYTHONUNBUFFERED=1
"%PYTHON_EXE%" -u research_runner.py --once
echo [%DATE% %TIME%] Research session ended (exit=%ERRORLEVEL%)
popd
endlocal
