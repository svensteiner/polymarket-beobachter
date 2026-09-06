@echo off
cd /d "%~dp0"

if not exist "logs" mkdir logs

:: Python in bekannten Pfaden suchen (Reihenfolge: System > User > PATH)
set PYTHON_EXE=

if exist "C:\Program Files\Python314\python.exe" (
    set PYTHON_EXE=C:\Program Files\Python314\python.exe
    goto :run
)
if exist "C:\Program Files\Python313\python.exe" (
    set PYTHON_EXE=C:\Program Files\Python313\python.exe
    goto :run
)
if exist "C:\Program Files\Python312\python.exe" (
    set PYTHON_EXE=C:\Program Files\Python312\python.exe
    goto :run
)
if exist "C:\Program Files\Python311\python.exe" (
    set PYTHON_EXE=C:\Program Files\Python311\python.exe
    goto :run
)
if exist "C:\Program Files\Python310\python.exe" (
    set PYTHON_EXE=C:\Program Files\Python310\python.exe
    goto :run
)
if exist "%LOCALAPPDATA%\Programs\Python\Python314\python.exe" (
    set PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Python314\python.exe
    goto :run
)
if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" (
    set PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Python313\python.exe
    goto :run
)
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
    set PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Python312\python.exe
    goto :run
)
if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" (
    set PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Python311\python.exe
    goto :run
)
if exist "%LOCALAPPDATA%\Programs\Python\Python310\python.exe" (
    set PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Python310\python.exe
    goto :run
)
if exist "%~dp0.venv\Scripts\python.exe" (
    set PYTHON_EXE=%~dp0.venv\Scripts\python.exe
    goto :run
)

:: Fallback: python aus PATH (ohne Microsoft Store Fake)
where /q python.exe && set PYTHON_EXE=python.exe

:run
if "%PYTHON_EXE%"=="" (
    echo Python nicht gefunden >> "%~dp0logs\mcp_server_error.log"
    exit /b 1
)

"%PYTHON_EXE%" -m mcp_server 2>> "%~dp0logs\mcp_server_error.log"
