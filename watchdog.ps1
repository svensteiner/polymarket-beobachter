# =============================================================================
# Weather Observer - Watchdog
# =============================================================================
#
# Wird alle 5 Minuten vom Windows Task Scheduler aufgerufen.
# Prueft ob der Bot noch lebt (Heartbeat) und startet ihn bei Bedarf neu.
#
# Usage (manuell):
#   powershell -ExecutionPolicy Bypass -File watchdog.ps1
# =============================================================================

$ErrorActionPreference = "Continue"

$BotDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$HeartbeatFile = Join-Path $BotDir "logs\heartbeat.txt"
$WatchdogLog = Join-Path $BotDir "logs\watchdog.log"
$StartBat = Join-Path $BotDir "start_bot.bat"
$LockFile = Join-Path $BotDir "cockpit.lock"
$MaxHeartbeatAgeMinutes = 20

# Sicherstellen dass logs-Ordner existiert
$LogDir = Join-Path $BotDir "logs"
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }

function Write-Log {
    param([string]$Message)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[$timestamp] $Message"
    Add-Content -Path $WatchdogLog -Value $line -Encoding UTF8
}

function Get-BotProcess {
    # Finde Python-Prozesse die cockpit.py ausfuehren
    Get-WmiObject Win32_Process -Filter "Name='python.exe' or Name='python3.exe'" 2>$null |
        Where-Object { $_.CommandLine -like "*cockpit.py*" }
}

function Test-BotRunning {
    $procs = Get-BotProcess
    return ($null -ne $procs -and @($procs).Count -gt 0)
}

function Stop-Bot {
    Write-Log "Stoppe haengenden Bot-Prozess..."
    $procs = Get-BotProcess
    foreach ($proc in $procs) {
        try {
            Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
            Write-Log "  PID $($proc.ProcessId) gekillt."
        } catch {
            Write-Log "  Fehler beim Killen von PID $($proc.ProcessId): $_"
        }
    }
    # Lockfile aufraeumen
    if (Test-Path $LockFile) {
        Remove-Item $LockFile -Force -ErrorAction SilentlyContinue
        Write-Log "  Lockfile entfernt."
    }
    Start-Sleep -Seconds 2
}

function Start-Bot {
    Write-Log "Starte Bot via start_bot.bat..."
    try {
        # Starte als verstecktes Fenster
        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName = "cmd.exe"
        $psi.Arguments = "/c `"$StartBat`""
        $psi.WorkingDirectory = $BotDir
        $psi.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden
        $psi.CreateNoWindow = $true
        [System.Diagnostics.Process]::Start($psi) | Out-Null
        Write-Log "Bot gestartet."
    } catch {
        Write-Log "FEHLER beim Starten: $_"
    }
}

# =============================================================================
# HAUPTLOGIK
# =============================================================================

Write-Log "--- Watchdog-Check ---"

# Fall 1: Kein Heartbeat-File -> Bot wurde noch nie gestartet
if (-not (Test-Path $HeartbeatFile)) {
    Write-Log "Kein Heartbeat gefunden. Bot scheint nie gestartet."
    if (-not (Test-BotRunning)) {
        Write-Log "Kein Bot-Prozess aktiv."
        Start-Bot
    } else {
        Write-Log "Bot-Prozess laeuft aber kein Heartbeat - warte ab."
    }
    exit 0
}

# Fall 2: Heartbeat vorhanden - Alter pruefen
try {
    $heartbeatContent = Get-Content $HeartbeatFile -Raw -Encoding UTF8
    $heartbeatTime = [datetime]::Parse($heartbeatContent.Trim())
    $age = (Get-Date) - $heartbeatTime
    $ageMinutes = [math]::Round($age.TotalMinutes, 1)
    Write-Log "Heartbeat-Alter: $ageMinutes Minuten"
} catch {
    Write-Log "Heartbeat unlesbar: $_"
    $ageMinutes = 999
}

# Fall 3: Heartbeat ist frisch genug -> alles OK
if ($ageMinutes -lt $MaxHeartbeatAgeMinutes) {
    Write-Log "Bot ist lebendig (Heartbeat $ageMinutes min alt). OK."
    exit 0
}

# Fall 4: Heartbeat ist zu alt -> Bot haengt oder ist tot
Write-Log "WARNUNG: Heartbeat zu alt ($ageMinutes min > $MaxHeartbeatAgeMinutes min Limit)!"

if (Test-BotRunning) {
    Write-Log "Bot-Prozess existiert noch - haengt vermutlich."
    Stop-Bot
}

Start-Bot
Write-Log "Neustart durchgefuehrt."
exit 0
