# Read-only-Forschung

Diese Forschungsstrecke ist paper-only. Sie erstellt keine Live-Orders und verändert kein Handelsbuch oder Kapital. Ergebnisse sind Messungen und keine Gewinnzusage.

## Einrichtung

Aus der Projektmappe:

```powershell
.\setup_research.ps1
```

Das Skript erstellt `.venv-research` mit Python 3.12 und prüft die Imports. Der Scanner benötigt nur die Python-Standardbibliothek. Es gibt keinen Fallback auf eine globale Python-Installation.

## Start und Status

```powershell
.\DAUERLAUF.bat
```

Die Batch-Datei öffnet den Supervisor verborgen. Pro Zyklus startet er `research_runner.py --once`. Die Standardcadenz beträgt 900 Sekunden; ein Kindprozess darf höchstens 300 Sekunden laufen. Fehler führen zu einer exponentiellen Pause bis maximal 3600 Sekunden.

`output/research_supervisor.json` enthält `status` (`starting`, `running`, `healthy`, `degraded`, `failed`), `child_pid`, `last_success`, `consecutive_failures` und `next_due`. Die Zeitfelder sind Unix-Wall-Clock-Sekunden. `child_pid` ist die PID des aktuellen Runner-Kindprozesses, nicht die PID des Supervisors. Ein zweiter Supervisor endet mit Exitcode 2; bei einem bereits laufenden Runner wird kein zweiter Runner gestartet.

Fordere einen kontrollierten Stop für die aktuell laufende Supervisor-Instanz an:

```powershell
.\.venv-research\Scripts\python.exe research_supervisor.py --stop
```

Die Anforderung wird atomar mit der aktuellen `run_id` in `output/research_supervisor.stop` gespeichert. Eine alte Anforderung wird von einer neuen Instanz ignoriert. Der Supervisor beendet ausschließlich sein eigenes Kind, schreibt `stopped` und beendet sich mit Exitcode 0; die Batch-Datei startet ihn deshalb nicht neu. Während des Wartens wird die Anforderung spätestens innerhalb einer Sekunde geprüft.

Für Diagnosezwecke kann der genaue Prozess schreibgeschützt geprüft werden:

```powershell
Get-CimInstance Win32_Process | Where-Object {
  $_.CommandLine -like '*research_supervisor.py*' -or
  $_.CommandLine -like '*research_runner.py --once*'
} | Select-Object ProcessId,CommandLine
```

Verwende keinen breiten Namenfilter und kein allgemeines `taskkill`. Ein sichtbarer Supervisor kann mit Ctrl+C beendet werden; dabei wird sein eigenes Kind aufgeräumt. Ein fehlendes Runtime-Verzeichnis wird als `runtime_missing` im Status vermerkt; danach zuerst `setup_research.ps1` erfolgreich ausführen. `research_runner.py --once` nicht parallel zum Supervisor starten.

## Offline-Koordinator und optionale API

Die lokale Planprüfung läuft ohne Netzwerk:

```powershell
.\.venv-research\Scripts\python.exe -c "from analytics.research_coordinator import main; raise SystemExit(main(['--model','gpt-5.6-luna']))"
```

Die OpenAI-Python-SDK-Umgebung ist getrennt und optional:

```powershell
py -3.12 -m venv .venv-agentic
.\.venv-agentic\Scripts\python.exe -m pip install -r requirements-agentic.txt
```

Die Installation startet keine Calls oder Scheduler. SDK-Sessions besitzen kein garantiertes hartes Kostenlimit, etwa 5 EUR; eine lokale Reservierung ist kein Kostenplafond. Die Agents-API ist kein integrierter Produktionsscheduler, und es gibt daraus keinen Nachweis für Edge oder Live-Handel.
