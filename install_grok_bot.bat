@echo off
cd /d "%~dp0"
echo.
echo ===================================================
echo   Grok Bot Desktop - Installation
echo ===================================================
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_grok_bot.ps1"
set EXITCODE=%ERRORLEVEL%
echo.
if not "%EXITCODE%"=="0" (
    echo Installation fehlgeschlagen. Code: %EXITCODE%
    pause
    exit /b %EXITCODE%
)
pause
