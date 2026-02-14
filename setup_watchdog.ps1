# =============================================================================
# Weather Observer - Task Scheduler Setup
# =============================================================================
#
# Erstellt zwei Windows Scheduled Tasks:
#   1. WeatherObserver-Bot:      Startet den Bot bei User-Login
#   2. WeatherObserver-Watchdog: Prueft alle 5 Minuten ob der Bot lebt
#
# MUSS als Administrator ausgefuehrt werden!
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File setup_watchdog.ps1
#
# Deinstallation:
#   Unregister-ScheduledTask -TaskName "WeatherObserver-Bot" -Confirm:$false
#   Unregister-ScheduledTask -TaskName "WeatherObserver-Watchdog" -Confirm:$false
# =============================================================================

$ErrorActionPreference = "Stop"

$BotDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$StartBat = Join-Path $BotDir "start_bot.bat"
$WatchdogPs1 = Join-Path $BotDir "watchdog.ps1"

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  Weather Observer - Task Scheduler Setup"    -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Bot-Verzeichnis: $BotDir"
Write-Host ""

# --- Admin-Check ---
$currentPrincipal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $currentPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "FEHLER: Dieses Script muss als Administrator ausgefuehrt werden!" -ForegroundColor Red
    Write-Host ""
    Write-Host "Rechtsklick auf PowerShell -> 'Als Administrator ausfuehren'" -ForegroundColor Yellow
    Write-Host "Dann erneut: powershell -ExecutionPolicy Bypass -File setup_watchdog.ps1" -ForegroundColor Yellow
    exit 1
}

# --- Dateien pruefen ---
if (-not (Test-Path $StartBat)) {
    Write-Host "FEHLER: start_bot.bat nicht gefunden: $StartBat" -ForegroundColor Red
    exit 1
}
if (-not (Test-Path $WatchdogPs1)) {
    Write-Host "FEHLER: watchdog.ps1 nicht gefunden: $WatchdogPs1" -ForegroundColor Red
    exit 1
}

# =============================================================================
# Task 1: Bot bei Login starten
# =============================================================================

Write-Host "[1/2] Erstelle Task: WeatherObserver-Bot" -ForegroundColor Green

$taskName1 = "WeatherObserver-Bot"

# Alten Task entfernen falls vorhanden
if (Get-ScheduledTask -TaskName $taskName1 -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $taskName1 -Confirm:$false
    Write-Host "  Alter Task entfernt." -ForegroundColor Yellow
}

$action1 = New-ScheduledTaskAction `
    -Execute "cmd.exe" `
    -Argument "/c `"$StartBat`"" `
    -WorkingDirectory $BotDir

$trigger1 = New-ScheduledTaskTrigger -AtLogOn

$settings1 = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Days 365) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask `
    -TaskName $taskName1 `
    -Action $action1 `
    -Trigger $trigger1 `
    -Settings $settings1 `
    -Description "Startet den Weather Observer Bot bei User-Login" `
    -RunLevel Limited | Out-Null

Write-Host "  Task '$taskName1' erstellt." -ForegroundColor Green
Write-Host "  -> Startet bei Login: $StartBat" -ForegroundColor DarkGray

# =============================================================================
# Task 2: Watchdog alle 5 Minuten
# =============================================================================

Write-Host ""
Write-Host "[2/2] Erstelle Task: WeatherObserver-Watchdog" -ForegroundColor Green

$taskName2 = "WeatherObserver-Watchdog"

# Alten Task entfernen falls vorhanden
if (Get-ScheduledTask -TaskName $taskName2 -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $taskName2 -Confirm:$false
    Write-Host "  Alter Task entfernt." -ForegroundColor Yellow
}

$action2 = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-ExecutionPolicy Bypass -WindowStyle Hidden -File `"$WatchdogPs1`"" `
    -WorkingDirectory $BotDir

# Trigger: Alle 5 Minuten, unbegrenzt
$trigger2 = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes 5) `
    -RepetitionDuration (New-TimeSpan -Days 9999)

$settings2 = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 2) `
    -MultipleInstances IgnoreNew

Register-ScheduledTask `
    -TaskName $taskName2 `
    -Action $action2 `
    -Trigger $trigger2 `
    -Settings $settings2 `
    -Description "Prueft alle 5 Min ob der Weather Observer Bot noch lebt" `
    -RunLevel Limited | Out-Null

Write-Host "  Task '$taskName2' erstellt." -ForegroundColor Green
Write-Host "  -> Alle 5 Min: watchdog.ps1" -ForegroundColor DarkGray

# =============================================================================
# Zusammenfassung
# =============================================================================

Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host "  Setup abgeschlossen!" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
Write-Host ""
Write-Host "Erstellte Tasks:"
Write-Host "  1. $taskName1      -> Startet Bot bei Login"
Write-Host "  2. $taskName2 -> Heartbeat-Check alle 5 Min"
Write-Host ""
Write-Host "Pruefen:"
Write-Host "  Get-ScheduledTask | Where TaskName -like 'WeatherObserver*'" -ForegroundColor DarkGray
Write-Host "  taskschd.msc  (GUI)" -ForegroundColor DarkGray
Write-Host ""
Write-Host "Deinstallation:"
Write-Host "  Unregister-ScheduledTask -TaskName '$taskName1' -Confirm:`$false" -ForegroundColor DarkGray
Write-Host "  Unregister-ScheduledTask -TaskName '$taskName2' -Confirm:`$false" -ForegroundColor DarkGray
Write-Host ""
