# =============================================================================
# POLYMARKET BEOBACHTER - TASK SCHEDULER SETUP
# =============================================================================
# Erstellt Windows Task Scheduler Jobs fuer 24/7 Betrieb.
#
# Ausfuehren mit: powershell -ExecutionPolicy Bypass -File setup_scheduler.ps1
# =============================================================================

$ErrorActionPreference = "Stop"
$ProjectPath = Split-Path -Parent $MyInvocation.MyCommand.Path
$TaskName = "PolymarketBeobachter"

Write-Host ""
Write-Host "====================================================" -ForegroundColor Cyan
Write-Host "  POLYMARKET BEOBACHTER - Task Scheduler Setup" -ForegroundColor Cyan
Write-Host "====================================================" -ForegroundColor Cyan
Write-Host ""

# Pruefe ob Task bereits existiert
$existingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue

if ($existingTask) {
    Write-Host "[INFO] Task '$TaskName' existiert bereits." -ForegroundColor Yellow
    $choice = Read-Host "Ueberschreiben? (j/n)"
    if ($choice -ne "j") {
        Write-Host "[ABBRUCH] Keine Aenderungen vorgenommen." -ForegroundColor Red
        exit 0
    }
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "[OK] Alter Task entfernt." -ForegroundColor Green
}

# Task-Aktion: Fuehre run_pipeline_once.bat alle 15 Minuten aus
$Action = New-ScheduledTaskAction -Execute "cmd.exe" `
    -Argument "/c `"$ProjectPath\run_pipeline_once.bat`"" `
    -WorkingDirectory $ProjectPath

# Trigger 1: Bei Benutzeranmeldung starten
$TriggerLogon = New-ScheduledTaskTrigger -AtLogOn

# Trigger 2: Alle 15 Minuten wiederholen (ab jetzt, unbegrenzt)
$TriggerRepeat = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes 15) `
    -RepetitionDuration (New-TimeSpan -Days 9999)

# Einstellungen
$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable `
    -MultipleInstances IgnoreNew

# Task erstellen
$Task = New-ScheduledTask -Action $Action `
    -Trigger $TriggerLogon, $TriggerRepeat `
    -Settings $Settings `
    -Description "Polymarket Beobachter - Sammelt Marktdaten alle 15 Minuten"

# Task registrieren (als aktueller Benutzer)
Register-ScheduledTask -TaskName $TaskName -InputObject $Task

Write-Host ""
Write-Host "[OK] Task erfolgreich erstellt!" -ForegroundColor Green
Write-Host ""
Write-Host "Details:" -ForegroundColor Cyan
Write-Host "  - Name: $TaskName"
Write-Host "  - Intervall: Alle 15 Minuten"
Write-Host "  - Start: Bei Anmeldung + sofort"
Write-Host "  - Laeuft auch im Akkubetrieb"
Write-Host ""
Write-Host "WICHTIG: Damit der Bot auch bei geschlossenem Laptop laeuft," -ForegroundColor Yellow
Write-Host "         muss der Standby-Modus deaktiviert werden!" -ForegroundColor Yellow
Write-Host ""
Write-Host "Zum Deaktivieren von Standby:" -ForegroundColor Cyan
Write-Host "  1. Einstellungen > System > Strom"
Write-Host "  2. Bildschirm & Standby > 'Nie'"
Write-Host "  oder: powercfg -change -standby-timeout-ac 0"
Write-Host ""

# Task sofort starten
Write-Host "Starte Task jetzt..." -ForegroundColor Cyan
Start-ScheduledTask -TaskName $TaskName

Write-Host "[OK] Task laeuft!" -ForegroundColor Green
Write-Host ""
