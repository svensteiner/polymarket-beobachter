' =============================================================================
' POLYMARKET BEOBACHTER - BACKGROUND RUNNER
' =============================================================================
' Startet den Bot unsichtbar im Hintergrund (kein Fenster).
' Wird vom Windows Task Scheduler aufgerufen.
' =============================================================================

Set WshShell = CreateObject("WScript.Shell")
strPath = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)

' Wechsle ins Projektverzeichnis und starte Python unsichtbar
WshShell.CurrentDirectory = strPath
WshShell.Run "python cockpit.py --scheduler --interval 900", 0, False

' 0 = verstecktes Fenster
' False = nicht auf Beendigung warten
