@echo off
setlocal
set LOGFILE=C:\Chatgpt_Codex\polymarket Beobachter\paper_trader\logs\scheduler.log
echo [%date% %time%] Starting paper trader >> "%LOGFILE%"
cd /d "C:\Chatgpt_Codex\polymarket Beobachter"
python -m paper_trader.run --once --quiet >> "%LOGFILE%" 2>&1
echo [%date% %time%] Paper trader complete >> "%LOGFILE%"
endlocal
