# =============================================================================
# Grok Bot Desktop - Windows Setup
# =============================================================================
#
# Installiert die Grok-Bot-Desktop-App und bindet den lokalen
# Polymarket-Weather MCP-Server an Cursor / Grok Bot.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File setup_grok_bot.ps1
#   oder doppelklick auf install_grok_bot.bat
# =============================================================================

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$BotDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$DownloadPage = "https://x.ai/bot"
$ServerName = "polymarket-beobachter"

function Write-Step($message) {
    Write-Host ""
    Write-Host $message -ForegroundColor Cyan
}

function Write-Ok($message) {
    Write-Host "  $message" -ForegroundColor Green
}

function Write-Warn($message) {
    Write-Host "  $message" -ForegroundColor Yellow
}

function Get-WindowsArch {
    $arch = $env:PROCESSOR_ARCHITECTURE
    if ($arch -eq "ARM64") { return "arm64" }
    return "x64"
}

function Find-PythonExe {
    $candidates = @(
        (Join-Path $BotDir ".venv\Scripts\python.exe"),
        "C:\Program Files\Python314\python.exe",
        "C:\Program Files\Python313\python.exe",
        "C:\Program Files\Python312\python.exe",
        "C:\Program Files\Python311\python.exe",
        "C:\Program Files\Python310\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python314\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python310\python.exe"
    )
    foreach ($path in $candidates) {
        if ($path -and (Test-Path $path)) { return $path }
    }
    $fromPath = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($fromPath) { return $fromPath.Source }
    $pyLauncher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($pyLauncher) { return $pyLauncher.Source }
    return $null
}

function Find-GrokBotExe {
    $candidates = @(
        "$env:LOCALAPPDATA\Programs\Grok Bot\Grok Bot.exe",
        "$env:LOCALAPPDATA\Programs\grok-bot\Grok Bot.exe",
        "$env:LOCALAPPDATA\Grok Bot\Grok Bot.exe",
        "${env:ProgramFiles}\Grok Bot\Grok Bot.exe",
        "${env:ProgramFiles(x86)}\Grok Bot\Grok Bot.exe"
    )
    foreach ($path in $candidates) {
        if (Test-Path $path) { return $path }
    }
    $roots = @(
        "$env:LOCALAPPDATA\Programs",
        ${env:ProgramFiles}
    )
    foreach ($root in $roots) {
        if (-not (Test-Path $root)) { continue }
        $hit = Get-ChildItem -Path $root -Filter "Grok Bot.exe" -Recurse -Depth 4 -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($hit) { return $hit.FullName }
    }
    return $null
}

function Get-InstallerUrl($arch) {
    $updateUrl = "https://api2.cursor.sh/updates/api/update/win32-$arch/sand/0.0.0/stable"
    Write-Host "  Update-API: $updateUrl"
    $response = Invoke-RestMethod -Uri $updateUrl
    if (-not $response.url) {
        throw "Update-API lieferte keine Installer-URL."
    }
    Write-Host "  Version: $($response.version)"
    return $response.url
}

function Install-GrokBotApp($arch) {
    $existing = Find-GrokBotExe
    if ($existing) {
        Write-Ok "Bereits installiert: $existing"
        return $existing
    }

    Write-Host "  Lade aktuellen Installer ..."
    $installerUrl = Get-InstallerUrl $arch
    $installerPath = Join-Path $env:TEMP "Grok_Bot_Setup.exe"
    Invoke-WebRequest -Uri $installerUrl -OutFile $installerPath -UseBasicParsing
    Write-Ok "Installer: $installerPath"

    Write-Host "  Starte stille Installation ..."
    $proc = Start-Process -FilePath $installerPath -ArgumentList "/S" -PassThru -Wait
    if ($proc.ExitCode -ne 0 -and $proc.ExitCode -ne $null) {
        Write-Warn "Stille Installation Exit $($proc.ExitCode) - starte interaktiven Installer."
        Start-Process -FilePath $installerPath -Wait
    }

    Start-Sleep -Seconds 3
    $installed = Find-GrokBotExe
    if (-not $installed) {
        Write-Warn "Grok Bot.exe noch nicht gefunden. Falls der Installer ein Fenster oeffnete, dort bestaetigen."
        Write-Warn "Manueller Download: $DownloadPage"
        return $null
    }
    Write-Ok "Installiert: $installed"
    return $installed
}

function Install-McpPackage($pythonExe) {
    if (-not $pythonExe) {
        Write-Warn "Python nicht gefunden. MCP-Paket wird spaeter manuell installiert: pip install mcp"
        return
    }
    Write-Host "  Python: $pythonExe"
    & $pythonExe -m pip install --quiet --upgrade mcp
    if ($LASTEXITCODE -ne 0) {
        throw "pip install mcp fehlgeschlagen."
    }
    Write-Ok "Paket mcp installiert."
}

