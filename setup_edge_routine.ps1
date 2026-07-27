# =============================================================================
# Edge Routine - Task Scheduler Setup (3x taeglich)
# =============================================================================
#
# Erstellt EINEN Windows Scheduled Task:
#   WeatherObserver-EdgeRoutine: laeuft 07:00, 13:00, 19:00
#     -> analytics/edge_routine.py (alle schweren Edge-Scans + Digest)
#     -> danach Claude-Agent, der am obersten Punkt der Arbeitsliste arbeitet
#
# Der Task laeuft als aktueller Benutzer (kein Admin noetig, keine Elevation).
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File setup_edge_routine.ps1
#
# Nur Analyse, ohne Agent (spart API-Budget):
#   powershell -ExecutionPolicy Bypass -File setup_edge_routine.ps1 -NoAgent
#
# Deinstallation:
#   Unregister-ScheduledTask -TaskName "WeatherObserver-EdgeRoutine" -Confirm:$false
# =============================================================================

param(
    [switch]$NoAgent,
    [string[]]$Times = @("07:00", "13:00", "19:00")
)

$ErrorActionPreference = "Stop"

$BotDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RoutineBat = Join-Path $BotDir "edge_routine.bat"
$taskName = "WeatherObserver-EdgeRoutine"

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  Edge Routine - Task Scheduler Setup"       -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Verzeichnis: $BotDir"
Write-Host "Zeiten:      $($Times -join ', ')"
Write-Host "Agent-Schritt: $(if ($NoAgent) { 'AUS (nur Analyse)' } else { 'AN' })"
Write-Host ""

if (-not (Test-Path $RoutineBat)) {
    Write-Host "FEHLER: edge_routine.bat nicht gefunden: $RoutineBat" -ForegroundColor Red
    exit 1
}

# Alten Task entfernen falls vorhanden
if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    Write-Host "  Alter Task entfernt." -ForegroundColor Yellow
}

# Agent-Schritt via Umgebungsvariable im cmd-Aufruf steuern
if ($NoAgent) {
    # Quoted set: 'set EDGE_AGENT=0 &&' would put the trailing space INTO the value.
    $argument = "/c set `"EDGE_AGENT=0`" && `"$RoutineBat`""
} else {
    $argument = "/c `"$RoutineBat`""
}

$action = New-ScheduledTaskAction `
    -Execute "cmd.exe" `
    -Argument $argument `
    -WorkingDirectory $BotDir

# Drei tägliche Trigger
$triggers = @()
foreach ($t in $Times) {
    $triggers += New-ScheduledTaskTrigger -Daily -At $t
}

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -MultipleInstances IgnoreNew

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $triggers `
    -Settings $settings `
    -Description "Edge-Suche: schwere Scans + Digest, danach Agent-Arbeit am obersten Punkt der Arbeitsliste (3x taeglich)" `
    -RunLevel Limited | Out-Null

Write-Host "  Task '$taskName' erstellt." -ForegroundColor Green
Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host "  Setup abgeschlossen!" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
Write-Host ""
Write-Host "Laeuft taeglich um: $($Times -join ', ')"
Write-Host ""
Write-Host "Sofort testen:"
Write-Host "  Start-ScheduledTask -TaskName '$taskName'" -ForegroundColor DarkGray
Write-Host "Ergebnis:"
Write-Host "  analytics\edge_routine_digest.md   (Digest + Arbeitsliste)" -ForegroundColor DarkGray
Write-Host "  logs\edge_routine.log              (Lauf-Log)" -ForegroundColor DarkGray
Write-Host "Status:"
Write-Host "  Get-ScheduledTask -TaskName '$taskName'" -ForegroundColor DarkGray
Write-Host "Deinstallation:"
Write-Host "  Unregister-ScheduledTask -TaskName '$taskName' -Confirm:`$false" -ForegroundColor DarkGray
Write-Host ""
