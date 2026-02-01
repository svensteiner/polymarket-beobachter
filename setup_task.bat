@echo off
schtasks /create /tn "PolymarketBeobachter" /tr "cmd.exe /c \"C:\automation\projects\polymarket Beobachter\run_pipeline_once.bat\"" /sc minute /mo 15 /f
echo Done.
pause
