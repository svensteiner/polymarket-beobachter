# Erstellt eine Autostart-Verknuepfung im Windows Startup-Ordner

$WshShell = New-Object -ComObject WScript.Shell
$Startup = $WshShell.SpecialFolders("Startup")
$ShortcutPath = Join-Path $Startup "PolymarketBeobachter.lnk"

$Shortcut = $WshShell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = "wscript.exe"
$Shortcut.Arguments = "`"C:\Chatgpt_Codex\polymarket Beobachter\run_background.vbs`""
$Shortcut.WorkingDirectory = "C:\Chatgpt_Codex\polymarket Beobachter"
$Shortcut.Description = "Polymarket Beobachter Autostart"
$Shortcut.Save()

Write-Host "[OK] Autostart-Verknuepfung erstellt:" -ForegroundColor Green
Write-Host "     $ShortcutPath"
