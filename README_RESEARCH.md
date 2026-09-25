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

## Read-only-Gesundheitsprüfung

Die Prüfung liest den Supervisorstatus und prüft die Prozesskennung des
Supervisors sowie eines laufenden Kindprozesses:

```powershell
.\.venv-research\Scripts\python.exe research_health.py
```

Die Ausgabe ist JSON. Exitcode `0` bedeutet `healthy` oder `running` innerhalb
der Frist, Exitcode `1` bedeutet `stale`, `failed`, `degraded` oder `stopped`,
Exitcode `2` bedeutet `unknown` (zum Beispiel fehlender Status, falsche PID
oder nicht prüfbare Identität). Ein gesunder Supervisor darf bis `next_due`
warten; die Toleranz beträgt 30 Sekunden. Ein laufendes Kind darf 300 Sekunden
laufen. Zeitstempel sind Unix-Wall-Clock-Werte; monotone Laufzeitmessung wird
nicht mit ihnen verglichen.

Die Identitätsprüfung verwendet PID und Skriptnamen in der Kommandozeile;
sie ist keine Absicherung gegen manipulierte Statusdateien oder gleichnamige
Skripte. Ein bestätigter Stop beendet auch den Windows-Starter ohne Neustart.

## Offline-Agent-Lebenszyklus

Vorbereitung persistiert einen unveränderlichen Entwurf lokal; sie erzeugt
keinen Client und keine Session:

```powershell
.\.venv-research\Scripts\python.exe research_agent.py --store output\agent_runs.json prepare --model gpt-5.6-luna
.\.venv-research\Scripts\python.exe research_agent.py --store output\agent_runs.json show --run-key <run-key>
```

Der Entwurf akzeptiert nur einen vollständigen, read-only Snapshot: `status` muss
`ok` sein, die drei Schutzflags müssen exakt `research_only=true`,
`live_orders=false` und `ledger_mutations=false` lauten. `started_at` und
`finished_at` brauchen eine Zeitzone; der Scan darf höchstens 30 Minuten alt
sein und höchstens fünf Sekunden in der Zukunft liegen. Nur erlaubte Zähler und
der normalisierte UTC-Wert von `finished_at` werden in den kanonischen Input
übernommen. Ein älter gewordener Entwurf wird bei jeder späteren Dispatch-
Validierung verworfen. Derselbe Snapshot behält seine Kennung; ein neuer
Scannerlauf erhält auch bei identischen Zählern eine andere Kennung. Alte
gespeicherte Läufe bleiben für Anzeige und Abgleich erhalten, müssen bei Bedarf
aber mit einem aktuellen Snapshot neu vorbereitet werden.

Diese Frist betrifft den Forschungsbericht. Sie bestätigt weder aktuelle
Orderbücher noch Ausführbarkeit oder einen nachgewiesenen Handelsvorteil.

Nur eine bereits gespeicherte Session darf abgeglichen werden. Dafür ist die
optionale OpenAI-Python-SDK-Umgebung nötig:

```powershell
.\.venv-agentic\Scripts\python.exe research_agent.py --store output\agent_runs.json reconcile --run-key <run-key> --timeout 30
```

Der gespeicherte Lauf muss Session- und Agent-Kennung enthalten. Beim Abgleich
müssen die zurückgegebene Session, ihr Agent und die Kennungen jedes Turns dazu
passen. Nachrichten werden über ihre Turn-Kennung zugeordnet; widersprüchliche
zusätzliche Kennungen werden abgewiesen. Fehlen bei einem laufenden Auftrag noch
die Turns, wird vorerst kein Antworttext zugeordnet.

Bei einem Zuordnungsfehler wird der Lauf als `failed` gespeichert; Antworttext,
Verbrauch und Kostenschätzung werden aus dem aktuellen Ergebnis entfernt. Die
Fehlerursache steht ohne fremden Antworttext in `ownership_reason`. Fehlende
Kennungen alter Datensätze werden nicht automatisch ergänzt. Ein späterer
erfolgreicher Abgleich ersetzt den Fehlerzustand; er erzeugt keine neue Session.

Es gibt keinen `dispatch`- oder `create`-Befehl. Vorbereitung und Anzeige
bleiben offline; `reconcile` liest nur eine bekannte Session. Exitcode 0 steht
für erfolgreiche Vorbereitung/Anzeige oder einen abgeschlossenen Abgleich,
1 für einen fehlgeschlagenen Vorgang und 3 für einen noch laufenden Abgleich.
Fehlender Lauf bei `show`, lokale Eingabefehler und Aufruffehler liefern 2.
Vorgangsfehler erscheinen als JSON; argparse-Aufruffehler auf stderr.
`--timeout` begrenzt jeden SDK-Request (höchstens 60 Sekunden), nicht den
gesamten Abgleich. Es gibt keine automatischen Wiederholungen.

Standardpfade werden aus dem Skriptverzeichnis abgeleitet; explizite relative
Pfade beziehen sich auf das Arbeitsverzeichnis. Der lokale Entwurf erteilt
keine Freigabe für bezahlte Sessions und reserviert kein Budget. Die SDK-Sitzung
hat kein garantiertes hartes Kostenlimit.

Der Integrationstest verwendet das installierte SDK und einen lokalen HTTP-Server
mit Testdaten. Er prüft genau drei GET-Requests und keine Session-Erstellung:

```powershell
.\.venv-agentic\Scripts\python.exe -m unittest discover -s tests/integration -p test_research_agent_sdk.py
```

## Status und begrenzter Start

Die schreibgeschützte Statusprüfung und ein einzelner, kontrollierter Start
können aus jedem Arbeitsverzeichnis ausgeführt werden:

```powershell
.\.venv-research\Scripts\python.exe research_control.py status
.\.venv-research\Scripts\python.exe research_control.py start
```

`start` prüft zuerst den bestehenden Supervisor-Lock und startet bei belegtem
Lock keinen Prozess. Bei freiem Lock wird ausschließlich die projektbezogene
`research_supervisor.py` mit absolutem `sys.executable`, festem Arbeitsordner
und ohne Shell gestartet. Die Rückkehr `starting_unknown` bedeutet, dass die
Statusbestätigung innerhalb des begrenzten Wartefensters ausblieb; es erfolgt
kein zweiter Start und keine automatische Reparatur. Es gibt keine
Stop-/Kill-Funktion in diesem CLI. Alle Aktionen bleiben read-only bezüglich
Markt- und Handelsdaten und lösen keine bezahlten Agentenaufrufe aus.

## Kostenübersicht (offline)

```powershell
.\.venv-research\Scripts\python.exe research_agent.py --store output\agent_runs.json costs
```

Die Übersicht liest den Store schreibgeschützt und erstellt weder SDK-Clients
noch Netzwerkaufrufe. Sie summiert ausschließlich gespeicherte, endliche
`estimated_cost_usd`-Schätzwerte abgeschlossener Läufe mit gültiger
Tokenbilanz, bekannter Modellkennung und eindeutiger Session-ID. Die Ausgabe
trägt `estimates_not_invoice: true` und `authorization: false`; sie behauptet
kein Budgetlimit und aktiviert keine Aufrufe. Exitcode 0 bedeutet einen
vollständig gültigen oder verifiziert leeren Store, 3 unvollständige Records,
2 einen fehlenden, beschädigten, übergroßen oder strukturell ungültigen Store.
