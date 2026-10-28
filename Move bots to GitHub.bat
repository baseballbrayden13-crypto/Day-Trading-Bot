@echo off
rem Moves bots 1, 2 and 3 and the daytime helpers to GitHub, so they run while this PC is off.
rem It turns OFF (doesn't delete) the PC tasks for bots 1-3, Guard, Lab and Reporter, then copies
rem bot 1's .env to GitHub's secret storage and switches bot 1 on there. Kalshi bots and Medic stay here.
rem Run it before 9am or after 4pm on a weekday, so bot 1 isn't mid-trade on the PC.
rem Undo: "Move bots to GitHub.bat" undo
cd /d "%~dp0"
set PATH=%PATH%;C:\Program Files\GitHub CLI
if /i "%1"=="undo" goto undo
for %%T in ("Trading bot (paper)" "Trading bot 2 (ETF rotation, paper)" "Trading bot 3 (crypto, paper)" "Fleet guard (read-only)" "Fleet lab (weekly, read-only)" "Fleet reporter (weekly)") do schtasks /Change /TN %%T /DISABLE
".venv\Scripts\python.exe" set_cloud_keys.py --move-bot1
if errorlevel 1 (
  echo Bot 1 wasn't moved, so its PC task is turned back on.
  schtasks /Change /TN "Trading bot (paper)" /ENABLE
)
pause
exit /b
:undo
".venv\Scripts\python.exe" set_cloud_keys.py --bot1-back
for %%T in ("Trading bot (paper)" "Trading bot 2 (ETF rotation, paper)" "Trading bot 3 (crypto, paper)" "Fleet guard (read-only)" "Fleet lab (weekly, read-only)" "Fleet reporter (weekly)") do schtasks /Change /TN %%T /ENABLE
echo Bots 1-3 and the helpers run on this PC again. Also turn off the Cloud bots workflow on GitHub (Actions tab) for bots 2 and 3.
pause