function Invoke-DesktopMcpMerge($pythonExe, $modeArgs) {
    $helper = Join-Path $BotDir "mcp_server\desktop_mcp.py"
    if (-not $pythonExe) {
        throw "Python wird zum Schreiben der MCP-Config benoetigt."
    }
    & $pythonExe $helper @modeArgs
    if ($LASTEXITCODE -ne 0) {
        throw "MCP-Config schreiben fehlgeschlagen ($modeArgs)."
    }
}

function Merge-CursorMcp($pythonExe, $command, $argsJson, $cwd) {
    $cursorDir = Join-Path $env:USERPROFILE ".cursor"
    if (-not (Test-Path $cursorDir)) {
        New-Item -ItemType Directory -Path $cursorDir | Out-Null
    }
    $configPath = Join-Path $cursorDir "mcp.json"
    Invoke-DesktopMcpMerge $pythonExe @("cursor", $configPath, $ServerName, $command, $argsJson, $cwd)
    Write-Ok "Cursor MCP: $configPath"
}

function Merge-GrokToml($pythonExe, $command, $argsJson) {
    $grokDir = Join-Path $env:USERPROFILE ".grok"
    if (-not (Test-Path $grokDir)) {
        New-Item -ItemType Directory -Path $grokDir | Out-Null
    }
    $configPath = Join-Path $grokDir "config.toml"
    Invoke-DesktopMcpMerge $pythonExe @("grok", $configPath, $ServerName, $command, $argsJson)
    Write-Ok "Grok MCP: $configPath"
}

function New-DesktopShortcut($targetPath) {
    if (-not $targetPath -or -not (Test-Path $targetPath)) { return }
    $desktop = [Environment]::GetFolderPath("Desktop")
    $shortcutPath = Join-Path $desktop "Grok Bot.lnk"
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $targetPath
    $shortcut.WorkingDirectory = Split-Path -Parent $targetPath
    $shortcut.Description = "Grok Bot - Weather Observer Fuehrungskraft"
    $shortcut.Save()
    Write-Ok "Desktop-Verknuepfung: $shortcutPath"
}

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  Grok Bot Desktop - Weather Observer" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Projekt: $BotDir"

$arch = Get-WindowsArch
Write-Host "Architektur: $arch"

Write-Step "[1/4] Grok Bot Desktop-App"
$exePath = $null
try {
    $exePath = Install-GrokBotApp $arch
} catch {
    Write-Warn "Download/Installation fehlgeschlagen: $($_.Exception.Message)"
    Write-Warn "Bitte manuell laden: $DownloadPage"
}

Write-Step "[2/4] Python MCP-Paket"
$pythonExe = Find-PythonExe
try {
    Install-McpPackage $pythonExe
} catch {
    Write-Warn $_.Exception.Message
}

Write-Step "[3/4] MCP an Cursor / Grok Bot anbinden"
$mcpCommand = if ($pythonExe) { $pythonExe } else { "python" }
$argsJson = '["-m","mcp_server"]'
$batPath = Join-Path $BotDir "run_mcp_server.bat"
$grokArgsJson = '["/c",' + ($batPath | ConvertTo-Json -Compress) + ']'
if ($pythonExe) {
    Merge-CursorMcp $pythonExe $mcpCommand $argsJson $BotDir
    Merge-GrokToml $pythonExe "cmd" $grokArgsJson
} else {
    Write-Warn "Python fehlt - MCP-Config nicht geschrieben. Python 3.10+ installieren und Setup erneut ausfuehren."
}
Write-Ok "Projekt-Configs: .cursor\mcp.json , .grok\config.toml"

Write-Step "[4/4] Desktop-Verknuepfung"
New-DesktopShortcut $exePath

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  Naechste Schritte" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "1. Grok Bot oeffnen und mit Cursor anmelden"
Write-Host "2. Bot anlegen:"
Write-Host "     Name: Weather Observer"
Write-Host "     Job:  Strategie-Manager fuer den Weather Paper-Trader"
Write-Host "3. Erste Nachricht:"
Write-Host "     Wie laeuft der Weather-Bot? Status, Kapital, Positionen, Health."
Write-Host "     Kein Live-Trading. Nichts aendern, nur reporten."
Write-Host ""
Write-Host "Anleitung: docs\GROK_BOT_DESKTOP.md"
Write-Host "Download:  $DownloadPage"
Write-Host ""

if ($exePath) {
    try {
        Start-Process $exePath
        Write-Ok "Grok Bot gestartet."
    } catch {
        Write-Warn "Konnte Grok Bot nicht starten. Bitte Startmenue verwenden."
    }
}

exit 0
