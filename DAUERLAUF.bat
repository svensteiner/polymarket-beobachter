@echo off
:: Hidden research loop; locking, status, and rotation live in research_runner.py.
if "%~1" NEQ "hidden" (
    powershell -NoProfile -WindowStyle Hidden -Command "Start-Process -FilePath 'cmd.exe' -ArgumentList '/c \"%~f0\" hidden' -WindowStyle Hidden -WorkingDirectory '%~dp0'"
    exit /b
)
setlocal EnableExtensions EnableDelayedExpansion
pushd "%~dp0"
set "PYTHON_EXE=%~dp0.venv-research\Scripts\python.exe"
if not exist "%PYTHON_EXE%" (
    echo Research runtime missing: %PYTHON_EXE% 1>&2
    >"%~dp0output\research_supervisor.json" echo {"status":"failed","error":"runtime_missing"}
    exit /b 3
)
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set PYTHONUNBUFFERED=1
set "ATTEMPT=0"
:run
set /a ATTEMPT+=1
"%PYTHON_EXE%" -u research_supervisor.py
set "EXIT_CODE=!ERRORLEVEL!"
if "!EXIT_CODE!"=="0" goto done
if "!EXIT_CODE!"=="2" goto done
if "!EXIT_CODE!"=="3" goto done
if !ATTEMPT! GEQ 3 goto done
timeout /t 30 /nobreak >nul
goto run
:done
popd
endlocal & exit /b %EXIT_CODE%
